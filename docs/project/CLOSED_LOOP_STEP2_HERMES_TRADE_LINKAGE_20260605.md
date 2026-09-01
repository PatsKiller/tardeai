# Closed-Loop Step 2 — Hermes Trade-Reflection Linkage (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T22:10:20-04:00
Measured at: efcc51365 / not measured

## Broken join fixed
`hermes_research_intelligence.related_trade_id / related_proposal_id = 0%` (0/1170) — Hermes reflection
orphaned from trades/proposals.

## Change (additive, read-only research path)
- `hermes_autonomous_loop.get_ticker_targets()` now resolves, per target, `related_trade_id`
  (paper_trades.id; for closed_trade src, latest paper_trade for the symbol) and `related_proposal_id`
  (open paper_trade_proposals.id) — paper loop only; live Schwab held positions have no paper trade so the
  link stays NULL (never fabricated).
- `run_ticker_challenger()` stamps `output.symbol`, `output.related_trade_id`, `output.related_proposal_id`
  before validate/insert, so new `ticker_thesis_challenge` / `trade_reflection` research is lineage-linked
  (`build_insert` already allows these columns).

## Backfill (conservative; `scripts/backfill_hermes_trade_links.py`)
Only TRADE-REFLECTION research types (ticker_thesis_challenge, trade_reflection), only where the symbol
maps 1:1 to a paper_trade / open proposal; never overwrites a non-NULL link; no symbol/date fuzzy guess.
- considered 103 reflection rows · related_trade_id 0→2 · related_proposal_id 0→2 ·
  skipped_ambiguous 14 · skipped_no_match 85.
The low backfill count is honest: most historical reflection symbols are live Schwab holdings or
candidates with no unique paper_trade. The **forward** write-path fix is the structural closure — future
paper-loop reflection research is stamped at write time.

## Validation / safety
get_ticker_targets returns related ids (held Schwab → NULL, correct). No broker order calls; ALPACA_MODE=
paper; LLM live disabled. No GO/WAIT, strategy, proposal, order, or Phase-205 changes.

## Next step
Step 3: unify the keyspace — add paper_trade_id to journal_trade_reviews + trade_backtest_results (or a
trade_key on paper_trades) so journal/backtest cover the paper loop, not only the Schwab import.
