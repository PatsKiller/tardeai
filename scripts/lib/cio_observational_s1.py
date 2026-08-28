"""Observational S1 for held equities with no open S1. Cap 5. No notify.

READ_ONLY_ADVISORY. Not eval_s1 (no invented PnL / basis). Draft only.
Skip CUSIP/CASH. Skip if an open S1 already exists for the symbol.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
S1 = "S1_POSITION_LIFECYCLE"
CAP = 5
DETECTOR_VERSION = "wave2-slice03-observational-s1"


def _iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()


def collect_held_without_open_s1(
    *,
    holdings: dict[str, Any] | None = None,
    plans: Any | None = None,
    root: Path | str | None = None,
    cap: int = CAP,
) -> dict[str, Any]:
    from scripts.lib.cio_investment_product import collect_holdings, held_equity_symbols

    if holdings is None:
        holdings = collect_holdings(root)
    held = list(held_equity_symbols(holdings))
    open_s1: set[str] = set()
    if plans is not None:
        try:
            rows = plans.list_open_plans(situation_type=S1, limit=400)
        except TypeError:
            rows = [
                p for p in (plans.list_open_plans(limit=400) or [])
                if p.get("situation_type") == S1
            ]
        for p in rows or []:
            for s in p.get("symbols") or []:
                if s:
                    open_s1.add(str(s).upper())
    would: list[dict[str, Any]] = []
    skipped_open: list[str] = []
    for sym in held:
        if sym in open_s1:
            skipped_open.append(sym)
            continue
        would.append({
            "symbol": sym,
            "situation_type": S1,
            "observational_only": True,
            "skip_reason": None,
            "class": "D",
        })
        if len(would) >= max(0, int(cap)):
            break
    return {
        "schema": "ObservationalS1Dry@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "held_n": len(held),
        "held": held,
        "open_s1_n": len(open_s1),
        "skipped_open_s1": skipped_open,
        "would_n": len(would),
        "would": would,
        "cap": int(cap),
        "notify": False,
        "memory_behavior_influence": 0,
    }


def candidate_for(symbol: str, *, now: datetime | None = None) -> dict[str, Any]:
    ts = now or datetime.now(timezone.utc)
    revisit = (ts + timedelta(hours=24)).replace(microsecond=0).isoformat()
    sym = str(symbol).upper()
    return {
        "situation_type": S1,
        "symbols": [sym],
        "title": f"S1 observational — {sym} held, no open plan",
        "summary": (
            f"{sym} is held with no open S1. Observational lifecycle note only. "
            "No order. No invented PnL."
        ),
        "options": [
            {"id": "keep_hold", "label": "Keep holding", "pros": "Already owned", "cons": "No new work"},
            {"id": "research", "label": "Queue research", "pros": "Fill thesis/plan hole", "cons": "Cost"},
        ],
        "recommendation": (
            f"{sym}: observational S1 because held-without-open-plan. Advisory only."
        ),
        "risks": ["Coverage hole, not a trade signal"],
        "evidence_refs": [{"domain": "holdings", "source": "holdings", "symbol": sym, "note": "held_equity"}],
        "revisit_at": revisit,
        "owner_agent": "alex",
        "status": "draft",
        "detector_version": DETECTOR_VERSION,
        "actor_id": "cio_observational_s1",
        "extra": {
            "observational_only": True,
            "fire_reasons": ["held_without_open_s1"],
            "shadow": True,
            "notify": False,
        },
    }


def apply_observational_s1(
    dry: dict[str, Any],
    *,
    plans: Any,
    apply: bool = False,
) -> dict[str, Any]:
    applied: list[dict[str, Any]] = []
    if apply:
        for row in dry.get("would") or []:
            cand = candidate_for(row["symbol"])
            extra = dict(cand.pop("extra") or {})
            plan = plans.create_plan(
                situation_type=cand["situation_type"],
                symbols=cand["symbols"],
                title=cand["title"],
                summary=cand["summary"],
                options=cand["options"],
                recommendation=cand["recommendation"],
                risks=cand["risks"],
                evidence_refs=cand["evidence_refs"],
                revisit_at=cand["revisit_at"],
                owner_agent=cand["owner_agent"],
                status=cand["status"],
                detector_version=cand["detector_version"],
                actor_id=cand["actor_id"],
                extra=extra,
            )
            applied.append({
                "symbol": row["symbol"],
                "plan_id": plan.get("plan_id"),
                "status": plan.get("status"),
                "observational_only": True,
            })
    return {
        "schema": "ObservationalS1Apply@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "notify": False,
        "would_n": int(dry.get("would_n") or 0),
        "applied_n": len(applied),
        "applied": applied,
        "would": dry.get("would") or [],
        "skipped_open_s1": dry.get("skipped_open_s1") or [],
    }
