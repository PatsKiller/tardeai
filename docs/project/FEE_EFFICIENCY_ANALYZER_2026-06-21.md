# Fee / Cost-Efficiency Analyzer (2026-06-21)

## Why
Operator: *"this is the type of stuff that should be autonomous in reports and rotation — Contrafund
expensive compared to SCHD cost and returns."* Trading commissions were tracked (journal net P&L) but the
real ongoing cost — fund/ETF expense ratios — was unaggregated and invisible. This makes fee drag
first-class and surfaces "expensive fund vs cheaper alternative that's matching/beating it" automatically.

## What it does
`scripts/fee_efficiency_analyzer.py`:
- Joins holdings (real accounts) to `symbol_profiles` (instrument_type, expense_ratio, ytd_return_pct,
  dividend_yield_pct).
- Computes **annual $ fee drag** per holding (expense_ratio × market_value), **total**, and **by account**.
- Flags **fee-inefficient** holdings (ER ≥ 0.20%, or an active fund with unknown/>0.05% ratio) and contrasts
  each against cheaper ETFs the household already owns (SCHD/SCHG) — cost + YTD return.
- Honest about gaps: stocks have no ER; a fund with a NULL ratio is flagged **"verify"**, never assumed free.
- `emit_findings()` writes one info `alert_events` row per flagged holding (`source_script='fee_efficiency'`)
  so Reports/Intelligence surface them autonomously.

## First run (2026-06-21)
- **Total portfolio fees: ~$2,279/yr** (rollover IRA $2,036, taxable $143, fidelity IRA $100, roth $0.58).
- **FCNTX**: ~$1,597/yr (~$1,542 excess vs a broad index); SCHD returned +14.9% YTD vs FCNTX +10.5% — cheaper
  AND ahead; in an IRA, so switching is tax-free. ⚠️ FCNTX's stored 1.47% ER looks high (published ~0.4–0.55%)
  — `symbol_profiles` data should be validated; the dollar figure scales with it.
- Also flagged: JEPI (0.35%), ARKQ/ARKG (0.75%), XAR (0.35%), DIV (0.45%), AMANX (ER unknown → verify).

## Surfaces
- `GET /api/v2/fee-efficiency` — full analysis (positions, findings, totals).
- Weekly cron (Mon 07:25, after the 07:15 perf refresh) runs `--emit` → findings into Reports.

## Remaining
- Rotation integration: turn a flagged finding into a rotation candidate (e.g., FCNTX→SCHD swap proposal,
  manual-review). Engine output is ready to feed it.
- Card/page surface (fee panel) + validating expense ratios against a reliable source (the FCNTX 1.47%).
