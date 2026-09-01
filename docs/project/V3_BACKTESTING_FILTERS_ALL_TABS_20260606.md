# v3 Backtesting — Account/Strategy Filters Apply to All Tabs (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T11:16:21-04:00
Measured at: efcc51365 / not measured

## Issue
The Backtesting filter bar (date/broker/account/strategy/run-type) renders above the tab menu and worked
for Trades/Missed/Results/Runs/Optimization, but several tabs fetched their data WITHOUT the filter
querystring, so account/strategy selections did nothing for them: Entry Quality, AI Trade Eval,
LLM Review Coverage.

## Fix
- Frontend (`BacktestPanel.tsx`): added the filter `qs` (date+broker+account+strategy+run_type) to the
  previously-unfiltered fetches — backtest-summary, backtest-analytics, trade-evaluations, llm-review-status.
- Registry dispatch (`api_v2.py`): introspects handler arity so query-accepting registry handlers receive
  the query (0-arg handlers unchanged).
- **Entry Quality** (`/journal/backtest-summary` + `/journal/backtest-analytics`): added ?strategy=&account=
  filter via `trade_backtest_results.trade_instance_id -> trade_instances` (strategy_id, execution_account).
  Verified: total 91 → 26 with account=alpaca_paper.
- **AI Trade Eval** (`/backtesting/trade-evaluations`): added strategy_id LIKE + account filter on
  trade_llm_reviews (rows + aggregate).

## Honest data limitations (filter mechanism correct; upstream data sparse)
- AI Trade Eval: the 51 structured_backtest_eval rows currently have NULL strategy_id AND account (the
  structured-eval writer doesn't populate them) → account/strategy filtering returns few/zero there until
  the writer stamps them (follow-up: backfill strategy_id/account from source strategy_backtest_trades).
- backtest-analytics by_type/left_by_type join trade_closed (Schwab ledger) → account=alpaca_paper yields
  0 by_type (paper trades aren't in trade_closed); rsi_hist still filters. Expected.
- LLM Review Coverage: frontend passes the filter; the tab is pipeline-health (infra/parser/retryable
  counts + Ollama health) and its aggregate counts remain global by design (per-strategy infra-failure
  counts aren't meaningful). Per-row provenance already shows source.

## Safety
ALPACA_MODE=paper, live disabled. Read-only analytics endpoints + frontend only. No broker/order/proposal/
GO-WAIT/strategy/live/Phase-205 changes. (Unrelated config/strategies/*.yaml daily-timestamp churn left
unstaged.)
