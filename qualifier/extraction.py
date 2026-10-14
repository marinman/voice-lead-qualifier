"""Post-call extraction: transcript -> structured fields for scoring.

Primary path is an LLM (OpenAI, JSON-schema constrained). When no OPENAI_API_KEY is
set, a keyword rule extractor runs instead so reviewer mode and the text fallback
still work with zero keys. Either way the output shape is identical, and the
method used is saved on the record.
"""

from __future__ import annotations

import json
import os
import re

import httpx

from .config import openai_configured

FIELD_VALUES = {
    "use_case": ["production", "pilot", "curiosity"],
    "company_size_band": ["1-10", "11-49", "50-199", "200+"],
    "timeline": ["under_1_month", "1_3_months", "3_6_months", "exploring"],
    "current_stack": ["vendor", "in_house", "from_zero"],
    "role_type": ["decision_maker", "practitioner", "unknown"],
}
EMPTY = {k: None for k in FIELD_VALUES} | {"use_case_detail": None}


class ExtractionError(Exception):
    pass


def transcript_text(transcript: list[dict]) -> str:
    who = {"assistant": "Agent", "user": "Visitor"}
    return "\n".join(f"{who.get(t['role'], t['role'])}: {t['text']}" for t in transcript)


def extract(transcript: list[dict]) -> tuple[dict, str]:
    """Return (fields, method). Raises ExtractionError if the LLM path fails."""
    mode = os.environ.get("EXTRACTION_MODE", "auto")
    if mode == "llm" or (mode == "auto" and openai_configured()):
        return extract_llm(transcript), "llm"
    return extract_rules(transcript), "rules"


# --------------------------------------------------------------------------- LLM

LLM_PROMPT = """You extract lead-qualification fields from a sales qualification call transcript.
Return JSON only. Use null when the visitor did not give an answer. Never guess.

Field definitions:
- use_case: "production" = shipping a voice agent to real users/customers;
  "pilot" = prototype, POC, pilot, internal test; "curiosity" = learning, research, no concrete project.
- use_case_detail: one short phrase describing what they want to build, or null.
- company_size_band: headcount band "1-10", "11-49", "50-199", "200+".
- timeline: "under_1_month" (live within ~4 weeks), "1_3_months", "3_6_months",
  "exploring" (6+ months, no timeline, or unsure).
- current_stack: "vendor" = using/evaluating/replacing another provider;
  "in_house" = building it themselves; "from_zero" = nothing yet.
- role_type: "decision_maker" = founder, C-level, VP, head of, director, budget owner;
  "practitioner" = engineer, developer, PM, designer, IC; "unknown" = answered but unclear."""


