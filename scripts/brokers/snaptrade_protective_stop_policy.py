"""SnapTrade / Fidelity protective-stop policy — commit-only literals, default OFF (operator 2026-06-22).

Fidelity is READ-ONLY on SnapTrade (allows_trading=False) — broker API stops cannot be placed there today.
This policy gates TWO paths:
  • BROKER_API_ENABLED — SnapTrade preview→place (Stop/StopLimit only; no native trailing in SnapTrade SDK).
    Stays False until a trade-capable brokerage is connected AND the operator commits a flip.
  • MONITORED_ENABLED — software-monitored stops + trailing ratchet for fidelity_rollover_ira holdings.
    Same per-order 2FA discipline as Schwab Stage 2c; arms a DB-monitored level (no broker order) until
    breach → 2FA → Fidelity Active Trader ticket.

Standing unlock (like Schwab protective_stops_enabled): system_controls['fidelity_stops_enabled']='true',
set by snaptrade_pilot_arm.py --approve after operator typed-phrase confirmation.
"""
from __future__ import annotations

BROKER_API_ENABLED = False                       # SnapTrade place() — False while Fidelity is read-only
MONITORED_ENABLED = True                         # software-monitored path — still needs DB standing unlock
GATES_REMOVED = True                             # match Schwab Stage 2c operator unlock (2026-06-19)
FIDELITY_ACCOUNT_ALLOWLIST: tuple[str, ...] = ("fidelity_rollover_ira",)
# fidelity_401k excluded — employer plan, no exchange stops
ALLOWED_ORDER_TYPES = ("STOP", "STOP_LIMIT", "TRAILING_STOP")
ALLOWED_INSTRUCTION = "SELL"
MAX_STOP_DRIFT_PCT = 8.0
MAX_POSITION_NOTIONAL_USD = 250_000.0
# SnapTrade equity API order_type strings (no TrailingStop in SDK docs)
SNAPTRADE_ORDER_MAP = {"STOP": "Stop", "STOP_LIMIT": "StopLimit", "TRAILING_STOP": "Stop"}


def evaluate(*, account_key: str | None, instruction: str, order_type: str,
             stop_price: float | None, advised_stop: float | None, current_price: float | None,
             qty: float | None, held_qty: float | None, symbol: str | None = None) -> tuple[bool, list[str]]:
    """Pure pass/fail. MONITORED path uses this envelope; broker API path adds snaptrade_trade envelope."""
    if not MONITORED_ENABLED and not BROKER_API_ENABLED:
        return (False, ["Fidelity/SnapTrade stop policy DISABLED (commit MONITORED_ENABLED or "
                        "BROKER_API_ENABLED after operator approval)"])
    if GATES_REMOVED:
        return (True, [])
    reasons: list[str] = []
    try:
        if (account_key or "").strip() not in FIDELITY_ACCOUNT_ALLOWLIST:
            reasons.append(f"account {account_key!r} not in Fidelity stop allowlist {FIDELITY_ACCOUNT_ALLOWLIST}")
        if (instruction or "").upper() != ALLOWED_INSTRUCTION:
            reasons.append(f"instruction {instruction!r} not allowed (SELL-to-close only)")
        if (order_type or "").upper() not in ALLOWED_ORDER_TYPES:
            reasons.append(f"order_type {order_type!r} not in {ALLOWED_ORDER_TYPES}")
        sp = float(stop_price) if stop_price is not None else None
        cp = float(current_price) if current_price is not None else None
        adv = float(advised_stop) if advised_stop is not None else None
        if sp is None or cp is None:
            reasons.append("missing stop_price / current_price — fail closed")
        else:
            if sp >= cp:
                reasons.append(f"stop ${sp:g} at/above price ${cp:g} — not a protective long stop")
            if adv is not None and adv > 0 and abs(sp - adv) / adv * 100 > MAX_STOP_DRIFT_PCT:
                reasons.append(f"stop ${sp:g} drifts >{MAX_STOP_DRIFT_PCT:g}% from advised ${adv:g}")
            if cp and qty and cp * float(qty) > MAX_POSITION_NOTIONAL_USD:
                reasons.append(f"notional ${cp*float(qty):,.0f} exceeds ${MAX_POSITION_NOTIONAL_USD:,.0f} cap")
        if qty is not None and held_qty is not None and float(qty) > float(held_qty) + 1e-6:
            reasons.append(f"qty {qty:g} exceeds held shares {held_qty:g}")
    except Exception as e:
        reasons.append(f"policy could not evaluate ({type(e).__name__}: {str(e)[:60]}) — fail closed")
    return (not reasons, reasons)