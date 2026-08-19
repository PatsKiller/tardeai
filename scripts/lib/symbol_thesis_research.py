"""Specific thesis → research-gap work generation (dry by default).

Reuses ResearchNeedDecision + Hermes capacity rules. Does NOT enqueue all
5,010 INSUFFICIENT_DATA watchlist rows. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.research_need_decision import decide as decide_research_need
from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol, watchlist_materiality
from scripts.lib.symbol_thesis_coverage import (
    build_coverage_report,
    research_gap_triggers,
    symbol_thesis_id,
)

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisResearchRequest@v1"

# Priority bands (prompt §J)
PRIORITY_ORDER = ("P0", "P1", "P2", "P3")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _specific_question(symbol: str, gap: str, *, memberships: list[str], role: str, thesis_state: str) -> str:
    """Turn a coverage gap string into a concrete unanswered investment question."""
    g = (gap or "").lower()
    memb = set(memberships or [])
    if "conflict" in g or thesis_state == "CONFLICTED":
        return (
            f"Why is {symbol} currently held while thesis stance conflicts? "
            f"What evidence resolves hold vs avoid for role={role}?"
        )
    if "stale" in g or thesis_state == "STALE":
        return (
            f"What material facts changed for {symbol} since last thesis review? "
            f"Does the living thesis still justify current memberships={sorted(memb)}?"
        )
    if "re-entry" in g or "reentry" in g or ("REENTRY" in memb and "missing" in g):
        return (
            f"For former holding {symbol}: why was it owned, why exited, is the thesis intact, "
            f"and what specific evidence would move NEAR→RE_ENTER without bypassing gates?"
        )
    if "role" in g and "unknown" in g:
        return (
            f"What portfolio role should {symbol} occupy (CORE/GROWTH/INCOME/SATELLITE/HEDGE) "
            f"and what operator/historical evidence supports it?"
        )
    # Prefer full living-thesis creation over narrow invalidation-only wording
    if (
        "why owned" in g or "why exit" in g or "living thesis" in g
        or "missing" in g or g.startswith("create ")
    ):
        if "HELD" in memb:
            return (
                f"Why is {symbol} still held (role={role})? State positive case, counter-thesis, "
                f"and what would justify ADD vs TRIM vs EXIT."
            )
        if "REENTRY" in memb or "FORMER_HOLDING" in memb:
            return (
                f"Build living exit/re-entry thesis for {symbol}: why previously owned, why exited, "
                f"what changed since exit, market/sector fit, and research gaps."
            )
        if "OPPORTUNITY" in memb:
            return (
                f"What specific thesis would make {symbol} actionable vs WATCH? "
                f"List unresolved evidence domains blocking ADD/REENTER."
            )
        return (
            f"Create a living symbol thesis for {symbol}: memberships={sorted(memb)}, "
            f"role={role}, stance, invalidation, counter-thesis, research gaps."
        )
    if "invalidation" in g or "what changes" in g:
        return (
            f"What explicit invalidation conditions and 'what changes my mind' criteria "
            f"should govern {symbol} for role={role}?"
        )
    # Fallback — still specific, never "research SCHG"
    return (
        f"For {symbol} (state={thesis_state}, role={role}): resolve gap — {gap[:160]}"
    )


def _priority_band(
    *,
    memberships: list[str],
    thesis_state: str,
    reentry_state: str | None,
    opportunity_rank: Any,
    materiality: str,
) -> str:
    m = set(memberships or [])
    # P0 material contradiction in current holding
    if "HELD" in m and thesis_state == "CONFLICTED":
        return "P0"
    # P1 material current-holding thesis gap
    if "HELD" in m and thesis_state in {"RESEARCH_REQUIRED", "STALE", "INSUFFICIENT_DATA"}:
        return "P1"
    # P1 re-entry candidate near actionable zone
    rs = str(reentry_state or "").upper()
    if ("REENTRY" in m or "FORMER_HOLDING" in m) and any(
        x in rs for x in ("NEAR", "READY", "IN_ZONE", "REENTER")
    ):
        return "P1"
    # P1 high-ranked opportunity with missing evidence
    try:
        rank = int(opportunity_rank) if opportunity_rank is not None else 999
    except (TypeError, ValueError):
        rank = 999
    if "OPPORTUNITY" in m and rank <= 20 and thesis_state in {
        "RESEARCH_REQUIRED", "STALE", "CONFLICTED", "INSUFFICIENT_DATA"
    }:
        return "P1"
    # P2 material watchlist thesis review
    if materiality in {"ACTIVE_MATERIAL", "ACTIVE_LOW_PRIORITY"} and "WATCHLIST" in m:
        return "P2"
    # P3 discovery
    return "P3"


def _domains_for_gap(gap: str, memberships: list[str]) -> list[str]:
    g = (gap or "").lower()
    domains = ["fundamentals", "valuation"]
    if "re-entry" in g or "reentry" in g or "REENTRY" in memberships:
        domains.extend(["exit_history", "technical_zone", "market_temperament"])
    if "conflict" in g or "counter" in g:
        domains.append("bear_case")
    if "role" in g:
        domains.append("portfolio_role")
    if "stale" in g:
        domains.extend(["news", "earnings"])
    if "HELD" in memberships:
        domains.append("position_management")
    # dedupe preserve order
    seen = set()
    out = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def build_research_request(
    symbol: str,
    *,
    gap: str,
    thesis_fields: dict[str, Any],
    coverage_row: Optional[dict[str, Any]] = None,
    parent_run: str | None = None,
    parent_product: str | None = None,
    budget_revisit_hours: int = 72,
) -> dict[str, Any]:
    """One specific research request — never vague 'research SCHG'."""
    cov = coverage_row or {}
    memberships = list(thesis_fields.get("memberships") or cov.get("memberships") or [])
    role = str(thesis_fields.get("portfolio_role") or "UNKNOWN")
    thesis_state = str(thesis_fields.get("thesis_state") or cov.get("coverage_state") or "INSUFFICIENT_DATA")
    materiality = watchlist_materiality(
        memberships,
        thesis_state=thesis_state,
        opp_rank=cov.get("opportunity_rank") or thesis_fields.get("opportunity_rank"),
    )
    priority = _priority_band(
        memberships=memberships,
        thesis_state=thesis_state,
        reentry_state=cov.get("reentry_state") or thesis_fields.get("reentry_state"),
        opportunity_rank=cov.get("opportunity_rank"),
        materiality=materiality,
    )
    question = _specific_question(
        symbol, gap, memberships=memberships, role=role, thesis_state=thesis_state
    )
    need = decide_research_need({
        "symbol": symbol,
        "held": "HELD" in memberships,
        "material": materiality == "ACTIVE_MATERIAL",
        "contradictions": thesis_state == "CONFLICTED",
        "research_complete": False,
        "questions": [{"dim": "thesis_gap", "q": question}],
    })
    req_id = "str_" + _digest(symbol, gap, thesis_fields.get("symbol_thesis_version"), question)
    return {
        "schema": SCHEMA,
        "request_id": req_id,
        "symbol": symbol.upper(),
        "thesis_id": thesis_fields.get("symbol_thesis_id") or symbol_thesis_id(symbol),
        "thesis_version": thesis_fields.get("symbol_thesis_version"),
        "research_gap": gap,
        "specific_question": question,
        "why_needed": (
            f"thesis_state={thesis_state}; memberships={sorted(set(memberships))}; "
            f"role={role}; materiality={materiality}"
        ),
        "priority": priority,
        "required_evidence_domains": _domains_for_gap(gap, memberships),
        "current_stance": thesis_fields.get("thesis_stance"),
        "counter_thesis": thesis_fields.get("counter_evidence") or [],
        "requested_at": _now(),
        "parent_run": parent_run,
        "parent_product": parent_product,
        "budget_revisit_hours": budget_revisit_hours if priority != "P0" else 24,
        "research_need_decision": need.get("decision"),
        "materiality": materiality,
        "enqueue": False,  # dry by default
        "authority": AUTHORITY,
        "financial_action": False,
    }


def propose_prioritized_research(
    *,
    root: Path | str | None = None,
    material_only: bool = True,
    max_p3: int = 5,
    limit: int = 40,
    parent_run: str | None = None,
    parent_product: str | None = None,
) -> dict[str, Any]:
    """Build a DRY prioritized research set. Does not enqueue Hermes jobs.

    Explicitly skips flooding discovery-only INSUFFICIENT_DATA rows.
    """
    root = _root(root)
    report = build_coverage_report(root=root, material_only=False)
    triggers = research_gap_triggers(report, limit=500)

    requests: list[dict[str, Any]] = []
    skipped_discovery = 0
    p3_count = 0

    # Index coverage rows
    by_sym = {r["symbol"]: r for r in (report.get("rows") or [])}

    for t in triggers:
        sym = t["symbol"]
        cov = by_sym.get(sym) or {}
        memberships = list(cov.get("memberships") or [])
        thesis_state = str(cov.get("coverage_state") or "")
        materiality = watchlist_materiality(
            memberships,
            thesis_state=thesis_state,
            opp_rank=cov.get("opportunity_rank"),
        )
        # Hard gate: do not auto-spawn research for discovery-only watchlist
        if materiality == "DISCOVERY_ONLY" and thesis_state == "INSUFFICIENT_DATA":
            skipped_discovery += 1
            continue
        if material_only and materiality not in {"ACTIVE_MATERIAL", "ACTIVE_LOW_PRIORITY", "RESEARCH_REQUIRED"}:
            # RESEARCH_REQUIRED materiality helper returns ACTIVE_* for held/reentry/opp
            if not cov.get("material"):
                skipped_discovery += 1
                continue

        fields = thesis_fields_for_symbol(sym, root=root)
        gaps = list(t.get("research_gaps") or fields.get("research_gaps") or [])
        if not gaps:
            gaps = ["Create living symbol thesis with invalidation and counter-thesis"]

        # One primary request per symbol (first/highest gap) to avoid spam
        primary_gap = gaps[0]
        req = build_research_request(
            sym,
            gap=primary_gap,
            thesis_fields=fields,
            coverage_row=cov,
            parent_run=parent_run,
            parent_product=parent_product,
        )
        if req["priority"] == "P3":
            if p3_count >= max_p3:
                skipped_discovery += 1
                continue
            p3_count += 1
        requests.append(req)
        if len(requests) >= limit:
            break

    # Sort P0 → P3, then symbol
    rank = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    requests.sort(key=lambda r: (rank.get(r["priority"], 9), r["symbol"]))

    by_pri: dict[str, int] = {p: 0 for p in PRIORITY_ORDER}
    for r in requests:
        by_pri[r["priority"]] = by_pri.get(r["priority"], 0) + 1

    return {
        "schema": "SymbolThesisResearchProposal@v1",
        "as_of": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "enqueued": False,
        "note": (
            "DRY proposal only — no Hermes enqueue, no production thesis backfill. "
            "Discovery-only INSUFFICIENT_DATA rows are not auto-queued."
        ),
        "counts": {
            "proposed": len(requests),
            "skipped_discovery_or_capped": skipped_discovery,
            "by_priority": by_pri,
            "universe_rows": (report.get("coverage_counts") or {}).get("rows"),
            "research_required_material": (report.get("coverage_counts") or {}).get("RESEARCH_REQUIRED"),
        },
        "requests": requests,
        "coverage_counts": report.get("coverage_counts"),
    }


def research_requests_for_symbol(
    symbol: str,
    *,
    root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """All specific gaps for one symbol (dry)."""
    root = _root(root)
    fields = thesis_fields_for_symbol(symbol, root=root)
    gaps = list(fields.get("research_gaps") or [])
    if not gaps and fields.get("thesis_state") in {
        "RESEARCH_REQUIRED", "STALE", "CONFLICTED", "INSUFFICIENT_DATA"
    }:
        gaps = [f"Living thesis incomplete ({fields.get('thesis_state')})"]
    return [
        build_research_request(symbol, gap=g, thesis_fields=fields)
        for g in gaps
    ]
