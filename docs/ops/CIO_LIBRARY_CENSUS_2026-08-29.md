# CIO library census (2026-08-29)

Answer to "where are the 20–30 institutional publications".

## They were never missing — they were catalogued

`config/cio_research_source_catalog.json`, 34 sources:

    20  institutional_canon books (Core Ten + #11–20)
     1  practitioner_seasonality  (Stock Trader's Almanac)
    13  primary research papers
    --
    34  total

**Correcting yesterday's corpus map.** It declared `CORPUS_UNLOCATED`. That was
a search failure on my part, not an absence: I swept `data/` directories and
filename globs (`*corpus*`, `*publication*`, `*almanac*`, `*book*`) and never
looked in `config/`. The registry existed the whole time and is loaded by
`scripts/lib/research_governance/source_catalog.py`.

## But no full text exists — and the catalog says so itself

Every one of the 34 entries carries:

    full_text_status : NOT_FOUND_IN_FILE_LIBRARY   34/34
    claim_status     : SOURCE_CLAIM_INCOMPLETE     34/34
    license_class    : COPYRIGHT                   34/34

The catalog's own note: *"Every source lacking lawful full text carries
`claim_status=SOURCE_CLAIM_INCOMPLETE`."* That is the correct posture, not a
gap to be closed by scraping — these are copyrighted books.

Searched for full text and found none in: repo tree, `persistent-state/data/**`,
`trade-ai-releases/agent-jobs/**`, and Google Drive (no PDF or EPUB of any
catalogued work exists there; the PDFs present are unrelated personal documents
and are not listed here). The one Drive item of interest is an inventory note,
`BOOK_KNOWLEDGE_INVENTORY.md` — id `15c_hTsSy2SSy9pD5DWz_uhhDDcQIK5ek`, listed
per instruction, not fetched.

## Census

Every row is `MISSING`, 0 bytes on disk, not in `library_facts`, proposed grade
**D** — "source claim recorded with citation; not independently reproduced;
must not be treated as a Trade AI fact." That is the only defensible grade for
a work whose text the system has never read.

| # | title | source_id | type | path | in library_facts | proposed family | proposed grade |
|---:|---|---|---|---|:---:|---|:---:|
| 1 | A Random Walk Down Wall Street | `malkiel_random_walk` | book | **MISSING** | n | context | D |
| 2 | The Intelligent Investor | `graham_zweig_intelligent_investor` | book | **MISSING** | n | context | D |
| 3 | The Psychology of Money | `housel_psychology_of_money` | book | **MISSING** | n | context | D |
| 4 | The Little Book of Common Sense Investing | `bogle_common_sense` | book | **MISSING** | n | context | D |
| 5 | The ETF Book | `ferri_etf_book` | book | **MISSING** | n | context | D |
| 6 | The Bond Book | `thau_bond_book` | book | **MISSING** | n | context | D |
| 7 | Trading and Exchanges | `harris_trading_exchanges` | book | **MISSING** | n | context | D |
| 8 | Options as a Strategic Investment | `mcmillan_options` | book | **MISSING** | n | context | D |
| 9 | Option Volatility and Pricing | `natenberg_option_volatility` | book | **MISSING** | n | context | D |
| 10 | Evidence-Based Technical Analysis | `aronson_evidence_based_ta` | book | **MISSING** | n | context | D |
| 11 | Advances in Financial Machine Learning | `lopez_de_prado_afml` | book | **MISSING** | n | context | D |
| 12 | Expected Returns | `ilmanen_expected_returns` | book | **MISSING** | n | context | D |
| 13 | Active Portfolio Management | `grinold_kahn_active_pm` | book | **MISSING** | n | context | D |
| 14 | Damodaran on Valuation | `damodaran_on_valuation` | book | **MISSING** | n | context | D |
| 15 | The Most Important Thing | `marks_most_important_thing` | book | **MISSING** | n | context | D |
| 16 | Options, Futures, and Other Derivatives | `hull_options_futures_derivatives` | book | **MISSING** | n | context | D |
| 17 | Fixed Income Securities | `tuckman_serrat_fixed_income` | book | **MISSING** | n | context | D |
| 18 | Adaptive Markets | `lo_adaptive_markets` | book | **MISSING** | n | context | D |
| 19 | Financial Shenanigans | `schilit_perler_financial_shenanigans` | book | **MISSING** | n | context | D |
| 20 | Expectations Investing: Reading Stock Prices for Bet | `expectations_investing_rappaport_mauboussin` | book | **MISSING** | n | context | D |
| 21 | Stock Trader's Almanac | `stock_traders_almanac` | book | **MISSING** | n | context | D |
| 22 | A Reality Check for Data Snooping | `white_reality_check_2000` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 23 | Data-Snooping, Technical Trading Rule Performance, a | `sullivan_timmermann_white_1999` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 24 | Dangers of Data Mining: The Case of Calendar Effects | `sullivan_timmermann_white_calendar_effects_2001` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 25 | The Deflated Sharpe Ratio: Correcting for Selection  | `bailey_lopez_de_prado_2014` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 26 | The Probability of Backtest Overfitting | `bailey_borwein_lopez_de_prado_zhu_2017` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 27 | ... and the Cross-Section of Expected Returns | `harvey_liu_zhu_2016` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 28 | Combinatorial Purged Cross-Validation (CPCV) | `lopez_de_prado_cpcv_2017` | book_chapter | **MISSING** | n | context | D |
| 29 | Continuous Auctions and Insider Trading | `kyle_1985` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 30 | Illiquidity and Stock Returns | `amihud_2002` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 31 | Inferring Trade Direction from Intraday Data | `lee_ready_1991` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 32 | Optimal Execution of Portfolio Transactions | `almgren_chriss_2001` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 33 | A Simple Way to Estimate Bid-Ask Spreads from Daily  | `corwin_schultz_2012` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |
| 34 | Presidential Address: The Scientific Outlook in Fina | `harvey_2017_p_hacking` | paper | **MISSING** | n | trend/value/risk (per abstract) | D |

## What this means for the gate

Grade D can never `corpus_hit`. So the 34 works are citable context and nothing
more, which is exactly what they should be until lawful full text exists. The
registry lists them so this question has one answer instead of a search.

## Candidate proposals (dry, 3 of 3 weekly budget, not ingested)

Given every catalogued work is COPYRIGHT-blocked, the useful additions are
lawfully redistributable series that could actually earn a grade:

| source_id | why | family | suggested |
|---|---|---|:---:|
| `ken_french_data_library_monthly` | free, citable monthly US series 1926– — would replace the **synthetic** series that currently backs every `grade=B` seasonality label | seasonality | B |
| `shiller_us_stock_market_data` | public academic dataset, 1871–, supports the existing `OOS_START_YEAR=2000` split | value | B |
| `sec_edgar_full_text` | primary filings are public domain; would give entity-level dimensions a lawful free source, which the corpus cannot serve at all today | risk | C |

Stored as `CANDIDATE` refs only — no grade, no ingest, no download.
