# Portfolio reconciliation — Command Center vs broker (2026-10-05)

Operator 2026-10-05, after thinkorswim showed SPCX $171.09 / P/L Open +$2,122.87 while the Command Center
showed $136.46 / −$8,272: *"This discrepancy is real, and we need to validate that everything in the command
center and the portfolio is correct … do the same thing for every current holding, everything that it has
sold. I need this to be the source of truth."*

Every number below is reproducible with `scripts/portfolio_reconcile.py` (read-only). Before = the served
release (c91fa6a32) at 2026-10-05T17:24:08; after = this branch's code (`--inprocess`) on the same data at
2026-10-05T17:19:05.

## Sources of truth used

| Fact | Broker truth | Evidence |
|---|---|---|
| Open Schwab positions (qty, average price, market value, open P/L) | `schwab_positions_live`, snapshot 2026-10-05 16:33:01.068588-04:00 (written by the read-only position sync) | 26 rows; SPCX 300 @ $164.033767 avg, MV $51,297, open P/L $2,086.87 — matches thinkorswim's P/L Open $2,122.87 at $171.09 |
| Price now | Command Center data broker quote (`market_quotes` via `/api/v2/schwab/quotes`) | as_of 2026-10-05 16:45:02 ET |
| Buys and sells | `trade_transactions` where `import_source='schwab_api'` | 170 Schwab sells, 2025-07-29 → 2026-10-05 |
| Closed trades | `trade_closed` (rebuilt each run by `schwab_journal_builder.py` from `schwab_round_trips`) | 174 rows |

