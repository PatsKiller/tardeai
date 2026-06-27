#!/usr/bin/env python3
"""account_policy.py — single source of truth for account sizing/risk policy + live equity + the
percent-of-equity sizing math. Used by BOTH auto_proposal_generator.normalize_size() and risk_gate so
the two can never disagree (operator 2026-06-19: switch from fixed-dollar to percent-of-equity sizing).

Unit convention: every *_pct value is a WHOLE percent — 5 == 5%, 20 == 20%.
Sizing is admin-configurable via account_automation_policies (edited in the v3 admin modal); NO sizing
constant is hardcoded here except the fail-safe fallback used only when equity/policy is unavailable.
"""
from __future__ import annotations
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

# Fail-safe fallback ONLY (used when policy/equity can't be resolved) — mirrors the legacy fixed caps so
# behaviour degrades to the old conservative sizing rather than to zero or to something unbounded.
FALLBACK_RISK_DOLLARS = 150.0
FALLBACK_SIZE_DOLLARS = 2000.0
FALLBACK_EQUITY = float(os.getenv("PAPER_ACCOUNT_SIZE", "100000"))

_POLICY_COLS = (
    "automation_mode", "approval_policy", "sizing_engine",
    "risk_per_trade_pct", "max_position_allocation_pct",
    "max_risk_dollars_per_trade", "max_notional_per_trade",
    "max_strategy_allocation_pct", "max_sector_allocation_pct",
    "max_concurrent_positions", "max_new_positions_per_day",
    "daily_loss_pause_pct",
)


