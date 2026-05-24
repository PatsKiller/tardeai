# Q-1C + AI-BRIEF-1B — Quote Writeback and Brief Freshness

**Status:** COMPLETE

## Q-1C: Quote Writeback Fix

**Root cause:** Q-1 refreshed quotes via `get_best_quote()` and `store_quote()` but never wrote to `paper_trade_proposals.last_price_checked_at`. The proposals API checks that field for UNKNOWN_QUOTE verdict.

**Fix:** Added UPDATE to `paper_trade_proposals` after successful quote fetch — writes `last_price_checked_at`, `last_price_source`, `current_price`.

**Before/After:**
| Field | Before | After |
|-------|--------|-------|
| unknown_quote_count | 2 | **0** |
| INGM price_checked | Never | 2026-05-20T10:15:01 |
| INGM source | unknown | alpaca |
| INGM price | unknown | $25.565 |
| CODX price_checked | Never | 2026-05-20T10:15:02 |
| CODX source | unknown | alpaca |
| CODX price | unknown | $2.07 |

## AI-BRIEF-1B: Brief Context Date Fix

**Root cause:** Executive summary prompt had no current date. LLM produced text referencing old context dates.

**Fix:** Added `TODAY'S DATE: {date}` to both the base context prompt and the executive summary prompt, with explicit instruction to not reference old dates as current.
