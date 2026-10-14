"""Parse config/faq.md. The voice agent gets the whole file in its prompt; the
text fallback matches questions against each entry's keywords."""

from __future__ import annotations

import re

from .config import OUT_OF_SCOPE, load_faq_text


def entries() -> list[dict]:
    out = []
    for block in re.split(r"^## ", load_faq_text(), flags=re.M)[1:]:
        lines = [l for l in block.strip().splitlines() if l.strip()]
        q, rest = lines[0].strip(), lines[1:]
        kw = []
        if rest and rest[0].lower().startswith("keywords:"):
            kw = [k.strip().lower() for k in rest[0].split(":", 1)[1].split(",") if k.strip()]
            rest = rest[1:]
        out.append({"question": q, "keywords": kw, "answer": " ".join(rest).strip()})
    return out


def prompt_block() -> str:
    return "\n\n".join(f"Q: {e['question']}\nA: {e['answer']}" for e in entries())


QUESTION_START = re.compile(
    r"^(what|how|where|who|why|when|is|are|do|does|can|could|which|tell me)\b", re.I
)


def looks_like_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or bool(QUESTION_START.match(t))


def answer(text: str) -> str | None:
    """FAQ answer for a visitor question, OUT_OF_SCOPE for other questions, None if not a question."""
    if not looks_like_question(text):
        return None
    t = text.lower()
    best, hits = None, 0
    for e in entries():
        n = sum(1 for k in e["keywords"] if k in t)
        if n > hits:
            best, hits = e, n
    return best["answer"] if best else OUT_OF_SCOPE
