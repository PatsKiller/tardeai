# V3 Journal Field Completeness — Exact Backfill (2026-06-06)

**Status:** Complete. Exact-only backfill of journal/analytics metadata. No execution mutation.

## Crawler finding

The v3 Journal Playwright audit flagged low field completeness on closed trades (`post_analyzed`,
`close_reason`, `broker_id`, `catalyst`, `MFE/MAE`). These are journal/analytics metadata columns on
`paper_trades` (the canonical paper journal underlying `trade_instances`).

## Approach

`scripts/backfill_journal_trade_fields.py` — **exact sources only, no fuzzy inference.** Unknown
stays NULL with a data-quality flag. Writes only non-execution journal-metadata columns; the running
Hermes drain neither reads nor writes these columns (verified before applying).

| Field | Exact source |
|-------|--------------|
| `broker`, `execution_broker` | `trade_instances.execution_broker` (exact `source_table`/`source_trade_id` linkage) |
| `close_reason` | `paper_trades.exit_reason` (same row, only when NULL) |
| `post_trade_analyzed` | existence of a row in `trade_llm_reviews` / `journal_trade_reviews` / `trade_thesis_reviews` (by `paper_trade_id`) |
| `max_favorable_excursion` / `max_adverse_excursion` | `trade_mfe_analysis` bar values (only when NULL) |
| `catalyst_at_entry` | exact proposal/candidate catalyst only — **left NULL** where no exact single source |

`scripts/validate_journal_field_completeness.py` reports before/after (read-only).

## Before / after (closed paper trades, n=34)

| Field | Before | After |
|-------|--------|-------|
| `post_analyzed` | 11.8% (4/34) | **20.6% (7/34)** |
| `close_reason` | 47.1% (16/34) | **100% (34/34)** |
| `broker_id` (broker/execution_broker) | per-column gaps (18/34, 28/34) | **100% (34/34 each)** |
| `catalyst` | 52.9% (18/34) | 52.9% (18/34) — no exact source, left NULL (honest) |
| `MFE` | 100% | 100% |
| `MAE` | 100% | 100% |

Backfill touched 33 trades: `broker 16`, `execution_broker 6`, `close_reason 18`,
`post_trade_analyzed 3`. `post_analyzed` only rises to the count of trades that genuinely have a
review — the remaining trades have no review and are correctly left `false` (no hallucination).
`catalyst` has no exact upstream link for the missing rows, so it is intentionally not inflated.

## Remaining gaps (honest)

- `post_analyzed` is capped by actual review coverage; raising it requires generating reviews, not
  metadata edits.
- `catalyst_at_entry` needs an exact proposal/candidate linkage to backfill; fuzzy inference is
  prohibited, so it stays NULL.

## Safety

No status/stop/order/take-profit/strategy mutation. `ALPACA_MODE=paper`,
`LLM_DISABLE_LIVE_EXECUTION=true`. Hermes drain untouched.
