"""Acceptance checks that run without any API keys."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from qualifier import config, scoring, storage
from qualifier.config import FIXTURES_DIR
from qualifier.extraction import extract_rules


DASH = "test-dashboard-token-123"
AUTH = {"X-Dashboard-Token": DASH}


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "leads.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setenv("EXTRACTION_MODE", "rules")
    monkeypatch.setenv("DASHBOARD_TOKEN", DASH)
    for k in ("DEMO_ENABLED", "MAX_SESSIONS_PER_DAY", "MAX_SESSIONS_PER_IP_PER_DAY", "MAX_SESSION_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def client():
    from web.server import app
    return TestClient(app)


def fixture(name):
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


def test_hot_sample_scores_70_plus_and_offers_booking(client):
    r = client.post("/api/samples/hot").json()
    assert r["score"] >= 70 and r["tier"] == "Hot"
    assert r["outcome"] == "meeting_offered"
    assert r["next_step"]["cta_url"] == config.load_links()["hot"]["booking_url"]


def test_low_sample_scores_under_40_and_shows_resources(client):
    r = client.post("/api/samples/low").json()
    assert r["score"] < 40 and r["tier"] == "Low"
    assert r["outcome"] == "resource"
    assert r["next_step"]["secondary_url"] == config.load_links()["low"]["docs_url"]


def test_warm_sample_routes_to_nurture_and_captures_email(client):
    r = client.post("/api/samples/warm").json()
    assert 40 <= r["score"] < 70 and r["outcome"] == "nurture"
    assert client.post("/api/nurture", json={"conversation_id": r["id"], "email": "a@b.co"}).status_code == 200
    assert client.post("/api/nurture", json={"conversation_id": r["id"], "email": "nope"}).status_code == 422
    assert storage.nurture_count() == 1


def test_editing_scoring_yaml_changes_next_score(client, tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, cfg)
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    before = client.post("/api/samples/low").json()["score"]
    text = (cfg / "scoring.yaml").read_text().replace('"1-10": 5', '"1-10": 25')
    (cfg / "scoring.yaml").write_text(text)
    after = client.post("/api/samples/low").json()["score"]
    assert after == before + 20


def test_breakdown_sums_to_score():
    result = scoring.score(extract_rules(fixture("warm")["transcript"]))
    assert sum(b["points"] for b in result["breakdown"]) == result["score"]
    assert result["max_score"] == 100


def test_missing_answers_score_zero_and_flag_incomplete(client):
    s = client.post("/api/text/start", json={}).json()
    client.post("/api/text/message", json={"session_id": s["session_id"], "text": "A production agent for our call center"})
    r = client.post("/api/text/message", json={"session_id": s["session_id"], "text": "stop"}).json()
    rec = r["result"]
    assert r["done"] and rec["incomplete"] and rec["end_reason"] == "visitor_stopped"
    assert rec["extracted"]["use_case"] == "production" and rec["extracted"]["role_type"] is None
    assert rec["utm_source"] == "direct"


def test_text_fallback_record_matches_voice_shape(client):
    s = client.post("/api/text/start", json={"utm_source": "google", "utm_campaign": "c1"}).json()
    for msg in ["What is LiveKit?", "A pilot for support", "40 people", "next month", "starting from zero", "I'm the founder"]:
        r = client.post("/api/text/message", json={"session_id": s["session_id"], "text": msg}).json()
    rec = r["result"]
    voice_like = fixture("hot")
    from qualifier.pipeline import finalize
    v = finalize(voice_like["transcript"], channel="voice", utm=voice_like["utm"], room_name="vlq-x")
    assert set(rec) - {"transcript"} == set(v) - {"transcript"}
    assert rec["utm_source"] == "google" and rec["utm_campaign"] == "c1"
    listed = client.get("/api/conversations", headers=AUTH).json()["rows"]
    assert {row["channel"] for row in listed} == {"text", "voice"}


def test_extraction_failure_saves_for_review(monkeypatch):
    from qualifier import pipeline
    from qualifier.extraction import ExtractionError

    def boom(_):
        raise ExtractionError("down")

    monkeypatch.setattr(pipeline, "extract", boom)
    rec = pipeline.finalize(fixture("hot")["transcript"], channel="voice")
    assert rec["score"] is None and rec["needs_review"] and rec["outcome"] == "needs_review"
    assert storage.get_conversation(rec["id"])["transcript"]


def test_keys_missing_app_boots_and_reports_voice_off(client):
    assert client.get("/api/config").json()["voice_configured"] is False
    assert client.post("/api/token", json={}).status_code == 503
    assert client.get("/").status_code == 200 and client.get("/healthz").status_code == 200


def test_dashboard_requires_token(client):
    client.post("/api/samples/hot")
    assert client.get("/dashboard").status_code == 404
    assert client.get("/dashboard/wrong-token").status_code == 404
    assert client.get(f"/dashboard/{DASH}").status_code == 200
    assert client.get("/api/conversations").status_code == 404
    assert client.get("/api/conversations", headers={"X-Dashboard-Token": "nope"}).status_code == 404
    rows = client.get("/api/conversations", headers=AUTH).json()["rows"]
    assert client.get(f"/api/conversations/{rows[0]['id']}").status_code == 404
    assert client.get(f"/api/conversations/{rows[0]['id']}", headers=AUTH).json()["transcript"]


def test_dashboard_closed_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN")
    assert client.get("/dashboard/anything").status_code == 404
    assert client.get("/api/conversations", headers={"X-Dashboard-Token": ""}).status_code == 404


def test_demo_disabled_blocks_new_sessions_but_not_samples(client, monkeypatch):
    monkeypatch.setenv("DEMO_ENABLED", "false")
    assert client.get("/api/config").json()["demo_enabled"] is False
    assert client.post("/api/text/start", json={}).status_code == 503
    assert client.post("/api/samples/hot").status_code == 200


def test_daily_session_cap(client, monkeypatch):
    monkeypatch.setenv("MAX_SESSIONS_PER_DAY", "2")
    monkeypatch.setenv("MAX_SESSIONS_PER_IP_PER_DAY", "100")
    for _ in range(2):
        assert client.post("/api/text/start", json={}).status_code == 200
    r = client.post("/api/text/start", json={})
    assert r.status_code == 429 and "limit" in r.json()["detail"]


def test_per_ip_session_cap(client, monkeypatch):
    monkeypatch.setenv("MAX_SESSIONS_PER_IP_PER_DAY", "1")
    a = {"Fly-Client-IP": "203.0.113.1"}
    assert client.post("/api/text/start", json={}, headers=a).status_code == 200
    assert client.post("/api/text/start", json={}, headers=a).status_code == 429
    assert client.post("/api/text/start", json={}, headers={"Fly-Client-IP": "203.0.113.2"}).status_code == 200


def test_text_session_time_limit(client, monkeypatch):
    s = client.post("/api/text/start", json={}).json()
    monkeypatch.setenv("MAX_SESSION_SECONDS", "0")
    r = client.post("/api/text/message", json={"session_id": s["session_id"], "text": "A pilot"}).json()
    assert r["done"] and r["result"]["end_reason"] == "time_limit" and r["result"]["incomplete"]
