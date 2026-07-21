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

ENABLED = True                                   # ← MASTER GATE (commit to flip). ARMED 2026-06-15 for the POC.
# ── ALL STAGE-2c STOP GATES REMOVED (operator 2026-06-19: "all gates for stops and trailing stops
# stage 2c should be removed"). While True, evaluate() is a PASS-THROUGH: the policy envelope no longer
# blocks ANY protective/trailing stop (no account allowlist, order-type, notional, drift, stop-below-
# price, qty, or POC checks). A protective SELL stop is the safe direction (sell-to-close a long), and
# the universal per-order 2FA (web typed-ticker + Telegram) — enforced in execution_guard, NOT here —
# still confirms EVERY order before it reaches Schwab. Flip back to False to restore the full envelope
# below (one-line revert; all gate logic is retained, just bypassed).
GATES_REMOVED = True
PROTECTIVE_ACCOUNT_ALLOWLIST: tuple[str, ...] = ("schwab_taxable",)   # base: taxable only (IRAs wired-but-off below)
ALLOWED_ORDER_TYPES = ("STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT", "OCO")   # OCO = protective stop + take-profit (P3)
ALLOWED_INSTRUCTION = "SELL"                     # sell-to-close a long; never SELL_SHORT
MAX_STOP_DRIFT_PCT = 8.0                          # placed stop must be within ±8% of the advised stop
MAX_POSITION_NOTIONAL_USD = 250_000.0            # full-envelope per-order ceiling (a held lot's value)

# ── IRA EXTENSION — WIRED BUT DISABLED (operator 2026-06-15) ───────────────────────────────────────
# The two Schwab IRAs are kept structurally excluded (operator decision 2026-06-12). The code path to
# include them is fully wired so enabling is ONE deliberate, explicitly-approved step: flip
# IRA_PROTECTIVE_ENABLED=True (commit) AND set broker_accounts.api_write_enabled=true on the two rows
# (a second, independent DB lock). While the flag is False the IRAs are blocked at BOTH the gate
# (effective allowlist excludes them) and the transport precondition. Fidelity-401k is never here —
# broker=fidelity has NO trading API at all (ticket-only forever, no flag can change that).
IRA_PROTECTIVE_ENABLED = True                    # ← ENABLED 2026-06-15 (operator: "enable the IRAs"). 2nd lock = api_write_enabled on the 2 rows.
SCHWAB_IRA_ACCOUNTS: tuple[str, ...] = ("schwab_roth_ira", "schwab_rollover_ira")


def effective_account_allowlist() -> tuple[str, ...]:
    """The accounts a protective stop may target right now: taxable always, plus the two Schwab IRAs
    ONLY when IRA_PROTECTIVE_ENABLED is committed True. Single source of truth for the gate AND the
    transport precondition, so the two can never drift."""
    return PROTECTIVE_ACCOUNT_ALLOWLIST + (SCHWAB_IRA_ACCOUNTS if IRA_PROTECTIVE_ENABLED else ())


# ── POC PROOF LAYER (operator 2026-06-15) — a tighter committed envelope IN FRONT of the full one, so
# the first LIVE protective stops are near-zero-risk proofs. Same canary discipline: commit-only literals,
# single-symbol allowlist, an auto-expiring session window, hard sub-$1k notional cap. While POC_MODE is
# True every protective submit must ALSO satisfy this layer. Flip POC_MODE=False (commit) once the proofs
# pass to open the full MAX_POSITION_NOTIONAL_USD envelope to all taxable (and, if enabled, IRA) holdings.
POC_MODE = False                                    # ← OPENED 2026-06-15 (operator: "open all taxable"). Full envelope now governs.
# operator picks (taxable, defensive, WHOLE-share, each < the POC cap so a fat-finger is bounded):
#   DRS 11@$46.68≈$513 · KBR 15@$34.82≈$522 · KTOS 9@$57≈$513 (all proven live 2026-06-15, fixed STOP)
#   IRDM 25@$45.39≈$1135 — added 2026-06-15 to prove the native TRAILING_STOP shape (advised trail 5%)
POC_SYMBOL_ALLOWLIST: tuple[str, ...] = ("DRS", "KBR", "KTOS", "IRDM")
# VALID-THROUGH window (operator 2026-06-15: "set pilot next friday expire"). The POC is live on every
# date up to AND INCLUDING this Friday, then auto-expires fail-closed. Reschedule = commit a new date.
POC_SESSION_THROUGH = "2026-06-19"                  # YYYY-MM-DD inclusive deadline (Fri); any later date ⇒ allowlist EMPTY
POC_MAX_NOTIONAL_USD = 1_200.0                      # POC ceiling — bumped $1k→$1.2k 2026-06-15 to fit IRDM (~$1135) for the trailing-shape proof


