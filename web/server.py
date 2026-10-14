"""FastAPI app: landing page, dashboard, LiveKit token endpoint, text fallback,
reviewer-mode samples, and the read API the dashboard uses.

Run: .venv/bin/uvicorn web.server:app --port 8000
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qualifier import storage, textchat  # noqa: E402
from qualifier.config import (  # noqa: E402
    AGENT_NAME, FIXTURES_DIR, livekit_configured, load_scoring, openai_configured,
)
from qualifier.pipeline import clean_utm, finalize, next_step  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="Voice Lead Qualifier")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class UTM(BaseModel):
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None


class TextMessage(BaseModel):
    session_id: str
    text: str


class NurtureIn(BaseModel):
    conversation_id: str
    email: str


def with_next_step(rec: dict | None) -> dict | None:
    if rec is None:
        return None
    rubric = load_scoring()
    max_score = sum(max(c["points"].values()) for c in rubric["criteria"].values())
    return {**rec, "max_score": max_score, "next_step": next_step(rec.get("tier"))}


# ----------------------------------------------------------------------- pages

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/dashboard")
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


# ------------------------------------------------------------------------- api

@app.get("/api/config")
def get_config():
    return {
        "voice_configured": livekit_configured(),
        "extraction_method": "llm" if openai_configured() and os.environ.get("EXTRACTION_MODE") != "rules" else "rules",
        "tiers": load_scoring()["tiers"],
    }


@app.post("/api/token")
def mint_token(utm: UTM):
    if not livekit_configured():
        raise HTTPException(503, "Voice not configured: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env")
    from livekit import api

    room = f"vlq-{uuid.uuid4().hex[:10]}"
    identity = f"visitor-{uuid.uuid4().hex[:6]}"
    attribution = clean_utm(utm.model_dump())
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name("Visitor")
        .with_ttl(timedelta(minutes=15))
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=json.dumps(attribution))]
            )
        )
        .to_jwt()
    )
    return {"token": token, "url": os.environ["LIVEKIT_URL"], "room": room}


@app.get("/api/rooms/{room}/result")
def room_result(room: str):
    rec = storage.get_by_room(room)
    if rec is None:
        raise HTTPException(404, "not finalized yet")
    return with_next_step(rec)


@app.post("/api/samples/{persona}")
def run_sample(persona: str):
    if not re.fullmatch(r"hot|warm|low", persona):
        raise HTTPException(404, "unknown persona")
    fx = json.loads((FIXTURES_DIR / f"{persona}.json").read_text())
    result = finalize(
        fx["transcript"], channel="sample", utm=fx.get("utm"), duration_seconds=fx.get("duration_seconds")
    )
    return {**result, "persona": fx["persona"], "persona_description": fx["description"]}


@app.post("/api/text/start")
def text_start(utm: UTM):
    return textchat.start(utm.model_dump())


@app.post("/api/text/message")
def text_message(msg: TextMessage):
    try:
        return textchat.message(msg.session_id, msg.text)
    except KeyError:
        raise HTTPException(404, "chat session expired, start a new one")


@app.post("/api/nurture")
def nurture(n: NurtureIn):
    email = n.email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        raise HTTPException(422, "enter a valid email")
    rec = storage.get_conversation(n.conversation_id)
    if rec is None:
        raise HTTPException(404, "unknown conversation")
    if rec.get("outcome") != "nurture":
        raise HTTPException(409, "email capture is only offered on nurture outcomes")
    storage.add_nurture(n.conversation_id, email)
    return {"ok": True}


@app.get("/api/conversations")
def conversations(include_samples: bool = True):
    rows = storage.list_conversations(include_samples)
    scored = [r for r in rows if r["tier"]]
    hot = sum(r["tier"] == "Hot" for r in rows)

    by_source: dict[tuple, dict] = defaultdict(lambda: {"total": 0, "hot": 0, "warm": 0, "low": 0})
    for r in rows:
        b = by_source[(r["utm_source"], r["utm_campaign"] or "—")]
        b["total"] += 1
        if r["tier"]:
            b[r["tier"].lower()] += 1

    return {
        "stats": {
            "total": len(rows),
            "hot": hot,
            "warm": sum(r["tier"] == "Warm" for r in rows),
            "low": sum(r["tier"] == "Low" for r in rows),
            "hot_rate": round(hot / len(scored), 3) if scored else 0,
            "meeting_offers": sum(r["outcome"] == "meeting_offered" for r in rows),
            "needs_review": sum(r["needs_review"] for r in rows),
            "incomplete": sum(r["incomplete"] for r in rows),
            "nurture_emails": storage.nurture_count(),
        },
        "by_source": [
            {"utm_source": s, "utm_campaign": c, **v,
             "hot_rate": round(v["hot"] / v["total"], 3) if v["total"] else 0}
            for (s, c), v in sorted(by_source.items(), key=lambda kv: -kv[1]["total"])
        ],
        "rows": [
            {k: r[k] for k in ("id", "created_at", "channel", "utm_source", "utm_medium", "utm_campaign",
                               "score", "tier", "outcome", "incomplete", "needs_review", "duration_seconds")}
            | {"use_case": (r["extracted"] or {}).get("use_case_detail") or (r["extracted"] or {}).get("use_case")}
            for r in rows
        ],
    }


@app.get("/api/conversations/{cid}")
def conversation(cid: str):
    rec = storage.get_conversation(cid)
    if rec is None:
        raise HTTPException(404, "not found")
    return with_next_step(rec)
