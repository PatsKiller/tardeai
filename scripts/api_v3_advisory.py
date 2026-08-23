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
    delta = thesis.get("research_delta") or {}
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
            "research_delta_id": delta.get("delta_id"),
            "research_delta_classification": delta.get("classification"),
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
        "watch_hub_total": meta.get("hub_watch_total"),
        "watch_hub_shown": by_class.get("watchlist_hub", 0),
        "reentry_universe": meta.get("reentry_universe_count"),
        "reentry_shown": by_class.get("closed_journal", 0),
    }
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
