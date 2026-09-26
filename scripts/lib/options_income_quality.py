"""Quality screen for income option ideas (covered calls, cash-secured puts).

2026-09-26: every desk card was BLOCKED because the generator built ideas the
enterprise liquidity gate was always going to refuse -- strikes set by a fixed
percentage, contracts ranked on strike/DTE distance only, no premium floor, a
$1.84 stock with no chain. The gate was right; the input was wrong. This module
screens before a card is built and names the reason, so the funnel says why a
name has no idea instead of showing a dead card.

Thresholds come from ``options_desk_settings`` in assets/portfolio_intent.yaml.
Advisory only: nothing here sizes, orders or loosens a gate.
"""
from __future__ import annotations

from typing import Any, Optional

# Fallbacks only; the YAML block is the source of truth.
_DEFAULTS = {
    "min_underlying_price": 5.0,
    "min_premium_per_share": 0.10,
    "min_annualized_roc_pct": 6.0,
    "picker_strike_slack_pct": 8.0,
    "csp_target_abs_delta": 0.25,
    "cc_target_delta": 0.25,
    "edge_roc_full_credit_ann_pct": 25.0,
}


def setting(cfg: Optional[dict], key: str) -> Any:
    cfg = cfg or {}
    v = cfg.get(key)
    return _DEFAULTS[key] if v is None else v


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def spread_pct(contract: dict) -> Optional[float]:
    bid, ask = _num(contract.get("bid")) or 0.0, _num(contract.get("ask")) or 0.0
    mid = _num(contract.get("mid")) or ((bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0)
    if mid <= 0 or ask < bid or bid <= 0:
        return None
    return 100.0 * (ask - bid) / mid


def is_liquid(contract: dict, cfg: Optional[dict]) -> bool:
    """Same thresholds as options_desk_enterprise.liquidity_gate (OI and spread)."""
    cfg = cfg or {}
    oi = _num(contract.get("oi"))
    sp = spread_pct(contract)
    min_oi = float(cfg.get("min_open_interest") or 50)
    max_sp = float(cfg.get("max_bid_ask_spread_pct") or 12.0)
    return oi is not None and oi >= min_oi and sp is not None and sp <= max_sp


def annualized_roc_pct(premium: float, capital: float, dte: int) -> float:
    if capital <= 0 or premium <= 0:
        return 0.0
    return (premium / capital) * (365.0 / max(int(dte or 0), 1)) * 100.0


def income_drop_reason(
    strategy: str,
    contract: Optional[dict],
    data_source: str,
    underlying: float,
    cfg: Optional[dict],
) -> Optional[str]:
    """Why this income idea should not become a card, or None when it may.

    PRICE_BELOW_FLOOR, NO_CHAIN, NO_LIQUID_CONTRACT, PREMIUM_BELOW_FLOOR.
    """
    cfg = cfg or {}
    if underlying < float(setting(cfg, "min_underlying_price")):
        return "PRICE_BELOW_FLOOR"
    if not contract:
        return "NO_CHAIN"
    if data_source == "bs_estimate" and bool(cfg.get("require_chain_for_live", True)):
        return "NO_CHAIN"
    if not is_liquid(contract, cfg):
        return "NO_LIQUID_CONTRACT"
    premium = _num(contract.get("mid")) or 0.0
    if premium < float(setting(cfg, "min_premium_per_share")):
        return "PREMIUM_BELOW_FLOOR"
    strike = _num(contract.get("strike")) or 0.0
    capital = (strike - premium) if strategy == "cash_secured_put" else underlying
    if annualized_roc_pct(premium, capital, int(contract.get("dte") or 0)) < float(setting(cfg, "min_annualized_roc_pct")):
        return "PREMIUM_BELOW_FLOOR"
    return None


def roc_score(ann_pct: float, cfg: Optional[dict], cap: float) -> float:
    """Return-on-capital points for the wheel edge score, full credit at the configured yield."""
    full = float(setting(cfg, "edge_roc_full_credit_ann_pct"))
    if full <= 0:
        return cap
    return max(0.0, min(cap, cap * ann_pct / full))
