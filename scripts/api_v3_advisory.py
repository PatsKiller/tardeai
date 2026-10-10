"""api_v3_advisory.py — /api/v3/advisory Command Center + feedback API.

READ_ONLY_ADVISORY. Zero broker authority.

Routes:
  GET  /api/v3/advisory              — desk snapshot + banners + synthesis
  GET  /api/v3/advisory/rows         — rows only (optional ?class=holding)
  GET  /api/v3/advisory/brief        — Telegram-sized brief (≤5 lines body)
  POST /api/v3/advisory/rate         — {row_id|symbol, rating, reason_code?, note?}
  POST /api/v3/advisory/ack          — {row_id|symbol}
  POST /api/v3/advisory/snooze       — {row_id|symbol}
  POST /api/v3/advisory/run-now      — rebuild facts + Flash/Pro (paid, advisory)
  GET  /api/v3/advisory/run-status   — last/current run-now state + next scheduled
  GET  /api/v3/advisory/calibration  — outcome calibration
  GET  /api/v3/advisory/history/{symbol} — prior + feedback
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "data" / "runtime" / "advisory_desk_latest.json"
OPINIONS_CACHE = PROJECT_ROOT / "data" / "runtime" / "advisory_opinion_cache.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _watch_hub_counts() -> dict[str, Any]:
    """Lazy Watch Hub counts for the chip labels. Never raises.

    The Advisory watch class is the *personal* watchlist.json; the Hub is the
    larger DB universe. Surface both so the operator sees the desk is a small
    intentional subset, not the full Hub.

    ``active`` is the material, actively-managed Hub set (the same pool the
    hub opportunity slice draws from). ``universe`` is the broader watchable
    set (active + researched), excluding removed names.
    """
    try:
        from db_adapter import _execute
        active = _execute(
            "SELECT count(DISTINCT symbol) AS n FROM watchlist_items "
            "WHERE status = 'active'",
            fetch="one",
        ) or {}
        universe = _execute(
            "SELECT count(DISTINCT symbol) AS n FROM watchlist_items "
            "WHERE status IN ('active','researched')",
            fetch="one",
        ) or {}
        return {
            "active": int(active.get("n") or 0),
            "universe": int(universe.get("n") or 0),
            "universe_is_not_canonical": True,
            "cohort": "watchlist_items_active_plus_researched",
            "canonical_contract": "TransfersonUniverseManifest@v1",
        }
    except Exception:
        return {"active": None, "universe": None}


def _verdict_str(v: Any) -> str:
    if hasattr(v, "value"):
        return str(v.value)
    return str(v or "")


def build_symbol_thesis_context(
    symbol: str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Return the governed thesis and latest research delta used by advisory."""
    from scripts.lib.research_prompt_context import latest_delta
    from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol

    base = Path(root) if root is not None else PROJECT_ROOT
    sym = str(symbol or "").upper().strip()
    fields = thesis_fields_for_symbol(sym, root=base) if sym else {}
    delta = latest_delta(sym, root=base) if sym else None
    thesis = {
        "thesis_id": fields.get("symbol_thesis_id"),
        "thesis_version": fields.get("symbol_thesis_version"),
        "state": fields.get("thesis_state"),
        "stance": fields.get("thesis_stance"),
        "summary": fields.get("thesis_summary"),
        "confidence": fields.get("thesis_confidence"),
        "evidence_for": fields.get("evidence_for") or [],
        "counter_evidence": fields.get("counter_evidence") or [],
        "invalidation_conditions": fields.get("invalidation_conditions") or [],
        "research_gaps": fields.get("research_gaps") or [],
        "last_reviewed": fields.get("last_reviewed"),
        "fresh": bool(fields.get("fresh")),
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }
    delta_context = None
    if isinstance(delta, dict):
        delta_context = {
            "delta_id": delta.get("delta_id"),
            "research_id": delta.get("research_id"),
            "classification": delta.get("classification"),
            "evidence_as_of": delta.get("evidence_as_of"),
            "freshness": delta.get("freshness"),
        }
    return {
        **thesis,
        "research_delta": delta_context,
    }


