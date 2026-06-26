#!/usr/bin/env python3
"""options_desk_enterprise.py — Enterprise trade desk layer for options_engine.

Adds institutional-grade controls on top of the advisory desk:
  • Earnings / event blackout (FMP calendar)
  • Liquidity gates (OI, volume, bid-ask spread)
  • Vol analytics (term structure, put/call skew from live chain)
  • Book-level greeks aggregation (Δ, Γ, Θ, ν)
  • Portfolio risk preflight (concentration, net delta, notional caps)
  • Desk approval queue (operator review before live submit)
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
DESK_RUNTIME = PROJECT_ROOT / "data" / "runtime" / "options_desk_enterprise.json"

SHORT_STRATEGIES = frozenset({"covered_call", "cash_secured_put", "credit_spread"})
BLOCKING_STRATEGIES = frozenset({"covered_call", "cash_secured_put", "credit_spread", "long_call"})


def _f(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_desk_config() -> dict:
    """Merge portfolio_intent options_desk_settings with env overrides."""
    cfg: dict = {}
    try:
        import yaml
        intent = yaml.safe_load((PROJECT_ROOT / "assets" / "portfolio_intent.yaml").read_text()) or {}
        cfg = dict(intent.get("options_desk_settings") or {})
        cc = intent.get("covered_call_settings") or {}
        cfg.setdefault("earnings_blackout_days", cc.get("earnings_blackout_days", 14))
    except Exception:
        cfg = {}
    cfg.setdefault("earnings_blackout_days", int(os.getenv("OPTIONS_EARNINGS_BLACKOUT_DAYS", "14")))
    cfg.setdefault("min_open_interest", int(os.getenv("OPTIONS_MIN_OI", "50")))
    cfg.setdefault("min_volume", int(os.getenv("OPTIONS_MIN_VOLUME", "5")))
    cfg.setdefault("max_bid_ask_spread_pct", float(os.getenv("OPTIONS_MAX_SPREAD_PCT", "12.0")))
    cfg.setdefault("require_chain_for_live", os.getenv("OPTIONS_REQUIRE_CHAIN_LIVE", "1") == "1")
    cfg.setdefault("max_net_delta_pct", float(os.getenv("OPTIONS_MAX_NET_DELTA_PCT", "35.0")))
    cfg.setdefault("max_symbol_notional_pct", float(os.getenv("OPTIONS_MAX_SYMBOL_NOTIONAL_PCT", "25.0")))
    cfg.setdefault("approval_required", os.getenv("OPTIONS_APPROVAL_REQUIRED", "1") == "1")
    cfg.setdefault("desk_tier_edge_a", float(os.getenv("OPTIONS_DESK_TIER_A_EDGE", "72")))
    cfg.setdefault("desk_tier_edge_b", float(os.getenv("OPTIONS_DESK_TIER_B_EDGE", "62")))
    # Hard preflight limits (live path only — advisory desk may warn)
    hr = cfg.get("hard_risk_limits") or {}
    cfg.setdefault("hard_max_contracts_per_order", int(hr.get("max_contracts_per_order", 5)))
    cfg.setdefault("hard_max_daily_orders", int(hr.get("max_daily_orders", 10)))
    cfg.setdefault("hard_max_daily_notional", float(hr.get("max_daily_notional", 50_000)))
    cfg.setdefault("hard_max_daily_loss", float(hr.get("max_daily_loss", 5_000)))
    cfg.setdefault("hard_max_per_strategy_notional", float(hr.get("max_per_strategy_notional", 30_000)))
    cfg.setdefault("hard_max_per_account_notional", float(hr.get("max_per_account_notional", 75_000)))
    cfg.setdefault("hard_min_buying_power", float(hr.get("min_buying_power", 5_000)))
    cfg.setdefault("hard_quote_max_age_seconds", int(hr.get("quote_max_age_seconds", 120)))
    cfg.setdefault("hard_chain_max_age_seconds", int(hr.get("chain_max_age_seconds", 300)))
    cfg.setdefault("hard_quote_move_tolerance_pct", float(hr.get("quote_move_tolerance_pct", 2.0)))
    return cfg


def _hard_block(
    code: str,
    reason: str,
    *,
    severity: str = "hard",
    source: str = "options_desk_enterprise",
    snapshot: Optional[dict] = None,
) -> dict:
    return {
        "code": code,
        "reason": reason,
        "severity": severity,
        "source": source,
        "function": "evaluate_hard_risk_blocks",
        "snapshot": snapshot or {},
    }


def is_desk_queue_approved(proposal_id: str) -> bool:
    ok, _ = check_preflight_approval(proposal_id)
    return ok


def evaluate_hard_risk_blocks(
    proposal: dict,
    *,
    mode: str = "live",
    holdings: Optional[List[dict]] = None,
    positions: Optional[List[dict]] = None,
    cfg: Optional[dict] = None,
) -> List[dict]:
    """Configurable hard preflight rejects for live paths. Each block is machine-coded."""
    if mode not in ("live", "operator_required"):
        return []
    cfg = cfg or load_desk_config()
    blocks: List[dict] = []
    sym = (proposal.get("symbol") or proposal.get("underlying") or "").upper()
    strat = proposal.get("strategy") or ""
    dte = int(proposal.get("dte") or 30)
    contracts = int(proposal.get("contracts") or 1)
    ent = proposal.get("enterprise") or {}
    liq = ent.get("liquidity") or proposal.get("liquidity") or {}

    # Earnings blackout
    blackout = ent.get("earnings") or earnings_blackout_check(sym, dte=dte, strategy=strat)
    if blackout.get("in_blackout"):
        blocks.append(_hard_block("earnings_blackout", blackout.get("reason") or "earnings window",
                                  snapshot=blackout))

    # Ex-dividend risk for covered calls
    if strat == "covered_call" and proposal.get("ex_div_within_dte"):
        blocks.append(_hard_block("ex_dividend_cc_risk", "ex-dividend within DTE for covered call",
                                  snapshot={"ex_div": proposal.get("ex_div_date")}))

    # Liquidity / chain
    if proposal.get("data_source") == "bs_estimate" and cfg.get("require_chain_for_live"):
        blocks.append(_hard_block("bs_estimate_only", "Black-Scholes-only estimate — live chain required",
                                  snapshot={"data_source": "bs_estimate"}))
    if proposal.get("occ_symbol") is None and proposal.get("contract") is None and cfg.get("require_chain_for_live"):
        blocks.append(_hard_block("no_resolved_occ", "no resolved OCC contract on proposal"))
    if not liq.get("pass", True):
        for issue in liq.get("issues") or []:
            code = "liquidity_gate"
            if "OI" in str(issue):
                code = "oi_below_threshold"
            elif "volume" in str(issue).lower():
                code = "volume_below_threshold"
            elif "spread" in str(issue).lower():
                code = "spread_too_wide"
            blocks.append(_hard_block(code, str(issue), snapshot=liq))

    # Quote / chain staleness
    q_age = proposal.get("quote_age_seconds")
    if q_age is not None and float(q_age) > cfg.get("hard_quote_max_age_seconds", 120):
        blocks.append(_hard_block("quote_stale", f"quote age {q_age}s exceeds cap",
                                  snapshot={"quote_age_seconds": q_age}))
    c_age = proposal.get("chain_age_seconds")
    if c_age is not None and float(c_age) > cfg.get("hard_chain_max_age_seconds", 300):
        blocks.append(_hard_block("option_chain_stale", f"chain age {c_age}s exceeds cap",
                                  snapshot={"chain_age_seconds": c_age}))
    if proposal.get("market_session") in ("closed", "unsupported"):
        blocks.append(_hard_block("market_closed", f"session={proposal.get('market_session')}"))

    # Contract caps
    if contracts > cfg.get("hard_max_contracts_per_order", 5):
        blocks.append(_hard_block("max_contracts_per_order",
                                  f"{contracts} > {cfg['hard_max_contracts_per_order']}",
                                  snapshot={"contracts": contracts}))

    notional = _f(proposal.get("premium_total")) or _f(proposal.get("max_loss")) or _f(proposal.get("underlying_price")) * 100 * contracts
    if notional > cfg.get("hard_max_per_strategy_notional", 30_000):
        blocks.append(_hard_block("max_per_strategy_notional",
                                  f"notional ${notional:,.0f} exceeds strategy cap",
                                  snapshot={"notional": notional, "strategy": strat}))

    # Assignment risk flag
    if proposal.get("assignment_risk") or proposal.get("deep_itm_short"):
        blocks.append(_hard_block("assignment_exercise_risk", "assignment/exercise risk flagged",
                                  snapshot={"assignment_risk": True}))

    # Portfolio-level when context provided
    if holdings is not None and positions is not None:
        book = portfolio_risk_preflight([proposal], holdings, positions, cfg=cfg)
        for w in book.get("hard_blocks") or []:
            if isinstance(w, dict):
                blocks.append(w)
            else:
                blocks.append(_hard_block("portfolio_risk", str(w), snapshot=book.get("limits")))

    # Enterprise blocks from enrich
    for b in ent.get("blocks") or proposal.get("enterprise_blocks") or []:
        if isinstance(b, str):
            blocks.append(_hard_block("enterprise_block", b))
        elif isinstance(b, dict):
            blocks.append(b)

    return blocks


_EARNINGS_CACHE: Dict[str, str] = {}
_EARNINGS_CACHE_AT: Optional[datetime] = None


def earnings_calendar(symbols: List[str]) -> Dict[str, str]:
    """Next earnings date per symbol (FMP), cached 6h."""
    global _EARNINGS_CACHE, _EARNINGS_CACHE_AT
    syms = {s.upper() for s in symbols if s}
    fresh = bool(_EARNINGS_CACHE_AT) and (_now() - _EARNINGS_CACHE_AT).total_seconds() < 21600
    missing = {s for s in syms if s not in _EARNINGS_CACHE}
    # Refetch when the cache is stale, OR when newly-requested symbols aren't cached
    # yet — otherwise a name added mid-window silently skips its earnings blackout.
    if not fresh or missing:
        to_fetch = syms if not fresh else missing
        try:
            from portfolio_options import _get_earnings_dates
            fetched = _get_earnings_dates(list(to_fetch), PROJECT_ROOT)
            _EARNINGS_CACHE.update(fetched)
            # Record "looked, none found" so a no-earnings name doesn't refetch every call.
            for s in to_fetch:
                _EARNINGS_CACHE.setdefault(s, "")
            if not fresh:
                _EARNINGS_CACHE_AT = _now()
        except Exception:
            pass
    return {s: _EARNINGS_CACHE.get(s, "") for s in syms}


def earnings_blackout_check(
    symbol: str,
    *,
    dte: int,
    strategy: str,
    blackout_days: Optional[int] = None,
) -> dict:
    """Return blackout status for short premium / directional entries near earnings."""
    cfg = load_desk_config()
    days = int(blackout_days or cfg.get("earnings_blackout_days") or 14)
    sym = (symbol or "").upper()
    if strategy not in BLOCKING_STRATEGIES:
        return {"in_blackout": False, "symbol": sym, "strategy": strategy}
    cal = earnings_calendar([sym])
    earn_raw = cal.get(sym) or ""
    if not earn_raw:
        return {"in_blackout": False, "symbol": sym, "next_earnings": None, "days_to_earnings": None}
    try:
        earn_dt = date.fromisoformat(str(earn_raw)[:10])
    except ValueError:
        return {"in_blackout": False, "symbol": sym, "next_earnings": earn_raw}
    today = date.today()
    days_to = (earn_dt - today).days
    # Block if earnings falls before expiration or within blackout window
    in_window = 0 <= days_to <= days
    expires_before_earn = dte >= days_to > 0
    in_blackout = in_window or expires_before_earn
    return {
        "in_blackout": in_blackout,
        "symbol": sym,
        "strategy": strategy,
        "next_earnings": earn_dt.isoformat(),
        "days_to_earnings": days_to,
        "blackout_days": days,
        "reason": (
            f"Earnings {earn_dt} in {days_to}d — inside {days}d blackout"
            if in_blackout else ""
        ),
    }


def liquidity_gate(contract: dict, *, cfg: Optional[dict] = None) -> dict:
    """Hard liquidity check on a chain contract."""
    cfg = cfg or load_desk_config()
    bid, ask = _f(contract.get("bid")), _f(contract.get("ask"))
    mid = _f(contract.get("mid"))
    if mid <= 0 and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
    oi = int(_f(contract.get("oi")))
    vol = int(_f(contract.get("volume")))
    spread_pct = 100.0 * (ask - bid) / mid if mid > 0 and ask >= bid else 999.0
    min_oi = int(cfg.get("min_open_interest") or 50)
    min_vol = int(cfg.get("min_volume") or 5)
    max_spread = float(cfg.get("max_bid_ask_spread_pct") or 12.0)
    issues = []
    if oi < min_oi:
        issues.append(f"OI {oi} < {min_oi}")
    if vol < min_vol and oi < min_oi * 2:
        issues.append(f"volume {vol} < {min_vol}")
    if spread_pct > max_spread:
        issues.append(f"spread {spread_pct:.1f}% > {max_spread}%")
    if mid <= 0:
        issues.append("no quotable mid")
    return {
        "pass": not issues,
        "oi": oi,
        "volume": vol,
        "bid_ask_spread_pct": round(spread_pct, 2) if spread_pct < 900 else None,
        "mid": round(mid, 4) if mid else None,
        "issues": issues,
    }


def vol_analytics_from_chain(chain: dict, underlying: float) -> dict:
    """Term structure + put/call skew from normalized Schwab chain."""
    if not chain or underlying <= 0:
        return {"ok": False}
    expirations = chain.get("expirations") or []
    if not expirations:
        return {"ok": False, "reason": chain.get("reason") or chain.get("status") or "empty_chain"}
    term: List[dict] = []
    for exp in sorted(expirations, key=lambda x: int(x.get("dte") or 0))[:8]:
        dte = int(exp.get("dte") or 0)
        if dte < 7:
            continue
        call_ivs, put_ivs = [], []
        for row in exp.get("strikes") or []:
            strike = _f(row.get("strike"))
            if strike <= 0:
                continue
            moneyness = abs(strike - underlying) / underlying
            if moneyness > 0.08:
                continue
            iv = _f(row.get("iv"))
            if iv > 3:
                iv /= 100.0
            if iv <= 0:
                continue
            if row.get("side") == "call":
                call_ivs.append(iv)
            elif row.get("side") == "put":
                put_ivs.append(iv)
        if not call_ivs and not put_ivs:
            continue
        atm_call = sum(call_ivs) / len(call_ivs) if call_ivs else None
        atm_put = sum(put_ivs) / len(put_ivs) if put_ivs else None
        atm = None
        skew = None
        if atm_call and atm_put:
            atm = (atm_call + atm_put) / 2.0
            skew = round((atm_put - atm_call) * 100.0, 2)
        elif atm_call:
            atm = atm_call
        elif atm_put:
            atm = atm_put
        term.append({
            "exp": exp.get("exp"),
            "dte": dte,
            "atm_iv_pct": round(atm * 100.0, 2) if atm else None,
            "put_call_skew_pct": skew,
        })
    if not term:
        return {"ok": False, "reason": "no_atm_iv"}
    front = term[0]
    back = term[-1] if len(term) > 1 else term[0]
    contango = None
    if front.get("atm_iv_pct") and back.get("atm_iv_pct"):
        contango = round(back["atm_iv_pct"] - front["atm_iv_pct"], 2)
    return {
        "ok": True,
        "underlying": round(underlying, 2),
        "term_structure": term,
        "front_iv_pct": front.get("atm_iv_pct"),
        "back_iv_pct": back.get("atm_iv_pct"),
        "term_slope_pct": contango,
        "avg_put_skew_pct": round(
            sum(t["put_call_skew_pct"] for t in term if t.get("put_call_skew_pct") is not None)
            / max(1, sum(1 for t in term if t.get("put_call_skew_pct") is not None)),
            2,
        ) if any(t.get("put_call_skew_pct") is not None for t in term) else None,
    }


def build_iv_surface_grid(chain: dict, underlying: float, *, max_exps: int = 6, moneyness: float = 0.12) -> dict:
    """Strike × DTE IV grid from normalized Schwab chain (heatmap / surface UI)."""
    if not chain or underlying <= 0:
        return {"ok": False}
    expirations = sorted(chain.get("expirations") or [], key=lambda x: int(x.get("dte") or 0))
    expirations = [e for e in expirations if int(e.get("dte") or 0) >= 7][:max_exps]
    if not expirations:
        return {"ok": False, "reason": "no_expirations"}
    strike_set: set = set()
    for exp in expirations:
        for row in exp.get("strikes") or []:
            strike = _f(row.get("strike"))
            if strike > 0 and abs(strike - underlying) / underlying <= moneyness:
                strike_set.add(round(strike, 2))
    strikes = sorted(strike_set)
    if not strikes:
        return {"ok": False, "reason": "no_strikes"}
    cells: List[dict] = []
    expiries: List[dict] = []
    for exp in expirations:
        dte = int(exp.get("dte") or 0)
        expiries.append({"exp": exp.get("exp"), "dte": dte})
        by_strike: Dict[float, List[float]] = {}
        for row in exp.get("strikes") or []:
            strike = round(_f(row.get("strike")), 2)
            if strike not in strike_set:
                continue
            iv = _f(row.get("iv"))
            if iv > 3:
                iv /= 100.0
            if iv <= 0:
                continue
            by_strike.setdefault(strike, []).append(iv)
        for strike in strikes:
            ivs = by_strike.get(strike) or []
            cells.append({
                "strike": strike,
                "dte": dte,
                "exp": exp.get("exp"),
                "iv_pct": round(sum(ivs) / len(ivs) * 100.0, 1) if ivs else None,
            })
    return {
        "ok": True,
        "underlying": round(underlying, 2),
        "strikes": strikes,
        "expiries": expiries,
        "cells": cells,
    }


def fetch_vol_history(symbol: str, limit: int = 48) -> List[dict]:
    """Recent ATM IV / skew snapshots for trends sparkline."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    conn = _conn()
    if not conn:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT captured_at, vol_analytics_json
               FROM options_chain_snapshots
               WHERE symbol = %s
               ORDER BY captured_at DESC
               LIMIT %s""",
            (sym, lim),
        )
        rows = cur.fetchall() or []
    except Exception:
        return []
    out: List[dict] = []
    for captured_at, vol_json in reversed(rows):
        vol = vol_json if isinstance(vol_json, dict) else {}
        if isinstance(vol_json, str):
            try:
                vol = json.loads(vol_json)
            except Exception:
                vol = {}
        out.append({
            "captured_at": captured_at.isoformat() if hasattr(captured_at, "isoformat") else str(captured_at),
            "front_iv_pct": vol.get("front_iv_pct"),
            "back_iv_pct": vol.get("back_iv_pct"),
            "term_slope_pct": vol.get("term_slope_pct"),
            "avg_put_skew_pct": vol.get("avg_put_skew_pct"),
        })
    return out


def _theta_decay_estimate(delta: float, gamma: float, iv: float, spot: float, dte: int) -> float:
    """Rough daily theta when chain theta unavailable."""
    if dte <= 0 or spot <= 0:
        return 0.0
    t = max(dte, 1) / 365.0
    vol = max(iv, 0.12)
    # Brenner-Subrahmanyam approximation scaled per contract. Returns the long-option
    # daily theta (negative), matching real chain theta convention; aggregate_book_greeks
    # flips the sign for short legs via side_mult.
    approx = -(spot * vol) / (2 * math.sqrt(t)) / 365.0
    # ATM contracts decay faster than OTM — magnitude scalar, NOT a sign flip.
    moneyness_scale = 1.0 if abs(delta) < 0.55 else 0.5
    return round(approx * moneyness_scale * 100.0, 2)


def aggregate_book_greeks(positions: List[dict], tech_map: Optional[dict] = None) -> dict:
    """Portfolio-level greeks from monitored open legs."""
    tech_map = tech_map or {}
    net_delta = net_gamma = net_theta = net_vega = 0.0
    net_delta_notional = 0.0
    by_underlying: Dict[str, dict] = {}
    legs = 0
    for pos in positions:
        qty = _f(pos.get("qty"), 1)
        mult = qty * 100.0
        delta = _f(pos.get("delta"))
        if delta == 0:
            # Estimate from moneyness if missing
            spot = _f(pos.get("underlying_price"))
            strike = _f(pos.get("strike"))
            dte = int(pos.get("dte") or 30)
            iv = 0.25
            if spot > 0 and strike > 0 and dte > 0:
                t = dte / 365.0
                d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
                def _ncdf(x: float) -> float:
                    k = 1.0 / (1.0 + 0.2316419 * abs(x))
                    poly = k * (0.319381530 + k * (-0.356563782 + k * (1.781477937 + k * (-1.821255978 + k * 1.330274429))))
                    n = math.exp(-x * x / 2.0) / math.sqrt(2 * math.pi)
                    return 1.0 - n * poly if x >= 0 else n * poly

                is_call = (pos.get("option_type") or "").lower() == "call"
                delta = _ncdf(d1) if is_call else _ncdf(d1) - 1.0
        side_mult = -1.0 if (pos.get("side") or "").upper() == "SHORT" or "short" in (pos.get("strategy") or "") else 1.0
        leg_delta = delta * mult * side_mult
        gamma = _f(pos.get("gamma")) * mult * side_mult
        theta = _f(pos.get("theta")) * mult * side_mult
        vega = _f(pos.get("vega")) * mult * side_mult
        if theta == 0:
            # Estimate is long-convention (negative); flip for short premium so the
            # book's net theta/day reflects decay collected, not decay paid.
            theta = _theta_decay_estimate(delta, gamma, 0.25, _f(pos.get("underlying_price")), int(pos.get("dte") or 30)) * qty * side_mult
        net_delta += leg_delta
        net_gamma += gamma
        net_theta += theta
        net_vega += vega
        net_delta_notional += leg_delta * _f(pos.get("underlying_price"))
        und = (pos.get("underlying") or "").upper()
        if und:
            bucket = by_underlying.setdefault(und, {"delta": 0.0, "theta": 0.0, "legs": 0})
            bucket["delta"] += leg_delta
            bucket["theta"] += theta
            bucket["legs"] += 1
        legs += 1
    return {
        "leg_count": legs,
        "net_delta_shares": round(net_delta, 1),
        "net_delta_notional": round(net_delta_notional, 2),
        "net_gamma": round(net_gamma, 4),
        "net_theta_per_day": round(net_theta, 2),
        "net_vega": round(net_vega, 2),
        "by_underlying": {
            k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}
            for k, v in sorted(by_underlying.items(), key=lambda x: -abs(x[1].get("delta", 0)))
        },
    }


def desk_tier(edge: float, cfg: Optional[dict] = None) -> str:
    cfg = cfg or load_desk_config()
    if edge >= _f(cfg.get("desk_tier_edge_a"), 72):
        return "A"
    if edge >= _f(cfg.get("desk_tier_edge_b"), 62):
        return "B"
    return "C"


def enterprise_enrich_proposal(
    proposal: dict,
    *,
    contract: Optional[dict] = None,
    chain: Optional[dict] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """Attach enterprise metadata and hard gates to a proposal row."""
    cfg = cfg or load_desk_config()
    sym = (proposal.get("symbol") or "").upper()
    strat = proposal.get("strategy") or ""
    dte = int(proposal.get("dte") or 30)
    edge = _f(proposal.get("edge_score"))

    blackout = earnings_blackout_check(sym, dte=dte, strategy=strat)
    liq = {"pass": True, "issues": []}
    if contract:
        liq = liquidity_gate(contract, cfg=cfg)
    elif proposal.get("data_source") == "bs_estimate" and cfg.get("require_chain_for_live"):
        liq = {"pass": False, "issues": ["BS estimate only — not eligible for live auto path"]}

    vol = {}
    und = _f(proposal.get("underlying_price"))
    if chain and und > 0:
        vol = vol_analytics_from_chain(chain, und)

    blocks = []
    if blackout.get("in_blackout"):
        blocks.append(blackout.get("reason") or "earnings_blackout")
    if not liq.get("pass"):
        blocks.extend(liq.get("issues") or [])

    tier = desk_tier(edge, cfg)
    live_eligible = not blocks and liq.get("pass", True)
    # No chain contract means no verifiable fill liquidity — never live-eligible,
    # regardless of the require_chain_for_live operator override.
    if contract is None:
        live_eligible = False
    if proposal.get("data_source") == "bs_estimate" and cfg.get("require_chain_for_live"):
        live_eligible = False

    proposal["desk_tier"] = tier
    proposal["enterprise"] = {
        "tier": tier,
        "live_eligible": live_eligible,
        "blocks": blocks,
        "earnings": blackout,
        "liquidity": liq,
        "vol_analytics": vol if vol.get("ok") else None,
        "approval_required": bool(cfg.get("approval_required")),
    }
    if blocks:
        proposal["enterprise_blocked"] = True
        note = " · Enterprise block: " + "; ".join(blocks[:3])
        proposal["reasoning"] = (proposal.get("reasoning") or "") + note
    return proposal


def portfolio_risk_preflight(
    proposals: List[dict],
    holdings: List[dict],
    positions: List[dict],
    *,
    cfg: Optional[dict] = None,
) -> dict:
    """Book-level risk snapshot for desk operator."""
    cfg = cfg or load_desk_config()
    total_mv = sum(_f(h.get("market_value")) for h in holdings if not h.get("is_cash")) or 1.0
    greeks = aggregate_book_greeks(positions)
    # Dollar-delta exposure (share-equivalent delta × each leg's real underlying price)
    # as a pct of book MV. No assumed share price.
    net_delta_pct = abs(greeks.get("net_delta_notional") or 0.0) / total_mv * 100.0

    sym_notional: Dict[str, float] = {}
    for p in proposals:
        sym = (p.get("symbol") or "").upper()
        notional = _f(p.get("premium_total")) or _f(p.get("max_loss")) or _f(p.get("underlying_price")) * 100
        sym_notional[sym] = sym_notional.get(sym, 0.0) + notional

    concentration = sorted(
        [{"symbol": s, "notional": round(v, 2), "pct": round(v / total_mv * 100, 2)} for s, v in sym_notional.items()],
        key=lambda x: -x["pct"],
    )
    top_sym_pct = concentration[0]["pct"] if concentration else 0.0
    warnings = []
    hard_blocks: List[dict] = []
    if net_delta_pct > _f(cfg.get("max_net_delta_pct"), 35):
        msg = f"Net delta exposure ~{net_delta_pct:.1f}% exceeds cap"
        warnings.append(msg)
        hard_blocks.append(_hard_block("max_net_delta_pct", msg,
                                      snapshot={"net_delta_pct": net_delta_pct,
                                                "cap": cfg.get("max_net_delta_pct")}))
    if top_sym_pct > _f(cfg.get("max_symbol_notional_pct"), 25):
        msg = f"Top symbol concentration {top_sym_pct:.1f}% exceeds cap"
        warnings.append(msg)
        hard_blocks.append(_hard_block("max_symbol_notional_pct", msg,
                                      snapshot={"top_sym_pct": top_sym_pct,
                                                "cap": cfg.get("max_symbol_notional_pct")}))

    blocked_count = sum(1 for p in proposals if p.get("enterprise_blocked"))
    live_count = sum(1 for p in proposals if (p.get("enterprise") or {}).get("live_eligible"))

    return {
        "captured_at": _iso(),
        "portfolio_mv": round(total_mv, 2),
        "proposal_count": len(proposals),
        "live_eligible_count": live_count,
        "enterprise_blocked_count": blocked_count,
        "greeks": greeks,
        "net_delta_pct_proxy": round(net_delta_pct, 2),
        "concentration": concentration[:8],
        "warnings": warnings,
        "hard_blocks": hard_blocks,
        "limits": {
            "max_net_delta_pct": cfg.get("max_net_delta_pct"),
            "max_symbol_notional_pct": cfg.get("max_symbol_notional_pct"),
        },
    }


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def sync_approval_queue(proposals: List[dict], *, apply: bool = True) -> dict:
    """Upsert desk proposals into options_approval_queue for operator review."""
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    cfg = load_desk_config()
    if not cfg.get("approval_required"):
        return {"ok": True, "skipped": True, "reason": "approval_not_required"}
    upserted = 0
    cur = conn.cursor()
    for p in proposals:
        pid = p.get("id")
        if not pid:
            continue
        ent = p.get("enterprise") or {}
        status = "blocked" if p.get("enterprise_blocked") else "pending"
        cur.execute(
            """INSERT INTO options_approval_queue
               (proposal_id, symbol, strategy, desk_tier, edge_score, status,
                live_eligible, blocks_json, proposal_json, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb, NOW() + INTERVAL '24 hours')
               ON CONFLICT (proposal_id) DO UPDATE SET
                 desk_tier=EXCLUDED.desk_tier,
                 edge_score=EXCLUDED.edge_score,
                 status=CASE WHEN options_approval_queue.status IN ('approved','rejected','executed')
                            THEN options_approval_queue.status ELSE EXCLUDED.status END,
                 live_eligible=EXCLUDED.live_eligible,
                 blocks_json=EXCLUDED.blocks_json,
                 proposal_json=EXCLUDED.proposal_json,
                 updated_at=NOW()""",
            (
                pid,
                p.get("symbol"),
                p.get("strategy"),
                p.get("desk_tier") or "C",
                _f(p.get("edge_score")),
                status,
                bool(ent.get("live_eligible")),
                json.dumps(ent.get("blocks") or []),
                json.dumps(p, default=str),
            ),
        )
        upserted += 1
    if apply:
        conn.commit()
    return {"ok": True, "upserted": upserted}


def fetch_approval_queue(*, status: str = "", limit: int = 50) -> List[dict]:
    conn = _conn()
    if not conn:
        return []
    cur = conn.cursor()
    if status:
        cur.execute(
            """SELECT id, proposal_id, symbol, strategy, desk_tier, edge_score, status,
                      live_eligible, blocks_json, reviewer, review_note, created_at, updated_at
               FROM options_approval_queue
               WHERE status=%s ORDER BY edge_score DESC NULLS LAST, created_at DESC LIMIT %s""",
            (status, limit),
        )
    else:
        cur.execute(
            """SELECT id, proposal_id, symbol, strategy, desk_tier, edge_score, status,
                      live_eligible, blocks_json, reviewer, review_note, created_at, updated_at
               FROM options_approval_queue
               WHERE status IN ('pending','blocked') ORDER BY desk_tier, edge_score DESC LIMIT %s""",
            (limit,),
        )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def resolve_approval(
    proposal_id: str,
    action: str,
    *,
    reviewer: str = "operator",
    note: str = "",
) -> dict:
    """Approve or reject a queued options proposal."""
    action = (action or "").lower()
    if action not in ("approve", "reject"):
        return {"ok": False, "error": "action must be approve or reject"}
    new_status = "approved" if action == "approve" else "rejected"
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    cur = conn.cursor()
    cur.execute(
        """UPDATE options_approval_queue
           SET status=%s, reviewer=%s, review_note=%s, reviewed_at=NOW(), updated_at=NOW()
           WHERE proposal_id=%s AND status IN ('pending','blocked')
           RETURNING id, symbol, strategy, live_eligible, blocks_json""",
        (new_status, reviewer, note[:500], proposal_id),
    )
    row = cur.fetchone()
    if not row:
        conn.rollback()
        return {"ok": False, "error": "proposal not in queue or already resolved"}
    if action == "approve" and row[3] is False:
        blocks = row[4] or []
        conn.rollback()
        return {"ok": False, "error": "cannot approve — enterprise blocks remain", "blocks": blocks}
    conn.commit()
    return {"ok": True, "proposal_id": proposal_id, "status": new_status, "symbol": row[1], "strategy": row[2]}


def check_preflight_approval(proposal_id: str) -> Tuple[bool, str]:
    """Gate live submit on desk approval when required."""
    cfg = load_desk_config()
    if not cfg.get("approval_required"):
        return True, ""
    conn = _conn()
    if not conn:
        return False, "approval queue unavailable"
    cur = conn.cursor()
    cur.execute(
        "SELECT status, live_eligible, blocks_json FROM options_approval_queue WHERE proposal_id=%s",
        (proposal_id,),
    )
    row = cur.fetchone()
    if not row:
        return False, "proposal not in desk approval queue — operator review required"
    status, live_eligible, blocks = row[0], row[1], row[2] or []
    if status == "rejected":
        return False, "desk rejected this proposal"
    if status != "approved":
        return False, f"desk status={status} — approve in queue before submit"
    if not live_eligible:
        return False, f"not live-eligible: {', '.join(blocks[:3]) if blocks else 'enterprise block'}"
    return True, ""


def persist_chain_snapshot(symbol: str, chain: dict, vol: dict) -> None:
    """Light vol surface persistence for desk analytics."""
    conn = _conn()
    if not conn or not vol.get("ok"):
        return
    sym = symbol.upper()
    # fetch_vol_history reads only vol_analytics_json. Persisting the full chain blob
    # both bloated the table and risked invalid JSON (a byte-slice of serialized JSON
    # is malformed → ::jsonb cast threw → snapshot silently lost). Store a small,
    # always-valid summary instead.
    chain_meta = {
        "underlying_price": _f(chain.get("underlying_price")),
        "expiration_count": len(chain.get("expirations") or []),
        "note": "summary only — full chain not persisted (size/retention)",
    }
    keep_days = int(os.getenv("OPTIONS_SNAPSHOT_RETENTION_DAYS", "45"))
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO options_chain_snapshots (symbol, chain_json, vol_analytics_json, captured_at)
               VALUES (%s, %s::jsonb, %s::jsonb, NOW())""",
            (sym, json.dumps(chain_meta), json.dumps(vol, default=str)),
        )
        # Bounded retention — uses idx_options_chain_snap_sym_time; cheap per-symbol prune.
        cur.execute(
            "DELETE FROM options_chain_snapshots WHERE symbol=%s AND captured_at < NOW() - (%s || ' days')::interval",
            (sym, str(keep_days)),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def prune_chain_snapshots(keep_days: Optional[int] = None) -> dict:
    """Global retention sweep across all symbols. Run from a daily cron so symbols
    that stop receiving new snapshots still get their tail pruned (the per-insert
    prune in persist_chain_snapshot only touches the symbol being written)."""
    days = int(keep_days if keep_days is not None else os.getenv("OPTIONS_SNAPSHOT_RETENTION_DAYS", "45"))
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM options_chain_snapshots WHERE captured_at < NOW() - (%s || ' days')::interval",
            (str(days),),
        )
        deleted = cur.rowcount
        conn.commit()
        return {"ok": True, "deleted": deleted, "keep_days": days}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:160]}


def build_enterprise_summary(
    proposals: List[dict],
    holdings: List[dict],
    positions: List[dict],
) -> dict:
    risk = portfolio_risk_preflight(proposals, holdings, positions)
    tiers = {"A": 0, "B": 0, "C": 0}
    for p in proposals:
        tiers[p.get("desk_tier") or "C"] = tiers.get(p.get("desk_tier") or "C", 0) + 1
    summary = {
        "generated_at": _iso(),
        "desk_level": "enterprise",
        "tier_counts": tiers,
        "risk": risk,
        "config": {k: load_desk_config()[k] for k in (
            "earnings_blackout_days", "min_open_interest", "min_volume",
            "max_bid_ask_spread_pct", "approval_required", "max_net_delta_pct",
        )},
    }
    _save_json(DESK_RUNTIME, summary)
    return summary