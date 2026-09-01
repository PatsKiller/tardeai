# v3 Missed-Opportunities Dedupe + Verdict Fix (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T10:16:08-04:00
Measured at: efcc51365 / not measured

## Root cause
- endpoint: `/api/v2/backtesting/missed-opportunities`
- bad join: `paper_trade_proposals ptp LEFT JOIN strategy_backtest_trades sbt ON symbol + strategy LIKE +
  |signal_time-created_at|<72h` — a one-to-many FAN-OUT (one proposal matches many backtest-run sim rows).
  `total_missed = len(rows)` counted fan-out rows, and `LIMIT 50` truncated the raw set. ARM/SNOW/MRVL/BLBD
  appeared repeated = one proposal × N sims.
- old UI: derived outcome from `simulated_pnl` sign only (no verdict field); cards counted fan-out rows.

## Implementation
- dedupe key: canonical **proposal_id** (PK, always present → dedupe_confidence=exact); raw rows grouped
  in Python, never `symbol+72h` identity. Same-symbol DIFFERENT proposals stay distinct (e.g. ARM ×2 props).
- verdict field: backend `sim_outcome_verdict` ∈ WIN|LOSS|BREAKEVEN|MIXED|NO_DATA, priority exit_reason
  (target→WIN / stop→LOSS) → sim_r → sim_pnl → NO_DATA; `sim_verdict_source` per row.
- mixed handling: if a proposal's sim rows disagree → **MIXED** with win_count/loss_count/breakeven_count
  (conflict shown, not hidden; not counted as clean win/lose).
- raw diagnostics: duplicate_count, raw_sim_row_ids, summary{raw_rows,deduped_rows,duplicates_removed}.

## Before → after
- raw rows: 1461 · deduped rows: **168** · duplicates removed: **1293**
- would_win 9 · would_lose 17 · breakeven 0 · **mixed 99** · no_data 43 · P&L left on table $5.58
- examples collapsed: ARM → 2 distinct proposals · SNOW → 1 · MRVL → 1 · BLBD → 5 (each one row/proposal)
- The old "21 win / 29 lose" was unreliable: 99/168 proposals are MIXED (sim runs disagree) — now visible.

## Frontend (BacktestPanel.tsx, Missed tab)
- summary cards now: Would win / Would lose / **Mixed-review** / No-sim-data / P&L left on table (from deduped summary).
- table columns added: Verdict, Source, Dupes (`deduped ×N` badge when >1).
- diagnostics line: "Showing X distinct missed opportunities from Y raw simulations; Z duplicates collapsed."
- note replaced: "Outcome supplied by backend sim_outcome_verdict; source shown per row. MIXED = sim runs disagree."

## Validation — 16/16 PASS (scripts/validate_missed_opportunities_dedup.py)
strict JSON · key on every row · no duplicate keys · raw>=deduped · duplicates_removed>0 · verdict counts
sum to deduped · verdict+source on every row · ARM/SNOW/MRVL/BLBD one-row-per-proposal · MIXED exposes counts.

## Safety
ALPACA_MODE=paper, live disabled. Analytics endpoint/frontend/validation/docs only. No broker/order/stop/
proposal/GO-WAIT/strategy/live/Phase-205 changes; executor + approval logic untouched.
