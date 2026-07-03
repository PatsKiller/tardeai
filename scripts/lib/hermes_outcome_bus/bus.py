"""Read/write helpers for state/hermes/outcome_bus.json (outcome-bus-v1)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTCOME_BUS_VERSION = "outcome-bus-v1"
OUTCOME_BUS_PATH = PROJECT_ROOT / "state" / "hermes" / "outcome_bus.json"
HISTORY_DIR = PROJECT_ROOT / "state" / "hermes" / "outcome_bus_history"


def read_outcome_bus(path: Path | None = None) -> dict[str, Any] | None:
    """Load the current bus; returns None if missing or corrupt."""
    p = path or OUTCOME_BUS_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") != OUTCOME_BUS_VERSION:
            return data  # still readable — consumers check version
        return data
    except Exception:
        return None


def load_outcome_bus(path: Path | None = None) -> dict[str, Any]:
    """Load bus or return an empty shell (safe for consumers that must not crash)."""
    data = read_outcome_bus(path)
    if data:
        return data
    return {
        "version": OUTCOME_BUS_VERSION,
        "generated_at": None,
        "global": {},
        "by_symbol": {},
        "by_tag": {},
        "feedback_to_governor": [],
        "feedback_to_research": [],
    }


def write_outcome_bus(payload: dict[str, Any], apply: bool = True) -> Path | None:
    """Atomically write bus + history snapshot. Returns path when applied."""
    if not apply:
        return None
    payload = dict(payload)
    payload["version"] = OUTCOME_BUS_VERSION
    payload.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

    OUTCOME_BUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTCOME_BUS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(OUTCOME_BUS_PATH)

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    run_id = payload.get("run_id", "unknown")
    stamp = str(payload["generated_at"]).replace(":", "").replace("+", "")[:15]
    hist = HISTORY_DIR / f"outcome_bus_{stamp}_{run_id}.json"
    hist.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return OUTCOME_BUS_PATH


def governor_feedback_index(bus: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """symbol -> highest-priority governor feedback entry."""
    if not bus:
        return {}
    priority = {"pause": 0, "demote_pressure": 1, "promote_eligible": 2, "neutral": 3}
    out: dict[str, dict[str, Any]] = {}
    for item in bus.get("feedback_to_governor") or []:
        sym = str(item.get("symbol") or "").upper().strip()
        if not sym:
            continue
        action = str(item.get("action") or "neutral")
        cur = out.get(sym)
        if cur is None or priority.get(action, 9) < priority.get(str(cur.get("action")), 9):
            out[sym] = item
    return out


def _parse_generated_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _gate_counts(by_symbol: dict[str, Any]) -> dict[str, int]:
    gates = {
        "promote_eligible": 0,
        "demote_pressure": 0,
        "pause_eligible": 0,
        "promote_blocked_bad_tag": 0,
        "neutral": 0,
    }
    for meta in (by_symbol or {}).values():
        gate = str(meta.get("gate") or "neutral")
        gates[gate] = gates.get(gate, 0) + 1
    return gates


def _stop_hot_cold_trail_delta(stop_q: dict[str, Any]) -> float | None:
    by_tier = stop_q.get("by_tier") or {}
    hot = (by_tier.get("hot") or {}).get("trail_activation_rate")
    cold = (by_tier.get("cold") or {}).get("trail_activation_rate")
    if hot is None or cold is None:
        return None
    try:
        return float(hot) - float(cold)
    except (TypeError, ValueError):
        return None


def _negative_lift_tags(snap: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for tag, meta in (snap.get("by_tag") or {}).items():
        lift = meta.get("lift")
        if lift is not None and float(lift) < 0:
            tags.append(str(tag))
    return sorted(tags)


def _snapshot_trend_point(snap: dict[str, Any], ts: datetime) -> dict[str, Any]:
    g = snap.get("global") or {}
    by_sym = snap.get("by_symbol") or {}
    resource = snap.get("resource_efficiency") or {}
    stop_q = snap.get("stop_quality") or {}
    trail_delta = _stop_hot_cold_trail_delta(stop_q)
    return {
        "at": ts.isoformat(),
        "day": ts.strftime("%Y-%m-%d"),
        "run_id": snap.get("run_id"),
        "hit_rate_promotions": g.get("hit_rate_promotions"),
        "hit_rate_research_actioned": g.get("hit_rate_research_actioned"),
        "hit_rate_trades": g.get("hit_rate_trades"),
        "avg_realized_r_trades_90d": g.get("avg_realized_r_trades_90d"),
        "symbols_in_bus": len(by_sym),
        "governor_feedback_count": len(snap.get("feedback_to_governor") or []),
        "throughput_research_rows_7d": g.get("throughput_research_rows_7d"),
        "throughput_score_writes_7d": g.get("throughput_score_writes_7d"),
        "write_reduction_pct": resource.get("write_reduction_vs_baseline_pct"),
        "resource_efficiency_score": resource.get("score") or resource.get("resource_efficiency_score"),
        "trend_7d": resource.get("trend_7d"),
        "trail_activation_rate": stop_q.get("trail_activation_rate"),
        "stop_hot_cold_trail_delta": trail_delta,
        "r_left_on_table_avg": stop_q.get("r_left_on_table_avg"),
        "mae_exceeded_planned_stop_pct": stop_q.get("mae_exceeded_planned_stop_pct"),
        "aligned_pct": stop_q.get("aligned_pct"),
        "negative_lift_tags": _negative_lift_tags(snap),
        "research_downrank_tags": [
            str(x.get("tag")) for x in (snap.get("feedback_to_research") or [])
            if x.get("action") == "downrank" and x.get("tag")
        ],
        "active_alert_ids": [a.get("id") for a in (snap.get("alerts") or {}).get("active") or [] if a.get("id")],
        "active_alert_count": len((snap.get("alerts") or {}).get("active") or []),
        "maturity_overall_status": (snap.get("maturity") or {}).get("overall_status"),
        "maturity_tier": (snap.get("maturity") or {}).get("tier"),
        "maturity_score": (snap.get("maturity") or {}).get("maturity_score"),
        "maturity_composite_score": (snap.get("maturity") or {}).get("composite_score"),
        "maturity_outcome_yield_score": ((snap.get("maturity") or {}).get("components") or {})
            .get("outcome_yield", {}).get("score"),
        "maturity_scope_discipline_score": ((snap.get("maturity") or {}).get("components") or {})
            .get("scope_discipline", {}).get("score"),
        "maturity_stop_quality_score": ((snap.get("maturity") or {}).get("components") or {})
            .get("stop_quality", {}).get("score"),
        "maturity_feedback_loop_score": ((snap.get("maturity") or {}).get("components") or {})
            .get("feedback_loop", {}).get("score"),
        "maturity_research_actionability_score": ((snap.get("maturity") or {}).get("components") or {})
            .get("research_actionability", {}).get("score"),
        "maturity_outcome_yield": (snap.get("maturity") or {}).get("outcome_yield", {}).get("rating"),
        "maturity_scope_discipline": (snap.get("maturity") or {}).get("scope_discipline", {}).get("rating"),
        "maturity_closed_loop": (snap.get("maturity") or {}).get("closed_loop", {}).get("rating"),
        "gates": _gate_counts(by_sym),
    }


def load_outcome_bus_trend(days: int = 30) -> dict[str, Any]:
    """Daily outcome-bus trend from current file + history snapshots (latest per UTC day)."""
    days = max(1, min(int(days), 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots: list[tuple[datetime, dict[str, Any]]] = []
    current = read_outcome_bus()
    if current:
        ts = _parse_generated_at(current.get("generated_at"))
        if ts and ts >= cutoff:
            snapshots.append((ts, current))

    if HISTORY_DIR.exists():
        for path in HISTORY_DIR.glob("outcome_bus_*.json"):
            try:
                snap = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            ts = _parse_generated_at(snap.get("generated_at"))
            if ts and ts >= cutoff:
                snapshots.append((ts, snap))

    by_day: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for ts, snap in snapshots:
        day = ts.strftime("%Y-%m-%d")
        cur = by_day.get(day)
        if cur is None or ts > cur[0]:
            by_day[day] = (ts, snap)

    series = [_snapshot_trend_point(snap, ts) for day, (ts, snap) in sorted(by_day.items())]
    promo = [s["hit_rate_promotions"] for s in series if s.get("hit_rate_promotions") is not None]
    symbols = [s["symbols_in_bus"] for s in series if s.get("symbols_in_bus") is not None]
    eff_scores = [s["resource_efficiency_score"] for s in series if s.get("resource_efficiency_score") is not None]
    trail_rates = [s["trail_activation_rate"] for s in series if s.get("trail_activation_rate") is not None]

    from .alerts import build_maturity_trend

    return {
        "days": days,
        "count": len(series),
        "series": series,
        "maturity_trend": build_maturity_trend({"series": series}),
        "summary": {
            "current_hit_rate_promotions": promo[-1] if promo else None,
            "peak_hit_rate_promotions": max(promo) if promo else None,
            "low_hit_rate_promotions": min(promo) if promo else None,
            "delta_hit_rate_promotions": (promo[-1] - promo[0]) if len(promo) >= 2 else None,
            "current_symbols_in_bus": symbols[-1] if symbols else None,
            "delta_symbols_in_bus": (symbols[-1] - symbols[0]) if len(symbols) >= 2 else None,
            "current_resource_efficiency_score": eff_scores[-1] if eff_scores else None,
            "delta_resource_efficiency_score": (eff_scores[-1] - eff_scores[0]) if len(eff_scores) >= 2 else None,
            "trend_7d": series[-1].get("trend_7d") if series else None,
            "current_trail_activation_rate": trail_rates[-1] if trail_rates else None,
            "first_at": series[0]["at"] if series else None,
            "last_at": series[-1]["at"] if series else None,
            "schedule": "nightly after tag_engine (03:25 UTC)",
        },
    }


def research_tag_multipliers(bus: dict[str, Any] | None) -> dict[str, float]:
    """tag -> quality_multiplier from by_tag and feedback_to_research."""
    if not bus:
        return {}
    mult: dict[str, float] = {}
    for tag, meta in (bus.get("by_tag") or {}).items():
        m = meta.get("quality_multiplier")
        if m is not None:
            mult[str(tag)] = float(m)
    for item in bus.get("feedback_to_research") or []:
        tag = str(item.get("tag") or "").strip()
        m = item.get("quality_multiplier")
        if tag and m is not None:
            mult[tag] = float(m)
    return mult