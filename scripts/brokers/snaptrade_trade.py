"""snaptrade_trade.py — FUTURE SnapTrade order path (gated OFF). Build-now, enable-later.

Scope: lets you eventually test orders on a SnapTrade-connected brokerage (e.g. the Fidelity Rollover IRA
once the rollover funds it). Mirrors the Schwab canary discipline — commit-only envelope, default OFF,
preview-before-place — WITHOUT a hard fence (operator wants trading addable later).

SnapTrade order flow is two-step and we keep it that way as the safety spine:
  1. preview(...)  -> trading.get_order_impact(...)  — NON-executing. Returns the impact + a trade_id.
                      Works even while ENABLED=False (it places nothing).
  2. place(trade_id) -> trading.place_order(trade_id=...) — EXECUTES. Gated behind ENABLED + the envelope
                      + (future) per-order 2FA, exactly like the Schwab pilot.

NOTHING here runs until ENABLED is flipped True in a commit AND the per-order confirm is wired. Default
state places nothing. The 401k is intentionally NOT tradeable here (employer plan, read-only on SnapTrade);
the allowlist is the brokerage account(s) only.
"""
from __future__ import annotations

import os

from . import snaptrade_credentials as _creds

# ── Master gate + commit-only envelope (widen only via a git commit) ───────────────────────────────
ENABLED = False                                  # ← flip True in a commit to arm. Default OFF.
# Internal account_keys allowed to trade (resolved to SnapTrade account_id by the caller via
# config/snaptrade_accounts.json). 401k excluded — it can't be traded through SnapTrade.
TRADE_ACCOUNT_ALLOWLIST: tuple[str, ...] = ("fidelity_rollover_ira",)
ALLOWED_ACTIONS = ("BUY", "SELL")
# SnapTrade equity API: no native TrailingStop — trailing uses fidelity_monitored_stop ratchet.
ALLOWED_ORDER_TYPES = ("Limit", "Market", "Stop", "StopLimit")
# Full-trade envelope (post-proof) — widen only by commit.
MAX_QTY_UNITS = 5
MAX_PRICE_USD = 10.0
MAX_NOTIONAL_USD = 50.0

# ── ONE-SHARE TEST MODE (operator 2026-06-22) — no SnapTrade sandbox; live broker is the test env.
# When system_controls['snaptrade_one_share_test_enabled']='true' (snaptrade_pilot_arm.py --arm-test),
# evaluate_envelope() applies THESE limits and requires exactly 1 unit. Preview works without the DB flag;
# place() requires ENABLED + DB flag + per-order 2FA.
ONE_SHARE_TEST_EXACT_UNITS = 1.0
ONE_SHARE_TEST_MAX_PRICE_USD = 50.0
ONE_SHARE_TEST_MAX_NOTIONAL_USD = 50.0
SNAPTRADE_ONE_SHARE_TEST_MARKER = "SNAPTRADE_ONE_SHARE_TEST"


def _user():
    from .snaptrade_read import SnapTradeUser
    return SnapTradeUser.from_env()


def broker_allows_trading() -> tuple[bool, str]:
    """Does the connected brokerage actually support trading via SnapTrade? Many (incl. FIDELITY) are
    READ-ONLY — allows_trading=False — so no order can ever be placed there regardless of this module's
    gate. Checked live so the scaffold never pretends a trade path exists where the broker has none.
    Returns (ok, detail)."""
    try:
        u = _user(); c = _client()
        auths = c.connections.list_brokerage_authorizations(user_id=u.user_id, user_secret=u.user_secret)
        for a in (getattr(auths, "body", auths) or []):
            b = a.get("brokerage") or {}
            if b.get("allows_trading"):
                return (True, f"{b.get('name')} allows_trading=True (type={a.get('type')})")
        return (False, "no connected brokerage allows trading via SnapTrade (e.g. Fidelity is read-only)")
    except Exception as e:
        return (False, f"capability check failed ({type(e).__name__}: {str(e)[:60]})")


def _client():
    from .snaptrade_read import _client as _c
    return _c()


