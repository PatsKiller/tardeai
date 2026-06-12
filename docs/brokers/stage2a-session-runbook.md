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

## Session start (Claude runs this when you say go)
watchers up (recon + activity, 30s) → GRAB/XRX spread + $2–$4 band re-verified → green light.

## THE 5 ORDERS — in this exact sequence, ONE AT A TIME
Wait for **PASS** before starting the next. All in the ACCOUNT you selected in the panel (default
TAXABLE — pick in the new dropdown and place in the SAME account in ToS).

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
- **ToS:** attach OCO to the position: SELL 10 GRAB OCO [LIMIT target / STOP stop] → Claude PASSes the live children → **cancel the OCO**, then **SELL 10 GRAB LIMIT @bid** to close flat.
- Proves: live children arm against a real position; close → ingestion lands **canary-tagged** (auto-excluded from all stats — already proven by test).

**End state: flat. Total real cost ≈ the spread on 10 shares = cents.**

## ABORT — either of us calls it, instantly
unexpected fill · ANY api-write attempt (impossible by construction — but it's the tripwire) ·
reconciliation mismatch beyond documented renames · token failure · GRAB leaves the $2–$4 band.

## After the session (Claude does)
rotate `CANARY_SYMBOL_ALLOWLIST` → `()` by commit · commit the reconciliation log · update the
UNVERIFIED register · re-run canary-exclusion proof · stop watchers · docs + Drive sync.
