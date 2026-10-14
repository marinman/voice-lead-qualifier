"""SQLite persistence. One row per conversation, plus a nurture table for email capture."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATA_DIR

DB_PATH = DATA_DIR / "leads.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    duration_seconds INTEGER,
    channel TEXT NOT NULL,              -- voice | text | sample
    room_name TEXT,
    transcript TEXT NOT NULL,           -- JSON [{role, text}]
    extracted TEXT,                     -- JSON fields, null if extraction failed
    extraction_method TEXT,             -- llm | rules
    score INTEGER,
    tier TEXT,
    outcome TEXT,                       -- meeting_offered | nurture | resource | needs_review
    score_breakdown TEXT,               -- JSON per rubric line
    utm_source TEXT NOT NULL DEFAULT 'direct',
    utm_medium TEXT,
    utm_campaign TEXT,
    incomplete INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    end_reason TEXT                     -- completed | visitor_stopped | silence | disconnected
);
CREATE INDEX IF NOT EXISTS idx_conv_room ON conversations(room_name);
CREATE TABLE IF NOT EXISTS nurture (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    email TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

JSON_COLS = ("transcript", "extracted", "score_breakdown")


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for c in JSON_COLS:
        if d.get(c) is not None:
            d[c] = json.loads(d[c])
    d["incomplete"] = bool(d["incomplete"])
    d["needs_review"] = bool(d["needs_review"])
    return d


def save_conversation(rec: dict) -> dict:
    rec = dict(rec)
    rec.setdefault("id", uuid.uuid4().hex[:12])
    rec.setdefault("created_at", now_iso())
    row = {k: (json.dumps(v) if k in JSON_COLS and v is not None else v) for k, v in rec.items()}
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    with connect() as c:
        c.execute(f"INSERT OR REPLACE INTO conversations ({cols}) VALUES ({marks})", row)
    return get_conversation(rec["id"])


def get_conversation(cid: str) -> dict | None:
    with connect() as c:
        return _row(c.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone())


def get_by_room(room: str) -> dict | None:
    with connect() as c:
        return _row(
            c.execute(
                "SELECT * FROM conversations WHERE room_name = ? ORDER BY created_at DESC LIMIT 1", (room,)
            ).fetchone()
        )


def list_conversations(include_samples: bool = True) -> list[dict]:
    q = "SELECT * FROM conversations"
    if not include_samples:
        q += " WHERE channel != 'sample'"
    with connect() as c:
        return [_row(r) for r in c.execute(q + " ORDER BY created_at DESC").fetchall()]


def update_transcript(cid: str, transcript: list[dict], duration_seconds: int | None = None) -> None:
    """Replace the stored transcript (e.g. to append the closing line spoken after scoring)."""
    with connect() as c:
        c.execute(
            "UPDATE conversations SET transcript = ?, duration_seconds = COALESCE(?, duration_seconds) WHERE id = ?",
            (json.dumps(transcript), duration_seconds, cid),
        )


def add_nurture(conversation_id: str, email: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO nurture (conversation_id, email, created_at) VALUES (?, ?, ?)",
            (conversation_id, email, now_iso()),
        )


def nurture_count() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM nurture").fetchone()[0]