def _today() -> str:
    """Date source only — never config/env (mirrors canary_gate discipline)."""
    import datetime
    return datetime.date.today().isoformat()


def _poc_window_open() -> bool:
    """True while today is on/before the committed POC deadline (fail-closed on any error)."""
    try:
        return _today() <= POC_SESSION_THROUGH
    except Exception:
        return False


def evaluate(*, account_key: str | None, instruction: str, order_type: str,
             stop_price: float | None, advised_stop: float | None, current_price: float | None,
             qty: float | None, held_qty: float | None, symbol: str | None = None,
             take_profit: float | None = None) -> tuple[bool, list[str]]:
    """Pure pass/fail + reasons. Fail closed on anything unexpected. ENABLED gates everything; while
    POC_MODE the tighter proof envelope (symbol allowlist + session date + sub-$1k notional) also applies."""
    reasons: list[str] = []
    if not ENABLED:
        return (False, ["Stage 2c protective-stop policy is DISABLED (commit ENABLED=True to arm "
                        "after the canary test passes)"])
    if GATES_REMOVED:
        # Operator 2026-06-19: all Stage-2c stop gates removed. Pass-through — the universal per-order
        # 2FA in execution_guard remains the sole confirm before any stop reaches the broker.
        return (True, [])
    try:
        _allow = effective_account_allowlist()
        if (account_key or "").strip() not in _allow:
            reasons.append(f"account {account_key!r} not in protective-stop allowlist {_allow}"
                           + ("" if IRA_PROTECTIVE_ENABLED else " (IRAs wired but DISABLED — flip IRA_PROTECTIVE_ENABLED + api_write)"))
        if (instruction or "").upper() != ALLOWED_INSTRUCTION:
            reasons.append(f"instruction {instruction!r} not allowed (SELL-to-close only)")
        if (order_type or "").upper() not in ALLOWED_ORDER_TYPES:
            reasons.append(f"order_type {order_type!r} not in {ALLOWED_ORDER_TYPES}")
        sp = float(stop_price) if stop_price is not None else None
        cp = float(current_price) if current_price is not None else None
        adv = float(advised_stop) if advised_stop is not None else None
        notional_cap = POC_MAX_NOTIONAL_USD if POC_MODE else MAX_POSITION_NOTIONAL_USD
        if sp is None or cp is None:
            reasons.append("missing stop_price / current_price — fail closed")
        else:
            if sp >= cp:
                reasons.append(f"stop ${sp:g} at/above price ${cp:g} — not a protective long stop")
            if adv is not None and adv > 0 and abs(sp - adv) / adv * 100 > MAX_STOP_DRIFT_PCT:
                reasons.append(f"stop ${sp:g} drifts >{MAX_STOP_DRIFT_PCT:g}% from advised ${adv:g}")
            if cp and qty and cp * float(qty) > notional_cap:
                reasons.append(f"notional ${cp*float(qty):,.0f} exceeds ${notional_cap:,.0f} cap")
        if qty is not None and held_qty is not None and float(qty) > float(held_qty) + 1e-6:
            reasons.append(f"qty {qty:g} exceeds held shares {held_qty:g} (would open a short)")

        # ── OCO (P3): the stop leg is validated exactly as a protective STOP above (sp<cp, drift, notional,
        #    qty<=held). ALSO require the take-profit leg to be a sell-to-close ABOVE market (a real profit
        #    target) — else it would fill at/through market. Both legs are sell-to-close, the safe direction. ──
        if (order_type or "").upper() == "OCO":
            tp = float(take_profit) if take_profit is not None else None
            if tp is None:
                reasons.append("OCO requires a take_profit (the limit leg)")
            elif cp is not None and tp <= cp:
                reasons.append(f"take-profit ${tp:g} at/below price ${cp:g} — not a protective profit target above market")

        # ── POC proof layer: single committed symbol, valid-through-deadline window (auto-expiry) ──
        if POC_MODE:
            sym = (symbol or "").strip().upper()
            allowlist = POC_SYMBOL_ALLOWLIST if _poc_window_open() else ()
            if not allowlist:
                reasons.append(f"POC window EXPIRED — committed valid through {POC_SESSION_THROUGH} "
                               f"(today {_today()}); recommit POC_SESSION_THROUGH to extend the proof window")
            elif sym not in allowlist:
                reasons.append(f"symbol {sym!r} not in committed POC allowlist {allowlist}")
    except Exception as e:                       # malformed input ⇒ fail closed
        reasons.append(f"protective-stop policy could not evaluate ({type(e).__name__}: {str(e)[:60]}) — fail closed")
    return (not reasons, reasons)
