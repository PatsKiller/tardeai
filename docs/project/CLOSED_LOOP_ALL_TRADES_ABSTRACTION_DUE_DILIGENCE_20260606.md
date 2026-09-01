# Closed-Loop All-Trades Abstraction — Due Diligence (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-05T23:46:56-04:00
Measured at: efcc51365 / not measured

## Root concern (operator/CIO)
Steps 1–7 closed real gaps but centered on `paper_trades`. Names like `paper_trade_id`,
`paper_trade_edge_comparison`, `closed_paper_trade`, `paper_trades.trade_key` must NOT become canonical.
The canonical learning loop must be broker/account-neutral: Broker → Account → Trade → Monitoring →
Journal → Backtest → Hermes → Learning → Shadow → Future candidate.

## Paper-specific surface found
- `paper_trades.trade_key`, `paper_trades.signal_id/source_signal_id/execution_*` (Steps 1/3)
- `journal_trade_reviews.paper_trade_id`, `trade_backtest_results.paper_trade_id`,
  `paper_trade_edge_comparison.paper_trade_id`, `candidate_shadow_efficacy.paper_trade_id`,
  `proposal_outcome_chain.paper_trade_id`
- `hermes_research_intelligence.related_trade_id` = `paper_trades.id` (Step 2)
- Hermes targeting tier `closed_paper_trade` keyed to `paper_trades.id` (Step 7)
- ~40 scripts reference paper-specific keys.

## Existing ledgers (backfill sources)
- `paper_trades` (51) — Alpaca paper; richest lineage (signal/execution/trade_key from Steps 1/3).
- `trades` (353) — ALREADY multi-broker: schwab_rollover_ira 187, schwab_taxable 102, alpaca_paper 51,
  schwab_roth_ira 13; cols broker/account/strategy_id/signal_id/source_table/status (open 152, closed 201).
  The alpaca_paper rows mirror paper_trades → exclude them to avoid double-count.
- `trade_closed` (119) — view, schwab closed only.
- Fidelity: NO closed-trade rows in `trades` yet (holdings-only / FCNTX) → 0 fidelity instances now (honest).

## Canonical plan
`trade_instances` (broker/account-neutral) backfilled from:
- paper_trades → source_system=alpaca_paper, source_table=paper_trades (51)
- trades WHERE account NOT LIKE alpaca% → source_system=schwab_import, source_table=trades (~302)
lineage_confidence: exact (proposal-linked paper), imported_broker_statement (schwab), missing otherwise.
Add `trade_instance_id` (additive) to: hermes_research_intelligence, journal_trade_reviews,
trade_backtest_results, paper_trade_edge_comparison, candidate_shadow_efficacy, proposal_outcome_chain.
Keep `paper_trade_id`/`related_trade_id` as legacy-compat. New canonical table `trade_edge_comparison`
populated from `paper_trade_edge_comparison` + future imported trades.
Hermes targeting: `closed_paper_trade` → `closed_trade_needing_reflection` (queries trade_instances,
all sources, sublabel by source_system).

## Safety
Additive schema only; paper loop keeps working; no broker writes, no order/GO-WAIT/strategy/live/Phase-205.
