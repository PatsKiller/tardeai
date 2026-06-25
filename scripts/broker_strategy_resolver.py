#!/usr/bin/env python3
"""Resolve watchlist sleeve labels → executable strategy YAML + strategy-based exit plan."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Watchlist strategy_cards use portfolio sleeve types — not proposal strategy_id values.
WATCHLIST_SLEEVES = frozenset({
    "income", "core_holding", "growth_etf", "speculative_growth", "defense_thesis",
})

SLEEVE_TO_STRATEGY: dict[str, str] = {
    "income": "dividend_growth_compounder",
    "core_holding": "core_growth_compounder",
    "growth_etf": "core_index",
    "speculative_growth": "swing_breakout",
    "defense_thesis": "defense_thesis",
}


def _load_cfg(strategy_id: str) -> dict:
    try:
        from strategy_config_loader import load_strategy_config
        return load_strategy_config(strategy_id) or {}
    except Exception:
        return {}


def _ticker_classification(symbol: str) -> str | None:
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            """SELECT strategy_type FROM ticker_strategy_classifications
               WHERE upper(symbol) = upper(%s)
               ORDER BY active DESC NULLS LAST, updated_at DESC NULLS LAST
               LIMIT 1""",
            (symbol,),
        )
        row = cur.fetchone()
        return str(row[0]).strip() if row and row[0] else None
    except Exception:
        return None


def is_watchlist_sleeve(strategy_id: str | None) -> bool:
    return str(strategy_id or "").strip().lower() in WATCHLIST_SLEEVES


def resolve_executable_strategy(symbol: str, strategy_id_or_sleeve: str | None = None) -> dict:
    """Map symbol + proposal strategy field to a YAML strategy_id with metadata."""
    sym = str(symbol or "").upper().strip()
    raw = str(strategy_id_or_sleeve or "").strip()
    sleeve = raw if is_watchlist_sleeve(raw) else None
    explicit = raw if raw and not sleeve else None

    classified = _ticker_classification(sym) if sym else None

    # EXPLICIT proposal strategy_id wins first: it's the strategy the signal actually fired on. A
    # generic ticker_classification must NOT override it — that mislabeled TECH's fib_retracement_bounce
    # as 'high_yield_income_bdc' (TECH is misclassified as income; a fib bounce on a biotech is not a
    # BDC/CLO income trade). Classification is only a fallback when there's no explicit signal strategy.
    if explicit and _load_cfg(explicit):
        return {
            "strategy_id": explicit,
            "watchlist_sleeve": sleeve,
            "resolve_source": "proposal_strategy_id",
            "classified_strategy": classified,
        }

    if classified and _load_cfg(classified):
        return {
            "strategy_id": classified,
            "watchlist_sleeve": sleeve or (raw if is_watchlist_sleeve(raw) else None),
            "resolve_source": "ticker_classification",
            "classified_strategy": classified,
        }

    if sleeve:
        mapped = SLEEVE_TO_STRATEGY.get(sleeve)
        if mapped and _load_cfg(mapped):
            return {
                "strategy_id": mapped,
                "watchlist_sleeve": sleeve,
                "resolve_source": "sleeve_map",
                "classified_strategy": classified,
            }

    fallback = "swing_breakout" if _load_cfg("swing_breakout") else "momentum_scalp"
    return {
        "strategy_id": fallback,
        "watchlist_sleeve": sleeve or raw or None,
        "resolve_source": "fallback",
        "classified_strategy": classified,
    }


def apply_strategy_exit_plan(
    entry: float,
    stop: float | None,
    target: float | None,
    strategy_id: str,
    *,
    support: float | None = None,
    resistance: float | None = None,
) -> tuple[float, float, float, dict]:
    """Fill missing stop/target using strategy exit_rules + risk.target_rr."""
    cfg = _load_cfg(strategy_id)
    risk = cfg.get("risk") or {}
    exit_rules = cfg.get("exit_rules") or {}
    target_rr = float(risk.get("target_rr") or 2.0)
    stop_method = str(exit_rules.get("stop_method") or "level_based")
    target_method = str(exit_rules.get("target_method") or "rr_based")
    sources: list[str] = []

    en = round(float(entry), 2)
    st = round(float(stop), 2) if stop else None
    tg = round(float(target), 2) if target else None

    if not st or st <= 0 or st >= en:
        if support and stop_method in ("level_based", "fundamental"):
            st = round(float(support) * 0.97, 2)
            sources.append(f"stop below support ${float(support):.2f} ({stop_method})")
        elif stop_method == "fixed_pct":
            pct = float(exit_rules.get("stop_max_pct") or 0.05)
            st = round(en * (1 - pct), 2)
            sources.append(f"stop {pct * 100:.1f}% below entry ({stop_method})")
        else:
            st = round(en * 0.95, 2)
            sources.append("stop 5% below entry (generic fallback)")

    risk_ps = max(0.01, en - st)
    resistance_target = None
    if not tg or tg <= en:
        if resistance and target_method in ("trailing", "rr_based", "level_based"):
            resistance_target = round(float(resistance) * 1.02, 2)
            tg = resistance_target
            sources.append(f"target above resistance ${float(resistance):.2f} ({target_method})")
        else:
            tg = round(en + risk_ps * target_rr, 2)
            sources.append(f"target {target_rr}:1 R:R policy ({strategy_id})")

    # Thesis + YAML floor: keep support-anchored stop, raise target if resistance caps R:R too low.
    try:
        from broker_thesis_validity import MIN_RR_DEFAULT
        min_rr = max(float(target_rr), float(MIN_RR_DEFAULT))
    except Exception:
        min_rr = max(float(target_rr), 2.0)
    policy_floor = round(en + risk_ps * min_rr, 2)
    if tg < policy_floor:
        capped = tg
        tg = policy_floor
        if resistance_target is not None:
            sources.append(
                f"target raised to {min_rr:.1f}:1 policy floor (resistance capped ${capped:.2f})"
            )
        else:
            sources.append(f"target set to {min_rr:.1f}:1 policy floor ({strategy_id})")

    execution = cfg.get("execution") or {}
    rationale = {
        "strategy_id": strategy_id,
        "display_name": cfg.get("display_name") or strategy_id.replace("_", " ").title(),
        "purpose": cfg.get("purpose"),
        "stop_method": stop_method,
        "target_method": target_method,
        "target_rr_policy": target_rr,
        "sources": sources,
        "live_allowed": execution.get("live_allowed"),
        "strategy_status": cfg.get("status"),
        "timeframe_class": cfg.get("timeframe_class"),
    }
    return en, st, tg, rationale


def build_exit_summary(rationale: dict, entry: float, stop: float, target: float) -> str:
    parts = [
        f"{rationale.get('display_name') or rationale.get('strategy_id')}",
        f"stop: {rationale.get('stop_method')}",
        f"target: {rationale.get('target_method')}",
        f"policy R:R {rationale.get('target_rr_policy')}",
    ]
    if entry and stop and target and entry > stop:
        rr = round((target - entry) / (entry - stop), 2)
        parts.append(f"plan {rr}:1")
    if rationale.get("sources"):
        parts.append("; ".join(rationale["sources"][:2]))
    return " · ".join(str(p) for p in parts if p)