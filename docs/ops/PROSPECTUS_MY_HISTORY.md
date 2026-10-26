# Ticker Prospectus — My history and fund gaps

```
Status:      DRAFT
as_of:       2026-10-26T23:00:00Z
Measured at: branch feat/prospectus-my-history-20261026 off origin/main d326dab2c (not live)
```

Operator 2026-10-26: "It's showing that I hold this. What is my average cost? Have I won or lost, P&L? What were the
catalysts that hit? Should we include that in stuff I actually own? If I owned it multiple round trips, should that be
analyzed? This is a customized prospectus for me, not for the public." And for XAR: "it's missing some data towards
the bottom".

## The `my_history` block

Built for every holding and for any symbol ever traded (`scope`: `held`, `previously_traded`, `never_traded`).
Code: `scripts/lib/prospectus/my_history.py`. It is placed right after the verdict tiles in the HTML, PDF and DOCX and
on the Prospectus page (`MyHistoryBlock.tsx`).

| Part | Source |
|---|---|
| Open lots by account name: shares, average cost, unrealized $ and % | position store through `lib.portfolio_positions` (same mark as the Position tile) |
| Lot dates, days held, short or long term | FIFO over `trade_transactions` buys and sells. When the FIFO does not match the store's shares (transfers, older lots) the row says `unreconciled` and no date is guessed |
| Round trips: entry and exit, shares, hold, realized $ and %, R | the Rec Intelligence "Purchased → Sold Lifecycle", reused unchanged: `recommendation_intelligence_engine.lifecycle_performance(symbol=…)` |
| Totals: lifetime realized, wins and losses, average win and loss, best and worst | derived from those trips |
| Why you got in | Rec Intelligence origin, plus every discovery source in `rec_ticker_attribution` recorded before the entry date. The earliest rationale is the thesis at entry |
| What happened while held | typed `catalyst_events` (earnings flagged), days with a move of 8% or more, and filled stops (`stop_last_known`), each with the day-of and 5-session reaction from house closes |
| Lessons | deterministic statistics: payoff ratio, entry position in the 52-week range vs result, hold length vs result, stop-out rate, re-entries after a loss. Journal lessons from `journal_trade_reviews` |
| Tax flags | taxable or tax-advantaged by account (`wash_sale.account_taxable`). For a loss sale in a taxable account, the 61-day replacement test (`wash_sale.replacement_purchases`). The window open today comes from `wash_sale.symbol_window` |

Every number is a fact with an F-id (`kind: my_history`, capped at 160 per prospectus; the cap is named in `gaps`).
The writer is asked for `notes.my_history.{summary, lessons}`. Both are guarded like the prose sections: a sentence
with an ungrounded number, or one that sizes, orders or stops, is dropped and logged.

Accounts appear by name only (`account_display.account_label`). Tests use synthetic tickers and accounts.

## Fund gaps

Code: `scripts/lib/prospectus/etf_profile.py`; map: `config/prospectus_etf_categories.json`.

- **Category → sector ETF and peer funds.** A pinned symbol wins. Otherwise the first category keyword found in the
  fund name, the index description or the look-through asset class is used. XAR maps to Aerospace & Defense, sector
  Industrials, XLI, with ITA and PPA as peer funds. Relative performance is rebuilt with these. Facts already written
  for the vendor-sector ETF keep their ids; their label marks them as the vendor sector.
- **Fund profile** (`blocks.fund_profile`): expense ratio, distribution yield and history, top holdings and weights,
  analyst look-through. AUM is not in any house store, and the block says so.
- **House scenarios** when there is no analyst target: a ±1σ 12-month lognormal band from the 1-year volatility of
  daily closes. The method is labelled, the probabilities are not assigned, and the footer says it is not an order.
- **Macro effect column**: OLS of the name's returns on changes in the 10-year yield (daily), CPI (monthly) and VIX
  (daily), over up to two years of house closes against FRED. A fit is "not reliable" below 120 daily points, 18
  monthly points or |t| 2. The effect is the sign of beta times the series' 3-month change.

## Hooks

`scripts/lib/prospectus/extensions.py` is the single entry point:

- `domains.full_assemble` calls `attach`
- `generate.build_prompt` calls `prompt_lines`
- `generate.write` calls `finalize`
- `render.html` and `render.docx` call `top_tables` and `bottom_tables`

Every step is wrapped. A failure becomes a recorded gap and never fails a prospectus.

## Tests

`tests/test_prospectus_my_history_20261026.py` (CI gate `prospectus_my_history_20261026`) and
`apps/command-center-v3/e2e/prospectus-my-history.spec.ts` (1440, 412 and 390, every API call mocked).
