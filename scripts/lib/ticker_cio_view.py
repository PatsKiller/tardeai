"""The living CIO view of one ticker, from memory the house already holds.

Operator 2026-09-26: "many of these tickers should already have a CIO review on
file". They do -- HOOD, SPCX and V each had a current symbol thesis reviewed in
the last day, CIO decision rows and dozens of research runs -- but the options
card read none of it and said "CIO unreviewed". This assembles, per ticker:
the current symbol thesis, the latest CIO decision (with its source named), what
changed since the previous decision, and the research on file. Read-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[2]

# action_class -> who made the call, so a rule-engine row is never shown as a CIO judgment.
SOURCE_LABEL = {
    "options_thesis_review": "CIO review (options)",
    "entry_review": "CIO review (entry)",
}


def _source(row: dict[str, Any]) -> str:
    return SOURCE_LABEL.get(str(row.get("action_class") or ""), "rule engine")


def latest_decisions(symbol: str, execute: Optional[Callable[..., Any]] = None) -> list[dict[str, Any]]:
    try:
        if execute is None:
            from db_adapter import _execute as execute  # type: ignore
        rows = execute(
            """SELECT decision_id, action, action_class, rationale, created_at, confidence_calibrated
               FROM cio_decisions WHERE symbol=%s ORDER BY created_at DESC LIMIT 40""",
            (symbol.upper(),), fetch="all") or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def research_on_file(symbol: str, projection: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    try:
        proj = projection if projection is not None else json.loads(
            (_ROOT / "data" / "cio" / "hermes_research_projection.json").read_text(encoding="utf-8"))
    except Exception:
        return {"count": 0, "last_completed": None}
    n, last = 0, None
    sym = symbol.upper()
    for r in (proj.get("by_research_id") or {}).values():
        req = r.get("request") or {}
        syms = [str(x).upper() for x in (req.get("symbols") or r.get("symbols") or [])]
        if sym in syms:
            n += 1
            done = r.get("completed_ts")
            if done and (last is None or str(done) > str(last)):
                last = done
    return {"count": n, "last_completed": last}


def cio_view(symbol: str, thesis: dict[str, Any], *, decisions: Optional[list[dict[str, Any]]] = None,
             research: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    decisions = decisions if decisions is not None else latest_decisions(symbol)
    research = research if research is not None else research_on_file(symbol)
    latest = decisions[0] if decisions else None
    previous = next((d for d in decisions[1:] if latest and d.get("action") != latest.get("action")), None)
    has_thesis = bool(thesis.get("symbol_thesis_version")) and str(thesis.get("thesis_state") or "") not in ("INSUFFICIENT_DATA",)
    has_view = has_thesis or bool(latest) or research.get("count", 0) > 0
    return {
        "schema": "TickerCIOView@v1",
        "symbol": symbol.upper(),
        "has_view": has_view,
        "genuinely_new": not has_view,
        "thesis": {
            "pin": thesis.get("symbol_thesis_version"),
            "state": thesis.get("thesis_state"),
            "stance": thesis.get("thesis_stance"),
            "summary": (thesis.get("thesis_summary") or "")[:400] or None,
            "last_reviewed": thesis.get("last_reviewed"),
            "next_review_at": thesis.get("next_review_at"),
        } if has_thesis else None,
        "latest_decision": {
            "decision_id": latest.get("decision_id"),
            "recommendation": latest.get("action"),
            "rationale": (latest.get("rationale") or "")[:300],
            "at": str(latest.get("created_at")),
            "source": _source(latest),
        } if latest else None,
        "change_since_previous": ({
            "previous": previous.get("action"),
            "current": latest.get("action"),
            "previous_at": str(previous.get("created_at")),
        } if previous and latest else None),
        "research": research,
        "authority": "READ_ONLY_ADVISORY",
    }