def compute_banners(meta: dict[str, Any], data: dict[str, Any]) -> list[dict[str, str]]:
    """Banner states for the desk surface (5 health + optional DATA CONFLICT)."""
    banners: list[dict[str, str]] = []
    conflicted_n = int(meta.get("conflicted_count") or 0)
    conflicted_syms = [str(s) for s in (meta.get("conflicted_symbols") or []) if s]
    if conflicted_n > 0 or conflicted_syms:
        shown = ", ".join(conflicted_syms[:8])
        extra = f" (+{conflicted_n - 8} more)" if conflicted_n > 8 else ""
        banners.append({
            "id": "DATA_CONFLICT",
            "severity": "critical",
            "title": "DATA CONFLICT — ACTION SUPPRESSED",
            "detail": (
                f"{conflicted_n or len(conflicted_syms)} row(s) have conflicting "
                f"marks/MV/targets{': ' + shown if shown else ''}{extra}"
            ),
        })
    # 1 Desk health — validation_ok + plausibility is NOT sufficient.
    health = (data.get("desk_health") or meta.get("desk_health") or {})
    overall = str(health.get("overall") or "")
    if not overall:
        # Fallback only when operator enrichment has not run.
        if meta.get("validation_ok") and meta.get("plausibility_gate") == "PASS":
            overall = "UNKNOWN"
        else:
            overall = "FAILED"
    if overall == "HEALTHY":
        banners.append({
            "id": "OK",
            "severity": "info",
            "title": "Desk HEALTHY",
            "detail": health.get("reason") or f"{meta.get('holdings_rows', 0)} holdings · facts current · validation PASS",
        })
    elif overall == "STALE":
        banners.append({
            "id": "DESK_STALE",
            "severity": "warn",
            "title": "Desk STALE",
            "detail": health.get("reason") or "Facts or cache older than policy — not current",
        })
    elif overall == "PARTIAL":
        banners.append({
            "id": "DESK_PARTIAL",
            "severity": "warn",
            "title": "Desk PARTIAL",
            "detail": health.get("reason") or "Some source families incomplete",
        })
    elif overall == "DEGRADED":
        banners.append({
            "id": "DESK_DEGRADED",
            "severity": "warn",
            "title": "Desk DEGRADED",
            "detail": health.get("reason") or "Opinions or secondary providers stale",
        })
    elif overall == "FAILED":
        banners.append({
            "id": "VALIDATION_FAIL",
            "severity": "critical",
            "title": "Desk FAILED",
            "detail": health.get("reason") or "; ".join((meta.get("validation_errors") or [])[:3]) or "validation_ok=false",
        })
    else:
        banners.append({
            "id": "DESK_UNKNOWN",
            "severity": "warn",
            "title": f"Desk {overall or 'UNKNOWN'}",
            "detail": health.get("reason") or "Operator health not attached — do not assume healthy",
        })
    # 2 Plausibility
    if meta.get("plausibility_gate") == "FAIL":
        banners.append({
            "id": "PLAUSIBILITY_FAIL",
            "severity": "critical",
            "title": "Plausibility gate FAIL",
            "detail": "Actionable verdict distribution or weight sum out of bounds",
        })
    else:
        banners.append({
            "id": "PLAUSIBILITY_OK",
            "severity": "info",
            "title": "Plausibility PASS",
            "detail": "Verdict mix and weight sum within bounds",
        })
    # 3 Untrusted lots
    n_untrusted = int(meta.get("untrusted_lot_count") or 0)
    if n_untrusted > 0:
        banners.append({
            "id": "UNTRUSTED_LOTS",
            "severity": "warn",
            "title": f"{n_untrusted} UNTRUSTED lot rows",
            "detail": "Signals from failed lot data are suppressed",
        })
    else:
        banners.append({
            "id": "LOTS_OK",
            "severity": "info",
            "title": "Lot data trusted",
            "detail": "No UNTRUSTED lot_data_status on holdings",
        })
    # 4 LLM / flag
    llm = bool(data.get("llm_in_path"))
    try:
        from lib.advisory.advisory_opinion_engine import _load_config
        from lib.data_broker.advisory_desk import _advisory_desk_v1_enabled
        flag = _advisory_desk_v1_enabled(_load_config())
    except Exception:
        flag = False
    if not flag:
        banners.append({
            "id": "LLM_OFF",
            "severity": "warn",
            "title": "ADVISORY_DESK_V1 off",
            "detail": "Deterministic desk only — Flash/Pro enrichment disabled",
        })
    elif not llm:
        banners.append({
            "id": "LLM_DRY",
            "severity": "warn",
            "title": "No LLM opinions on snapshot",
            "detail": "Run enrich_advisory_with_opinions with flag ON for Flash/Pro",
        })
    else:
        banners.append({
            "id": "LLM_ON",
            "severity": "info",
            "title": "LLM opinions in path",
            "detail": "Flash row opinions and/or Pro synthesis present",
        })
    # 5 Invariants
    n_inv = int(meta.get("invariant_violation_count") or 0)
    if n_inv > 0:
        banners.append({
            "id": "INVARIANT_VIOLATIONS",
            "severity": "critical",
            "title": f"{n_inv} external invariant violations",
            "detail": "Rows forced to INSUFFICIENT_DATA where applicable",
        })
    else:
        banners.append({
            "id": "INVARIANTS_OK",
            "severity": "info",
            "title": "External invariants green",
            "detail": "0 listing/price/basis reality failures",
        })
    # Base contract is 5 health banners; DATA CONFLICT may prepend a 6th.
    cap = 6 if banners and banners[0].get("id") == "DATA_CONFLICT" else 5
    return banners[:cap]


def _split_rationale_signals(raw: str) -> list[str]:
    """Deterministic split of the pipe-joined rationale into clean, deduped signals."""
    if not raw:
        return []
    seen: list[str] = []
    for part in str(raw).split("|"):
        s = part.strip().rstrip(" —").strip()
        if not s or s in seen:
            continue
        seen.append(s)
    return seen


def _ensure_row_provenance(row: dict[str, Any], analyst: dict[str, Any] | None) -> dict[str, Any]:
    """Idempotent attach so cached desk payloads still grow expand.provenance."""
    pre = row.get("expand") if isinstance(row.get("expand"), dict) else {}
    if pre.get("canonical_financial_facts") and pre.get("advisory_provenance"):
        return row
    if row.get("canonical_financial_facts") and row.get("advisory_provenance"):
        expand = dict(pre)
        expand.setdefault("canonical_financial_facts", row["canonical_financial_facts"])
        expand.setdefault("advisory_provenance", row["advisory_provenance"])
        if analyst and not expand.get("analyst"):
            expand["analyst"] = analyst
        row["expand"] = expand
        return row
    try:
        from lib.data_broker.advisory_desk import attach_advisory_row_provenance
        return attach_advisory_row_provenance(row, analyst=analyst)
    except Exception:
        try:
            from lib.cio_advisory_provenance import attach_expand_provenance
            return attach_expand_provenance(row, analyst=analyst)
        except Exception:
            return row


