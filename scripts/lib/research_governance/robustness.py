"""Research governance — robustness checklist evaluator (PR-R1).

The single canonical evaluator for the robustness evidence checklist. The
method-specific governed robustness producer invokes this function over raw
checklist evidence; the promotion gate (RG-8) invokes the SAME function, so a
governed robustness result cannot diverge from what the gate actually checks.

Fail-closed checklist semantics:
  * a missing field fails;
  * PASS passes;
  * FAIL fails;
  * NOT_APPLICABLE is blocked for critical fields and requires a reason for
    conditional fields.
"""
from __future__ import annotations

from typing import Any, Mapping

ROBUSTNESS_FIELDS = [
    "sample_n", "benchmark", "subperiods", "regimes", "costs",
    "outlier_dependence", "lookahead_control", "survivorship_control", "limitations",
]

CRITICAL_NA_BLOCKED = {"sample_n", "benchmark", "lookahead_control", "limitations"}
CONDITIONAL_NA = {"survivorship_control", "costs", "outlier_dependence", "subperiods", "regimes"}


def evaluate_robustness(items: Mapping[str, Any]) -> list[str]:
    """Return the list of checklist problems ([] == fully satisfied)."""
    fails: list[str] = []
    for field in ROBUSTNESS_FIELDS:
        item = items.get(field)
        if item is None:
            fails.append(f"{field}:missing")
            continue
        state = getattr(item, "state", item) if not isinstance(item, str) else item
        if state == "PASS":
            continue
        if state == "FAIL":
            fails.append(f"{field}:FAIL")
            continue
        if state == "NOT_APPLICABLE":
            if field in CRITICAL_NA_BLOCKED:
                fails.append(f"{field}:NOT_APPLICABLE (critical, cannot be NA)")
            elif field in CONDITIONAL_NA:
                reason = getattr(item, "reason", "")
                if not reason:
                    fails.append(f"{field}:NOT_APPLICABLE without reason")
            else:
                fails.append(f"{field}:unknown state")
        else:
            fails.append(f"{field}:invalid state {state!r}")
    return fails
