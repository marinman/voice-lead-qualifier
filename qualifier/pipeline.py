"""Finalize a conversation: extract -> score -> route -> persist.

Voice, text fallback, and reviewer samples all end here, so every channel
produces the same record shape.
"""

from __future__ import annotations

import logging

from . import storage
from .config import load_links
from .extraction import ExtractionError, extract
from .scoring import FIELDS, OUTCOME_BY_TIER, score

log = logging.getLogger("qualifier.pipeline")


def clean_utm(utm: dict | None) -> dict:
    utm = utm or {}
    pick = lambda k: (str(utm.get(k) or "").strip()[:100] or None)  # noqa: E731
    return {
        "utm_source": pick("utm_source") or "direct",
        "utm_medium": pick("utm_medium"),
        "utm_campaign": pick("utm_campaign"),
    }


def next_step(tier: str | None) -> dict:
    """What the UI shows (and the agent offers) for a tier."""
    links = load_links()
    if tier == "Hot":
        return {
            "outcome": "meeting_offered",
            "headline": "Let's get you a working session with a solutions engineer.",
            "cta_label": links["hot"]["cta"],
            "cta_url": links["hot"]["booking_url"],
            "agent_line": "Based on what you shared, the best next step is a 30-minute architecture "
            "session with our team. I've put a booking link on your screen.",
        }
    if tier == "Warm":
        return {
            "outcome": "nurture",
            "headline": "We'll send your readiness recap and a build guide.",
            "cta_label": links["warm"]["resource_title"],
            "cta_url": links["warm"]["resource_url"],
            "email_capture": True,
            "agent_line": "Thanks. I'd suggest a short readiness recap plus a build guide for your "
            "use case. If you drop your email on screen, we'll send it over.",
        }
    if tier == "Low":
        return {
            "outcome": "resource",
            "headline": "The fastest way in is the docs and the getting-started guide.",
            "cta_label": "Voice AI quickstart",
            "cta_url": links["low"]["getting_started_url"],
            "secondary_label": "LiveKit docs",
            "secondary_url": links["low"]["docs_url"],
            "agent_line": "Great place to start is the voice AI quickstart in the docs. I've put "
            "the links on your screen so you can build at your own pace.",
        }
    return {
        "outcome": "needs_review",
        "headline": "Thanks. A human will review this conversation and follow up.",
        "agent_line": "Thanks for your time. Someone from the team will follow up.",
    }


def finalize(
    transcript: list[dict],
    *,
    channel: str,
    utm: dict | None = None,
    duration_seconds: int | None = None,
    room_name: str | None = None,
    end_reason: str = "completed",
    conversation_id: str | None = None,
    extracted: tuple[dict, str] | None = None,
) -> dict:
    """extracted: optional (fields, method) produced by the caller, e.g. the voice
    agent's own LLM. When omitted, the default extractor runs."""
    transcript = [t for t in transcript if t.get("text", "").strip()]
    rec: dict = {
        "channel": channel,
        "room_name": room_name,
        "duration_seconds": duration_seconds,
        "transcript": transcript,
        "end_reason": end_reason,
        **clean_utm(utm),
    }
    if conversation_id:
        rec["id"] = conversation_id

    try:
        fields, method = extracted if extracted else extract(transcript)
    except ExtractionError as e:
        log.warning("extraction failed, saving for review: %s", e)
        rec.update(
            extracted=None, extraction_method=None, score=None, tier=None,
            score_breakdown=None, outcome="needs_review", needs_review=1,
            incomplete=int(end_reason != "completed"),
        )
        saved = storage.save_conversation(rec)
        return {**saved, "next_step": next_step(None)}

    result = score(fields)
    incomplete = end_reason != "completed" or any(fields.get(f) is None for f in FIELDS)
    rec.update(
        extracted=fields,
        extraction_method=method,
        score=result["score"],
        tier=result["tier"],
        score_breakdown=result["breakdown"],
        outcome=OUTCOME_BY_TIER[result["tier"]],
        incomplete=int(incomplete),
        needs_review=0,
    )
    saved = storage.save_conversation(rec)
    return {**saved, "max_score": result["max_score"], "next_step": next_step(result["tier"])}
