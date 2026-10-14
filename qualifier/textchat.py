"""Text-chat fallback for visitors without a mic. Runs the same five questions,
then the same finalize() pipeline, so the saved record matches the voice channel."""

from __future__ import annotations

import re
import time
import uuid

from . import faq, storage
from .config import DISCLOSURE, QUESTIONS
from .pipeline import finalize

ACKS = ["Got it.", "Thanks, noted.", "Understood.", "Great, thanks."]
STOP = re.compile(r"^\s*(stop|quit|end|cancel|exit|bye|goodbye|not interested|no thanks)\b|\b(stop|end) (the|this) (chat|call)\b", re.I)

_sessions: dict[str, dict] = {}


def start(utm: dict | None) -> dict:
    sid = uuid.uuid4().hex[:12]
    first = f"{DISCLOSURE} {QUESTIONS[0][1]}"
    _sessions[sid] = {"step": 0, "utm": utm or {}, "started": time.time(), "transcript": [
        {"role": "assistant", "text": first}
    ]}
    return {"session_id": sid, "messages": [first], "done": False}


def _finish(sid: str, s: dict, end_reason: str, closing: str | None) -> dict:
    result = finalize(
        s["transcript"],
        channel="text",
        utm=s["utm"],
        duration_seconds=int(time.time() - s["started"]),
        end_reason=end_reason,
        conversation_id=sid,
    )
    line = closing or result["next_step"]["agent_line"]
    s["transcript"].append({"role": "assistant", "text": line})
    storage.update_transcript(sid, s["transcript"])
    _sessions.pop(sid, None)
    result["transcript"] = s["transcript"]
    return {"messages": [line], "done": True, "result": result}


def message(sid: str, text: str) -> dict:
    s = _sessions.get(sid)
    if s is None:
        raise KeyError(sid)
    text = text.strip()[:1000]
    if not text:
        return {"messages": [], "done": False}
    s["transcript"].append({"role": "user", "text": text})

    if STOP.search(text):
        return _finish(sid, s, "visitor_stopped", "No problem, ending here. Thanks for your time.")

    reply = faq.answer(text)
    if reply is not None and s["step"] < len(QUESTIONS):
        out = f"{reply} Back to the assessment: {QUESTIONS[s['step']][1]}"
        s["transcript"].append({"role": "assistant", "text": out})
        return {"messages": [out], "done": False}

    s["step"] += 1
    if s["step"] >= len(QUESTIONS):
        return _finish(sid, s, "completed", None)
    out = f"{ACKS[(s['step'] - 1) % len(ACKS)]} {QUESTIONS[s['step']][1]}"
    s["transcript"].append({"role": "assistant", "text": out})
    return {"messages": [out], "done": False}
