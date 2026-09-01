# ATM approve_proposal_failed Investigation — 2026-05-22

Status:      HISTORICAL
as_of:       2026-05-22T15:47:55-04:00
Measured at: efcc51365 / not measured

## Summary

- Total ATM evaluations today: 82 decisions across 17 cycles (09:45–12:45 ET)
- Dry-run mode (09:45–11:15): 36 dry_run_approved, 6 dry_run_rejected (classifier_health)
- Active mode (11:30–12:45): 4 approved, 10 rejected, 31 deferred
- Failed at `approve_proposal` step: 10 (2 unique proposals x 5 cycles each)
- Failed at ATM gates before approval attempt: 0
- Deferred (bucket2 exclusion / not_yet_enriched): 31

## RESOLVED: NWG & NVDA Stop-Loss Orders Placed

NWG (trade #28) and NVDA (trade #29) were **fully filled in Alpaca** but had no
stop-loss orders due to the partial-fill race condition. **Remediated 2026-05-23:**

- Stop-loss orders placed manually for both positions
- `paper_trades` #28 and #29 synced from `pending` → `open`, `broker_status` → `filled`
- `paper_trade_proposals` #117 and #118 synced from `BLOCKED` → `EXECUTED`

### Alpaca State (post-remediation):
| Symbol | Shares | Avg Entry | Current Price | Unrealized P/L | Stop Order |
|--------|--------|-----------|---------------|----------------|------------|
| NWG    | 189    | $15.81    | $15.72        | -$14.18        | $15.05 ✓ (placed 2026-05-23) |
| NVDA   | 13     | $218.03   | $216.88       | -$16.04        | $210.58 ✓ (placed 2026-05-23) |
| AGNC   | 293    | $10.22    | $10.205       | -$4.40         | $9.71 ✓    |
| CMCSA  | 120    | $24.97    | $24.985       | +$1.80         | $23.61 ✓   |
| ASPN   | 553    | $5.52     | $5.765        | +$135.49       | $5.15 ✓ (pre-existing) |

Account: $100,470 equity, $85,501 cash, $14,969 in positions.
All 5 positions now have stop protection.

## Per-failure breakdown

### Issue 1: Stale Entry Prices — ARM #115 and BCS #122

| proposal_id | symbol | strategy | decided_at | category | root cause |
|---|---|---|---|---|---|
| 115 | ARM | core_growth_compounder | 11:30 | E (stale entry) | Price $308.23 vs entry $287.60 — 7.2% drift |
| 122 | BCS | dividend_growth_compounder | 11:30 | E (stale entry) | Price $23.98 vs entry $22.85 — 5.0% drift |
| 115 | ARM | core_growth_compounder | 12:00 | E (stale entry) | 7.1% drift |
| 122 | BCS | dividend_growth_compounder | 12:00 | E (stale entry) | 4.7% drift |
| 115 | ARM | core_growth_compounder | 12:15 | E (stale entry) | 7.7% drift |
| 122 | BCS | dividend_growth_compounder | 12:15 | E (stale entry) | 4.7% drift |
| 115 | ARM | core_growth_compounder | 12:30 | E (stale entry) | 7.7% drift |
| 122 | BCS | dividend_growth_compounder | 12:30 | E (stale entry) | 4.9% drift |
| 115 | ARM | core_growth_compounder | 12:45 | E (stale entry) | 6.9% drift |
| 122 | BCS | dividend_growth_compounder | 12:45 | E (stale entry) | 4.8% drift |

**Root cause**: Proposals created at ~09:05 AM with entry prices set at that time.
ATM activated at 11:25 AM (2+ hours later). ARM moved 7%+ up, BCS moved 5%+ up.
The `validate_paper_proposal_live_market()` function correctly blocks when drift > 3.0%.
ATM re-evaluates every 15 min but never refreshes the proposed_entry — same stale price
gets rejected every cycle indefinitely.

**Verdict**: The rejection gate is working correctly. The bug is that ATM has no
mechanism to re-enrich/refresh entry prices for proposals that fail the drift check.

### Issue 2: Partial Fill Handling Bug — NWG #28 and NVDA #29

Log evidence from `atm.log`:
```
11:30:04 [alpaca_paper_adapter] NWG PARTIAL FILL: 180/189 — canceling remainder
11:30:04 [atm] NWG: APPROVED — trade #28, broker=error

11:30:07 [alpaca_paper_adapter] NVDA PARTIAL FILL: 7/13 — canceling remainder
11:30:07 [atm] NVDA: APPROVED — trade #29, broker=error
```

However, Alpaca shows **full fills** (189 NWG, 13 NVDA). The adapter's partial-fill
detection was incorrect — likely a race condition where Alpaca filled the full order
but the adapter read an intermediate status showing partial fill, then cancelled
what it thought was the remainder (which was already filled).

Consequences:
1. Paper_trades #28 and #29 stuck in `pending` with no broker_order_id
2. Paper_trade_proposals #117 and #118 have `paper_submit_state=BLOCKED`
3. No stop-loss orders were placed (bracket setup skipped due to "error")
4. Duplicate paper_trades exist for AGNC (#30 pending + #31 open) and CMCSA (#32 pending + #33 open)

### Issue 3: Quote Fetch 404s (all 4 symbols)

```
Quote fetch failed for NWG: 404 Not Found
Quote fetch failed for NVDA: 404 Not Found
Quote fetch failed for AGNC: 404 Not Found
Quote fetch failed for CMCSA: 404 Not Found
```

All on `/v2/stocks/{SYMBOL}/trades/latest`. Adapter fell back to `validated_price`
from the proposal. Orders were placed using potentially stale proposal prices, not
live market quotes.

### Issue 4: Audit Log Schema Mismatch

```
Audit log write failed: column "event" of relation "audit_log" does not exist
```

Fires on every approval. Doesn't block trades but loses the audit trail.

## Root cause distribution

- Category E (stale entry prices): 10 rejections (2 proposals x 5 cycles)
- Category D (partial fill bug): 2 proposals affected (NWG, NVDA)
- Category C (quote API 404): 4 symbols affected (all ATM trades)
- Category D (audit_log schema): systemic (every approval)
- Category A (duplicate symbol): 0
- Category B (insufficient BP): 0

## Open positions check

Verified via Alpaca API — all 4 ATM-opened positions exist in Alpaca paper:
- NWG: 189 shares ✓ filled and "open", stop @ $15.05 ✓ (remediated 2026-05-23)
- NVDA: 13 shares ✓ filled and "open", stop @ $210.58 ✓ (remediated 2026-05-23)
- AGNC: 293 shares ✓ filled and "open", stop @ $9.71 ✓
- CMCSA: 120 shares ✓ filled and "open", stop @ $23.61 ✓

The 4 successful fills are unaffected by the ARM/BCS stale-price rejections.

## Recommended fixes (do NOT auto-deploy)

### P0 — Before Monday market open

1. ~~**Manual stop-loss orders for NWG and NVDA**~~ **DONE 2026-05-23**
   - NWG: stop sell 189 shares @ $15.05 — placed and confirmed
   - NVDA: stop sell 13 shares @ $210.58 — placed and confirmed
   - paper_trades #28/#29 synced to status=open, broker_status=filled
   - paper_trade_proposals #117/#118 synced to paper_submit_state=EXECUTED

2. ~~**Fix partial-fill race condition in `alpaca_paper_adapter.py`**~~ **DONE 2026-05-23**
   - Root cause: fill loop treated `partially_filled` as immediate error, cancelled order + closed position.
     For market orders on liquid stocks, this is a transient state — full fill arrives milliseconds later.
   - Fix: `partially_filled` now continues polling in the loop. After loop exhausts, accepts partial
     fills (cancels remainder, keeps filled shares, proceeds with stop placement and DB record).
   - No filled shares are ever abandoned or positions silently closed.

### P1 — Before next ATM activation

3. ~~**ATM stale-proposal expiry or re-enrichment**~~ **DONE 2026-05-23**
   - Added 5 columns to `paper_trade_proposals`: `atm_evaluation_count`, `atm_last_evaluation_at`,
     `atm_last_failure_reason`, `atm_expired_at`, `atm_expiry_reason`.
   - Expiry conditions: age >4h, 5+ consecutive same-reason failures, enrichment failed 3x.
   - ATM now skips expired proposals (filtered in query + belt-and-suspenders check).
   - Batched Telegram: one message per cycle listing all expired proposals.
   - ARM #115 and BCS #122 backfilled with 6 evaluation counts from decision log.

4. ~~**Fix quote endpoint fallback**~~ **DONE 2026-05-23**
   - Root cause: adapter was hitting `paper-api.alpaca.markets/v2/stocks/...` (trading API)
     instead of `data.alpaca.markets/v2/stocks/...` (data API). Trading API doesn't serve
     market data — always returned 404.
   - Fix: added `DATA_BASE_URL` constant, `_data_get()` method, and rewired quote fetch to
     use `data.alpaca.markets/v2/stocks/{symbol}/quotes/latest` as primary (bid/ask mid-price).
   - Fallback chain: data API quotes → data API bars → yfinance → validated_price.
   - Smoke test: SPY, NWG, NVDA, BCS, ARM all return real quotes, no fallbacks.
   - Added startup smoke test (SPY quote on adapter init) to detect data API issues early.

### P2 — Housekeeping

5. **Fix audit_log schema** — add missing `event` column or update the INSERT query.

6. **Clean up duplicate paper_trades** — pending trades #28, #29, #30, #32 are orphaned
   stubs. Either reconcile them with the actual open trades or mark them as superseded.

---

*Investigation performed: 2026-05-22 PM*
*ATM mode: active (not modified during investigation)*
*IRON RULE: ATM state verified at start — mode=active, set by dashboard at 11:25*
