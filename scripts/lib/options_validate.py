"""Validate one options proposal against the live Schwab chain (operator 2026-09-26).

"For live-money trading, never rely on cached, weekend, stale, estimated or
AI-generated option values." Validate re-reads the exact contract from Schwab
(market data only -- the same read the engine uses; no order route), confirms it
still exists, refreshes bid/ask/mid/last/OI/volume, recomputes premium,
breakeven and max profit/loss, and flags material changes. The result is stamped
on the options thesis record; the approval queue requires a fresh VALIDATED
result. Thresholds live in portfolio_intent.yaml options_desk_settings.validation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

DEFAULTS = {
    "max_premium_change_pct": 15.0,
    "max_spot_change_pct": 3.0,
    "fresh_minutes": 30,
    "strike_count": 40,
}
SHORT = {"cash_secured_put", "covered_call", "credit_spread"}


def settings(cfg: Optional[dict[str, Any]]) -> dict[str, Any]:
    blk = (cfg or {}).get("validation") or {}
    return {k: blk.get(k, v) for k, v in DEFAULTS.items()}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _side(p: dict[str, Any]) -> str:
    t = str(p.get("option_type") or "").lower()
    if t in ("call", "put"):
        return t
    return "call" if p.get("strategy") in ("covered_call", "long_call") else "put"


def _economics(strategy: str, spot: float, strike: float, mid: float, contracts: int) -> dict[str, Any]:
    n = 100 * max(1, contracts)
    if strategy == "cash_secured_put":
        return {"premium_total": round(mid * n, 2), "breakeven": round(strike - mid, 2),
                "max_profit": round(mid * n, 2), "max_loss": round((strike - mid) * n, 2), "cash_flow": "credit"}
    if strategy == "covered_call":
        return {"premium_total": round(mid * n, 2), "breakeven": round(spot - mid, 2),
                "max_profit": round((mid + max(0.0, strike - spot)) * n, 2), "max_loss": None, "cash_flow": "credit"}
    if strategy in ("protective_put", "long_put"):
        return {"premium_total": round(mid * n, 2), "breakeven": round(strike - mid, 2),
                "max_profit": None, "max_loss": round(mid * n, 2), "cash_flow": "debit"}
    if strategy == "long_call":
        return {"premium_total": round(mid * n, 2), "breakeven": round(strike + mid, 2),
                "max_profit": None, "max_loss": round(mid * n, 2), "cash_flow": "debit"}
    return {"premium_total": round(mid * n, 2), "cash_flow": "credit" if strategy in SHORT else "debit"}


def validate(p: dict[str, Any], *, chain_fn: Callable[..., dict[str, Any]], cfg: Optional[dict[str, Any]] = None,
             session: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    s = settings(cfg)
    sym = str(p.get("symbol") or "").upper()
    strike, exp = _f(p.get("strike")), str(p.get("expiration") or "")[:10]
    side = _side(p)
    base = {"schema": "OptionsValidation@v1", "symbol": sym, "proposal_id": p.get("id"),
            "position_guid": p.get("option_strategy_guid"), "strategy": p.get("strategy"),
            "strike": strike, "expiration": exp, "side": side, "validated_at": now.isoformat(),
            "market_session": session, "source": "schwab_chain", "authority": "READ_ONLY_ADVISORY"}
    if p.get("data_source") == "bs_estimate":
        return {**base, "status": "NOT_A_LISTED_QUOTE", "reason": "proposal was priced by Black-Scholes, not the chain"}
    try:
        chain = chain_fn(sym, strikes=int(s["strike_count"])) or {}
    except Exception as exc:  # noqa: BLE001
        return {**base, "status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if chain.get("status") not in (None, "ok"):
        return {**base, "status": "UNAVAILABLE", "reason": str(chain.get("status") or chain.get("error"))[:120]}
    row = None
    for e in chain.get("expirations") or []:
        if str(e.get("exp") or "")[:10] != exp:
            continue
        for r in e.get("strikes") or []:
            if r.get("side") == side and strike is not None and abs((_f(r.get("strike")) or 0) - strike) < 1e-6:
                row = r
                break
    if row is None:
        return {**base, "status": "CONTRACT_NOT_FOUND",
                "reason": f"{sym} {exp} {strike:g} {side} is not in the live chain; regenerate the proposal"}
    bid, ask, last = _f(row.get("bid")) or 0.0, _f(row.get("ask")) or 0.0, _f(row.get("last"))
    mid = round((bid + ask) / 2.0, 4) if bid > 0 and ask > 0 else (last or 0.0)
    spot = _f(chain.get("underlying_price")) or _f(p.get("underlying_price")) or 0.0
    contracts = int(_f(p.get("contracts")) or 1)
    live = {"bid": bid, "ask": ask, "mid": mid, "last": last, "oi": row.get("oi"), "volume": row.get("volume"),
            "delta": row.get("delta"), "iv": row.get("iv"), "spot": spot,
            "bid_ask_spread_pct": round(100.0 * (ask - bid) / mid, 2) if mid > 0 and ask >= bid and bid > 0 else None}
    econ = _economics(str(p.get("strategy") or ""), spot, strike or 0.0, mid, contracts)
    changes: list[str] = []
    old_prem = _f(p.get("premium"))
    if old_prem and mid > 0:
        d = 100.0 * (mid - old_prem) / old_prem
        if abs(d) > float(s["max_premium_change_pct"]):
            changes.append(f"premium {old_prem:g} -> {mid:g} ({d:+.1f}%)")
    old_spot = _f(p.get("underlying_price"))
    if old_spot and spot:
        d = 100.0 * (spot - old_spot) / old_spot
        if abs(d) > float(s["max_spot_change_pct"]):
            changes.append(f"spot {old_spot:g} -> {spot:g} ({d:+.1f}%)")
    liq_issues: list[str] = []
    try:
        from options_desk_enterprise import liquidity_gate
    except ImportError:  # pragma: no cover
        from scripts.options_desk_enterprise import liquidity_gate  # type: ignore
    lg = liquidity_gate({"bid": bid, "ask": ask, "mid": mid, "oi": row.get("oi"), "volume": row.get("volume")})
    liq_issues = list(lg.get("issues") or [])
    status = "ILLIQUID" if liq_issues else ("CHANGED" if changes else "VALIDATED")
    if mid <= 0:
        status, changes = "NO_QUOTE", changes + ["no two-sided quote"]
    closed = bool(session) and session != "REGULAR"
    return {**base, "status": status, "live": live, "recomputed": econ, "material_changes": changes,
            "liquidity_issues": liq_issues,
            "note": ("Quotes read while the market is closed; validate again at the open before approving."
                     if closed else None)}


def fresh_validation(events: list[dict[str, Any]], fresh_minutes: float, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Latest OPTIONS_VALIDATED event if it is VALIDATED and inside the window."""
    now = now or datetime.now(timezone.utc)
    vals = [e for e in events if e.get("event_type") == "OPTIONS_VALIDATED"]
    if not vals:
        return None
    last = vals[-1]
    try:
        at = datetime.fromisoformat(str(last.get("validated_at")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if last.get("status") != "VALIDATED" or (now - at).total_seconds() > fresh_minutes * 60:
        return None
    return last
