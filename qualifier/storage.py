"""Persistence. One row per conversation, plus nurture (email capture) and usage
(guardrail counters) tables.

Two interchangeable backends behind the same tiny interface:
- Local SQLite file (default, for development and tests).
- Turso (hosted libSQL) over its HTTP API, when TURSO_DATABASE_URL is set. Used in
  production so the web server (Render) and the agent (LiveKit Cloud) share one
  database from different machines.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

import httpx

from .config import DATA_DIR

DB_PATH = DATA_DIR / "leads.db"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS conversations (
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
    end_reason TEXT                     -- completed | visitor_stopped | silence | disconnected | time_limit | abandoned
)""",
    "CREATE INDEX IF NOT EXISTS idx_conv_room ON conversations(room_name)",
    """CREATE TABLE IF NOT EXISTS usage (  -- session starts, for cost guardrails
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- voice | text | sample
    ip_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(created_at)",
    """CREATE TABLE IF NOT EXISTS nurture (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    email TEXT NOT NULL,
    created_at TEXT NOT NULL
)""",
]

JSON_COLS = ("transcript", "extracted", "score_breakdown")
CONV_COLS = (
    "id", "created_at", "duration_seconds", "channel", "room_name", "transcript", "extracted",
    "extraction_method", "score", "tier", "outcome", "score_breakdown", "utm_source", "utm_medium",
    "utm_campaign", "incomplete", "needs_review", "end_reason",
)

Statement = tuple[str, list]


# ------------------------------------------------------------------- backends

class SQLiteDB:
    def __init__(self, path):
        self.path = path

    def run(self, stmts: list[Statement]) -> list[dict]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            out = []
            for sql, args in stmts:
                cur = conn.execute(sql, args)
                out.append({"rows": [dict(r) for r in cur.fetchall()], "affected": cur.rowcount})
            conn.commit()
            return out
        finally:
            conn.close()


class TursoDB:
    """Minimal client for Turso's HTTP pipeline API (/v2/pipeline). Each run() is one
    HTTP request; statements in it execute in order on one connection."""

    def __init__(self, url: str, token: str):
        self.url = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
        self.token = token

    @staticmethod
    def _arg(v):
        if v is None:
            return {"type": "null"}
        if isinstance(v, bool) or isinstance(v, int):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        return {"type": "text", "value": str(v)}

    @staticmethod
    def _cell(c):
        t = c.get("type")
        if t == "null":
            return None
        if t == "integer":
            return int(c["value"])
        if t == "float":
            return float(c["value"])
        if t == "blob":
            return base64.b64decode(c.get("base64", ""))
        return c.get("value")

    def run(self, stmts: list[Statement]) -> list[dict]:
        body = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": [self._arg(a) for a in args]}}
                for sql, args in stmts
            ]
            + [{"type": "close"}]
        }
        resp = httpx.post(self.url, json=body, headers={"Authorization": f"Bearer {self.token}"}, timeout=15)
        resp.raise_for_status()
        out = []
        for res in resp.json()["results"][: len(stmts)]:
            if res.get("type") != "ok":
                raise RuntimeError(f"Turso error: {res.get('error')}")
            r = res["response"]["result"]
            names = [c["name"] for c in r["cols"]]
            out.append({
                "rows": [dict(zip(names, (self._cell(c) for c in row))) for row in r["rows"]],
                "affected": r.get("affected_row_count", 0),
            })
        return out


_initialized: set[str] = set()


def _db():
    url = os.environ.get("TURSO_DATABASE_URL")
    db = TursoDB(url, os.environ.get("TURSO_AUTH_TOKEN", "")) if url else SQLiteDB(DB_PATH)
    key = url or str(DB_PATH)
    if key not in _initialized:
        db.run([(s, []) for s in SCHEMA])
        _initialized.add(key)
    return db


def run(stmts: list[Statement]) -> list[dict]:
    return _db().run(stmts)


def query(sql: str, args: list | tuple = ()) -> list[dict]:
    return run([(sql, list(args))])[0]["rows"]


def execute(sql: str, args: list | tuple = ()) -> int:
    """Run a write; returns the number of affected rows."""
    return run([(sql, list(args))])[0]["affected"]


# ---------------------------------------------------------------- data access

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(d: dict | None) -> dict | None:
    if d is None:
        return None
    d = dict(d)
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
    cols = [c for c in CONV_COLS if c in rec]
    vals = [json.dumps(rec[c]) if c in JSON_COLS and rec[c] is not None else rec[c] for c in cols]
    execute(
        f"INSERT OR REPLACE INTO conversations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        vals,
    )
    return get_conversation(rec["id"])


def get_conversation(cid: str) -> dict | None:
    rows = query("SELECT * FROM conversations WHERE id = ?", [cid])
    return _row(rows[0]) if rows else None


def get_by_room(room: str) -> dict | None:
    rows = query("SELECT * FROM conversations WHERE room_name = ? ORDER BY created_at DESC LIMIT 1", [room])
    return _row(rows[0]) if rows else None


def list_conversations(include_samples: bool = True) -> list[dict]:
    q = "SELECT * FROM conversations"
    if not include_samples:
        q += " WHERE channel != 'sample'"
    return [_row(r) for r in query(q + " ORDER BY created_at DESC")]


def update_transcript(cid: str, transcript: list[dict], duration_seconds: int | None = None) -> None:
    """Replace the stored transcript (e.g. to append the closing line spoken after scoring)."""
    execute(
        "UPDATE conversations SET transcript = ?, duration_seconds = COALESCE(?, duration_seconds) WHERE id = ?",
        [json.dumps(transcript), duration_seconds, cid],
    )


def add_nurture(conversation_id: str, email: str) -> None:
    execute(
        "INSERT INTO nurture (conversation_id, email, created_at) VALUES (?, ?, ?)",
        [conversation_id, email, now_iso()],
    )


def nurture_count() -> int:
    return query("SELECT COUNT(*) AS n FROM nurture")[0]["n"]
