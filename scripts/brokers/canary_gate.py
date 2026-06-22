"""Hardcoded canary execution envelope (Stage 2a Part D) — changeable ONLY by commit.

This is an ADDITIVE fail-closed gate that sits IN FRONT of any future execution path, on top of
BROKER_DISABLED. It pre-positions the operator's canary caps in CODE so that when L3/L4 eventually
opens, the envelope is hardcoded — not config-driven. UI/config/env/DB can NEVER widen it:

  HARD RULE (operator, 2026-06-12): this module must contain NO os.getenv, NO DB reads, NO config
  imports. Every value below is a committed literal. Widening it requires a git commit.
  (Intentional, documented exception to the no-hardcoded-values rule — the POINT is immutability.)

Envelope (operator-confirmed 2026-06-12): symbol in the committed allowlist · price <= $4.00 ·
qty <= 10 shares · notional <= $40 · US equities only · long-only. Anything else => BLOCKED.

The symbol allowlist ships EMPTY: it is committed AT SESSION TIME once the $2-$4 liquidity screen
runs (see docs/brokers/stage2a-canary-protocol.md). Empty allowlist = every order blocked, which is
the correct resting state between sessions. NOTE: the previously screened ITUB ($7.91) / SNAP
($5.33) picks violate the new $2-$4 cap and must NOT be committed without re-screening.

This phase the gate is redundant (BROKER_DISABLED blocks everything anyway) — proven unit-tested in
isolation by tests/test_canary_gate.py, including the hypothetical where every other lock is open.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── THE COMMITTED ENVELOPE — change only by commit ──────────────────────────────────────────────
# SESSION COMMIT 2026-06-15 MONDAY (operator-ordered; full log in stage2a-canary-protocol.md):
#   PRIMARY  GRAB ~$3.30 — re-screened 2026-06-13: 0.6% spread after-hours, ZERO footprint (never
#            held/watched/papered/journaled). Clean primary. ⚠ RE-VERIFY price ≤$4 + spread at the open.
#   FALLBACK XRX  ~$3.35 — 3.8% AH spread (wide — verify ≤1.5% at open; GRAB is primary). Both ≤$4.
#   (06-13 was a Saturday; rescheduled to Monday 06-15 for the live battery session.)
CANARY_SYMBOL_ALLOWLIST: tuple[str, ...] = ("GRAB", "XRX")

# ── CANARY ENVELOPE REMOVED (operator 2026-06-21: "remove $40 canary envelope") ──────────────────
# While True, evaluate() is a PASS-THROUGH: the $4 price / 10-share / $40 notional / symbol-allowlist /
# session-date / equities / long-only checks below NO LONGER block any BUY. This mirrors the Stage-2c
# stop decision (GATES_REMOVED) the operator already made. The per-order 2FA (web typed-ticker +
# Telegram) — enforced in execution_guard, NOT here — and the armed-session/standing-approval locks
# still gate EVERY submit. Flip back to False (one-line, committed) to restore the full envelope below;
# every check is retained, just bypassed. (Committed literal — honors this module's no-config rule.)
GATES_REMOVED = True

# AUTO-EXPIRY: the allowlist is honored ONLY on this committed date. Any other date ⇒ the gate treats
# the allowlist as EMPTY — fail-closed — so a forgotten post-session rotate-back can never leave the
# envelope armed. Rescheduling = commit a new date.
CANARY_SESSION_DATE = "2026-06-22"   # [OPERATOR_SET 2026-06-19] Monday — prior gate auto-expired 2026-06-15
MAX_PRICE_USD = 4.00
MAX_QTY_SHARES = 10
MAX_NOTIONAL_USD = 40.00
ALLOWED_ASSET_TYPES = ("EQUITY",)               # US equities only
ALLOWED_DIRECTIONS = ("LONG",)                  # long-only
# ────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class CanaryGateDecision:
    allowed: bool
    reasons: list[str]          # empty when allowed


def _worst_case_prices(intent) -> list[float]:
    """Every committed BUY price the order could transact at. Empty => unbounded => fail closed.
    MARKET / market-on-close entries carry no committed price cap, so they are BLOCKED by design
    (the protocol's one micro-fill is a marketable LIMIT, which is representable and capped)."""
    prices: list[float] = []
    e = intent.entry
    if intent.ladder:
        prices += [float(l.entry_price) for l in intent.ladder.legs if l.entry_price]
    if e.limit_price:
        prices.append(float(e.limit_price))
    elif e.entry_range and e.entry_range.get("high"):
        prices.append(float(e.entry_range["high"]))
    # Stage 2b battery (2026-06-15): a SELL STOP / protective-stop entry commits its price in
    # entry.stop_price (not limit_price) — count it so the shape is bounded by the ≤$4/≤$40 envelope
    # and is NOT treated as an uncapped (MARKET-like) order. A SELL LIMIT close / trailing reference
    # both carry entry.limit_price (handled above). A true MARKET entry has neither ⇒ still blocked.
    if getattr(e, "stop_price", None):
        prices.append(float(e.stop_price))
    return prices


def _today() -> str:
    """Isolated for testability; date source only — never config/env."""
    import datetime
    return datetime.date.today().isoformat()


def evaluate(intent) -> CanaryGateDecision:
    """Pure, deterministic, fail-closed. Any doubt => BLOCKED with the reason(s)."""
    # Envelope removed (operator 2026-06-21): pass through — per-order 2FA + armed-session locks in
    # execution_guard remain the gate. Flip GATES_REMOVED=False to restore the full envelope below.
    if GATES_REMOVED:
        return CanaryGateDecision(allowed=True, reasons=[])
    reasons: list[str] = []
    try:
        # auto-expiry: allowlist is live ONLY on the committed session date (fail-closed otherwise)
        try:
            allowlist = CANARY_SYMBOL_ALLOWLIST if _today() == CANARY_SESSION_DATE else ()
        except Exception:
            allowlist = ()
        sym = (intent.instrument.symbol or "").strip().upper()
        if not allowlist:
            if CANARY_SYMBOL_ALLOWLIST and _safe_today_mismatch():
                reasons.append(f"allowlist EXPIRED — committed for {CANARY_SESSION_DATE}, today is not "
                               "that date (auto-expiry fail-closed; recommit to reschedule)")
            else:
                reasons.append("allowlist EMPTY — no canary session is committed (commit symbols at session time)")
        elif sym not in allowlist:
            reasons.append(f"symbol {sym!r} not in committed canary allowlist {allowlist}")

        if intent.instrument.asset_type.value not in ALLOWED_ASSET_TYPES or intent.instrument.option_legs:
            reasons.append(f"asset type {intent.instrument.asset_type.value} not allowed (US equities only)")

        if intent.direction.value not in ALLOWED_DIRECTIONS:
            reasons.append(f"direction {intent.direction.value} not allowed (long-only)")

        q = intent.quantity
        if q.notional or q.contracts or not q.qty:
            reasons.append("quantity must be share-based (qty), not notional/contracts")
            qty = 0.0
        else:
            qty = float(q.qty)
            if qty <= 0 or qty > MAX_QTY_SHARES:
                reasons.append(f"qty {qty:g} outside (0, {MAX_QTY_SHARES}]")

        prices = _worst_case_prices(intent)
        if not prices:
            reasons.append("no committed price cap (MARKET/uncapped entry) — envelope requires a limit price")
        else:
            worst = max(prices)
            if worst > MAX_PRICE_USD:
                reasons.append(f"price ${worst:g} > ${MAX_PRICE_USD:g} cap")
            if qty and worst * qty > MAX_NOTIONAL_USD:
                reasons.append(f"notional ${worst * qty:.2f} > ${MAX_NOTIONAL_USD:g} cap")

    except Exception as e:                      # malformed intent => fail closed, never allow
        reasons.append(f"gate could not evaluate intent ({type(e).__name__}: {str(e)[:80]}) — fail closed")
    return CanaryGateDecision(allowed=not reasons, reasons=reasons)


def _safe_today_mismatch() -> bool:
    try:
        return _today() != CANARY_SESSION_DATE
    except Exception:
        return True   # can't determine the date => treat as expired (fail closed)
