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
    def _find(k: Optional[float]) -> Optional[dict[str, Any]]:
        for e in chain.get("expirations") or []:
            if str(e.get("exp") or "")[:10] != exp:
                continue
            for r in e.get("strikes") or []:
                if r.get("side") == side and k is not None and abs((_f(r.get("strike")) or 0) - k) < 1e-6:
                    return r
        return None
    if str(p.get("strategy") or "") == "credit_spread":
        return _validate_spread(p, base, chain, s, session, now, _find)
    row = _find(strike)
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


def _validate_spread(p: dict[str, Any], base: dict[str, Any], chain: dict[str, Any], s: dict[str, Any],
                     session: Optional[str], now: datetime, find) -> dict[str, Any]:
    """Two-leg validation (operator 2026-09-27): a credit spread was validated as ONE contract,
    comparing the short put's mid to the net credit, so DELL always read "premium 8.1 -> 32.9".
    Both legs are re-quoted, the credit is recomputed under the explicit fill assumption
    (sell short at bid, buy long at ask), and a spread that is not a credit fails."""
    try:
        from lib.options_economics import spread_quote
    except ImportError:  # pragma: no cover
        from scripts.lib.options_economics import spread_quote  # type: ignore
    try:
        from options_desk_enterprise import liquidity_gate
    except ImportError:  # pragma: no cover
        from scripts.options_desk_enterprise import liquidity_gate  # type: ignore
    sk, lk = _f(p.get("short_strike")) or _f(p.get("strike")), _f(p.get("long_strike"))
    short_r, long_r = find(sk), find(lk)
    sym, exp = base["symbol"], base["expiration"]
    if short_r is None or long_r is None:
        missing = f"{sk:g}" if short_r is None else f"{lk:g}"
        return {**base, "status": "CONTRACT_NOT_FOUND", "short_strike": sk, "long_strike": lk,
                "reason": f"{sym} {exp} {missing} put is not in the live chain; regenerate the proposal"}
    sq = spread_quote(short_r, long_r, session=session, quotes_as_of=chain.get("fetched_at"))
    spot = _f(chain.get("underlying_price")) or _f(p.get("underlying_price")) or 0.0
    n = 100 * max(1, int(_f(p.get("contracts")) or 1))
    credit = sq["executable_credit"]
    econ = None
    if credit is not None and sk is not None and lk is not None:
        econ = {"credit_basis": "executable", "net_credit": credit, "premium_total": round(credit * n, 2),
                "max_profit": round(credit * n, 2), "max_loss": round((sk - lk - credit) * n, 2),
                "breakeven": round(sk - credit, 2), "mid_credit": sq["mid_credit"],
                "credit_haircut": sq["credit_haircut"], "cash_flow": "credit" if credit > 0 else "debit"}
    changes: list[str] = []
    old = _f(p.get("executable_credit")) if p.get("executable_credit") is not None else _f(p.get("premium"))
    if old and credit is not None and old > 0:
        d = 100.0 * (credit - old) / old
        if abs(d) > float(s["max_premium_change_pct"]):
            changes.append(f"executable credit {old:g} -> {credit:g} ({d:+.1f}%)")
    old_spot = _f(p.get("underlying_price"))
    if old_spot and spot:
        d = 100.0 * (spot - old_spot) / old_spot
        if abs(d) > float(s["max_spot_change_pct"]):
            changes.append(f"spot {old_spot:g} -> {spot:g} ({d:+.1f}%)")
    liq_issues: list[str] = []
    for leg in sq["legs"]:
        lg = liquidity_gate({"bid": leg["bid"], "ask": leg["ask"], "mid": leg["mid"],
                             "oi": leg["open_interest"], "volume": leg["volume"]})
        liq_issues += [f"{leg['role']} {leg['strike']:g}: {i}" for i in lg.get("issues") or []]
    if credit is None:
        status, changes = "NO_QUOTE", changes + ["a leg has no two-sided quote"]
    elif credit <= 0:
        status = "NOT_A_CREDIT"
        changes.append(f"sell {sk:g}p at bid {sq['legs'][0]['bid']} - buy {lk:g}p at ask {sq['legs'][1]['ask']} = {credit:g}")
    else:
        status = "ILLIQUID" if liq_issues else ("CHANGED" if changes else "VALIDATED")
    closed = bool(session) and session != "REGULAR"
    return {**base, "status": status, "short_strike": sk, "long_strike": lk, "live": sq,
            "recomputed": econ, "material_changes": changes, "liquidity_issues": liq_issues,
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


def refresh_exact(p, *, chain_fn, clock=None, cfg=None):
    """One expiration-scoped provider read for every leg; HTTP time is not quote time.

    Returns a receipt and refreshed economics without changing the authorized limit.
    The caller persists a new revision for material movement and returns to review.
    Injectable clock/readers are the only route used by engineering tests.
    """
    from scripts.lib import options_workflow as wf
    clock = clock or (lambda: datetime.now(timezone.utc))
    try:
        wanted = wf.proposal_legs(p)
        chain = chain_fn(p.get("symbol") or p.get("underlying"),
                         expiration=wanted[0]["expiration"], account_key=p.get("account"),
                         all_strikes=True)
        received = clock()
    except Exception as exc:
        return {"ok": False, "refusals": [wf.refusal("quotes_unavailable", str(exc)[:160])]}
    if not chain or chain.get("status") != "ok":
        return {"ok": False, "refusals": [wf.refusal("quotes_unavailable", "Exact-contract chain unavailable")]}
    legs, problems = [], []
    fields = ("bid", "ask", "last", "iv", "delta", "gamma", "theta", "vega", "rho", "volume", "oi",
              "quote_time", "trade_time", "oi_time", "greeks_time", "volume_time", "multiplier",
              "deliverables", "nonstandard", "non_standard", "occ_symbol")
    for leg in wanted:
        rows = [r for e in chain.get("expirations", []) if str(e.get("exp"))[:10] == leg["expiration"]
                for r in e.get("strikes", []) if r.get("side") == leg["option_type"]
                and wf.number(r.get("strike")) == leg["strike"]]
        if len(rows) != 1:
            problems.append(wf.refusal("contract_not_found", "Exact contract missing or ambiguous", leg=leg))
            continue
        row = rows[0]
        q = {**leg, **{k: row.get(k) for k in fields}}
        q["occ_symbol"] = row.get("symbol") or row.get("occ_symbol")
        bid, ask = wf.number(q.get("bid")), wf.number(q.get("ask"))
        q["mid"] = (bid + ask) / 2 if bid is not None and ask is not None else None
        legs.append(q)
    problems.extend(wf.quote_refusals(legs, now=received))
    from scripts.options_desk_enterprise import liquidity_gate
    for i, leg in enumerate(legs):
        problems.extend(wf.refusal("liquidity", str(issue), leg=i)
                        for issue in liquidity_gate(leg, cfg=cfg).get("issues", []))
    underlying_time = wf.timestamp(chain.get("underlying_quote_time"))
    if underlying_time is None or not 0 <= (received - underlying_time).total_seconds() <= 120:
        problems.append(wf.refusal("underlying_quote_stale", "Timestamped underlying quote is missing, future or stale"))
    receipt = {"underlying_quote_time": chain.get("underlying_quote_time"), "source": "schwab_chain", "received_at": received.isoformat(), "legs": legs,
               "underlying_price": wf.number(chain.get("underlying_price")),
               "chain_fetched_at": chain.get("fetched_at"), "environment": chain.get("environment", "live")}
    receipt["id"] = wf.digest(receipt)
    if problems:
        return {"ok": False, "receipt": receipt, "refusals": problems}
    credit = p["strategy"] in {"covered_call", "cash_secured_put", "credit_spread"}
    signed = sum((l["bid"] if l["side"] == "SELL" else -l["ask"]) * l["ratio"] for l in legs)
    quote_price = signed if credit else -signed
    if len(legs) == 1:
        quote_price = legs[0]["mid"]
    if quote_price <= 0:
        return {"ok": False, "receipt": receipt,
                "refusals": [wf.refusal("quote_invalid", "Strategy has no positive executable premium")]}
    live = {**p, "legs": legs, "legs_liquidity": legs,
            "quotes_as_of": min(wf.timestamp(l["quote_time"]) for l in legs).isoformat(),
            "quote_time": min(wf.timestamp(l["quote_time"]) for l in legs).isoformat(),
            "chain_fetched_at": receipt["received_at"], "underlying_price": receipt["underlying_price"],
            "quote_receipt": receipt, "data_source": "schwab_chain"}
    changes = []
    limits = settings(cfg)
    for field, value, threshold in (("premium", quote_price, limits["max_premium_change_pct"]),
                                    ("underlying_price", receipt["underlying_price"], limits["max_spot_change_pct"])):
        old = wf.number(p.get(field))
        if old and value is not None and abs(value - old) / abs(old) * 100 > float(threshold):
            changes.append({"field": field, "reviewed": old, "current": value,
                            "change_pct": 100 * (value - old) / abs(old)})
    return {"ok": True, "proposal": live, "receipt": receipt, "market_premium": quote_price,
            "material_changes": changes, "refusals": []}
