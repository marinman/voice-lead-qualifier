"""Cost guardrails for a public demo link.

All limits come from environment variables (the host's secret settings), so they
can be changed with e.g. `fly secrets set DEMO_ENABLED=false`, no code redeploy.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from . import storage


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def demo_enabled() -> bool:
    return os.environ.get("DEMO_ENABLED", "true").strip().lower() not in ("0", "false", "off", "no")


def max_session_seconds() -> int:
    return _int("MAX_SESSION_SECONDS", 300)


def limits() -> dict:
    return {
        "max_sessions_per_day": _int("MAX_SESSIONS_PER_DAY", 50),
        "max_sessions_per_ip_per_day": _int("MAX_SESSIONS_PER_IP_PER_DAY", 5),
        "max_samples_per_ip_per_day": _int("MAX_SAMPLES_PER_IP_PER_DAY", 30),
    }


class GuardrailError(Exception):
    def __init__(self, message: str, status: int = 429):
        super().__init__(message)
        self.message = message
        self.status = status


def _ip_hash(ip: str) -> str:
    # Store a hash, not the raw IP.
    return hashlib.sha256(f"vlq:{ip}".encode()).hexdigest()[:16]


def _today_start() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")


def start_session(kind: str, ip: str) -> None:
    """Check the caps and record a new session start. kind: voice | text | sample.

    Voice and text share the global daily cap and the per-IP cap. Reviewer samples
    cost at most one extraction call, so they only get a per-IP cap.
    """
    if kind != "sample" and not demo_enabled():
        raise GuardrailError("The live demo is paused right now. Reviewer mode below still works.", 503)
    lim = limits()
    ip_h = _ip_hash(ip)
    since = _today_start()
    with storage.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if kind == "sample":
            n_ip = c.execute(
                "SELECT COUNT(*) FROM usage WHERE kind = 'sample' AND ip_hash = ? AND created_at >= ?",
                (ip_h, since),
            ).fetchone()[0]
            if n_ip >= lim["max_samples_per_ip_per_day"]:
                raise GuardrailError("You've run a lot of samples today. Try again tomorrow.")
        else:
            total = c.execute(
                "SELECT COUNT(*) FROM usage WHERE kind != 'sample' AND created_at >= ?", (since,)
            ).fetchone()[0]
            if total >= lim["max_sessions_per_day"]:
                raise GuardrailError(
                    "The demo has hit today's session limit. Reviewer mode below still shows the full system."
                )
            n_ip = c.execute(
                "SELECT COUNT(*) FROM usage WHERE kind != 'sample' AND ip_hash = ? AND created_at >= ?",
                (ip_h, since),
            ).fetchone()[0]
            if n_ip >= lim["max_sessions_per_ip_per_day"]:
                raise GuardrailError("You've reached today's limit for live sessions. Reviewer mode still works.")
        c.execute(
            "INSERT INTO usage (kind, ip_hash, created_at) VALUES (?, ?, ?)",
            (kind, ip_h, storage.now_iso()),
        )


def sessions_today() -> int:
    with storage.connect() as c:
        return c.execute(
            "SELECT COUNT(*) FROM usage WHERE kind != 'sample' AND created_at >= ?", (_today_start(),)
        ).fetchone()[0]
