"""Holdings health scoring and lifecycle stages — advisory only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CFG_PATH = PROJECT_ROOT / "config" / "hermes_holdings_lifecycle.yaml"
STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_holdings_lifecycle.json"
AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_holdings_lifecycle_audit.jsonl"
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
TECH_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "technical_snapshot.json"

HoldingStage = Literal["healthy", "watch", "trim_candidate", "exited"]

STAGE_LABELS: dict[str, str] = {
    "healthy": "Healthy",
    "watch": "Watch",
    "trim_candidate": "Trim Candidate",
    "exited": "Exited / Archived",
}

RECOMMENDED_ACTIONS: dict[str, str] = {
    "healthy": "monitor",
    "watch": "review_stops_and_research",
    "trim_candidate": "operator_trim_review",
    "exited": "none",
}


def load_config() -> dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"enabled": True}


def load_holdings_lifecycle_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": "holdings-lifecycle-v1", "holdings": {}, "summary": {}, "history": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "holdings-lifecycle-v1", "holdings": {}, "summary": {}, "history": {}}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def save_state(payload: dict[str, Any]) -> Path:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(STATE_PATH, payload)
    return STATE_PATH


def append_audit(event: dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), **event}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _norm_0_100(value: float | None, lo: float, hi: float, default: float = 50.0) -> float:
    if value is None:
        return default
    if hi <= lo:
        return default
    return _clamp(100.0 * (float(value) - lo) / (hi - lo))


def _load_positions() -> dict[str, dict[str, Any]]:
    """Aggregate holdings.json by symbol."""
    agg: dict[str, dict[str, Any]] = {}
    try:
        data = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return agg
    tech: dict[str, Any] = {}
    try:
        tech = json.loads(TECH_PATH.read_text(encoding="utf-8")) if TECH_PATH.exists() else {}
    except Exception:
        pass

    for p in data.get("holdings") or []:
        if p.get("is_cash") or p.get("is_loan"):
            continue
        sym = str(p.get("symbol") or "").upper().strip()
        if not sym or sym == "CASH":
            continue
        shares = float(p.get("shares") or 0)
        price = float(p.get("current_price") or p.get("price") or 0)
        cost = float(p.get("cost_basis") or 0)
        mv = float(p.get("market_value") or (shares * price if price else 0))
        if sym not in agg:
            agg[sym] = {
                "symbol": sym,
                "shares": 0.0,
                "market_value": 0.0,
                "cost_basis": 0.0,
                "accounts": [],
            }
        agg[sym]["shares"] += shares
        agg[sym]["market_value"] += mv
        agg[sym]["cost_basis"] += cost
        acct = p.get("account")
        if acct and acct not in agg[sym]["accounts"]:
            agg[sym]["accounts"].append(acct)

    for sym, row in agg.items():
        cb = row["cost_basis"]
        mv = row["market_value"]
        row["gain_pct"] = round((mv - cb) / cb * 100, 2) if cb > 0 and mv > 0 else None
        ts = tech.get(sym) if isinstance(tech.get(sym), dict) else {}
        row["pct_from_high"] = ts.get("pct_from_high")
        row["rsi"] = ts.get("rsi")
    return agg


def _llm_health_scores(cfg: dict[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in (cfg.get("llm_health_scores") or {}).items()}


def _fetch_llm_health() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _db_query, USE_DB
        if not USE_DB:
            return out
        rows = _db_query("""
            SELECT UPPER(symbol) AS symbol, holdings_llm_health, holdings_llm_action,
                   holdings_llm_confidence, holdings_llm_at
            FROM watchlist_items
            WHERE source = 'portfolio' AND holdings_llm_health IS NOT NULL
        """) or []
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if sym:
                out[sym] = r
    except Exception:
        pass
    return out


def _component_scores(
    sym: str,
    position: dict[str, Any],
    bus_sym: dict[str, Any] | None,
    gov_fb: dict[str, Any] | None,
    llm: dict[str, Any] | None,
    stop_global: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, float]:
    llm_map = _llm_health_scores(cfg)
    bus_sym = bus_sym or {}
    gov_fb = gov_fb or {}

    # Stop quality — hot-tier slice for S0 holdings + global fallbacks
    by_tier = stop_global.get("by_tier") or {}
    hot_tier = by_tier.get("hot") or {}
    aligned = hot_tier.get("aligned_pct") or stop_global.get("aligned_pct")
    trail = hot_tier.get("trail_activation_rate") or stop_global.get("trail_activation_rate")
    r_left = hot_tier.get("r_left_on_table_avg") or stop_global.get("r_left_on_table_avg")
    stop_pts = 65.0
    if aligned is not None:
        stop_pts = _norm_0_100(float(aligned), 0.4, 0.85, 55.0)
    if trail is not None:
        stop_pts = _clamp(0.55 * stop_pts + 0.45 * _norm_0_100(float(trail), 0.25, 0.65, 50.0))
    if r_left is not None:
        try:
            rl = float(r_left)
            if rl > 20:
                stop_pts = _clamp(stop_pts - 15)
            elif rl > 12:
                stop_pts = _clamp(stop_pts - 8)
        except (TypeError, ValueError):
            pass
    if str(gov_fb.get("action") or "").lower() in ("pause", "demote_pressure"):
        stop_pts = _clamp(stop_pts - 20)

    # Outcome consistency from bus by_symbol
    gate = str(bus_sym.get("gate") or "neutral")
    lift = bus_sym.get("lift")
    n = int(bus_sym.get("n") or 0)
    outcome_pts = 60.0
    if n >= 3:
        hits = int(bus_sym.get("outcome_hits") or bus_sym.get("hits") or 0)
        misses = int(bus_sym.get("misses") or 0)
        graded = hits + misses + int(bus_sym.get("neutral") or 0)
        if graded > 0:
            outcome_pts = _norm_0_100(hits / graded, 0.25, 0.65, 50.0)
    if gate == "promote_eligible":
        outcome_pts = _clamp(outcome_pts + 10)
    elif gate in ("demote_pressure", "pause_eligible"):
        outcome_pts = _clamp(outcome_pts - 25)
    if lift is not None and float(lift) < 0:
        outcome_pts = _clamp(outcome_pts - 15)

    # Realized R
    avg_r = bus_sym.get("avg_r")
    r_pts = _norm_0_100(float(avg_r) if avg_r is not None else None, -0.5, 1.5, 50.0)

    # Research actionability
    llm_tier = str((llm or {}).get("holdings_llm_health") or "").upper()
    research_pts = llm_map.get(llm_tier, 60.0)
    if bus_sym.get("tag_flagged"):
        research_pts = _clamp(research_pts - 10)

    # Position risk — drawdown / underwater
    gain = position.get("gain_pct")
    from_high = position.get("pct_from_high")
    risk_pts = 70.0
    if gain is not None:
        if gain < -15:
            risk_pts = 25.0
        elif gain < -5:
            risk_pts = 45.0
        elif gain > 20:
            risk_pts = 85.0
    if from_high is not None:
        try:
            dd = abs(float(from_high))
            if dd > 25:
                risk_pts = _clamp(risk_pts - 20)
            elif dd > 15:
                risk_pts = _clamp(risk_pts - 10)
        except (TypeError, ValueError):
            pass

    return {
        "stop_quality": round(stop_pts, 1),
        "outcome_consistency": round(outcome_pts, 1),
        "realized_r": round(r_pts, 1),
        "research_actionability": round(research_pts, 1),
        "position_risk": round(risk_pts, 1),
    }


def compute_health_score_raw(components: dict[str, float], cfg: dict[str, Any]) -> float:
    weights = cfg.get("health_weights") or {}
    total_w = sum(float(v) for v in weights.values()) or 1.0
    return sum(float(weights.get(k, 0)) * components.get(k, 50.0) for k in components) / total_w


def apply_confidence_discount(score: float, graded_n: int, cfg: dict[str, Any]) -> tuple[float, str]:
    conf = cfg.get("confidence") or {}
    min_full = int(conf.get("min_graded_for_full", 4))
    min_samples = int(conf.get("min_graded_samples", 2))
    mult_low = float(conf.get("low_graded_multiplier", 0.80))
    mult_sparse = float(conf.get("sparse_multiplier", 0.88))
    if graded_n < min_samples:
        return round(_clamp(score * mult_sparse), 1), "sparse_data"
    if graded_n < min_full:
        return round(_clamp(score * mult_low), 1), "low_confidence"
    return round(_clamp(score), 1), "full"


def compute_health_score(components: dict[str, float], cfg: dict[str, Any], graded_n: int = 0) -> float:
    raw = compute_health_score_raw(components, cfg)
    final, _ = apply_confidence_discount(raw, graded_n, cfg)
    return final


def resolve_stage(
    health: float,
    gate: str | None,
    gov_action: str | None,
    override: str | None,
    is_exited: bool,
    cfg: dict[str, Any],
) -> tuple[str, str]:
    if override in STAGE_LABELS:
        return override, f"manual_override:{override}"
    if is_exited:
        return "exited", "no_longer_in_portfolio"

    thr = cfg.get("thresholds") or {}
    healthy_min = float(thr.get("healthy_min", 70))
    watch_min = float(thr.get("watch_min", 50))

    ga = str(gov_action or "").lower()
    g = str(gate or "neutral")
    if g == "pause_eligible" or ga == "pause":
        return "trim_candidate", "outcome_pause_or_governor_pause"
    if g == "demote_pressure" or ga == "demote_pressure":
        return "watch", "outcome_demote_pressure"
    if health >= healthy_min:
        return "healthy", f"health>={healthy_min:.0f}"
    if health >= watch_min:
        return "watch", f"health>={watch_min:.0f}"
    return "trim_candidate", f"health<{watch_min:.0f}"


def build_holdings_lifecycle_snapshot(
    run_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    if not cfg.get("enabled", True):
        return {"enabled": False}

    positions = _load_positions()
    llm_health = _fetch_llm_health()
    prev = load_holdings_lifecycle_state()
    prev_holdings = prev.get("holdings") or {}
    overrides = prev.get("overrides") or {}
    history: dict[str, list] = dict(prev.get("history") or {})

    bus: dict[str, Any] = {}
    stop_global: dict[str, Any] = {}
    gov_by_sym: dict[str, dict[str, Any]] = {}
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
        from lib.hermes_outcome_bus.bus import read_outcome_bus
        bus = read_outcome_bus() or {}
        stop_global = bus.get("stop_quality") or {}
        for fb in bus.get("feedback_to_governor") or []:
            s = str(fb.get("symbol") or "").upper()
            if s:
                gov_by_sym[s] = fb
    except Exception:
        pass

    holdings_out: dict[str, dict[str, Any]] = {}
    current_syms = set(positions.keys())

    for sym, pos in positions.items():
        bus_sym = (bus.get("by_symbol") or {}).get(sym)
        components = _component_scores(
            sym, pos, bus_sym, gov_by_sym.get(sym), llm_health.get(sym), stop_global, cfg,
        )
        graded_n = int((bus_sym or {}).get("n") or 0)
        raw_health = round(_clamp(compute_health_score_raw(components, cfg)), 1)
        health, confidence_tier = apply_confidence_discount(raw_health, graded_n, cfg)
        gate = (bus_sym or {}).get("gate")
        gov_action = (gov_by_sym.get(sym) or {}).get("action")
        override = (overrides.get(sym) or {}).get("stage")
        stage, reason = resolve_stage(health, gate, gov_action, override, False, cfg)
        hints = (cfg.get("monitoring_hints") or {}).get(stage) or {}

        prev_h = prev_holdings.get(sym) or {}
        entry = {
            "symbol": sym,
            "lifecycle_stage": stage,
            "lifecycle_label": STAGE_LABELS.get(stage, stage),
            "health_score": health,
            "health_score_raw": raw_health,
            "confidence_tier": confidence_tier,
            "graded_n": graded_n,
            "components": components,
            "health_components": components,
            "recommended_action": RECOMMENDED_ACTIONS.get(stage, "monitor"),
            "stage_reason": reason,
            "gain_pct": pos.get("gain_pct"),
            "market_value": round(pos.get("market_value") or 0, 2),
            "outcome_gate": gate,
            "governor_action": gov_action,
            "llm_health": (llm_health.get(sym) or {}).get("holdings_llm_health"),
            "monitoring": hints,
            "evidence": {
                "bus_n": (bus_sym or {}).get("n"),
                "bus_lift": (bus_sym or {}).get("lift"),
                "pct_from_high": pos.get("pct_from_high"),
            },
        }
        if prev_h.get("health_score") is not None:
            entry["health_delta"] = round(health - float(prev_h["health_score"]), 1)
        if prev_h.get("lifecycle_stage") != stage:
            entry["last_transition_at"] = datetime.now(timezone.utc).isoformat()
            entry["last_transition_reason"] = reason
            append_audit({
                "action": "stage_transition",
                "symbol": sym,
                "from_stage": prev_h.get("lifecycle_stage"),
                "to_stage": stage,
                "health_score": health,
                "components": components,
                "reason": reason,
                "run_id": run_id,
            })
        else:
            entry["last_transition_at"] = prev_h.get("last_transition_at")
            entry["last_transition_reason"] = prev_h.get("last_transition_reason") or reason

        hist = list(history.get(sym) or [])
        hist.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "health_score": health,
            "stage": stage,
        })
        history[sym] = hist[-int(cfg.get("history_days", 14)):]

        holdings_out[sym] = entry

    for sym, prev_h in prev_holdings.items():
        if sym not in current_syms and prev_h.get("lifecycle_stage") != "exited":
            holdings_out[sym] = {
                **prev_h,
                "lifecycle_stage": "exited",
                "lifecycle_label": STAGE_LABELS["exited"],
                "stage_reason": "no_longer_in_portfolio",
                "last_transition_at": datetime.now(timezone.utc).isoformat(),
                "monitoring": (cfg.get("monitoring_hints") or {}).get("exited") or {},
            }

    summary: dict[str, int] = {}
    for e in holdings_out.values():
        if e.get("lifecycle_stage") == "exited" and e.get("symbol") not in current_syms:
            summary["exited"] = summary.get("exited", 0) + 1
        st = e.get("lifecycle_stage", "healthy")
        summary[st] = summary.get(st, 0) + 1

    panel_limit = int(cfg.get("panel_limit", 25))
    panel_rows = sorted(
        [e for e in holdings_out.values() if e.get("lifecycle_stage") != "exited"],
        key=lambda e: (
            {"trim_candidate": 0, "watch": 1, "healthy": 2}.get(e.get("lifecycle_stage", ""), 3),
            float(e.get("health_score") or 100),
        ),
    )[:panel_limit]

    return {
        "version": "holdings-lifecycle-v1",
        "run_id": run_id,
        "review_mode": bool(cfg.get("review_mode", True)),
        "holdings": holdings_out,
        "panel_rows": panel_rows,
        "summary": summary,
        "position_count": len(current_syms),
        "stage_labels": STAGE_LABELS,
        "history": history,
    }


def build_and_persist_holdings_lifecycle(run_id: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    snap = build_holdings_lifecycle_snapshot(run_id=run_id, cfg=cfg)
    prev = load_holdings_lifecycle_state()
    payload = {**snap, "overrides": prev.get("overrides") or {}}
    save_state(payload)
    append_audit({
        "action": "holdings_lifecycle_tick",
        "run_id": run_id,
        "position_count": snap.get("position_count"),
        "summary": snap.get("summary"),
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

    state = load_holdings_lifecycle_state()
    overrides = dict(state.get("overrides") or {})
    overrides[sym] = {"stage": stage, "reason": trimmed, "by": by, "at": datetime.now(timezone.utc).isoformat()}
    state["overrides"] = overrides
    holdings = dict(state.get("holdings") or {})
    if sym in holdings:
        holdings[sym] = {
            **holdings[sym],
            "lifecycle_stage": stage,
            "lifecycle_label": STAGE_LABELS.get(stage, stage),
            "stage_reason": f"manual_override:{trimmed[:120]}",
            "last_transition_at": datetime.now(timezone.utc).isoformat(),
        }
    state["holdings"] = holdings
    save_state(state)
    append_audit({"action": "manual_override", "symbol": sym, "stage": stage, "reason": trimmed, "by": by})
    return {"ok": True, "symbol": sym, "stage": stage, "reason": trimmed}