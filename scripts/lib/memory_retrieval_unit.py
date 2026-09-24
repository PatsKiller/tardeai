"""MemoryRetrievalUnit@v1 — bounded ASKU-equivalent for ContextEnvelope."""
from __future__ import annotations

import json
import os
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "MemoryRetrievalUnit@v1"
MODES = (
    "CURRENT",
    "HISTORICAL",
    "WHAT_CHANGED",
    "COUNTEREVIDENCE",
    "OPERATOR_MEMORY",
    "RESEARCH_EVIDENCE",
)


def from_fact(fact: dict[str, Any], *, mode: str, why_selected: str, scores: dict[str, float] | None = None) -> dict[str, Any]:
    if mode not in MODES:
        raise RuntimeError("UNKNOWN_RETRIEVAL_MODE")
    scores = scores or {}
    summary = fact.get("object")
    if not isinstance(summary, str):
        summary = str(summary)[:240]
    summary = summary[:500]
    return {
        "schema": SCHEMA,
        "memory_id": fact.get("memory_id"),
        "memory_version_id": fact.get("memory_version_id"),
        "subject_guid": fact.get("subject_guid"),
        "namespace": fact.get("namespace"),
        "content_summary": summary,
        "valid_from": fact.get("valid_from"),
        "valid_to": fact.get("valid_to"),
        "tx_from": fact.get("tx_from"),
        "tx_to": fact.get("tx_to"),
        "source_refs": [fact.get("source_id")],
        "evidence_refs": list(fact.get("evidence_refs") or []),
        "contradiction_refs": list(fact.get("contradiction_refs") or []),
        "authority": AUTHORITY,
        "confidence": fact.get("confidence"),
        "retrieval_score": float(scores.get("retrieval") or 0),
        "semantic_score": float(scores.get("semantic") or 0),
        "temporal_score": float(scores.get("temporal") or 0),
        "source_score": float(scores.get("source") or 0),
        "why_selected": why_selected,
        "token_estimate": max(1, len(summary) // 4),
        "mode": mode,
        "overrides_office_truth": False,
        "financial_action": False,
    }


# --- Context bounding (M5 Module 2.3) ------------------------------------
# Units enter a context envelope in priority order (highest first). The
# envelope keeps the longest priority prefix that fits the token budget and
# names every unit it dropped, so a bounded envelope is never a silent one.
TOKEN_BUDGET_ENV = "MEMORY_RETRIEVAL_TOKEN_BUDGET"
DEFAULT_TOKEN_BUDGET = 12000


def token_budget(budget: int | None = None) -> int:
    """Configured MRU token budget (``MEMORY_RETRIEVAL_TOKEN_BUDGET``, default 12000)."""
    if budget is not None:
        return max(0, int(budget))
    raw = str(os.environ.get(TOKEN_BUDGET_ENV) or "").strip()
    if not raw:
        return DEFAULT_TOKEN_BUDGET
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_TOKEN_BUDGET


def unit_token_estimate(unit: Any) -> int:
    """A unit's own ``token_estimate`` when it has one, else ~4 chars/token of its JSON."""
    if isinstance(unit, dict):
        est = unit.get("token_estimate")
        if isinstance(est, (int, float)) and not isinstance(est, bool) and est > 0:
            return int(est)
    return max(1, len(json.dumps(unit, default=str, sort_keys=True)) // 4)


def unit_ref(unit: Any, index: int) -> str:
    if isinstance(unit, dict):
        for key in ("memory_version_id", "memory_id", "receipt_id", "id", "symbol"):
            if unit.get(key):
                return str(unit[key])
    return f"#{index}"


def enforce_token_budget(units: list[Any] | None, *, budget: int | None = None) -> dict[str, Any]:
    """Keep the highest-priority prefix of ``units`` that fits the budget.

    ``units`` must already be in priority order. Returns the kept units, the
    refs of every dropped unit (``dropped_for_budget``), the tokens used and
    the budget applied.
    """
    limit = token_budget(budget)
    kept: list[Any] = []
    dropped: list[str] = []
    used = 0
    full = False
    for i, unit in enumerate(units or []):
        est = unit_token_estimate(unit)
        if full or used + est > limit:
            full = True
            dropped.append(unit_ref(unit, i))
            continue
        kept.append(unit)
        used += est
    return {"units": kept, "dropped_for_budget": dropped, "token_estimate": used, "token_budget": limit}
