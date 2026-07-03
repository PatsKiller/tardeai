"""Watchlist lifecycle — stages, conviction, audit (parallel to scope_tier S0–S3)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .models import ScopeDecision, heat_of

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CFG_PATH = PROJECT_ROOT / "config" / "hermes_watchlist_lifecycle.yaml"
LIFECYCLE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_watchlist_lifecycle.json"
AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_watchlist_lifecycle_audit.jsonl"

LifecycleStage = Literal[
    "new", "monitoring", "watch", "promoted", "demoted", "archived", "blacklisted"
]

STAGE_LABELS: dict[str, str] = {
    "new": "New / Monitoring",
    "monitoring": "Monitoring",
    "watch": "Watch",
    "promoted": "Promoted",
    "demoted": "Demoted",
    "archived": "Archived",
    "blacklisted": "Blacklisted",
}


def load_lifecycle_config() -> dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"enabled": True, "review_mode": True}


def load_lifecycle_state() -> dict[str, Any]:
    if not LIFECYCLE_PATH.exists():
        return {"version": "watchlist-lifecycle-v1", "symbols": {}, "pending_transitions": [], "summary": {}}
    try:
        return json.loads(LIFECYCLE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "watchlist-lifecycle-v1", "symbols": {}, "pending_transitions": [], "summary": {}}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def save_lifecycle_state(payload: dict[str, Any]) -> Path:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(LIFECYCLE_PATH, payload)
    return LIFECYCLE_PATH


def append_lifecycle_audit(event: dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), **event}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def load_lifecycle_audit_tail(limit: int = 20) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
        if len(rows) >= limit:
            break
    return rows


def compute_conviction(
    edge_score: float | None,
    outcome_gate: str | None,
    bus_action: str | None,
    cfg: dict[str, Any],
) -> float:
    base = float(edge_score or 50.0)
    conv = (cfg.get("conviction") or {})
    gate_adj = (conv.get("gate_adjustments") or {})
    bus_adj = (conv.get("bus_action_adjustments") or {})
    gate = str(outcome_gate or "neutral")
    delta = float(gate_adj.get(gate, gate_adj.get("neutral", 0)))
    if bus_action:
        ba = str(bus_action).lower()
        if "pause" in ba:
            delta += float(bus_adj.get("pause", -20))
        elif "demote" in ba:
            delta += float(bus_adj.get("demote_pressure", -10))
        elif "promote" in ba:
            delta += float(bus_adj.get("promote_eligible", 5))
    return max(0.0, min(100.0, round(base + delta, 1)))


def resolve_stage(
    scope_tier: str,
    desired_tier: str,
    pending: dict[str, Any] | None,
    outcome_gate: str | None,
    conviction: float,
    health_score: float,
    health_trend: float | None,
    first_seen_days: int | None,
    override_stage: str | None,
    last_demoted_at: str | None,
    cfg: dict[str, Any],
) -> tuple[str, str]:
    """Return (stage, reason)."""
    if override_stage in STAGE_LABELS:
        return override_stage, f"manual_override:{override_stage}"

    new_days = int(cfg.get("new_symbol_days", 7))
    thr = cfg.get("health_thresholds") or {}
    archive_floor = float(thr.get("archive_floor", cfg.get("archive_conviction_floor", 35)))
    watch_min = float(thr.get("watch_min", 45))
    watch_max = float(thr.get("watch_max", 59))
    trend_decline = float(thr.get("trend_decline_watch", 10))
    rules = cfg.get("transition_rules") or {}
    auto_bl = rules.get("auto_blacklist_on_pause", True)

    gate = str(outcome_gate or "neutral")
    if auto_bl and gate == "pause_eligible":
        return "blacklisted", "outcome_pause_eligible"

    if pending:
        act = str(pending.get("action") or "")
        if act in ("promote", "reactivate", "assign") and pending.get("to_tier") in ("S0", "S1", "S2"):
            if pending.get("to_tier") in ("S0", "S1"):
                return "promoted", f"pending_{act}:{pending.get('reason', '')[:80]}"
        if act == "demote":
            return "demoted", f"pending_demote:{pending.get('reason', '')[:80]}"

    if scope_tier in ("S0", "S1"):
        return "promoted", f"hot_tier_{scope_tier}"

    if gate == "demote_pressure":
        return "demoted", "outcome_demote_pressure"

    if health_trend is not None and health_trend <= -trend_decline:
        return "watch", f"health_declining_{health_trend:.0f}pts"
    if watch_min <= health_score <= watch_max:
        return "watch", f"health_watch_band_{health_score:.0f}"

    if scope_tier == "S2":
        if first_seen_days is not None and first_seen_days < new_days:
            return "new", f"discovery_grace_{first_seen_days}d"
        if gate == "promote_eligible" and desired_tier in ("S1", "S0"):
            return "promoted", "outcome_promote_eligible_warm"
        return "monitoring", "warm_tier_active"

    if first_seen_days is not None and first_seen_days < new_days:
        return "new", f"cold_discovery_{first_seen_days}d"
    if health_score < archive_floor and gate in ("demote_pressure", "pause_eligible", "neutral"):
        return "archived", f"low_health_{health_score:.0f}"
    if gate == "promote_eligible":
        return "monitoring", "cold_promote_candidate"
    return "archived", "cold_no_trigger"


def prepare_watchlist_health_context(
    cur,
    signals: dict[str, Any],
    edge_scores_map: dict[str, float],
    edge_details: dict[str, dict],
    regime_label: str | None,
    cfg: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    """Load bus + promo stats and return (health_map, bus_by_symbol, stop_global, promo_rates)."""
    cfg = cfg or load_lifecycle_config()
    bus_by_symbol: dict[str, Any] = {}
    stop_global: dict[str, Any] = {}
    try:
        from lib.hermes_outcome_bus.bus import read_outcome_bus
        bus = read_outcome_bus() or {}
        bus_by_symbol = bus.get("by_symbol") or {}
        stop_global = bus.get("stop_quality") or {}
    except Exception:
        pass
    lookback = int((cfg.get("promotion_success") or {}).get("lookback_days", 90))
    from .watchlist_health import fetch_promotion_success_rates
    promo_rates = fetch_promotion_success_rates(cur, lookback)
    health_map = compute_symbol_health_map(
        signals, edge_scores_map, edge_details,
        bus_by_symbol, stop_global, regime_label, promo_rates, cfg,
    )
    return health_map, bus_by_symbol, stop_global, promo_rates


def compute_symbol_health_map(
    signals: dict[str, Any],
    edge_scores_map: dict[str, float],
    edge_details: dict[str, dict],
    bus_by_symbol: dict[str, Any],
    stop_global: dict[str, Any],
    regime_label: str | None,
    promo_rates: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    from .watchlist_health import (
        compute_health_components,
        compute_watchlist_health_score,
        blend_display_score,
    )

    out: dict[str, dict[str, Any]] = {}
    for sym, sig in signals.items():
        bus_sym = bus_by_symbol.get(sym) or bus_by_symbol.get(sym.upper())
        detail = dict(edge_details.get(sym) or {})
        detail["edge_score"] = edge_scores_map.get(sym)
        hits = int(getattr(sig, "outcome_hits", 0) or 0)
        misses = int(getattr(sig, "outcome_misses", 0) or 0)
        neutral = int(getattr(sig, "outcome_neutral", 0) or 0)
        graded_n = hits + misses + neutral
        components = compute_health_components(
            sym, sig, detail, bus_sym, promo_rates.get(sym), stop_global, regime_label, cfg,
        )
        raw, final, conf_tier = compute_watchlist_health_score(components, graded_n, cfg)
        out[sym] = {
            "health_score_raw": raw,
            "health_score": final,
            "confidence_tier": conf_tier,
            "graded_n": graded_n,
            "health_components": components,
            "display_score": blend_display_score(final, edge_scores_map.get(sym), cfg),
        }
    return out


def _pending_by_symbol(decisions: list[ScopeDecision]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for d in decisions:
        if d.from_tier == d.to_tier:
            continue
        out[d.symbol] = {
            "symbol": d.symbol,
            "action": d.action,
            "from_tier": d.from_tier,
            "to_tier": d.to_tier,
            "reason": d.reason,
            "edge_score": d.edge_score,
        }
    return out


def _age_days(iso_text: str | None) -> int | None:
    if not iso_text:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_text).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def build_lifecycle_snapshot(
    run_id: str,
    signals: dict[str, Any],
    edge_scores_map: dict[str, float],
    edge_details: dict[str, dict],
    have: dict[str, dict],
    want: dict[str, tuple[str, str]],
    decisions: list[ScopeDecision],
    post: dict[str, str],
    bus_feedback: dict[str, dict[str, Any]] | None = None,
    cfg: dict[str, Any] | None = None,
    health_map: dict[str, dict[str, Any]] | None = None,
    regime_label: str | None = None,
    blocked_promotions: list[dict[str, Any]] | None = None,
    cur=None,
) -> dict[str, Any]:
    cfg = cfg or load_lifecycle_config()
    if not cfg.get("enabled", True):
        return {"enabled": False}

    prev = load_lifecycle_state()
    overrides = (prev.get("overrides") or {})
    prev_symbols = prev.get("symbols") or {}
    prev_health_hist: dict[str, list] = dict(prev.get("health_history") or {})
    pending_map = _pending_by_symbol(decisions)
    bus_feedback = bus_feedback or {}
    hist_days = int(cfg.get("health_history_days", 14))

    if health_map is None and cur is not None:
        health_map, _, _, _ = prepare_watchlist_health_context(
            cur, signals, edge_scores_map, edge_details, regime_label, cfg,
        )
    health_map = health_map or {}

    from .watchlist_health import health_trend_delta

    symbols_out: dict[str, dict[str, Any]] = {}
    health_history: dict[str, list] = {}
    all_syms = set(have.keys()) | set(want.keys()) | set(post.keys())

    for sym in sorted(all_syms):
        cur_state = have.get(sym, {})
        scope_tier = post.get(sym) or cur_state.get("tier") or "S3"
        desired, want_reason = want.get(sym, ("S3", "no_trigger"))
        detail = edge_details.get(sym, {})
        gate = detail.get("outcome_gate")
        edge = edge_scores_map.get(sym)
        fb = bus_feedback.get(sym.upper()) or bus_feedback.get(sym)
        bus_action = (fb or {}).get("action")
        conviction = compute_conviction(edge, gate, bus_action, cfg)
        hm = health_map.get(sym) or {}
        health_score = float(hm.get("health_score") or 50.0)
        prev_hist = list(prev_health_hist.get(sym) or [])
        health_trend = health_trend_delta(prev_hist, days=7)
        first_seen_days = _age_days(cur_state.get("first_seen"))
        pending = pending_map.get(sym)
        override = (overrides.get(sym.upper()) or overrides.get(sym) or {}).get("stage")
        last_demoted = (prev_symbols.get(sym) or {}).get("last_demoted_at")

        stage, reason = resolve_stage(
            scope_tier, desired, pending, gate, conviction,
            health_score, health_trend,
            first_seen_days, override, last_demoted, cfg,
        )

        hist = list(prev_hist)
        hist.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "health_score": health_score,
            "stage": stage,
        })
        health_history[sym] = hist[-hist_days:]

        entry = {
            "symbol": sym,
            "lifecycle_stage": stage,
            "lifecycle_label": STAGE_LABELS.get(stage, stage),
            "conviction_score": conviction,
            "health_score": health_score,
            "health_score_raw": hm.get("health_score_raw"),
            "display_score": hm.get("display_score"),
            "confidence_tier": hm.get("confidence_tier"),
            "graded_n": hm.get("graded_n"),
            "health_components": hm.get("health_components"),
            "health_trend": health_trend,
            "scope_tier": scope_tier,
            "desired_tier": desired,
            "heat": heat_of(scope_tier),
            "outcome_gate": gate,
            "edge_score": edge,
            "pending_transition": pending,
            "stage_reason": reason,
            "want_reason": want_reason,
            "bus_feedback_action": bus_action,
            "evidence": {
                "components": detail.get("components"),
                "reasons": (detail.get("reasons") or [])[:5],
            },
        }
        prev_entry = prev_symbols.get(sym) or {}
        if prev_entry.get("health_score") is not None:
            entry["health_delta"] = round(health_score - float(prev_entry["health_score"]), 1)
        if prev_entry.get("lifecycle_stage") != stage:
            entry["last_transition_at"] = datetime.now(timezone.utc).isoformat()
            entry["last_transition_reason"] = reason
        else:
            entry["last_transition_at"] = prev_entry.get("last_transition_at")
            entry["last_transition_reason"] = prev_entry.get("last_transition_reason") or reason
        if stage == "demoted" and prev_entry.get("lifecycle_stage") != "demoted":
            entry["last_demoted_at"] = entry["last_transition_at"]
        else:
            entry["last_demoted_at"] = prev_entry.get("last_demoted_at")

        symbols_out[sym] = entry

    pending_list = sorted(
        pending_map.values(),
        key=lambda x: (-(x.get("edge_score") or 0), x.get("symbol", "")),
    )
    summary: dict[str, int] = {}
    for e in symbols_out.values():
        st = e.get("lifecycle_stage", "monitoring")
        summary[st] = summary.get(st, 0) + 1

    panel_limit = int((cfg.get("monitoring") or {}).get("panel_limit", 30))
    panel_rows = sorted(
        symbols_out.values(),
        key=lambda e: (
            0 if e.get("pending_transition") else 1,
            0 if e.get("lifecycle_stage") == "watch" else 1,
            -abs(float(e.get("display_score") or e.get("health_score") or e.get("conviction_score") or 0)),
        ),
    )[:panel_limit]

    return {
        "version": "watchlist-lifecycle-v1",
        "run_id": run_id,
        "review_mode": bool(cfg.get("review_mode", True)),
        "symbols": symbols_out,
        "pending_transitions": pending_list,
        "pending_count": len(pending_list),
        "blocked_promotions": blocked_promotions or [],
        "blocked_promotion_count": len(blocked_promotions or []),
        "panel_rows": panel_rows,
        "summary": summary,
        "stage_labels": STAGE_LABELS,
        "health_history": health_history,
    }


def build_and_persist_lifecycle(
    run_id: str,
    signals: dict[str, Any],
    edge_scores_map: dict[str, float],
    edge_details: dict[str, dict],
    have: dict[str, dict],
    want: dict[str, tuple[str, str]],
    decisions: list[ScopeDecision],
    post: dict[str, str],
    bus_feedback: dict[str, dict[str, Any]] | None = None,
    apply: bool = False,
    health_map: dict[str, dict[str, Any]] | None = None,
    regime_label: str | None = None,
    blocked_promotions: list[dict[str, Any]] | None = None,
    cur=None,
) -> dict[str, Any]:
    cfg = load_lifecycle_config()
    snap = build_lifecycle_snapshot(
        run_id, signals, edge_scores_map, edge_details, have, want,
        decisions, post, bus_feedback, cfg,
        health_map=health_map, regime_label=regime_label,
        blocked_promotions=blocked_promotions, cur=cur,
    )
    prev = load_lifecycle_state()
    payload = {
        **snap,
        "overrides": prev.get("overrides") or {},
        "health_history": snap.get("health_history") or {},
        "last_apply": apply,
    }
    save_lifecycle_state(payload)
    append_lifecycle_audit({
        "action": "lifecycle_tick",
        "run_id": run_id,
        "apply": apply,
        "pending_count": snap.get("pending_count"),
        "blocked_promotion_count": snap.get("blocked_promotion_count", 0),
        "summary": snap.get("summary"),
    })
    for bp in (blocked_promotions or [])[:20]:
        append_lifecycle_audit({
            "action": "blocked_promotion",
            "run_id": run_id,
            "symbol": bp.get("symbol"),
            "edge_score": bp.get("edge_score"),
            "health_score": bp.get("health_score"),
            "reason": bp.get("reason"),
        })
    return snap


def apply_manual_override(
    symbol: str,
    stage: str,
    reason: str,
    by: str = "operator",
) -> dict[str, Any]:
    sym = (symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "reason": "symbol_required"}
    if stage not in STAGE_LABELS:
        return {"ok": False, "reason": "invalid_stage", "allowed": list(STAGE_LABELS.keys())}
    trimmed = (reason or "").strip()
    if len(trimmed) < 3:
        return {"ok": False, "reason": "reason_required_min_3_chars"}

    state = load_lifecycle_state()
    overrides = dict(state.get("overrides") or {})
    overrides[sym] = {
        "stage": stage,
        "reason": trimmed,
        "by": by,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    symbols = dict(state.get("symbols") or {})
    if sym in symbols:
        symbols[sym] = {
            **symbols[sym],
            "lifecycle_stage": stage,
            "lifecycle_label": STAGE_LABELS.get(stage, stage),
            "stage_reason": f"manual_override:{trimmed[:120]}",
            "last_transition_at": datetime.now(timezone.utc).isoformat(),
            "last_transition_reason": trimmed[:200],
        }
    state["overrides"] = overrides
    state["symbols"] = symbols
    save_lifecycle_state(state)
    append_lifecycle_audit({
        "action": "manual_override",
        "symbol": sym,
        "stage": stage,
        "reason": trimmed,
        "by": by,
    })
    return {"ok": True, "symbol": sym, "stage": stage, "reason": trimmed}