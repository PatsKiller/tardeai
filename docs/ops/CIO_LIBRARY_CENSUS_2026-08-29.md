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

---

# Wave 3A.2 — seed + ingest (same day)

## The grading series changed, and that is the point

3A.1 established the seasonality file is **synthetic**. Reproducing a calendar
claim against it proves the pipeline is deterministic and says nothing about
markets, so no grade derived from it can honestly read "independently
reproduced".

Wave 3A.2 ingests the **Ken French Data Library** monthly series and grades
against that instead:

| | synthetic file | Ken French (now the grading series) |
|---|---:|---:|
| span | 1950-01 … 2024-12 | 1926-07 … 2026-06 |
| months | 900 | **1200** |
| 1987-10 | +3.27% | **−23.19%** |
| worst month | −7.88% | **−28.74%** |

Public, redistributable, citable. The synthetic file stays only for the
determinism check it was always performing.

## Ingested this PR (8 files, ~848 KB, all hashed)

| source_id | grade | rows |
|---|:---:|---:|
| `ken_french_data_library` | A | 1200 monthly |
| `fred_sp500` `fred_nasdaqcom` `fred_fedfunds` `fred_t10y2y` `fred_cpiaucsl` `fred_unrate` `fred_vixcls` | A | 7 series |

Fed documents (FOMC minutes, Beige Books, FRBSF WP 2025-30) are registered
`OFFICIAL_URL_ONLY` with `refresh: event` rather than committed: they are
event-driven by design — a hash change *is* the trigger — so pinning stale
copies in the release would work against the cadence rule. Flagged as a
deviation from the ingest list.

## Calendar effects — 12 rows, 9 reproduced

Reproduced against Ken French, never against the synthetic file:

| fact | grade | n | result |
|---|:---:|---:|---|
| `best_six_months` / `halloween_nov_apr` | B | 99 | +7.68% mean, win 74.8% |
| `worst_six_months_may_oct` | B | 99 | **+3.96% mean, win 71.7%** |
| `september_weakness` | B | 100 | −0.77% mean, win 51.0% |
| `january_barometer` | B | 99 | sign agreement |
| `midterm_year_pattern` | B | 300 | +0.56%/mo |
| `post_election_year` | B | 300 | +0.84%/mo |
| `presidential_4yr_cycle` | B | 1200 | by mechanical year%4 label |
| `midterm_bottom_picker` | B | 75 | Q2–Q3 −0.16%/mo vs Q4 **+2.08%/mo**, spread +2.24pp |
| `santa_claus_rally` | C | — | December proxy only; true window needs daily data |
| `turn_of_month`, `pre_holiday` | C | 0 | monthly series cannot express them |

**Worth reading twice:** on real 1926– data the "worst six months" averages
**+3.96%** with a 71.7% win rate. "Sell in May" reads as though May–Oct is
negative; it is not. The effect is a *differential* against Nov–Apr's +7.68%.
This is exactly why these are stored as `calendar_context` with
`standalone_sell: False` and never as a verb — a test asserts no calendar row
contains an imperative.

Nothing claims grade **A**: A additionally requires out-of-sample directional
support, so B is the ceiling for a single in-sample reproduction.

## Registry: 34 rows across Families A–G

    A 16 | B 12 | C 6      on disk 8 | official-url-only 26

Every row carries `source_id, family, title, authors, year, isbn_or_doi,
official_url, path_or_MISSING, content_hash, as_of, evidence_grade,
application_law, dimension_scope, refresh, notes`. All are
`dimension_scope: context` — none may close an entity question.

Copyright books (Natenberg, Hull, Gatheral, Almanac 2026) stay grade C,
`path_or_MISSING: MISSING`, official URL + ISBN recorded. The Almanac upgrades
to B *per named effect* only once that effect is reproduced — which several now
are, against French rather than against itself.

## Candidates (dry, 3 of 3)

`hirsch_stock_traders_almanac_2026`, `dimson_marsh_staunton_yearbook`,
`natenberg_option_volatility` — all owned-book candidates whose files are not
lawfully on disk. `CANDIDATE`, no grade, no ingest.
