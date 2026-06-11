# Stage 2a — Shadow Validation Protocol (manual orders + read-only API)

**Status:** READY FOR OPERATOR SESSION · paperMoney is NOT API-visible (operator-confirmed), so tests are
tiny REAL orders placed MANUALLY in thinkorswim; the API surface stays read-only throughout (fence 12/12).

## Canary instrument (live-screened 2026-06-11 via our batch-quotes endpoint)
| Pick | Px | Spread | Vol | Why |
|---|---|---|---|---|
| **PRIMARY: ITUB** | $7.91 | $0.02 (0.25%) | 33.9M | in band; penny-ish spread; boring ADR (low headline risk); **zero footprint** in holdings/watchlist/paper history — sterile |
| BACKUP: SNAP | $5.33 | $0.02 | 32.1M | also fully sterile; slightly newsier |
| (screened out) | NIO/LCID/BBD have watchlist rows; AGNC/NWG etc. are HELD — contamination risk |

**Size: 2 shares** (≈$16 max notional) — qty=2 not 1, so cancel-partial and split-exit semantics are at
least representable; true partial fills on a name this liquid are unlikely (documented limitation).

## Pre-session checklist (I do these before you trade)
1. Add ITUB to a `canary_symbols` exclusion consumed by journal/digest/round-trips stats (test trades must
   never pollute real-account analytics or coaching).
2. Start the shadow-reconciliation harness (reads `get_orders` every 30s during the session; diffs each
   observed order against translator expectations; logs to docs/brokers/).
3. Confirm ACCT_ACTIVITY read-only subscription running (your manual orders generate the events we need).

## Test battery (operator places in ToS; ~20 min; expected realized cost ≈ spread on 2 shares ≈ $0.04–$0.50)
| # | Manual order | Validates (UNVERIFIED item) | Fill risk |
|---|---|---|---|
| 1 | BUY 2 ITUB LIMIT @ $4.00 (≈50% below) — wait 60s — CANCEL | order shape, status lifecycle, cancel | none |
| 2 | Same but GTC + PM session | sessions/TIF representation (#8) | none |
| 3 | OTOCO: BUY 2 LIMIT @ $4.00 w/ bracket (TP $9.50 / SL $3.50) — CANCEL | TRIGGER→OCO response shape (#1 partial) | none |
| 4 | OTOCO w/ TRAILING_STOP exit (3% LAST) — CANCEL | trailing field representation | none |
| 5 | OCO multi-target: 2 exits 1sh each (requires position — do after #7) | multi-target acceptance (#1) | n/a |
| 6 | MODIFY #1-style order's limit price in ToS (before cancel) | replace-as-experienced (read side of #2) | none |
| 7 | BUY 2 ITUB marketable LIMIT @ ask — REAL FILL | fill lifecycle, ACCT_ACTIVITY fill event (#6) | ~$16 position |
| 8 | Attach OCO exits to the live position (TP +2% / SL −2%) | live child behavior; then manual close | ±$0.35 |
| 9 | SELL to close (marketable limit) | close lifecycle + round-trip ingestion w/ canary tag | spread |

## During session
Quiet window 11:30–14:00 ET · one order at a time · I reconcile each read-back live and tell you PASS/FAIL
before you place the next.

## Outputs
stage2a-reconciliation-log.md (per-order: ToS intent vs API representation vs translator expectation) ·
resolved/remaining UNVERIFIED register updates · ACCT_ACTIVITY payload captures.

## What this CANNOT validate (stays for gated Stage 2b API canaries)
API-side `replace_order` semantics · priceLink fields on API submission · API reject taxonomy.
