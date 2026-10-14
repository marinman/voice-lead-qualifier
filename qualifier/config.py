"""Paths, environment, and config-file loading shared by the web server and agent."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
FIXTURES_DIR = ROOT / "fixtures"
DATA_DIR = Path(os.environ.get("VLQ_DATA_DIR", ROOT / "data"))

load_dotenv(ROOT / ".env")

AGENT_NAME = os.environ.get("AGENT_NAME", "lead-qualifier")

# The five qualification questions, in order. The voice agent prompt and the
# text-chat fallback both read from here so the two channels stay identical.
QUESTIONS = [
    ("use_case", "What are you looking to build or improve with voice AI?"),
    ("company_size_band", "Roughly how many people are at your company?"),
    ("timeline", "When are you hoping to have something live?"),
    (
        "current_stack",
        "What are you using today: building in-house, another provider, or starting from zero?",
    ),
    ("role_type", "And what is your role on the team?"),
]

DISCLOSURE = (
    "Hi, I'm an AI assistant running a short qualification chat for the "
    "Voice AI Readiness Assessment. It takes about three minutes."
)
OUT_OF_SCOPE = "A human can follow up on that one."


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_scoring() -> dict:
    """Re-read on every call so edits to scoring.yaml apply to the next score."""
    return _load_yaml("scoring.yaml")


def load_links() -> dict:
    return _load_yaml("links.yaml")


def load_faq_text() -> str:
    return (CONFIG_DIR / "faq.md").read_text(encoding="utf-8")


def livekit_configured() -> bool:
    return all(os.environ.get(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))


def openai_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