def _schema() -> dict:
    props = {k: {"type": ["string", "null"], "enum": v + [None]} for k, v in FIELD_VALUES.items()}
    props["use_case_detail"] = {"type": ["string", "null"]}
    return {
        "name": "lead_fields",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


def extract_llm(transcript: list[dict]) -> dict:
    try:
        resp = httpx.post(
            f"{os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": os.environ.get("EXTRACTION_MODEL", "gpt-4.1-mini"),
                "temperature": 0,
                "response_format": {"type": "json_schema", "json_schema": _schema()},
                "messages": [
                    {"role": "system", "content": LLM_PROMPT},
                    {"role": "user", "content": transcript_text(transcript)},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:  # network, auth, bad JSON
        raise ExtractionError(f"LLM extraction failed: {e}") from e
    return validate(data)


def validate(data: dict) -> dict:
    out = dict(EMPTY)
    for k, allowed in FIELD_VALUES.items():
        v = data.get(k)
        out[k] = v if v in allowed else None
    detail = data.get("use_case_detail")
    out["use_case_detail"] = detail.strip()[:200] if isinstance(detail, str) and detail.strip() else None
    return out


# ------------------------------------------------------------------------- rules

QUESTION_KEYS = [
    ("use_case", ("build or improve", "looking to build")),
    ("company_size_band", ("how many people", "company size")),
    ("timeline", ("something live", "hoping to have", "go live")),
    ("current_stack", ("using today", "starting from zero")),
    ("role_type", ("your role",)),
]

NUM_WORDS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "dozen": 12, "couple": 2, "few": 3,
}


def _numbers(text: str) -> list[float]:
    t = text.lower().replace(",", "")
    nums: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(k|thousand|hundred)?\b", t):
        n = float(m.group(1))
        n *= {"k": 1000, "thousand": 1000, "hundred": 100}.get(m.group(2) or "", 1)
        nums.append(n)
    words = re.findall(r"[a-z]+", t)
    for i, w in enumerate(words):
        if w in ("hundred", "thousand"):
            base = NUM_WORDS.get(words[i - 1], 1) if i else 1
            nums.append(base * (100 if w == "hundred" else 1000))
        elif w in NUM_WORDS and w != "a":
            nums.append(NUM_WORDS[w])
    return nums


def _has(text: str, words) -> bool:
    return any(re.search(rf"\b{re.escape(w)}", text) for w in words)


def classify_use_case(t: str):
    if _has(t, ("curious", "learning", "learn ", "research", "nothing specific", "just looking", "exploring", "explore", "no idea")):
        return "curiosity"
    if _has(t, ("pilot", "prototype", "poc", "proof of concept", "experiment", "mvp", "trial", "test it", "see if")):
        return "pilot"
    if _has(t, ("production", "ship", "launch", "real callers", "customers", "at scale", "replace our", "rollout", "roll out",
                "into my", "into our", "integrate", "insert", "add voice", "our app", "my app", "our product", "our users", "my users")):
        return "production"
    return None


def classify_size(t: str, mapped: bool):
    if _has(t, ("just me", "solo", "only me", "myself")):
        return "1-10"
    if not mapped and not _has(t, ("people", "employees", "staff", "headcount", "person company")):
        return None
    nums = _numbers(t)
    if not nums:
        return None
    n = max(nums)
    if n >= 200:
        return "200+"
    if n >= 50:
        return "50-199"
    if n >= 11:
        return "11-49"
    return "1-10"


def classify_timeline(t: str):
    if _has(t, ("no timeline", "no real timeline", "not sure", "someday", "next year", "no rush", "just exploring", "exploring")):
        return "exploring"
    if _has(t, ("asap", "this week", "next week", "this month", "within the month", "few weeks", "couple weeks", "days", "immediately", "yesterday",
                "tomorrow", "today", "right now", "right away", "already live")):
        return "under_1_month"
    m = re.search(r"([\w.]+)(?:\s*(?:or|to|-)\s*([\w.]+))?\s+(weeks?|months?)", t)
    if m:
        vals = [v for v in (m.group(1), m.group(2)) if v]
        nums = [n for v in vals for n in _numbers(v)] or [1]
        n = max(nums)
        months = n / 4.3 if m.group(3).startswith("week") else n
        if months <= 1:
            return "under_1_month"
        if months <= 3:
            return "1_3_months"
        if months <= 6:
            return "3_6_months"
        return "exploring"
    if _has(t, ("next month", "this quarter", "end of quarter")):
        return "1_3_months"
    if _has(t, ("next quarter", "half", "summer", "by fall", "end of year", "end of the year")):
        return "3_6_months"
    return None


def classify_stack(t: str):
    if _has(t, ("from zero", "scratch", "nothing yet", "haven't built", "have not built", "nothing today", "starting fresh", "none")):
        return "from_zero"
    if _has(t, ("provider", "vendor", "replacing", "switching", "evaluating", "migrat", "twilio", "vapi", "retell", "bland")):
        return "vendor"
    if _has(t, ("in-house", "in house", "ourselves", "our own", "homegrown", "built", "building it")):
        return "in_house"
    return None


def classify_role(t: str, mapped: bool):
    if _has(t, ("ceo", "cto", "cpo", "coo", "chief", "founder", "co-founder", "vp", "vice president", "head of", "director", "owner", "president", "budget", "gm ",
                "doing everything", "do everything", "solo", "just me", "i run", "my own company", "my company")):
        return "decision_maker"
    if _has(t, ("engineer", "developer", "dev ", "programmer", "product manager", "pm ", "designer", "architect", "scientist", "write the code", "analyst", "tech lead", "student", "manager")):
        return "practitioner"
    return "unknown" if mapped else None


CLASSIFIERS = {
    "use_case": lambda t, m: classify_use_case(t),
    "company_size_band": classify_size,
    "timeline": lambda t, m: classify_timeline(t),
    "current_stack": lambda t, m: classify_stack(t),
    "role_type": classify_role,
}


def extract_rules(transcript: list[dict]) -> dict:
    out = dict(EMPTY)
    answers: dict[str, str] = {}
    current = None
    for turn in transcript:
        text = turn["text"].lower()
        if turn["role"] == "assistant":
            for field, keys in QUESTION_KEYS:
                if any(k in text for k in keys):
                    current = field
        elif turn["role"] == "user" and current:
            answers[current] = (answers.get(current, "") + " " + text).strip()

    for field, fn in CLASSIFIERS.items():
        if field in answers:
            out[field] = fn(" " + answers[field] + " ", True)
    if out["use_case"] is None and len(answers.get("use_case", "").split()) >= 4:
        out["use_case"] = "pilot"
    # Second pass: pick up answers volunteered out of order.
    for turn in transcript:
        if turn["role"] != "user":
            continue
        for field, fn in CLASSIFIERS.items():
            if out[field] is None:
                out[field] = fn(" " + turn["text"].lower() + " ", False)
    if "use_case" in answers:
        out["use_case_detail"] = answers["use_case"][:200]
    return out