def is_one_share_test_unlocked() -> bool:
    """Standing DB unlock for live one-share proof orders (no sandbox)."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='snaptrade_one_share_test_enabled'")
        r = cur.fetchone()
        return bool(r and str(r[0]).lower() == "true")
    except Exception:
        return False


def envelope_limits(*, one_share_test: bool | None = None) -> dict:
    """Active caps — one-share test mode is stricter (exactly 1 unit)."""
    test = one_share_test if one_share_test is not None else is_one_share_test_unlocked()
    if test:
        return {
            "mode": "one_share_test",
            "max_units": ONE_SHARE_TEST_EXACT_UNITS,
            "exact_units": True,
            "max_price": ONE_SHARE_TEST_MAX_PRICE_USD,
            "max_notional": ONE_SHARE_TEST_MAX_NOTIONAL_USD,
        }
    return {
        "mode": "standard",
        "max_units": MAX_QTY_UNITS,
        "exact_units": False,
        "max_price": MAX_PRICE_USD,
        "max_notional": MAX_NOTIONAL_USD,
    }


def evaluate_envelope(*, account_key: str | None, action: str, order_type: str,
                      units: float | None, price: float | None,
                      one_share_test: bool | None = None, for_place: bool = False) -> tuple[bool, list[str]]:
    """Pure pass/fail + reasons. Fails closed on anything unexpected.

    for_place=False (preflight/preview): envelope checked even if ENABLED=False.
    for_place=True (execute): requires ENABLED + one_share_test DB flag when in test mode."""
    reasons: list[str] = []
    limits = envelope_limits(one_share_test=one_share_test)
    test_mode = limits["mode"] == "one_share_test"
    if for_place and not ENABLED:
        return (False, ["SnapTrade trade path DISABLED (commit ENABLED=True to arm)"])
    if for_place and test_mode and not is_one_share_test_unlocked():
        return (False, ["one-share test mode not armed — run snaptrade_pilot_arm.py --arm-test"])
    try:
        if (account_key or "") not in TRADE_ACCOUNT_ALLOWLIST:
            reasons.append(f"account {account_key!r} not in trade allowlist {TRADE_ACCOUNT_ALLOWLIST}")
        if (action or "").upper() not in ALLOWED_ACTIONS:
            reasons.append(f"action {action!r} not in {ALLOWED_ACTIONS}")
        if (order_type or "") not in ALLOWED_ORDER_TYPES:
            reasons.append(f"order_type {order_type!r} not in {ALLOWED_ORDER_TYPES}")
        u = float(units) if units is not None else 0.0
        p = float(price) if price is not None else 0.0
        if limits["exact_units"]:
            if abs(u - ONE_SHARE_TEST_EXACT_UNITS) > 1e-6:
                reasons.append(f"one-share test requires exactly {ONE_SHARE_TEST_EXACT_UNITS:g} unit(s), got {u:g}")
        elif u <= 0 or u > limits["max_units"]:
            reasons.append(f"units {u:g} outside (0, {limits['max_units']}]")
        if p > limits["max_price"]:
            reasons.append(f"price ${p:g} > ${limits['max_price']:g} cap ({limits['mode']})")
        if u and p and u * p > limits["max_notional"]:
            reasons.append(f"notional ${u*p:.2f} > ${limits['max_notional']:g} cap ({limits['mode']})")
    except Exception as e:
        reasons.append(f"envelope could not evaluate ({type(e).__name__}: {str(e)[:60]}) — fail closed")
    return (not reasons, reasons)


def resolve_universal_symbol_id(symbol: str) -> str:
    """Map a US ticker to SnapTrade universal_symbol_id for order preview/place."""
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol required")
    u = _user(); c = _client()
    for meth in (
        lambda: c.reference_data.get_symbols(query=sym, user_id=u.user_id, user_secret=u.user_secret),
        lambda: c.reference_data.symbol_search(user_input=sym, user_id=u.user_id, user_secret=u.user_secret),
    ):
        try:
            resp = meth()
            body = getattr(resp, "body", resp) or []
            if isinstance(body, dict):
                body = body.get("results") or body.get("symbols") or [body]
            for item in body:
                if not isinstance(item, dict):
                    continue
                raw = (item.get("symbol") or item.get("ticker") or "").upper()
                if raw == sym or sym in raw:
                    uid = item.get("id") or item.get("universal_symbol_id")
                    if uid:
                        return str(uid)
        except Exception:
            continue
    raise RuntimeError(f"could not resolve universal_symbol_id for {sym!r} via SnapTrade reference data")


def preview(*, account_id: str, action: str, universal_symbol_id: str, order_type: str,
            units: float, price: float | None = None, stop: float | None = None,
            time_in_force: str = "Day") -> dict:
    """NON-executing order impact. Returns the broker's impact estimate + a trade_id you'd pass to place().
    Safe to call any time — places nothing. (Needs the account's universal_symbol_id from a quote lookup.)"""
    u = _user(); c = _client()
    resp = c.trading.get_order_impact(
        account_id=account_id, action=action, universal_symbol_id=universal_symbol_id,
        order_type=order_type, time_in_force=time_in_force, units=units, price=price, stop=stop,
        user_id=u.user_id, user_secret=u.user_secret)
    return dict(getattr(resp, "body", resp) or {})


def place(*, trade_id: str, confirmed: bool = False, one_share_test: bool = False) -> dict:
    """EXECUTE a previewed order. Gated: ENABLED + broker allows trading + 2FA consumed by caller."""
    if not ENABLED:
        raise RuntimeError("SnapTrade trade path DISABLED — commit ENABLED=True to arm.")
    ok, detail = broker_allows_trading()
    if not ok:
        raise RuntimeError(f"broker does not support SnapTrade trading: {detail}")
    if one_share_test and not is_one_share_test_unlocked():
        raise RuntimeError("one-share test not armed — snaptrade_pilot_arm.py --arm-test required.")
    if not confirmed:
        raise RuntimeError("per-order confirmation required (2FA) before place() — refusing.")
    u = _user(); c = _client()
    resp = c.trading.place_order(trade_id=trade_id, user_id=u.user_id, user_secret=u.user_secret)
    return dict(getattr(resp, "body", resp) or {})


def cancel(*, account_id: str, brokerage_order_id: str) -> dict:
    """Cancel a working order. Allowed whenever ENABLED (cancelling is risk-reducing)."""
    if not ENABLED:
        raise RuntimeError("SnapTrade trade path DISABLED.")
    u = _user(); c = _client()
    resp = c.trading.cancel_user_account_order(
        account_id=account_id, brokerage_order_id=brokerage_order_id,
        user_id=u.user_id, user_secret=u.user_secret)
    return dict(getattr(resp, "body", resp) or {})
