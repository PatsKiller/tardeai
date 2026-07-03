"""Outcome bus v1 traceability — watchlist/holdings health, proposals, lineage, stop trends."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def make_snapshot_id(run_id: str | None, generated_at: str | None) -> str | None:
    if not run_id or not generated_at:
        return None
    stamp = str(generated_at).replace(":", "").replace("+", "").replace("-", "")[:15]
    return f"outcome_bus_{stamp}_{run_id}"


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _series_delta(series: list[dict[str, Any]], key: str, window: int = 7) -> float | None:
    vals = [_num(s.get(key)) for s in series if _num(s.get(key)) is not None]
    if len(vals) < 2:
        return None
    tail = vals[-window:] if len(vals) >= window else vals
    if len(tail) < 2:
        return None
    return round(tail[-1] - tail[0], 4)


def _tier_trend_deltas(series: list[dict[str, Any]], window: int = 7) -> dict[str, float | None]:
    return {
        "trail_activation_rate": _series_delta(series, "trail_activation_rate", window),
        "aligned_pct": _series_delta(series, "aligned_pct", window),
        "r_left_on_table_avg": _series_delta(series, "r_left_on_table_avg", window),
        "tier_alignment_delta": _series_delta(series, "tier_alignment_delta", window),
        "stop_hot_cold_trail_delta": _series_delta(series, "stop_hot_cold_trail_delta", window),
    }


def enrich_stop_quality_trends(stop_quality: dict[str, Any], trend: dict[str, Any] | None) -> dict[str, Any]:
    """Attach 7d/14d trend deltas to stop_quality (backward-compatible)."""
    out = dict(stop_quality or {})
    series = (trend or {}).get("series") or []
    if not series:
        out.setdefault("trends", {"notes": "insufficient_history"})
        return out
    out["trends"] = {
        "window_7d": _tier_trend_deltas(series, 7),
        "window_14d": _tier_trend_deltas(series, 14),
        "series_days": len(series),
    }
    return out


def _data_quality_from_confidence(confidence_tier: str | None, graded_n: int | None) -> str:
    tier = str(confidence_tier or "").lower()
    n = int(graded_n or 0)
    if tier in ("low", "minimal") or n < 3:
        return "limited"
    if tier in ("partial", "medium") or n < 8:
        return "partial"
    return "full"


def build_watchlist_health_section(
    wl_state: dict[str, Any],
    *,
    run_id: str | None,
    snapshot_id: str | None,
) -> dict[str, Any]:
    symbols_raw = wl_state.get("symbols") or {}
    health_history = wl_state.get("health_history") or {}
    symbols: dict[str, Any] = {}

    for sym, entry in symbols_raw.items():
        if not isinstance(entry, dict):
            continue
        key = str(sym).upper()
        components = dict(entry.get("health_components") or {})
        symbols[key] = {
            "health_score": entry.get("health_score"),
            "display_score": entry.get("display_score"),
            "confidence_tier": entry.get("confidence_tier"),
            "data_quality": _data_quality_from_confidence(
                entry.get("confidence_tier"), entry.get("graded_n"),
            ),
            "graded_n": entry.get("graded_n"),
            "lifecycle_stage": entry.get("lifecycle_stage"),
            "scope_tier": entry.get("scope_tier"),
            "outcome_gate": entry.get("outcome_gate"),
            "health_trend_7d": entry.get("health_trend"),
            "health_delta": entry.get("health_delta"),
            "components": components,
            "health_history": list(health_history.get(sym) or health_history.get(key) or [])[-14:],
            "lineage": {
                "source": "data/runtime/hermes_watchlist_lifecycle.json",
                "outcome_bus_run_id": run_id,
                "outcome_bus_snapshot_id": snapshot_id,
                "watchlist_entry_ref": f"watchlist_health.symbols.{key}",
            },
        }

    return {
        "version": "watchlist-health-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enabled": wl_state.get("enabled", True),
        "review_mode": wl_state.get("review_mode", True),
        "summary": wl_state.get("summary") or {},
        "blocked_promotion_count": wl_state.get("blocked_promotion_count", 0),
        "symbol_count": len(symbols),
        "symbols": symbols,
    }


def build_holdings_health_section(
    hl_state: dict[str, Any],
    stop_quality: dict[str, Any] | None,
    *,
    run_id: str | None,
    snapshot_id: str | None,
) -> dict[str, Any]:
    holdings_raw = hl_state.get("holdings") or {}
    history = hl_state.get("history") or {}
    stop_global = stop_quality or {}
    symbols: dict[str, Any] = {}

    for sym, entry in holdings_raw.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("lifecycle_stage") == "exited":
            continue
        key = str(sym).upper()
        components = dict(entry.get("health_components") or {})
        symbols[key] = {
            "health_score": entry.get("health_score"),
            "lifecycle_stage": entry.get("lifecycle_stage"),
            "lifecycle_label": entry.get("lifecycle_label"),
            "gain_pct": entry.get("gain_pct"),
            "outcome_gate": entry.get("outcome_gate"),
            "health_delta": entry.get("health_delta"),
            "components": components,
            "stop_quality": {
                "trail_activation_rate": stop_global.get("trail_activation_rate"),
                "aligned_pct": stop_global.get("aligned_pct"),
                "r_left_on_table_avg": stop_global.get("r_left_on_table_avg"),
                "mae_exceeded_planned_stop_pct": stop_global.get("mae_exceeded_planned_stop_pct"),
                "by_tier": stop_global.get("by_tier"),
            },
            "monitoring": entry.get("monitoring"),
            "health_history": list(history.get(sym) or history.get(key) or [])[-14:],
            "lineage": {
                "source": "data/runtime/hermes_holdings_lifecycle.json",
                "outcome_bus_run_id": run_id,
                "outcome_bus_snapshot_id": snapshot_id,
                "holding_entry_ref": f"holdings_health.symbols.{key}",
            },
        }

    return {
        "version": "holdings-health-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enabled": hl_state.get("enabled", True),
        "review_mode": hl_state.get("review_mode", True),
        "summary": hl_state.get("summary") or {},
        "position_count": len(symbols),
        "symbols": symbols,
    }


def _metrics_at_bus_snapshot(bus: dict[str, Any]) -> dict[str, Any]:
    g = bus.get("global") or {}
    sq = bus.get("stop_quality") or {}
    re = bus.get("resource_efficiency") or {}
    by_tier = sq.get("by_tier") or {}
    hot = (by_tier.get("hot") or {}).get("trail_activation_rate")
    cold = (by_tier.get("cold") or {}).get("trail_activation_rate")
    trail_delta = None
    if hot is not None and cold is not None:
        try:
            trail_delta = round(float(hot) - float(cold), 4)
        except (TypeError, ValueError):
            pass
    return {
        "hit_rate_promotions": g.get("hit_rate_promotions"),
        "hit_rate_trades": g.get("hit_rate_trades"),
        "resource_efficiency_score": re.get("score") or re.get("resource_efficiency_score"),
        "trail_activation_rate": sq.get("trail_activation_rate"),
        "aligned_pct": sq.get("aligned_pct"),
        "stop_hot_cold_trail_delta": trail_delta,
        "maturity_composite_score": (bus.get("maturity") or {}).get("composite_score"),
    }


def _compact_proposal(p: dict[str, Any], bus: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(p.get("evidence") or {})
    lineage = dict(p.get("lineage") or {})
    tid = p.get("threshold_id")
    if not lineage.get("outcome_bus_run_id"):
        lineage.update({
            "outcome_bus_run_id": bus.get("run_id"),
            "outcome_bus_snapshot_id": bus.get("lineage", {}).get("snapshot_id"),
            "outcome_bus_generated_at": bus.get("generated_at"),
        })
    prior_chain = lineage.get("prior_proposal_ids") or []
    return {
        "id": p.get("id"),
        "threshold_id": tid,
        "label": p.get("label"),
        "status": p.get("status"),
        "direction": p.get("direction"),
        "current_value": p.get("current_value"),
        "proposed_value": p.get("proposed_value"),
        "created_at": p.get("created_at"),
        "decided_at": p.get("decided_at"),
        "confidence": evidence.get("confidence"),
        "metrics_at_generation": lineage.get("metrics_at_generation") or evidence.get("metrics_at_generation"),
        "lineage": lineage,
        "prior_proposal_ids": prior_chain,
        "evaluation_outcome": p.get("evaluation_outcome"),
        "impact_narrative": p.get("impact_narrative"),
    }


def _prior_proposals_by_threshold(proposals: dict[str, Any]) -> dict[str, list[str]]:
    chain: dict[str, list[str]] = {}
    for p in (proposals.get("decided") or []) + (proposals.get("pending") or []):
        tid = p.get("threshold_id")
        pid = p.get("id")
        if tid and pid:
            chain.setdefault(str(tid), []).append(str(pid))
    return chain


def build_threshold_proposals_section(bus: dict[str, Any]) -> dict[str, Any]:
    try:
        from lib.hermes_thresholds.store import load_proposals
        from lib.hermes_thresholds.workflow import _enrich_decided_proposals
        from lib.hermes_thresholds.store import load_active_thresholds

        proposals = load_proposals()
        active = load_active_thresholds()
        decided_raw = list(proposals.get("decided") or [])[-10:]
        try:
            from lib.hermes_thresholds.evaluation_engine import evaluation_status
            evals = list((evaluation_status().get("evaluations") or []))
        except Exception:
            evals = []
        decided = _enrich_decided_proposals(
            decided_raw,
            list(active.get("history") or []),
            evals,
        )
    except Exception:
        proposals = {"pending": [], "decided": []}
        decided = []

    metrics_now = _metrics_at_bus_snapshot(bus)
    prior_chain = _prior_proposals_by_threshold(proposals)

    pending = [_compact_proposal(p, bus) for p in (proposals.get("pending") or [])]
    for p in pending:
        tid = str(p.get("threshold_id") or "")
        p["prior_proposal_ids"] = prior_chain.get(tid, [])[:-1]

    return {
        "version": "threshold-proposals-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcome_bus_run_id": bus.get("run_id"),
        "outcome_bus_snapshot_id": (bus.get("lineage") or {}).get("snapshot_id"),
        "outcome_bus_generated_at": bus.get("generated_at"),
        "metrics_at_snapshot": metrics_now,
        "pending_count": len(pending),
        "pending": pending,
        "recent_decided": [_compact_proposal(p, bus) for p in decided],
        "prior_proposal_chain": prior_chain,
    }


def build_bus_lineage(bus: dict[str, Any], prior_bus: dict[str, Any] | None = None) -> dict[str, Any]:
    run_id = bus.get("run_id")
    generated_at = bus.get("generated_at")
    snap_id = make_snapshot_id(str(run_id or ""), str(generated_at or ""))
    prior = prior_bus or {}
    return {
        "snapshot_id": snap_id,
        "run_id": run_id,
        "generated_at": generated_at,
        "prior_run_id": prior.get("run_id"),
        "prior_snapshot_id": (prior.get("lineage") or {}).get("snapshot_id"),
        "upstream": (bus.get("source_runs") or {}).get("upstream"),
        "downstream": (bus.get("source_runs") or {}).get("downstream"),
    }


def _attach_symbol_lineage(bus: dict[str, Any]) -> None:
    snap_id = (bus.get("lineage") or {}).get("snapshot_id")
    run_id = bus.get("run_id")
    wl = (bus.get("watchlist_health") or {}).get("symbols") or {}
    hl = (bus.get("holdings_health") or {}).get("symbols") or {}
    by_sym = dict(bus.get("by_symbol") or {})

    for sym, row in list(by_sym.items()):
        key = str(sym).upper()
        lineage: dict[str, Any] = {
            "outcome_bus_snapshot_id": snap_id,
            "outcome_bus_run_id": run_id,
        }
        if key in wl:
            lineage["watchlist_health_ref"] = f"watchlist_health.symbols.{key}"
            lineage["watchlist_stage"] = wl[key].get("lifecycle_stage")
            lineage["watchlist_health_score"] = wl[key].get("health_score")
        if key in hl:
            lineage["holdings_health_ref"] = f"holdings_health.symbols.{key}"
            lineage["holdings_stage"] = hl[key].get("lifecycle_stage")
            lineage["holdings_health_score"] = hl[key].get("health_score")
        enriched = dict(row)
        enriched["lineage"] = lineage
        by_sym[key] = enriched
    bus["by_symbol"] = by_sym


def _attach_governor_feedback_lineage(bus: dict[str, Any]) -> None:
    snap_id = (bus.get("lineage") or {}).get("snapshot_id")
    run_id = bus.get("run_id")
    wl = (bus.get("watchlist_health") or {}).get("symbols") or {}
    feedback = []
    for item in bus.get("feedback_to_governor") or []:
        fb = dict(item)
        sym = str(fb.get("symbol") or "").upper()
        refs: dict[str, Any] = {
            "outcome_bus_snapshot_id": snap_id,
            "outcome_bus_run_id": run_id,
            "by_symbol_ref": f"by_symbol.{sym}" if sym else None,
        }
        if sym and sym in wl:
            refs["watchlist_health_ref"] = f"watchlist_health.symbols.{sym}"
            refs["watchlist_health_score"] = wl[sym].get("health_score")
            refs["watchlist_stage"] = wl[sym].get("lifecycle_stage")
        fb["source_refs"] = refs
        feedback.append(fb)
    bus["feedback_to_governor"] = feedback


def enrich_bus_traceability(
    bus: dict[str, Any],
    trend: dict[str, Any] | None = None,
    prior_bus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full traceability enrichment — preserves lifecycle slice + adds new top-level sections.
    Safe to call on a partially-built bus; all new sections are optional for consumers.
    """
    from .lifecycle_slice import _load_holdings_lifecycle, _load_watchlist_lifecycle, enrich_bus_with_lifecycle

    bus = enrich_bus_with_lifecycle(bus)

    run_id = bus.get("run_id")
    generated_at = bus.get("generated_at")
    snap_id = make_snapshot_id(str(run_id or ""), str(generated_at or ""))

    wl_state = _load_watchlist_lifecycle()
    hl_state = _load_holdings_lifecycle()

    bus["lineage"] = build_bus_lineage(bus, prior_bus)
    bus["watchlist_health"] = build_watchlist_health_section(
        wl_state, run_id=str(run_id) if run_id else None, snapshot_id=snap_id,
    )
    bus["holdings_health"] = build_holdings_health_section(
        hl_state,
        bus.get("stop_quality"),
        run_id=str(run_id) if run_id else None,
        snapshot_id=snap_id,
    )
    bus["threshold_proposals"] = build_threshold_proposals_section(bus)
    bus["stop_quality"] = enrich_stop_quality_trends(bus.get("stop_quality") or {}, trend)

    _attach_symbol_lineage(bus)
    _attach_governor_feedback_lineage(bus)
    return bus