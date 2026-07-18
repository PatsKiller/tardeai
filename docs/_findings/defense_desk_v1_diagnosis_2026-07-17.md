# Defense Desk v1 — Phase 0 Diagnosis (2026-07-17)

## Capability matrix
| Capability | Verdict | Evidence |
|---|---|---|
| Sector RS depth | **FULL — no warm-up** | prompt guessed `sector_rs_history` (absent); Watch v4 actually landed `sector_rs_daily` (262 rows, 10 ETFs, since 05-04) AND `ticker_prices` holds **5 years** of daily closes for all 11 sector ETFs + SPY + QQQ (1,259-1,260 rows each) — the engine computes RS 5/20/60d directly from ticker_prices |
| Short float | **CAPTURED** | finviz_enrichment.py v=131 ownership view → `short_float_pct`, `short_ratio` fields; persistence target + coverage % deferred to WS-B (storage is inside the enrichment payload path, not a dedicated table) |
| Options chains readable | **YES** | `schwab_transport.get_option_chain` + `normalize_option_chain` exist inside the fence — B2 viable without widening the Schwab surface |
| Options approval levels | **NOT machine-readable** | no config/table anywhere → `config/account_capabilities.json` created operator-fillable; hedge menu degrades to inverse-ETF+CC until filled |
| Paper short capable | **YES** | alpaca_paper_adapter handles side='short'/'sell' (dir mapping at :296); strategy YAML pattern in config/strategies/ |
| **Taxable margin** | **VERIFIED ENABLED** | live account record: `type: MARGIN`, buyingPower $114,263 = 2× availableFunds $57,131 — short-stock ADVISORIES permitted per operator + this verification |
| Breadth inputs | **YES** | screener_symbol_membership: 10,869 distinct symbols with sector attribution |
| Book sector weights | **YES — reuse** | /api/v2/portfolio/book-map (Home v2) = holdings × sector × value, memoized |

## 0.5 rotation-alternatives "not_yet" root cause
aegis_synthesis.py:454-492 — two paths: (a) FROM symbol "still in <verdict> — wait for verdict
clarity" (the four stopped defense names sit in recovery/relist states → engine refuses to
rotate while the source verdict is unsettled — DESIGN, arguably correct); (b) "No strong
watchlist alternative passes threshold" — universe/threshold starvation. WS-C item: config
loosening vs flag; deferred with C (not in this session's core).

## Session scope decision (per prompt's time-box clause)
This session ships the visibility core **A + E + F** plus **D1** (capabilities config w/ margin
verdict). **B/C/D2-D5 deferred** to the next Defense session with stubs + this diagnosis in
place (chains verified readable, short-float fields verified captured, paper-short verified,
anti-squeeze/thresholds specified in the prompt carry over verbatim).
