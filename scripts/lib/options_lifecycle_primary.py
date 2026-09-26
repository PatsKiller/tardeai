"""One primary lifecycle bucket per strategy. Other matches are subordinate."""
from __future__ import annotations

from typing import Any

ORDER = ("blocked", "action_now", "harvest", "defend", "expiry", "mature")


def _matches(position: dict[str, Any]) -> list[str]:
    decision = position.get("decision") or {}
    rec = str(decision.get("recommendation") or "")
    econ = position.get("economics") or {}
    dte = econ.get("dte_nearest")
    try:
        dte_n = float(dte) if dte is not None else 99.0
    except (TypeError, ValueError):
        dte_n = 99.0
    found = []
    if rec == "DATA_BLOCKED":
        found.append("blocked")
    if decision.get("urgency") == "red":
        found.append("action_now")
    if rec.startswith("HARVEST"):
        found.append("harvest")
    if rec in {"DEFEND", "ROLL"}:
        found.append("defend")
    if dte_n <= 7 or rec in {"ACCEPT_ASSIGNMENT", "EXERCISE_REVIEW"}:
        found.append("expiry")
    if rec in {"LET_MATURE", "HOLD"}:
        found.append("mature")
    return found


def primary_bucket(position: dict[str, Any]) -> str:
    found = _matches(position)
    for key in ORDER:
        if key in found:
            return key
    return "mature"


def subordinate_buckets(position: dict[str, Any]) -> list[str]:
    primary = primary_bucket(position)
    return [k for k in _matches(position) if k != primary]
