# Stage 2a Canary Session — OPERATOR RUNBOOK (compressed 5-order battery)

**Date prepared:** 2026-06-12 · Allowlist committed: **GRAB** (primary, ~$3.35) / XRX (fallback)

## ⚠️ THE ONE THING TO UNDERSTAND FIRST

**NOTHING IS QUEUED. NOTHING AUTO-EXECUTES. THE SYSTEM CANNOT SEND ORDERS — THE CODE PATH DOES NOT
EXIST** (validate_schwab_no_writes 17/17). Every order below is placed BY YOU, BY HAND, IN
THINKORSWIM. The system only READS your orders back every 30 seconds and checks that what Schwab
shows matches what our translator predicted. A "draft" in the Broker Orders panel is a PREDICTION
for that comparison — not a queued order.

```
 YOU (thinkorswim)              THE SYSTEM (read-only)
 ──────────────────             ─────────────────────────────
 1. draft in panel  ──────────► saves the PREDICTION
 2. place order in ToS          (does nothing)
 3. wait ~30s                   reads order back via API
                                diffs actual vs prediction
 4. Claude says PASS/FAIL ◄──── reconciliation verdict
 5. cancel / next order         logs everything, canary-tags fills
```

## Division of labor — who does what

| Actor | Does | Never does |
|---|---|---|
| **You** | draft in panel → place in ToS → cancel in ToS → decide to proceed/abort | — |
| **System** | reads orders/fills every 30s, diffs vs drafts, logs, canary-tags the round-trip | place, modify, cancel, queue, or suggest sending ANYTHING |
| **Claude (live)** | calls PASS/FAIL per order, watches for abort conditions | touch the broker |

## Session start (Claude runs this when you say go) — GREEN-LIGHT PRECONDITIONS
1. Watchers up (recon + activity, 30s cadence)
2. GRAB/XRX spread + $2–$4 band re-verified live
3. **TOKEN FRESHNESS (blocking):** Gate-A token health = `ok` on a KNOWN-FRESH re-auth — not
   coasting toward the 7-day expiry. A token that dies mid-battery aborts the session half-tested;
   we start fresh or we don't start.
4. Gate auto-expiry date check: today == `CANARY_SESSION_DATE` (otherwise the allowlist is dead by
   design and the session cannot arm).

## THE 5 ORDERS — in this exact sequence, ONE AT A TIME
Wait for **PASS** before starting the next.

**☑ PER-ORDER CHECK (every single order, not once):** panel ACCOUNT selector == thinkorswim
account selector — confirm BOTH before placing. A mismatch makes the harness reconcile against the
wrong account (reads as a false FAIL) and risks placing real orders in the wrong account.

### Order 1 — plain limit + cancel (cost $0)
- **Panel draft:** symbol GRAB · account (your pick) · qty 10 · structure SINGLE · LIMIT $1.70 · DAY → press "BUY (fields)"
- **ToS:** BUY 10 GRAB LIMIT 1.70 DAY (≈50% below market — it can never fill)
- Wait for Claude: PASS = shape + WORKING status verified → **cancel it in ToS** → Claude verifies the cancel propagates.
- Proves: order JSON shape, status lifecycle, cancel.

### Order 2 — bracket (OTOCO) + cancel ($0)
- **Panel draft:** same but structure **BRACKET** · LIMIT $1.70 · stop-loss $1.50 · target $4.00
- **ToS:** BUY 10 GRAB LIMIT 1.70 with bracket (1st trgr seq): TP 4.00 / SL 1.50 → after PASS, **cancel the parent**
- Proves: TRIGGER→OCO structure; **does cancelling the parent kill the children?** (we assume yes — this is the test)

### Order 3 — trailing-stop bracket + cancel ($0)
- **Panel draft:** structure **TRAILING STOP** · LIMIT $1.70 · trail 3% / PERCENT / LAST · target $4.00
- **ToS:** BUY 10 GRAB LIMIT 1.70 w/ TRAILSTOP 3% exit → after PASS, **cancel**
- Proves: stopPriceLinkBasis/Type/Offset representation.

### Order 4 — THE ONE REAL FILL (≈$34, attended)
- **Panel draft:** structure SINGLE · LIMIT **at the live ask** (press BUY @ ASK — it fills the field from the quote)
- **ToS:** BUY 10 GRAB LIMIT @ask — marketable, fills in seconds
- Claude verifies the FILL event lands in activity capture with full payload.
- Proves: fill lifecycle + ACCT-activity payload shape. **You now own 10 GRAB (~$34).**

### Order 5 — OCO exits on the live position, then close (± cents)
- **Panel draft:** structure **OCO EXITS** · stop-loss ≈ −2% from your fill · target ≈ +2%
- **ToS:** attach OCO to the position: SELL 10 GRAB OCO [LIMIT target / STOP stop] → Claude PASSes the live children → **cancel the OCO**.
- **🛑 BLOCKING OVERSELL GUARD — before the closing sell:** Claude confirms via read-back that the
  position shows **ZERO working sell orders** — the OCO children must be VERIFIED GONE, not merely
  cancel-submitted. Cancel propagation is an assumption until orders 2/3 observed it live. **If ANY
  working sell remains: do NOT place the closing sell — re-cancel and re-verify first.**
  *Why this is the real-money step: a still-working child + a new closing sell = selling 20 shares
  against 10 owned ⇒ an unintended SHORT position.*
- Only after the zero-working-sells confirmation: **SELL 10 GRAB LIMIT @bid** to close flat.
- Proves: live children arm against a real position; close → ingestion lands **canary-tagged** (auto-excluded from all stats — already proven by test).

**End state: flat. Total real cost ≈ the spread on 10 shares = cents.**

## ABORT — either of us calls it, instantly
unexpected fill · ANY api-write attempt (impossible by construction — but it's the tripwire) ·
reconciliation mismatch beyond documented renames · token failure · GRAB leaves the $2–$4 band.

## After the session (Claude does)
rotate `CANARY_SYMBOL_ALLOWLIST` → `()` by commit · commit the reconciliation log · update the
UNVERIFIED register · re-run canary-exclusion proof · stop watchers · docs + Drive sync.