def _row_view(row: dict[str, Any], opinions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Surface-friendly row with expand payload + data_quality column."""
    opinions = opinions or {}
    rh = str(row.get("advisory_row_hash") or "")
    eb = row.get("evidence_bundle") or {}
    items = eb.get("evidence_items") or []
    gaps = eb.get("evidence_gaps") or []
    opinion = opinions.get(rh) if rh else None
    if not opinion and isinstance(opinions.get("rows"), dict):
        opinion = opinions["rows"].get(rh)

    lot = row.get("lot_basis") or {}
    pa = row.get("price_action") or {}
    pre_expand = row.get("expand") if isinstance(row.get("expand"), dict) else {}
    # Prefer attached analyst (honest denominators) over raw evidence item
    analyst = pre_expand.get("analyst") or row.get("analyst")
    if not isinstance(analyst, dict):
        analyst = next((i for i in items if isinstance(i, dict) and i.get("type") == "analyst_context"), None)
    row = _ensure_row_provenance(row, analyst if isinstance(analyst, dict) else None)
    pre_expand = row.get("expand") if isinstance(row.get("expand"), dict) else {}
    facts = pre_expand.get("canonical_financial_facts") or row.get("canonical_financial_facts")
    provenance = pre_expand.get("advisory_provenance") or row.get("advisory_provenance")
    analyst = pre_expand.get("analyst") or analyst
    if isinstance(pre_expand.get("price_action"), dict):
        pa = {**pa, **pre_expand["price_action"]}

    memory = row.get("memory") or {}
    if opinion and opinion.get("thrash_penalty"):
        memory = {
            **memory,
            "thrash_penalty": opinion.get("thrash_penalty"),
            "conviction": opinion.get("conviction"),
            "conviction_pre_thrash": opinion.get("conviction_pre_thrash"),
        }

    conflicts = []
    if isinstance(facts, dict):
        conflicts.extend(facts.get("conflicts") or [])
    if isinstance(provenance, dict):
        for c in provenance.get("conflicts") or []:
            if c not in conflicts:
                conflicts.append(c)
    action_suppressed = bool(
        (isinstance(facts, dict) and facts.get("action_suppressed"))
        or (isinstance(provenance, dict) and provenance.get("action_suppressed"))
        or conflicts
    )
    quality = None
    if isinstance(facts, dict):
        quality = facts.get("quality")
    elif isinstance(row.get("data_quality"), dict):
        quality = row["data_quality"].get("quality")

    dq = {
        "evidence_count": eb.get("evidence_count") if eb.get("evidence_count") is not None else len(items),
        "evidence_gaps": gaps,
        "gap_count": len(gaps),
        "sufficient": bool(eb.get("sufficient")),
        "lot_data_status": row.get("lot_data_status") or lot.get("lot_data_status") or "",
        "invariant_violations": row.get("invariant_violations") or [],
        "basis_partial": bool(row.get("basis_partial")),
        "conflicts": conflicts,
        "quality": quality,
        "action_suppressed": action_suppressed,
    }
    if action_suppressed:
        dq["banner"] = "DATA CONFLICT — ACTION SUPPRESSED"

    operator = row.get("operator") if isinstance(row.get("operator"), dict) else {}
    watch = row.get("watch_intelligence") or operator.get("watch_intelligence")
    reentry = row.get("reentry") or operator.get("reentry")
    durable = row.get("durable_memory") or operator.get("durable_memory")
    senses = row.get("financial_senses") or operator.get("financial_senses")
    field_states = row.get("field_states") or operator.get("field_states")
    thesis = build_symbol_thesis_context(str(row.get("symbol") or ""))
    latest_research_delta = thesis.get("research_delta") or {}
    decision_delta = (
        row.get("research_delta")
        if isinstance(row.get("research_delta"), dict)
        else latest_research_delta
    )
    return {
        "symbol": row.get("symbol"),
        "account": row.get("account"),
        "row_class": row.get("row_class"),
        "verdict": _verdict_str(row.get("verdict")),
        "verdict_suppressed": bool(row.get("verdict_suppressed")),
        "verdict_suppressed_reason": row.get("verdict_suppressed_reason"),
        "trim_kind": row.get("trim_kind"),
        "housekeeping_flag": bool(row.get("housekeeping_flag")),
        "housekeeping_reason": row.get("housekeeping_reason"),
        "confidence": row.get("confidence"),
        "setup_state": row.get("setup_state") or operator.get("setup_state"),
        "setup_confidence": row.get("setup_confidence"),
        "watch_filters": row.get("watch_filters") or operator.get("watch_filters") or [],
        "watch_rank": row.get("watch_rank") if row.get("watch_rank") is not None else operator.get("watch_rank"),
        "market_value": row.get("market_value"),
        "weight_pct": row.get("weight_pct"),
        "gain_loss_pct": row.get("gain_loss_pct"),
        "days_held": row.get("days_held"),
        "holding_period": row.get("holding_period"),
        "adjusted_cost": row.get("adjusted_cost"),
        "cost_basis_source": row.get("cost_basis_source"),
        "rationale": row.get("rationale"),
        "rationale_signals": _split_rationale_signals(row.get("rationale") or ""),
        "risk_signals": row.get("risk_signals") or [],
        "why_call": row.get("why_call") or operator.get("why_call"),
        "advisory_row_hash": rh,
        "row_id": f"{row.get('symbol')}:{row.get('account') or ''}|{(row.get('computed_at') or '')[:10]}|{rh[:12]}",
        "data_quality": dq,
        "canonical_financial_facts": facts,
        "advisory_provenance": provenance,
        "field_states": field_states,
        "watch_intelligence": watch,
        "reentry": reentry,
        "reentry_state": row.get("reentry_state"),
        "reentry_entry_low": row.get("reentry_entry_low"),
        "reentry_entry_high": row.get("reentry_entry_high"),
        "reentry_price": row.get("reentry_price"),
        "reentry_rsi": row.get("reentry_rsi"),
        "reentry_distance_label": row.get("reentry_distance_label"),
        "reentry_next_action": row.get("reentry_next_action"),
        "reentry_reason": row.get("reentry_reason"),
        "reentry_wash_status": row.get("reentry_wash_status"),
        "durable_memory": durable,
        "financial_senses": senses,
        "symbol_thesis": thesis,
        "decision_context": {
            "decision_id": row.get("decision_id"),
            "thesis_id": thesis.get("thesis_id"),
            "thesis_version": thesis.get("thesis_version"),
            "research_delta_id": decision_delta.get("delta_id"),
            "research_delta_classification": decision_delta.get("classification"),
            "research_delta": decision_delta or None,
            "authority": "READ_ONLY_ADVISORY",
            "financial_action": False,
        },
        "operator": operator,
        "expand": {
            "lots": lot,
            "canonical_financial_facts": facts,
            "advisory_provenance": provenance,
            "price_action": pa,
            "analyst": analyst,
            "memory": memory,
            "durable_memory": durable,
            "financial_senses": senses,
            "watch_intelligence": watch,
            "reentry": reentry,
            "field_states": field_states,
            "evidence_items": items[:20],
            "opinion": opinion,
            "instrument": row.get("instrument"),
        },
    }


def _load_desk(*, force: bool = False) -> dict[str, Any]:
    """Honor advisory_desk.DEFAULT_MAX_AGE_S. Never serve a day-old ok=true blob."""
    from lib.data_broker.advisory_desk import DEFAULT_MAX_AGE_S, build_advisory_desk
    try:
        desk = build_advisory_desk(force=force, max_age_s=0 if force else DEFAULT_MAX_AGE_S)
    except Exception:
        # Last resort: labeled stale cache only when recompute is impossible.
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(cached, dict):
                    cached["cache_hit"] = True
                    cached["stale_fallback"] = True
                    cached["desk_freshness_state"] = "EXPIRED"
                    return cached
            except Exception:
                pass
        raise
    return desk


def _load_opinions_blob() -> dict[str, Any]:
    """Opinions may live on desk cache, the live enrichment artifact, or the
    per-row opinion cache file (in that preference order)."""
    try:
        from lib.data_broker.advisory_desk import OPINIONS_LATEST_FILE

        if OPINIONS_LATEST_FILE.exists():
            d = json.loads(OPINIONS_LATEST_FILE.read_text(encoding="utf-8"))
            if d.get("rows") or d.get("synthesis"):
                return d
    except Exception:
        pass
    try:
        if CACHE_FILE.exists():
            d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if d.get("opinions"):
                return d["opinions"]
    except Exception:
        pass
    try:
        if OPINIONS_CACHE.exists():
            rows = json.loads(OPINIONS_CACHE.read_text(encoding="utf-8"))
            if isinstance(rows, dict):
                return {"rows": rows}
    except Exception:
        pass
    return {}


# Run-now refresh audit (scripts/lib/advisory_desk_schedule.py::_execute_run):
# run-now calls build_advisory_desk(force=True, max_age_s=0) — which re-reads
# holdings.json, indicator_confluence_cache, analyst/Hermes/agent DB rows and
# the re-entry artifact without running any producer — and then
# enrich_advisory_with_opinions(include_synthesis=True), which writes the
# Flash opinions + Pro synthesis.  Only the synthesis clock can advance
# because of run-now.  tests/test_cio_advisory_dependency_clocks_20261002.py
# pins this audit against the _execute_run source.
RUN_NOW_REFRESHES: dict[str, bool] = {
    "advisory_synthesis": True,
    "technicals": False,
    "prices": False,
    "watch_intelligence": False,
    "reentry": False,
    "analyst_data": False,
    "research": False,
    "hermes_research": False,
    "durable_memory": False,
}

# Declared producer lanes (config/lane_registry.json) per dependency clock.
# Empty = no lane declares the producer; next_scheduled_run is null + reason.
DEPENDENCY_LANES: dict[str, tuple[str, ...]] = {
    "technicals": ("indicator-cache-refresh",),
    "prices": ("portfolio-repricer",),
    "watch_intelligence": ("watch-review-workers", "watch-review-workers-cio"),
    "reentry": (),
    "analyst_data": (),
    "research": (
        "research-scheduler-holdings",
        "research-scheduler-priority-hourly",
        "research-scheduler-watchlist-2030",
        "governed-research-producer",
    ),
    "hermes_research": (),
    "durable_memory": ("advisory-shadow-seed",),
}

DEPENDENCY_LABELS: dict[str, str] = {
    "advisory_synthesis": "synthesis",
    "technicals": "technicals",
    "prices": "prices",
    "watch_intelligence": "watch intelligence",
    "reentry": "re-entry",
    "analyst_data": "analyst data",
    "research": "research",
    "hermes_research": "Hermes research",
    "durable_memory": "durable memory",
}


def _stale_budgets() -> dict[str, int]:
    """Explicit staleness budgets, from the desk's declared source thresholds."""
    from lib.advisory_desk_operator import (
        FACTS_STALE_S,
        MEMORY_STALE_S,
        OPINION_STALE_S,
        REENTRY_STALE_S,
        STREET_STALE_S,
    )
    from lib.cio_source_clocks import SPECS_BY_SOURCE

    return {
        "advisory_synthesis": int(OPINION_STALE_S),
        "technicals": int(SPECS_BY_SOURCE["technicals"].stale_after_seconds),
        "prices": int(FACTS_STALE_S),
        "watch_intelligence": 4 * 86400,  # watch review workers run Mon/Wed/Fri
        "reentry": int(REENTRY_STALE_S),
        "analyst_data": int(STREET_STALE_S),
        "research": 48 * 3600,
        "hermes_research": 48 * 3600,
        "durable_memory": int(MEMORY_STALE_S),
    }


def _fmt_lag(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 90:
        return f"{s}s"
    if s < 90 * 60:
        return f"{round(s / 60)}m"
    if s < 48 * 3600:
        return f"{round(s / 3600)}h"
    return f"{round(s / 86400)}d"


def _dependency_clock(
    rows: list[dict[str, Any]],
    timestamps: dict[str, Any],
    *,
    price_clock: dict[str, Any] | None = None,
    producer_clocks: dict[str, dict[str, Any]] | None = None,
    next_runs: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Independent per-dependency clocks; run-now synthesis never stands in.

    Every clock is the dependency producer's *own* data clock:
      * technicals — indicator_confluence_cache max(computed_at) when supplied
        in ``producer_clocks``, else a row-level technicals ``as_of``.  A quote
        tick (``quote.price_as_of``) and the indicator_snapshot.json
        projection time are never technicals clocks.
      * prices — holdings.json repricer clock (``price_clock``), else the
        newest watch quote; prices never feed technicals.
      * watch_intelligence — newest CIO/Maria watch review completion.
      * analyst_data — target snapshot dates of rows that carry a target.
      * research vs hermes_research — research deltas + agent opinions vs
        hermes_external_research evidence.
    """
    from lib.cio_source_clocks import ET, classify, newest_clock, parse_clock

    def et_wall(value: Any) -> str | None:
        # Evidence items truncate DB timestamptz strings to 19 chars, leaving
        # the DB session's America/New_York wall time without an offset.
        dt = parse_clock(value, naive_tz=ET)
        return dt.isoformat() if dt else None

    now = now or datetime.now(timezone.utc)
    producer_clocks = producer_clocks or {}
    next_runs = next_runs or {}
    budgets = _stale_budgets()

    technicals: list[Any] = []
    quotes: list[Any] = []
    watch_reviews: list[Any] = []
    analysts: list[Any] = []
    research: list[Any] = []
    hermes: list[Any] = []
    for row in rows:
        wi = row.get("watch_intelligence") or {}
        tech = wi.get("technicals") or {}
        technicals.extend([tech.get("as_of"), tech.get("updated_at")])
        quotes.append((wi.get("quote") or {}).get("price_as_of"))
        for review in ((wi.get("reviews") or {}).values() if isinstance(wi.get("reviews"), dict) else []):
            if isinstance(review, dict):
                watch_reviews.extend([review.get("completed_at"), review.get("generated_at")])
        expand = row.get("expand") if isinstance(row.get("expand"), dict) else {}
        analyst = expand.get("analyst") or row.get("analyst") or {}
        # A target-less analyst block inherits the holdings date as target_as_of
        # (cio_advisory_provenance fallback) — that is not an analyst clock.
        if analyst.get("target") is not None or analyst.get("price_target_mean") is not None or "target" not in analyst:
            analysts.extend([analyst.get("as_of"), analyst.get("target_as_of")])
        prov = row.get("advisory_provenance") or {}
        research.extend([prov.get("research_as_of"), prov.get("evidence_as_of")])
        delta = (row.get("decision_context") or {}).get("research_delta") or {}
        if isinstance(delta, dict):
            research.append(delta.get("evidence_as_of"))
        for item in expand.get("evidence_items") or []:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "external_research" or str(item.get("source") or "").startswith("hermes_external"):
                hermes.extend([et_wall(item.get("as_of")), et_wall(item.get("created_at"))])
            elif kind == "agent_opinion":
                research.append(et_wall(item.get("as_of")))
            elif kind == "analyst_context":
                if item.get("target") is not None:
                    analysts.append(item.get("target_as_of"))
            elif kind in (None, "research", "research_evidence"):
                research.extend([item.get("retrieved_at"), item.get("published_at")])

    pc = price_clock or {}
    tech_prod = producer_clocks.get("technicals") or {}

    def clock(name: str, source_as_of: Any, producer: str, source_ref: str, *, basis: str | None = None) -> dict[str, Any]:
        stale_after = budgets.get(name)
        age, freshness = classify(source_as_of, stale_after, now)
        nxt = next_runs.get(name) or {"next_run_at": None, "reason": "not computed"}
        return {
            "name": name,
            "label": DEPENDENCY_LABELS.get(name, name),
            "source_as_of": str(source_as_of) if source_as_of not in (None, "") else None,
            "source_as_of_utc": (parse_clock(source_as_of).isoformat() if parse_clock(source_as_of) else None),
            "producer": producer,
            "source_ref": source_ref,
            "clock_basis": basis,
            "age_seconds": age,
            "stale_after_seconds": stale_after,
            "freshness": freshness,
            "refreshed_by_run_now": bool(RUN_NOW_REFRESHES.get(name, False)),
            "next_scheduled_run": nxt.get("next_run_at"),
            "next_scheduled_run_reason": nxt.get("reason"),
            "next_scheduled_lane": nxt.get("lane_id"),
        }

    tech_as_of = tech_prod.get("source_as_of") or newest_clock(technicals, now=now)
    price_as_of = pc.get("as_of") or newest_clock(quotes, now=now)
    return {
        "advisory_synthesis": clock(
            "advisory_synthesis", timestamps.get("synthesis"), "advisory_desk_synthesis",
            "data/runtime/advisory_opinions_latest.json", basis="opinions generated_at",
        ),
        "technicals": clock(
            "technicals", tech_as_of,
            tech_prod.get("producer") or "watch_intelligence technicals",
            tech_prod.get("source_ref") or "watch_intelligence.technicals.as_of",
            basis="indicator_confluence_cache max(computed_at)" if tech_prod.get("source_as_of") else "row technicals as_of (quote time excluded)",
        ),
        "prices": clock(
            "prices", price_as_of,
            f"portfolio_repricer ({pc.get('reprice_source')})" if pc.get("as_of") else "watch canonical quote",
            "data/portfolios/state/holdings.json" if pc.get("as_of") else "watch_intelligence.quote.price_as_of",
            basis=f"holdings.{pc.get('clock_field')}" if pc.get("as_of") else "newest watch quote",
        ),
        "watch_intelligence": clock(
            "watch_intelligence", newest_clock(watch_reviews, now=now), "watch_review_workers (CIO/Maria reviews)",
            "watch_intelligence.reviews.*.completed_at", basis="newest watch review completion (quote time excluded)",
        ),
        "reentry": clock(
            "reentry", timestamps.get("reentry"), "reentry_decision_desk",
            "data/runtime/reentry_decision_desk_latest.json", basis="artifact generated_at",
        ),
        "analyst_data": clock(
            "analyst_data", newest_clock(analysts, now=now), "analyst_projection",
            "yahoo_analyst_targets_history.snapshot_date", basis="newest target snapshot date of rows with a target",
        ),
        "research": clock(
            "research", newest_clock(research, now=now), "research_evidence",
            "research_delta.evidence_as_of + watchlist_agent_results", basis="newest research delta / agent opinion",
        ),
        "hermes_research": clock(
            "hermes_research", newest_clock(hermes, now=now), "hermes_external_research",
            "db:hermes_external_research.created_at", basis="newest external research evidence consumed by the desk",
        ),
        "durable_memory": clock(
            "durable_memory", timestamps.get("memory"), "durable_memory",
            "DurableJsonlMemoryProvider", basis="last admitted memory",
        ),
    }


def _dependency_refresh(clocks: dict[str, Any], run_now: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derived (never static) list of dependencies older than the synthesis."""
    from lib.cio_source_clocks import parse_clock

    run_now = run_now or {}
    synth = clocks.get("advisory_synthesis") or {}
    synth_dt = parse_clock(synth.get("source_as_of"))
    older: list[dict[str, Any]] = []
    unknown: list[str] = []
    for name, c in clocks.items():
        if name == "advisory_synthesis":
            continue
        dt = parse_clock(c.get("source_as_of"))
        if dt is None:
            unknown.append(name)
            continue
        if synth_dt is not None and dt < synth_dt:
            lag = (synth_dt - dt).total_seconds()
            older.append({
                "name": name,
                "lag_seconds": int(lag),
                "label": f"{c.get('label') or name} {_fmt_lag(lag)} older than synthesis",
                "refreshed_by_run_now": bool(c.get("refreshed_by_run_now")),
            })
    older.sort(key=lambda x: -x["lag_seconds"])
    not_refreshed = [n for n, c in clocks.items() if not c.get("refreshed_by_run_now")]
    stale = [n for n, c in clocks.items() if c.get("freshness") == "STALE"]
    if synth_dt is None:
        status = "SYNTHESIS_CLOCK_UNKNOWN"
    elif older or unknown:
        status = "DEPENDENCIES_NOT_ALL_REFRESHED"
    else:
        status = "DEPENDENCIES_AT_OR_AFTER_SYNTHESIS"
    parts = [o["label"] for o in older]
    if unknown:
        parts.append("no source clock: " + ", ".join(DEPENDENCY_LABELS.get(n, n) for n in unknown))
    return {
        "status": status,
        # Never "all refreshed": run-now advances only the synthesis clock.
        "all_dependencies_at_or_after_synthesis": status == "DEPENDENCIES_AT_OR_AFTER_SYNTHESIS",
        "synthesis_as_of": synth.get("source_as_of"),
        "last_run_state": run_now.get("state"),
        "last_run_finished_at": run_now.get("finished_at"),
        "older_than_synthesis": older,
        "unknown_clock": unknown,
        "stale": stale,
        "not_refreshed_by_run_now": not_refreshed,
        "summary": "; ".join(parts) if parts else "every dependency clock is at or after the synthesis",
    }


def _dependency_next_runs(schedule: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {
        "advisory_synthesis": {
            "next_run_at": schedule.get("next_run_at"),
            "reason": None if schedule.get("next_run_at") else "advisory schedule unavailable",
            "lane_id": schedule.get("timer_unit"),
        }
    }
    try:
        from lib.cio_source_clocks import next_scheduled_run
        for name, lanes in DEPENDENCY_LANES.items():
            out[name] = next_scheduled_run(lanes)
    except Exception as exc:  # noqa: BLE001
        for name in DEPENDENCY_LANES:
            out.setdefault(name, {"next_run_at": None, "reason": f"schedule lookup failed: {type(exc).__name__}"})
    return out


def get_advisory_desk(*, force: bool = False, row_class: str | None = None) -> dict[str, Any]:
    desk = _load_desk(force=force)
    opinions = desk.get("opinions") or _load_opinions_blob()
    # Operator-grade join: watch intelligence, re-entry, durable memory, FS.
    # Re-enrich when the cached envelope predates this contract.
    try:
        from lib.advisory_desk_operator import OPERATOR_TRUTH_VERSION, enrich_desk
        ot = desk.get("operator_truth") or (desk.get("data") or {}).get("operator_truth") or {}
        if ot.get("version") != OPERATOR_TRUTH_VERSION:
            desk = enrich_desk(desk, opinions=opinions if isinstance(opinions, dict) else {}, cache_path=CACHE_FILE)
            if not desk.get("cache_hit") or desk.get("stale_fallback"):
                try:
                    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_FILE.write_text(json.dumps(desk, indent=2, default=str), encoding="utf-8")
                except Exception:
                    pass
    except Exception:
        pass
    data = desk.get("data") or {}
    meta = data.get("metadata") or {}
    rows_raw = data.get("rows") or []
    opinion_rows = opinions.get("rows") if isinstance(opinions, dict) else None

    rows = [_row_view(r, opinion_rows if isinstance(opinion_rows, dict) else opinions) for r in rows_raw]
    if row_class:
        rows = [r for r in rows if r.get("row_class") == row_class]

    by_class: dict[str, int] = {}
    for r in rows:
        c = str(r.get("row_class") or "unknown")
        by_class[c] = by_class.get(c, 0) + 1

    conflicted_syms = [
        str(r.get("symbol"))
        for r in rows
        if (r.get("data_quality") or {}).get("action_suppressed")
        or (r.get("canonical_financial_facts") or {}).get("conflicts")
    ]
    if conflicted_syms:
        meta = dict(meta)
        meta["conflicted_symbols"] = conflicted_syms
        meta["conflicted_count"] = len(conflicted_syms)

    llm_in_path = bool(data.get("llm_in_path")) or bool(
        opinions.get("llm_in_path") if isinstance(opinions, dict) else False
    )
    # compute_banners reads data.get("llm_in_path") — surface the enriched value.
    data["llm_in_path"] = llm_in_path
    banners = compute_banners(meta, data)
    synthesis = ""
    if isinstance(opinions, dict):
        synthesis = opinions.get("synthesis") or ""

    promotion = {}
    try:
        from lib.advisory.promotion_gate import load_promotion_state
        promotion = load_promotion_state()
    except Exception:
        promotion = {"status": "UNKNOWN"}

    health = data.get("desk_health") or desk.get("desk_health") or {}
    timestamps = data.get("timestamps") or desk.get("timestamps") or {}
    ot = data.get("operator_truth") or desk.get("operator_truth") or {}
    price_clock: dict[str, Any] = {}
    try:
        from lib.advisory_desk_operator import holdings_source_freshness as _hsf
        hsf = _hsf()
        price_clock = {
            "as_of": hsf.get("holdings_source_as_of"),
            "age_seconds": hsf.get("holdings_source_age_seconds"),
            "freshness": hsf.get("holdings_source_freshness"),
            "clock_field": hsf.get("holdings_source_clock_field"),
            "reprice_source": hsf.get("holdings_reprice_source"),
        }
    except Exception:
        price_clock = {"freshness": "UNAVAILABLE"}
    schedule: dict[str, Any] = {}
    run_now: dict[str, Any] = {"state": "idle"}
    try:
        from lib.advisory_desk_schedule import run_status as _run_status
        st = _run_status()
        schedule = dict(st.get("schedule") or {})
        run_now = {k: v for k, v in st.items() if k != "schedule"}
    except Exception:
        schedule = {
            "cadence": "weekdays 09:15 America/New_York",
            "source": "unavailable",
        }
    desk_sources: dict[str, Any] = {
        "watchlist_personal_total": meta.get("personal_watchlist_count"),
        "watchlist_personal_shown": by_class.get("watchlist", 0),
        "watch_hub_active": _watch_hub_counts().get("active"),
        "watch_hub_universe": _watch_hub_counts().get("universe"),
        "watch_hub_universe_is_not_canonical": True,
        "watch_hub_cohort": "watchlist_items_active_plus_researched",
        "reentry_universe_is_not_canonical": True,
        "reentry_cohort": "reentry_decision_desk",
        "canonical_contract": "TransfersonUniverseManifest@v1",
        "watch_hub_total": meta.get("hub_watch_total"),
        "watch_hub_shown": by_class.get("watchlist_hub", 0),
        "reentry_universe": meta.get("reentry_universe_count"),
        "reentry_shown": by_class.get("closed_journal", 0),
    }
    producer_clocks: dict[str, dict[str, Any]] = {}
    try:
        from lib.cio_source_clocks import cached_source_row
        tech_row = cached_source_row("technicals")
        if tech_row and tech_row.get("source_as_of"):
            producer_clocks["technicals"] = tech_row
    except Exception:
        producer_clocks = {}
    try:
        dependency_clocks = _dependency_clock(
            rows,
            timestamps,
            price_clock=price_clock,
            producer_clocks=producer_clocks,
            next_runs=_dependency_next_runs(schedule),
        )
        dependency_refresh = _dependency_refresh(dependency_clocks, run_now)
    except Exception as exc:  # noqa: BLE001 — clocks never break the desk
        dependency_clocks = {}
        dependency_refresh = {"status": "UNAVAILABLE", "all_dependencies_at_or_after_synthesis": False, "error": type(exc).__name__}
    return {
        "ok": True,
        "as_of": data.get("computed_at") or _now_iso(),
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": ot.get("memory_behavior_influence") or "0",
        "broker_write_authority": "NONE",
        "version": data.get("version"),
        "operator_truth_version": ot.get("version"),
        "desk_computed_at": desk.get("desk_computed_at") or data.get("computed_at"),
        "desk_cache_age_seconds": desk.get("desk_cache_age_seconds"),
        "desk_cache_hit": bool(desk.get("cache_hit")),
        "desk_freshness_state": desk.get("desk_freshness_state") or timestamps.get("facts_freshness"),
        "desk_health": health,
        "timestamps": timestamps,
        "dependency_clocks": dependency_clocks,
        "dependency_refresh": dependency_refresh,
        # desk_freshness_state is the desk *composition* (facts) clock only.
        "desk_freshness_scope": "DESK_COMPOSITION_ONLY",
        "price_clock": price_clock,
        "banners": banners,
        "metadata": meta,
        "portfolio_analytics": meta.get("portfolio_analytics") or {},
        "performance": meta.get("performance") or {},
        "by_class": by_class,
        "desk_sources": desk_sources,
        "verdict_counts": meta.get("verdict_counts") or {},
        "synthesis": synthesis,
        "synthesis_label": timestamps.get("synthesis_label"),
        "rows": rows,
        "row_count": len(rows),
        "content_hash": data.get("content_hash"),
        "llm_in_path": llm_in_path,
        "deterministic": data.get("deterministic", True),
        "promotion": {
            "status": promotion.get("status"),
            "promoted": bool(promotion.get("promoted")),
            "morning_path_default": bool(promotion.get("morning_path_default")),
        },
        "schedule": schedule,
        "run_now": run_now,
    }


def get_advisory_brief(*, max_items: int = 3) -> dict[str, Any]:
    """Compact brief for Telegram (body ≤5 lines beyond header)."""
    desk = get_advisory_desk(force=False)
    rows = desk.get("rows") or []
    # Rank by market value among actionable / material
    actionable = {"TRIM", "EXIT", "ADD", "RE_ENTER"}
    ranked = sorted(
        [r for r in rows if (r.get("market_value") or 0) >= 500],
        key=lambda r: (
            1 if r.get("verdict") in actionable else 0,
            float(r.get("market_value") or 0),
        ),
        reverse=True,
    )
    top = ranked[:max_items]
    lines: list[str] = []
    for r in top:
        mv = r.get("market_value") or 0
        lines.append(
            f"• {r.get('symbol')} {r.get('verdict')} "
            f"${mv:,.0f} — {(r.get('rationale') or '')[:80]}"
        )
    # Fill to highlight cash / blind spot if room
    if len(lines) < 5:
        for r in rows:
            if r.get("row_class") == "allocation" and "cash" in str(r.get("symbol") or "").lower():
                lines.append(
                    f"• {r.get('symbol')} {r.get('verdict')} — {(r.get('rationale') or '')[:90]}"
                )
                break
    body_lines = lines[:5]
    header = f"📋 Advisory desk · {desk.get('row_count', 0)} rows · {(_verdict_top(desk))}"
    text = header + "\n" + "\n".join(body_lines)
    # Cap growth: body ≤5 lines
    return {
        "ok": True,
        "as_of": desk.get("as_of"),
        "text": text,
        "body_line_count": len(body_lines),
        "header": header,
        "lines": body_lines,
        "banners": [b for b in desk.get("banners") or [] if b.get("severity") in ("critical", "warn")][:2],
    }


def _verdict_top(desk: dict[str, Any]) -> str:
    vc = desk.get("verdict_counts") or {}
    if not vc:
        return "—"
    top = sorted(vc.items(), key=lambda x: -x[1])[:3]
    return " ".join(f"{k}:{v}" for k, v in top)


def get_run_status() -> dict[str, Any]:
    from lib.advisory_desk_schedule import run_status as _run_status
    st = _run_status()
    return {"ok": True, **st}


def post_run_now(_body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Operator on-demand desk rebuild. Paid Flash/Pro. No broker writes."""
    from lib.advisory_desk_schedule import start_run_now
    return start_run_now(live_llm=True)


def post_feedback(body: dict[str, Any], *, kind: str = "rate") -> dict[str, Any]:
    from lib.advisory.advisory_memory import record_feedback

    target = str(body.get("row_id") or body.get("symbol") or "").strip()
    if not target:
        return {"ok": False, "error": "row_id or symbol required"}
    row_id, symbol, account = "", "", ""
    if "|" in target:
        row_id = target
        head = target.split("|", 1)[0]
        if ":" in head:
            symbol, account = head.split(":", 1)
        else:
            symbol = head
    elif ":" in target:
        symbol, account = target.split(":", 1)
    else:
        symbol = target

    if kind == "rate":
        rating = str(body.get("rating") or "").lower()
        code = str(body.get("reason_code") or "")
        note = str(body.get("note") or "")
        try:
            entry = record_feedback(
                row_id=row_id, symbol=symbol, account=account,
                rating=rating, reason_code=code, note=note,
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "entry": entry}

    if kind in ("ack", "snooze"):
        entry = record_feedback(
            row_id=row_id, symbol=symbol, account=account, rating=kind,
        )
        return {"ok": True, "entry": entry}

    return {"ok": False, "error": f"unknown kind {kind}"}


def get_history(symbol: str, account: str = "") -> dict[str, Any]:
    from lib.advisory.advisory_memory import load_prior_for_row, load_feedback_for_symbol

    prior = load_prior_for_row(symbol, account)
    fb = load_feedback_for_symbol(symbol, account, limit=20)
    return {"ok": True, "symbol": symbol, "account": account, "prior": prior, "feedback": fb}


def get_calibration() -> dict[str, Any]:
    from lib.advisory.advisory_memory import load_calibration

    return {"ok": True, "calibration": load_calibration()}