def _f(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def default_paper_account() -> str:
    """The configured default paper account_key — sourced from ATM/broker config, never hardcoded
    (honours the no-hardcoded-values rule). Last resort is an env-backed default."""
    try:
        from atm_config_manager import get_enabled_accounts
        enabled = get_enabled_accounts()
        if enabled:
            return enabled[0]
    except Exception:
        pass
    try:
        from broker_config import get_default_paper_account
        acct = get_default_paper_account()
        if acct:
            return acct
    except Exception:
        pass
    from automated_account import AUTOMATED_ACCOUNT_KEY
    return os.getenv("DEFAULT_PAPER_ACCOUNT", AUTOMATED_ACCOUNT_KEY)


def load_policy(account_key: str) -> dict:
    """Return the effective automation policy for an account_key (joined broker_accounts→policy).
    Missing rows/fields degrade to a safe fixed_dollar policy so callers never crash."""
    key = (account_key or "").strip()
    out = {"account_key": key, "sizing_engine": "fixed_dollar"}
    try:
        cur = _get_conn().cursor()
        cols = ",".join(f"p.{c}" for c in _POLICY_COLS)
        cur.execute(f"""SELECT {cols} FROM account_automation_policies p
                         JOIN broker_accounts b ON b.id = p.account_id
                        WHERE b.account_key = %s""", (key,))
        row = cur.fetchone()
        if row:
            for c, v in zip(_POLICY_COLS, row):
                out[c] = v
            for c in _POLICY_COLS:
                if c.endswith("_pct") or c.startswith("max_risk") or c.startswith("max_notional"):
                    out[c] = _f(out.get(c))
            out["sizing_engine"] = (out.get("sizing_engine") or "fixed_dollar")
    except Exception as e:
        try:
            _get_conn().rollback()
        except Exception:
            pass
        out["_policy_error"] = str(e)[:120]
    return out


_EQUITY_CACHE: dict = {}   # account_key -> (monotonic_ts, equity, source); avoids hammering the broker API
_EQUITY_TTL = 60.0         # seconds — the single-threaded server may call this per risk-gate check


def equity_for_account(account_key: str) -> tuple[float, str]:
    """Live account equity for sizing, wired for Alpaca paper AND Schwab, with fallbacks.
    Returns (equity, source). Never raises; falls back to a holdings snapshot then to env.
    Cached for _EQUITY_TTL seconds per account so repeated risk-gate checks don't hit the broker API."""
    key = (account_key or "").strip()
    low = key.lower()

    import time as _t
    _hit = _EQUITY_CACHE.get(key)
    if _hit and (_t.monotonic() - _hit[0]) < _EQUITY_TTL:
        return _hit[1], _hit[2]

    eq, src = _resolve_equity(low, key)
    _EQUITY_CACHE[key] = (_t.monotonic(), eq, src)
    return eq, src


def _resolve_equity(low: str, key: str) -> tuple[float, str]:

    if low in ("alpaca_paper", "alpaca"):
        try:
            from alpaca_paper_adapter import AlpacaPaperAdapter
            acct = AlpacaPaperAdapter().get_account() or {}
            eq = _f(acct.get("equity"))
            if eq and eq > 0:
                return eq, "alpaca_live"
        except Exception:
            pass

    if low.startswith("schwab"):
        try:
            import schwab_transport as st
            acct = st.get_account(key) or {}
            eq = _f(acct.get("equity"))
            if eq and eq > 0:
                return eq, "schwab_live"
        except Exception:
            pass

    # Fallback: settled-holdings snapshot for this account (holdings.json account_summaries)
    try:
        eq = _equity_from_holdings(key)
        if eq and eq > 0:
            return eq, "holdings_snapshot"
    except Exception:
        pass

    return FALLBACK_EQUITY, "env_fallback"


def _equity_from_holdings(account_key: str) -> float | None:
    import json
    root = Path(__file__).resolve().parent.parent
    hj = json.loads((root / "data" / "portfolios" / "state" / "holdings.json").read_text())
    summ = (hj.get("account_summaries") or {}).get(account_key)
    if summ:
        return _f(summ.get("total_value"))
    return None


def cash_for_account(account_key: str) -> tuple[float | None, str]:
    """Settled cash / buying power for notional cap. Returns (cash, source). Never raises."""
    key = (account_key or "").strip()
    low = key.lower()

    if low.startswith("schwab"):
        try:
            import schwab_transport as st
            acct = st.get_account(key) or {}
            if acct.get("status") == "active":
                cash = _f(acct.get("cash"))
                bp = _f(acct.get("buying_power"))
                val = cash if cash and cash > 0 else bp
                if val and val > 0:
                    return val, "schwab_live"
        except Exception:
            pass

    if low in ("alpaca_paper", "alpaca"):
        try:
            from alpaca_paper_adapter import AlpacaPaperAdapter
            acct = AlpacaPaperAdapter().get_account() or {}
            cash = _f(acct.get("cash")) or _f(acct.get("buying_power"))
            if cash and cash > 0:
                return cash, "alpaca_live"
        except Exception:
            pass

    return None, "unavailable"


def compute_sizing(policy: dict, equity: float, entry: float, stop: float,
                   desired_shares: int | None = None, tilt: float = 1.0,
                   cash_available: float | None = None,
                   sizing_base: float | None = None) -> dict:
    """The ONE sizing implementation. Shares = min(desired_shares?, position-cap shares, risk-cap shares).
    percent_equity engine: caps = base * pct/100 where base defaults to equity; pass sizing_base=cash for
    live broker promotes. fixed_dollar engine (or missing policy/equity): the
    fail-safe fixed caps. Optional absolute ceilings (max_risk_dollars_per_trade / max_notional_per_trade)
    clamp the percent caps when the admin sets them. `tilt` (per-strategy allocation tilt, default 1.0)
    scales the RISK budget up AND, for boosted winners (tilt>1.0), TIGHTENS the position cap inversely
    (÷tilt) — winners get more trades + risk budget, but smaller individual positions (concentration
    control). Optional `cash_available` further caps notional to settled cash/buying power.
    Returns a basis dict for audit/reproducibility."""
    entry = _f(entry) or 0.0
    stop = _f(stop) or 0.0
    risk_per_share = abs(entry - stop)
    if entry <= 0 or risk_per_share <= 0:
        return {"valid": False, "reason": "MISSING_PLAN_DATA",
                "entry": entry, "stop": stop, "risk_per_share": risk_per_share}

    engine = (policy or {}).get("sizing_engine") or "fixed_dollar"
    risk_pct = (policy or {}).get("risk_per_trade_pct")
    pos_pct = (policy or {}).get("max_position_allocation_pct")
    eq = _f(equity) or 0.0
    base = _f(sizing_base) if sizing_base is not None else eq
    use_cash_base = sizing_base is not None and base > 0

    if engine == "percent_equity" and base > 0 and risk_pct and pos_pct:
        max_dollar_risk = base * (risk_pct / 100.0)
        max_dollar_size = base * (pos_pct / 100.0)
        basis_engine = "percent_cash" if use_cash_base else "percent_equity"
    else:
        max_dollar_risk = FALLBACK_RISK_DOLLARS
        max_dollar_size = FALLBACK_SIZE_DOLLARS
        basis_engine = "fixed_dollar_fallback" if engine == "percent_equity" else "fixed_dollar"

    # optional absolute ceilings (belt-and-suspenders) when the admin sets them
    abs_risk = (policy or {}).get("max_risk_dollars_per_trade")
    abs_notional = (policy or {}).get("max_notional_per_trade")
    if abs_risk and abs_risk > 0:
        max_dollar_risk = min(max_dollar_risk, abs_risk)
    if abs_notional and abs_notional > 0:
        max_dollar_size = min(max_dollar_size, abs_notional)

    # Per-strategy allocation tilt: scale the RISK budget (winning strategies risk more). The position
    # cap (max_dollar_size) is NOT tilted, so concentration is preserved — a tilt only lets a strategy
    # use more of its risk budget up to that cap.
    try:
        tilt_f = float(tilt) if tilt else 1.0
    except (TypeError, ValueError):
        tilt_f = 1.0
    if tilt_f != 1.0:
        max_dollar_risk = max_dollar_risk * tilt_f
    # Boosted winners (tilt > 1.0) get a TIGHTER position cap, scaled inversely by tilt (operator
    # 2026-06-19): allocate to winners via more trades + risk budget, NOT via one oversized position.
    # e.g. fib 1.5x → 20% ÷ 1.5 = 13.3%; swing 1.11x → 18%. Demoted strategies keep the base cap.
    if tilt_f > 1.0:
        max_dollar_size = max_dollar_size / tilt_f

    max_by_risk = int(max_dollar_risk / risk_per_share) if risk_per_share > 0 else 0
    max_by_size = int(max_dollar_size / entry) if entry > 0 else 0

    cash_cap_shares = None
    cash_avail = _f(cash_available)
    if cash_avail and cash_avail > 0 and entry > 0:
        cash_cap_shares = int(cash_avail / entry)

    candidates = [max_by_size, max_by_risk]
    if cash_cap_shares is not None:
        candidates.append(cash_cap_shares)
    if desired_shares and int(desired_shares) > 0:
        candidates.append(int(desired_shares))
    shares = max(0, min(candidates))

    binding = "risk_cap" if max_by_risk <= min(max_by_size, cash_cap_shares or max_by_size) else "position_cap"
    if cash_cap_shares is not None and shares == cash_cap_shares and shares < min(max_by_size, max_by_risk):
        binding = "cash_cap"
    if desired_shares and int(desired_shares) == shares and shares < min(max_by_size, max_by_risk, cash_cap_shares or max_by_size):
        binding = "signal_shares"

    return {
        "valid": shares >= 1,
        "reason": None if shares >= 1 else "SIZE_TOO_SMALL",
        "shares": shares,
        "engine": basis_engine,
        "equity": round(eq, 2),
        "sizing_base": round(base, 2) if base else None,
        "sizing_base_label": "cash" if use_cash_base else "equity",
        "risk_pct": risk_pct,
        "pos_pct": pos_pct,
        "risk_per_share": round(risk_per_share, 4),
        "max_dollar_risk": round(max_dollar_risk, 2),
        "max_dollar_size": round(max_dollar_size, 2),
        "max_shares_by_risk": max_by_risk,
        "max_shares_by_size": max_by_size,
        "max_shares_by_cash": cash_cap_shares,
        "cash_available": round(cash_avail, 2) if cash_avail else None,
        "dollar_size": round(shares * entry, 2),
        "dollar_risk": round(shares * risk_per_share, 2),
        "binding": binding,
        "tilt": tilt_f,
        "stop_pct": round(risk_per_share / entry, 4) if entry > 0 else 0,
    }


if __name__ == "__main__":
    # quick self-check: SNOW at 5% risk / 20% position on $100k
    pol = load_policy("alpaca_paper")
    eq, src = equity_for_account("alpaca_paper")
    print("policy:", {k: pol.get(k) for k in ("sizing_engine", "risk_per_trade_pct", "max_position_allocation_pct")})
    print("equity:", eq, "source:", src)
    s = compute_sizing(pol, eq, 236.50, 228.01)
    print("SNOW sizing:", {k: s[k] for k in ("shares", "engine", "binding", "max_shares_by_risk", "max_shares_by_size", "dollar_size")})
