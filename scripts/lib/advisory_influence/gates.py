"""Capability gates for ratified lessons and Financial Senses.

Modes: OFF | SHADOW | CANARY | ACTIVE_ADVISORY
Default OFF. No mode grants execution authority.
"""
from __future__ import annotations

import os
from typing import Any

MODES = ("OFF", "SHADOW", "CANARY", "ACTIVE_ADVISORY")
LESSON_FLAG = "RATIFIED_LESSON_ADVISORY_INFLUENCE"
FS_FLAG = "FINANCIAL_SENSES_ADVISORY_INFLUENCE"
ELIGIBLE_LESSON_STATES = frozenset({"RATIFIED_CONTEXT", "SHADOW_INFLUENCE", "ADVISORY_ACTIVE"})
FS_BLOCKING = frozenset({"NOT_CONFIGURED", "UNKNOWN", "STALE", "CONFLICT", "DENIED", "FAIL", "FAILED"})


def _mode(name: str, env: dict[str, str] | None = None) -> str:
    raw = str((env or os.environ).get(name) or "OFF").strip().upper()
    return raw if raw in MODES else "OFF"


def current_gates(env: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "lesson_mode": _mode(LESSON_FLAG, env),
        "financial_senses_mode": _mode(FS_FLAG, env),
        "memory_behavior_influence_untouched": True,
        "execution_authority": False,
        "contract": "advisory-influence-v1",
    }


def inject_lessons(mode: str) -> bool:
    return mode in {"SHADOW", "CANARY", "ACTIVE_ADVISORY"}


def present_enhanced(mode: str) -> bool:
    return mode in {"CANARY", "ACTIVE_ADVISORY"}


def lesson_eligible(state: str) -> bool:
    return str(state or "").upper() in ELIGIBLE_LESSON_STATES


def fs_receipt_eligible(rec: dict[str, Any]) -> bool:
    if not rec:
        return False
    status = str(rec.get("status") or rec.get("validation") or "").upper()
    if status in FS_BLOCKING or not rec.get("request_id"):
        return False
    if rec.get("quality_summary") in {"STALE", "UNKNOWN"} and status != "OK":
        return False
    return status in {"OK", "VALID", "PASS"}