**Not verifiable here (labelled, not guessed):** cash balances (no broker balance snapshot in the read
paths); Fidelity Rollover IRA (no broker API — ACATS to Schwab 2026-07-16, SnapTrade activity only; the
portfolio total already excludes it); moomoo and Alpaca (read-only syncs, no position ledger table; moomoo
NVDA 0.133 sh is dust); the cost basis of shares that arrived by transfer (the Schwab ledger records
transfers at $0 — Schwab's Realized Gain/Loss export is the authority). thinkorswim's "Avg Price $148.37"
for SPCX does not match the API average ($164.03) that reproduces its own P/L Open; unexplained, flagged.

## What was wrong — root causes

1. **Frozen price field (open positions).** `schwab_position_sync._build_account_rows` rebuilds each row
   from `dict(prior)` and refreshes `price`; nothing refreshed `current_price`, so it froze. The holdings API
   (`api_v2.portfolio_holdings`) priced Schwab rows `current_price or price` **ahead of the data-broker
   quote**, labelled the number `schwab`, and stamped it with the live quote's timestamp. 15 Schwab
   positions were mispriced by −20.4% to +15.9%; the Portfolio table, the symbol card (MARKET VALUE,
   UNREALIZED) and every consumer of the holdings API showed them. The header total and the stop panel were
   right (they use other fields).
2. **Stale cost anchors scaled to today's shares.** `cost_basis_anchors` (an April-21 Schwab export) were
   multiplied by today's share count when the share count no longer matched — after sells and re-buys the
   result was neither the broker's basis nor the anchor's (SCHD rollover $125,341.52 vs broker $132,173.07;
   SCHG $66,998.40 vs $72,735.00; V 0.7963 sh $63.38 vs $277.89).
3. **accounts-live mislabelled fields.** `/api/v2/schwab/accounts-live` serves holdings.json (not Schwab)
   and returned the TOTAL cost basis as `avg_price` (SPCX 49,210.13) and the frozen `current_price`.
4. **Analyst upside measured against the snapshot price.** "+105.7% upside" used the Yahoo snapshot price
   (≈$115.07); against $171.34 the $236.71 mean target is +38.2%.
5. **Probe rows counted as trades.** Two `trade_closed` rows on accounts `health` / `journal_check`
   (2026-08-07; no writer left in the code) — TRADING showed 167 trades (166 real), REALIZED 173 (172 real), +$0.01.
6. **Sells left out of REALIZED without disclosure.** 33 sells (proceeds $901,194.23)
   have no basis in the broker ledger — mostly shares that arrived by the 2025-07 and 2026-07 transfers — and
   the builder correctly refuses to invent P&L for them, but REALIZED never said they were missing.
7. **Close dated by order time.** An after-hours mutual-fund order (FCNTX, placed 2026-07-13 21:05 ET,
   traded 2026-07-14) was closed on 07-13.

## Totals

| Measure | Before | After | Broker / check |
|---|---:|---:|---:|
| Portfolio table, all accounts | $1,274,616.47 | $1,270,876.09 | header total $1,271,085.05 (computed from the fresh `market_value`) |
| Schwab non-cash positions | $414,015.50 | $410,275.12 | broker snapshot $410,396.90 (16:33) — Δ after = dust hidden (<$50, ≈$84) + quote time |
| Net value misstatement on mispriced Schwab rows | $3,740.38 (gross: SPCX −$13,952; SCHD +$9,761; XAR +$3,669; XLB +$2,238; V +$1,715 …) | $0.00 | — |
| REALIZED (all closed) | $158,876.56 · 173 trades | $158,876.55 · 172 trades | plus 33 sells, proceeds $901,194.23, basis unknown — now disclosed |
| TRADING (day + swing) | $44,316.92 · 167 trades | $44,316.91 · 166 trades | builder dry run: 166 active trips |

## Open positions — every Schwab holding

| Account | Symbol | Broker qty | Broker cost | Broker MV (16:33) | CC price before (source) | CC value before | Quote | CC value after | CC cost after | P&L after | Before | After |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| schwab_rollover_ira | 543354104 | 3000.0 | $4,762.95 | $0.00 | — (—) | — | — | — | — | — | delisted CUSIP position (broker value $0.00) — not shown in CC by design | delisted CUSIP position (broker value $0.00) — not shown in CC by design |
| schwab_rollover_ira | 628518102 | 125.0 | $0.00 | $0.00 | — (—) | — | — | — | — | — | delisted CUSIP position (broker value $0.00) — not shown in CC by design | delisted CUSIP position (broker value $0.00) — not shown in CC by design |
| schwab_rollover_ira | AMANX | 63.366 | $1,229.80 | $5,019.22 | $81.50 (schwab) | $5,164.33 | $79.21 | $5,019.22 | $1,215.90 | $3,803.32 | COST: CC $1,215.90 vs broker $1,229.80 (Δ $-13.90); PRICE: CC $81.50 (schwab) vs data-broker quote $79.21 (+2.9%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $5,164.33 vs shares×quote $5,019.22 (Δ $145.11) | COST: CC $1,215.90 vs broker $1,229.80 (Δ $-13.90) |
| schwab_rollover_ira | AXTI | 400.0 | $32,430.95 | $34,708.00 | $86.71 (schwab) | $34,684.00 | $86.62 | $34,648.00 | $32,430.95 | $2,217.05 | ok | ok |
| schwab_rollover_ira | BND | 0.776 | $56.21 | $54.23 | $72.54 (schwab) | $56.29 | $69.88 | $54.23 | $55.83 | $-1.60 | COST: CC $57.60 vs broker $56.21 (Δ $1.39); PRICE: CC $72.54 (schwab) vs data-broker quote $69.88 (+3.8%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $56.29 vs shares×quote $54.23 (Δ $2.06) | ok |
| schwab_rollover_ira | JEPI | 0.394 | $22.64 | $22.18 | — (—) | — | $56.27 | — | — | — | dust (<$50) — in holdings.json, hidden from the CC table by design | dust (<$50) — in holdings.json, hidden from the CC table by design |
| schwab_rollover_ira | SCHD | 4000.2529 | $132,173.07 | $130,888.27 | $35.14 (schwab) | $140,568.89 | $32.70 | $130,808.27 | $132,173.07 | $-1,364.80 | COST: CC $125,341.52 vs broker $132,173.07 (Δ $-6,831.55); PRICE: CC $35.14 (schwab) vs data-broker quote $32.70 (+7.5%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $140,568.89 vs shares×quote $130,808.27 (Δ $9,760.62) | ok |
| schwab_rollover_ira | SCHG | 2000.0 | $72,735.00 | $73,440.00 | $36.72 (schwab) | $73,440.00 | $36.71 | $73,420.00 | $72,735.00 | $685.00 | COST: CC $66,998.40 vs broker $72,735.00 (Δ $-5,736.60) | ok |
| schwab_rollover_ira | SPCX | 300.0 | $49,210.13 | $51,297.00 | $136.46 (schwab) | $40,938.00 | $171.34 | $51,402.00 | $49,210.13 | $2,191.87 | PRICE: CC $136.46 (schwab) vs data-broker quote $171.34 (-20.4%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $40,938.00 vs shares×quote $51,402.00 (Δ $-10,464.00) | ok |
| schwab_rollover_ira | SRNE | 1000.0 | $13,177.95 | $0.80 | — (—) | — | $0.30 | — | — | — | dust (<$50) — in holdings.json, hidden from the CC table by design | dust (<$50) — in holdings.json, hidden from the CC table by design |
| schwab_rollover_ira | V | 0.7963 | $277.89 | $294.40 | $382.85 (schwab) | $304.86 | $369.79 | $294.46 | $277.89 | $16.57 | COST: CC $63.38 vs broker $277.89 (Δ $-214.51); PRICE: CC $382.85 (schwab) vs data-broker quote $369.79 (+3.5%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $304.86 vs shares×quote $294.46 (Δ $10.40) | ok |
| schwab_rollover_ira | XAR | 100.0 | $28,238.00 | $23,128.00 | $267.70 (schwab) | $26,770.00 | $231.01 | $23,101.00 | $28,238.00 | $-5,137.00 | PRICE: CC $267.70 (schwab) vs data-broker quote $231.01 (+15.9%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $26,770.00 vs shares×quote $23,101.00 (Δ $3,669.00) | ok |
| schwab_rollover_ira | XLB | 506.3274 | $27,011.39 | $25,063.21 | $53.92 (schwab) | $27,301.17 | $49.50 | $25,063.21 | $26,799.14 | $-1,735.93 | COST: CC $26,799.14 vs broker $27,011.39 (Δ $-212.25); PRICE: CC $53.92 (schwab) vs data-broker quote $49.50 (+8.9%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $27,301.17 vs shares×quote $25,063.21 (Δ $2,237.96) | COST: CC $26,799.14 vs broker $27,011.39 (Δ $-212.25) |
| schwab_rollover_ira | XLI | 0.0443 | $7.98 | $7.54 | — (—) | — | $170.09 | — | — | — | dust (<$50) — in holdings.json, hidden from the CC table by design | dust (<$50) — in holdings.json, hidden from the CC table by design |
| schwab_roth_ira | V | 130.4985 | $40,125.75 | $48,246.60 | $382.85 (schwab) | $49,961.35 | $369.79 | $48,257.04 | $39,951.37 | $8,305.67 | COST: CC $39,951.37 vs broker $40,125.75 (Δ $-174.38); PRICE: CC $382.85 (schwab) vs data-broker quote $369.79 (+3.5%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $49,961.35 vs shares×quote $48,257.04 (Δ $1,704.31) | COST: CC $39,951.37 vs broker $40,125.75 (Δ $-174.38) |
| schwab_taxable | 12507E201 | 7.0 | $0.00 | $0.00 | — (—) | — | — | — | — | — | delisted CUSIP position (broker value $0.00) — not shown in CC by design | delisted CUSIP position (broker value $0.00) — not shown in CC by design |
| schwab_taxable | BAH | 9.0 | $698.44 | $617.58 | $74.87 (schwab) | $673.83 | $68.59 | $617.36 | $698.44 | $-81.09 | PRICE: CC $74.87 (schwab) vs data-broker quote $68.59 (+9.1%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $673.83 vs shares×quote $617.36 (Δ $56.48) | ok |
| schwab_taxable | CSWC | 3.594 | $86.25 | $84.71 | $25.35 (schwab) | $91.11 | $23.57 | $84.71 | $86.25 | $-1.54 | COST: CC $84.83 vs broker $86.25 (Δ $-1.42); PRICE: CC $25.35 (schwab) vs data-broker quote $23.57 (+7.6%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $91.11 vs shares×quote $84.71 (Δ $6.40) | ok |
| schwab_taxable | DIV | 4.6535 | $91.84 | $88.18 | $19.93 (schwab) | $92.74 | $18.94 | $88.14 | $91.05 | $-2.91 | PRICE: CC $19.93 (schwab) vs data-broker quote $18.94 (+5.2%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $92.74 vs shares×quote $88.14 (Δ $4.60) | ok |
| schwab_taxable | LDOS | 0.2274 | $40.26 | $27.16 | — (—) | — | $119.27 | — | — | — | dust (<$50) — in holdings.json, hidden from the CC table by design | dust (<$50) — in holdings.json, hidden from the CC table by design |
| schwab_taxable | NOC | 0.2328 | $175.68 | $110.84 | $551.65 (schwab) | $128.42 | $475.99 | $110.81 | $175.11 | $-64.30 | PRICE: CC $551.65 (schwab) vs data-broker quote $475.99 (+15.9%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $128.42 vs shares×quote $110.81 (Δ $17.61) | ok |
| schwab_taxable | PFLT | 12.1461 | $121.03 | $82.35 | $7.45 (schwab) | $89.45 | $6.78 | $81.41 | $111.66 | $-30.25 | QTY: CC 12.0071 vs broker 12.1461; COST: CC $111.66 vs broker $121.03 (Δ $-9.37); PRICE: CC $7.45 (schwab) vs data-broker quote $6.78 (+9.9%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $89.45 vs shares×quote $81.41 (Δ $8.04) | QTY: CC 12.0071 vs broker 12.1461; COST: CC $111.66 vs broker $121.03 (Δ $-9.37) |
| schwab_taxable | RTX | 0.4952 | $102.70 | $91.28 | $212.16 (schwab) | $105.06 | $184.28 | $91.26 | $102.34 | $-11.08 | PRICE: CC $212.16 (schwab) vs data-broker quote $184.28 (+15.1%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $105.06 vs shares×quote $91.26 (Δ $13.80) | ok |
| schwab_taxable | SCHD | 0.5478 | $17.50 | $17.92 | — (—) | — | $32.70 | — | — | — | dust (<$50) — in holdings.json, hidden from the CC table by design | dust (<$50) — in holdings.json, hidden from the CC table by design |
| schwab_taxable | SCHG | 0.2297 | $7.01 | $8.43 | — (—) | — | $36.71 | — | — | — | dust (<$50) — in holdings.json, hidden from the CC table by design | dust (<$50) — in holdings.json, hidden from the CC table by design |
| schwab_taxable | SPCX | 100.0 | $18,173.00 | $17,099.00 | $136.46 (schwab) | $13,646.00 | $171.34 | $17,134.00 | $18,173.00 | $-1,039.00 | PRICE: CC $136.46 (schwab) vs data-broker quote $171.34 (-20.4%) — came from stored holdings.json `current_price` (never refreshed); VALUE: CC $13,646.00 vs shares×quote $17,134.00 (Δ $-3,488.00) | ok |

Remaining after the fix — an operator decision (AGENTS.md §0 rule 5: both bases are now shown, nothing is
picked automatically): AMANX $1,215.90 vs broker $1,229.80; XLB $26,799.14 vs $27,011.39; V (Roth)
$39,951.37 vs $40,125.75; PFLT $111.66 vs $121.03. In each, the April anchor covers the original lots but not
the dividend-reinvested shares bought since; PFLT also has a pending DRIP share-drift approval (12.0071 vs
broker 12.1461). The holdings API now returns `cost_basis_broker` and `cost_basis_note` beside `cost_basis`.

## Closed positions — every Schwab sale

139 account×symbol×day sale groups compared with the broker ledger (quantity, net proceeds, FIFO basis from broker buys). Groups that match are omitted; every exception is listed.

| Account | Symbol | Date | Sold qty | Broker net | In REALIZED | Left out (basis unknown) | Finding |
|---|---|---|---:|---:|---|---|---|
| schwab_rollover_ira | ADBE | 2026-02-12 | 13.0 | $3,358.68 | 4.0 sh · P&L $-1,030.56 | 9.0 sh · $2,325.24 | PARTIAL_BASIS_UNKNOWN: 9 of 13 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | AMAGX | 2025-08-28 | 72.456 | $6,213.83 | — | 72.456 sh · $6,213.83 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | AMC | 2026-02-12 | 21.0 | $26.67 | — | 21.0 sh · $26.67 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | ANET | 2026-07-27 | 200.0 | $33,361.83 | — | 200.0 sh · $33,362.56 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | ARKX | 2026-09-14 | 1000.0 | $31,248.78 | — | 1000.0 sh · $31,249.60 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | BND | 2026-08-25 | 375.0 | $27,198.12 | 375.0 sh · P&L $-450.36 | — | BASIS: closed cost $27,648.48 vs FIFO from broker buys $27,711.92 (P&L Δ $63.44) |
| schwab_rollover_ira | BRO | 2025-07-29 | 200.0 | $19,223.97 | 47.0 sh · P&L $-377.89 | 153.0 sh · $14,706.36 | PARTIAL_BASIS_UNKNOWN: 153 of 200 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | CSCO | 2026-07-28 | 100.0 | $11,178.75 | — | 100.0 sh · $11,179.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | DIVI | 2026-08-25 | 1000.0 | $44,678.88 | — | 1000.0 sh · $44,680.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | DXCM | 2026-08-25 | 225.0 | $20,380.04 | — | 225.0 sh · $20,380.50 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | FCNTX | 2026-07-13 | — | — | 182.096 sh · P&L $461.15 | — | DATE: closed on 2026-07-13 but the broker trade date is 2026-07-14 (order time used instead of trade date) |
| schwab_rollover_ira | FCNTX | 2026-07-14 | 4034.942 | $107,023.01 | — | 3852.846 sh · $102,216.00 | MISSING_CLOSE: broker sell has no closed record |
| schwab_rollover_ira | FSELX | 2025-08-22 | 109.298 | $4,028.72 | — | 109.298 sh · $4,028.72 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | FSPTX | 2025-08-28 | 467.039 | $19,069.20 | — | 467.039 sh · $19,069.20 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | IPM | 2026-02-12 | 24.0 | $40.32 | — | 24.0 sh · $40.32 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | JEPQ | 2026-07-23 | 1355.0 | $79,062.36 | 355.0 sh · P&L $-662.58 | 1000.0 sh · $58,350.00 | PARTIAL_BASIS_UNKNOWN: 1000 of 1355 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | LASE | 2025-09-18 | 500.0 | $2,199.92 | — | 500.0 sh · $2,200.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | QCOM | 2026-08-25 | 55.0 | $8,818.51 | — | 55.0 sh · $8,818.70 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | SCHD | 2026-08-25 | 6155.0 | $215,911.75 | 4155.251 sh · P&L $16,767.71 | 1999.749 sh · $70,151.19 | PARTIAL_BASIS_UNKNOWN: 1999.75 of 6155 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | SCHG | 2026-07-23 | 7774.0 | $259,411.52 | 2774.0 sh · P&L $2,743.53 | 5000.0 sh · $166,850.00 | PARTIAL_BASIS_UNKNOWN: 5000 of 7774 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | SCLX | 2026-02-12 | 4.0 | $33.32 | — | 4.0 sh · $33.32 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | TSLA | 2026-02-05 | 145.0 | $57,353.13 | — | 145.0 sh · $57,353.15 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | UBER | 2026-01-14 | 409.0 | $34,614.94 | — | 409.0 sh · $34,615.02 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | V | 2026-04-21 | 175.0 | $54,626.84 | 5.107 sh · P&L $-85.81 | 169.893 sh · $53,033.80 | PARTIAL_BASIS_UNKNOWN: 169.893 of 175 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | V | 2026-06-18 | 100.0 | $32,898.30 | — | 100.0 sh · $32,899.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_rollover_ira | V | 2026-09-09 | 201.0 | $73,666.78 | — | 201.0 sh · $73,668.33 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | AGMH | 2025-09-19 | 800.0 | $6,175.95 | — | 800.0 sh · $6,176.08 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | AMD | 2025-09-30 | 100.0 | $16,134.48 | — | 100.0 sh · $16,134.50 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | APAM | 2025-12-31 | 102.117 | $4,168.61 | 2.117 sh · P&L $-1.58 | 100.0 sh · $4,082.21 | PARTIAL_BASIS_UNKNOWN: 100 of 102.117 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | EKSO | 2025-12-30 | 1500.0 | $13,129.76 | 500.0 sh · P&L $231.59 | 1000.0 sh · $8,753.30 | PARTIAL_BASIS_UNKNOWN: 1000 of 1500 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | LAC | 2025-09-25 | 1000.0 | $7,044.83 | — | 1000.0 sh · $7,045.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | MOGU | 2025-09-11 | 1000.0 | $5,599.83 | — | 1000.0 sh · $5,600.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | SPRC | 2025-09-17 | 101.0 | $521.14 | 100.0 sh · P&L $64.98 | 1.0 sh · $5.16 | PARTIAL_BASIS_UNKNOWN: 1 of 101 sold shares left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | SSKN | 2025-09-23 | 500.0 | $1,345.37 | — | 500.0 sh · $1,345.45 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |
| schwab_taxable | XMTR | 2025-08-19 | 100.0 | $4,601.98 | — | 100.0 sh · $4,602.00 | BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger) |

- **BND 2026-08-25:** closed cost $27,648.48 vs FIFO-by-trade-date $27,711.92. The ledger has a BND buy of
  9.218 sh dated 2026-08-05 but time-stamped 2026-03-04 12:21 and priced $53.78 (BND traded ≈$73) — a suspect
  ledger row; the builder orders by timestamp, the check by trade date. Unverifiable without Schwab's lot
  detail; flagged, not changed.
- Duplicate `dedupe_key`s in `trade_closed`: none. Closes with no broker sale: none, other than the FCNTX
  date shift (fixed in the builder) and the two probe rows.
- Fidelity: 10 SnapTrade sells (2026-06-22 → 07-13) have no `trade_closed` rows — the journal builder covers
  Schwab only; Fidelity realized P&L is not in REALIZED (not verifiable here).

## What changed (this PR)

- `scripts/lib/portfolio_positions.py` — the one accessor: `resolve_mark` (data-broker quote → Finviz →
  stored mark with its age; never `current_price`), `value_and_pl`, `per_share_cost`, `load_store`, config.
- `scripts/api_v2.py` — holdings, accounts-live and analyst-detail price through it; stale anchors are no
  longer scaled; both bases exposed; REALIZED/TRADING exclude probe accounts and disclose basis-unknown sells.
- `scripts/portfolio_repricer.py` — keeps the deprecated `current_price` equal to the mark it writes, so the
  frozen value disappears for not-yet-migrated readers on the next reprice (no hand edit of the store).
- `scripts/schwab_journal_builder.py` — open/close dates from the broker trade date (schema column added only
  on `--apply`).
- `apps/command-center-v3/src/components/MetricStrip.tsx` — REALIZED tile states the excluded sells.
- `scripts/portfolio_reconcile.py` — this report; `scripts/archive_trade_closed_probe_rows.py` — dry-run-first
  archive of the two probe rows (JSON backup + copy-verify before removal).
- Guard: `tests/test_portfolio_price_truth_20261005.py` (gate `portfolio_price_truth_20261005`), including a
  ratchet that freezes the 288 files reading holdings.json directly.

## Operator decisions

1. Cost basis: keep the April anchors (operator-repaired) or let broker basis supersede them for AMANX, XLB,
   V (Roth), PFLT (differences $13.90, $212.25, $174.38, $9.37).
2. The 33 basis-unknown sells (proceeds $901,194.23): provide Schwab's Realized
   Gain/Loss export (or extend `config/journal_basis_overrides.yaml`) so their P&L can enter REALIZED.
3. Run `scripts/archive_trade_closed_probe_rows.py --apply` (dry run quoted in the PR).
4. Schedule the read-only reconciliation lane `portfolio-broker-reconciliation` (proposed cron in
   `config/lane_registry.json`).
