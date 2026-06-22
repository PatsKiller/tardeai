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
# Canary-style ceilings for the FIRST tests — tiny, like the Schwab pilot. Widen by commit later.
MAX_QTY_UNITS = 5
MAX_PRICE_USD = 10.0
MAX_NOTIONAL_USD = 50.0


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


def evaluate_envelope(*, account_key: str | None, action: str, order_type: str,
                      units: float | None, price: float | None) -> tuple[bool, list[str]]:
    """Pure pass/fail + reasons. Fails closed on anything unexpected. ENABLED gates everything."""
    reasons: list[str] = []
    if not ENABLED:
        return (False, ["SnapTrade trade path DISABLED (commit ENABLED=True to arm — future)"])
    try:
        if (account_key or "") not in TRADE_ACCOUNT_ALLOWLIST:
            reasons.append(f"account {account_key!r} not in trade allowlist {TRADE_ACCOUNT_ALLOWLIST}")
        if (action or "").upper() not in ALLOWED_ACTIONS:
            reasons.append(f"action {action!r} not in {ALLOWED_ACTIONS}")
        if (order_type or "") not in ALLOWED_ORDER_TYPES:
            reasons.append(f"order_type {order_type!r} not in {ALLOWED_ORDER_TYPES}")
        u = float(units) if units is not None else 0.0
        p = float(price) if price is not None else 0.0
        if u <= 0 or u > MAX_QTY_UNITS:
            reasons.append(f"units {u:g} outside (0, {MAX_QTY_UNITS}]")
        if p > MAX_PRICE_USD:
            reasons.append(f"price ${p:g} > ${MAX_PRICE_USD:g} cap")
        if u and p and u * p > MAX_NOTIONAL_USD:
            reasons.append(f"notional ${u*p:.2f} > ${MAX_NOTIONAL_USD:g} cap")
    except Exception as e:
        reasons.append(f"envelope could not evaluate ({type(e).__name__}: {str(e)[:60]}) — fail closed")
    return (not reasons, reasons)


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


def place(*, trade_id: str, confirmed: bool = False) -> dict:
    """EXECUTE a previewed order. Gated: requires ENABLED + an explicit confirmed=True (stand-in for the
    per-order 2FA to be wired before real use). Raises if not armed/confirmed."""
    if not ENABLED:
        raise RuntimeError("SnapTrade trade path DISABLED — commit ENABLED=True to arm (future).")
    ok, detail = broker_allows_trading()
    if not ok:
        raise RuntimeError(f"broker does not support SnapTrade trading: {detail}")
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
