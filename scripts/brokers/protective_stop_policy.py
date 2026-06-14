"""Stage 2c protective-stop policy — commit-only literals, default OFF (operator 2026-06-14).

The Open Trades cards advise a protective SELL STOP / STOP_LIMIT per holding; the future [Queue stop]
buttons route that order through the SAME fenced Schwab pilot + per-order 2FA as the canary battery.
But holdings (V ~$97K, FCNTX ~$104K) are FAR outside the $4/$40 canary envelope — so they need their
OWN committed envelope, enabled ONLY after the canary write test (Stage 2b) passes and the operator
arms this stage. Same discipline as canary_gate/pilot_caps: NO os.getenv, NO config reads — every
value is a committed literal; widening requires a git commit; default state places NOTHING.

Envelope (operator decisions 2026-06-14, build-now-gated-off):
  • ENABLED = False  ← the master gate. While False, every protective-stop submit is BLOCKED.
  • Direction: SELL-to-CLOSE an EXISTING LONG only (never opens a short/position).
  • Order types: STOP / STOP_LIMIT, GTC. No market, no buy.
  • Account: taxable only first (IRAs excluded), same as the canary pilot.
  • Sanity: the placed stop must be within MAX_STOP_DRIFT_PCT of the engine-advised stop, and BELOW
    the current price (a protective long stop). Quantity may not exceed the held share count.
  • Per-order 2FA (web typed-ticker + Telegram) still applies to EVERY order — arming this stage
    only opens the window; it never auto-places.
"""
from __future__ import annotations

ENABLED = False                                  # ← MASTER GATE (commit to flip). Default OFF.
PROTECTIVE_ACCOUNT_ALLOWLIST: tuple[str, ...] = ("schwab_taxable",)
ALLOWED_ORDER_TYPES = ("STOP", "STOP_LIMIT", "TRAILING_STOP")   # native trailing per operator 2026-06-14
ALLOWED_INSTRUCTION = "SELL"                     # sell-to-close a long; never SELL_SHORT
MAX_STOP_DRIFT_PCT = 5.0                          # placed stop must be within ±5% of the advised stop
MAX_POSITION_NOTIONAL_USD = 250_000.0            # per-order ceiling (a held lot's value)


def evaluate(*, account_key: str | None, instruction: str, order_type: str,
             stop_price: float | None, advised_stop: float | None, current_price: float | None,
             qty: float | None, held_qty: float | None) -> tuple[bool, list[str]]:
    """Pure pass/fail + reasons. Fail closed on anything unexpected. ENABLED gates everything."""
    reasons: list[str] = []
    if not ENABLED:
        return (False, ["Stage 2c protective-stop policy is DISABLED (commit ENABLED=True to arm "
                        "after the canary test passes)"])
    try:
        if (account_key or "").strip() not in PROTECTIVE_ACCOUNT_ALLOWLIST:
            reasons.append(f"account {account_key!r} not in protective-stop allowlist {PROTECTIVE_ACCOUNT_ALLOWLIST}")
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
            reasons.append(f"qty {qty:g} exceeds held shares {held_qty:g} (would open a short)")
    except Exception as e:                       # malformed input ⇒ fail closed
        reasons.append(f"protective-stop policy could not evaluate ({type(e).__name__}: {str(e)[:60]}) — fail closed")
    return (not reasons, reasons)
