"""Deterministic lead scoring. Plain rules read from config/scoring.yaml, no LLM judgment."""

from __future__ import annotations

from .config import load_scoring

FIELDS = ["use_case", "company_size_band", "timeline", "current_stack", "role_type"]


def tier_for(score: int, tiers: dict) -> str:
    if score >= tiers["hot"]:
        return "Hot"
    if score >= tiers["warm"]:
        return "Warm"
    return "Low"


def score(extracted: dict, rubric: dict | None = None) -> dict:
    """Score extracted fields against the rubric.

    Returns {score, max_score, tier, breakdown: [{field, label, value, value_label, points, max}]}.
    A missing (null) or unrecognised value scores 0 for that line.
    """
    rubric = rubric or load_scoring()
    labels = rubric.get("value_labels", {})
    breakdown = []
    total = 0
    max_total = 0
    for field, crit in rubric["criteria"].items():
        points_map = {str(k): int(v) for k, v in crit["points"].items()}
        value = extracted.get(field)
        pts = points_map.get(str(value), 0) if value is not None else 0
        line_max = max(points_map.values()) if points_map else 0
        total += pts
        max_total += line_max
        breakdown.append(
            {
                "field": field,
                "label": crit.get("label", field),
                "value": value,
                "value_label": labels.get(str(value), value) if value is not None else None,
                "points": pts,
                "max": line_max,
            }
        )
    return {
        "score": total,
        "max_score": max_total,
        "tier": tier_for(total, rubric["tiers"]),
        "breakdown": breakdown,
    }


OUTCOME_BY_TIER = {"Hot": "meeting_offered", "Warm": "nurture", "Low": "resource"}
