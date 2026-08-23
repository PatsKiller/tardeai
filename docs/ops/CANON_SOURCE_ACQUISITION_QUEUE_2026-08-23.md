# Canon Source Acquisition Queue - 2026-08-23

Status: `SOURCE_REQUIRED`  
Authority: `READ_ONLY_ADVISORY`  
Catalog: `config/cio_research_source_catalog.json` (`schema_version=1.2`)  
Measured result: 34 sources total; 34 `NOT_FOUND_IN_FILE_LIBRARY`; 34 `SOURCE_CLAIM_INCOMPLETE`.

## Operator action

Supply an operator-owned/licensed digital source, a lawful institutional-library export, or a lawful public/author-hosted source URL for each item below. Do not supply credentials. Trade AI must hash and register the exact edition before extraction. A catalog entry does not authorize acquisition, and no claim may become active without source text and an exact locator.

Accepted inputs: PDF, text, Markdown, HTML, or operator-owned EPUB. OCR is permitted only where text extraction is unavailable. Unauthorized copies must not be downloaded or ingested.

## Queue

| # | Source ID | Type | Title | Required acquisition |
|---:|---|---|---|---|
| 1 | `malkiel_random_walk` | book | A Random Walk Down Wall Street | Operator-owned/licensed edition |
| 2 | `graham_zweig_intelligent_investor` | book | The Intelligent Investor | Operator-owned/licensed edition; identify Graham/Zweig edition |
| 3 | `housel_psychology_of_money` | book | The Psychology of Money | Operator-owned/licensed edition |
| 4 | `bogle_common_sense` | book | The Little Book of Common Sense Investing | Operator-owned/licensed edition |
| 5 | `ferri_etf_book` | book | The ETF Book | Operator-owned/licensed edition |
| 6 | `thau_bond_book` | book | The Bond Book | Operator-owned/licensed edition |
| 7 | `harris_trading_exchanges` | book | Trading and Exchanges | Operator-owned/licensed edition |
| 8 | `mcmillan_options` | book | Options as a Strategic Investment | Operator-owned/licensed edition |
| 9 | `natenberg_option_volatility` | book | Option Volatility and Pricing | Operator-owned/licensed edition |
| 10 | `aronson_evidence_based_ta` | book | Evidence-Based Technical Analysis | Operator-owned/licensed edition |
| 11 | `lopez_de_prado_afml` | book | Advances in Financial Machine Learning | Operator-owned/licensed 2018 edition; ISBN already cataloged |
| 12 | `ilmanen_expected_returns` | book | Expected Returns | Operator-owned/licensed edition |
| 13 | `grinold_kahn_active_pm` | book | Active Portfolio Management | Operator-owned/licensed edition |
| 14 | `damodaran_on_valuation` | book | Damodaran on Valuation | Operator-owned/licensed edition |
| 15 | `marks_most_important_thing` | book | The Most Important Thing | Operator-owned/licensed edition |
| 16 | `hull_options_futures_derivatives` | book | Options, Futures, and Other Derivatives | Operator-owned/licensed edition |
| 17 | `tuckman_serrat_fixed_income` | book | Fixed Income Securities | Operator-owned/licensed edition |
| 18 | `lo_adaptive_markets` | book | Adaptive Markets | Operator-owned/licensed edition |
| 19 | `schilit_perler_financial_shenanigans` | book | Financial Shenanigans | Operator-owned/licensed edition |
| 20 | `expectations_investing_rappaport_mauboussin` | book | Expectations Investing: Reading Stock Prices for Better Returns | Operator-owned/licensed edition |
| 21 | `stock_traders_almanac` | book | Stock Trader's Almanac | Operator-owned/licensed edition and year; seasonality remains shadow context |
| 22 | `white_reality_check_2000` | paper | A Reality Check for Data Snooping | Lawful publisher/library/author copy |
| 23 | `sullivan_timmermann_white_1999` | paper | Data-Snooping, Technical Trading Rule Performance, and the Bootstrap | Lawful publisher/library/author copy |
| 24 | `sullivan_timmermann_white_calendar_effects_2001` | paper | Dangers of Data Mining: The Case of Calendar Effects in Stock Returns | Lawful publisher/library/author copy |
| 25 | `bailey_lopez_de_prado_2014` | paper | The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality | Lawful publisher/library/author copy; DOI cataloged |
| 26 | `bailey_borwein_lopez_de_prado_zhu_2017` | paper | The Probability of Backtest Overfitting | Lawful publisher/library/author copy; journal/SSRN metadata cataloged |
| 27 | `harvey_liu_zhu_2016` | paper | ... and the Cross-Section of Expected Returns | Lawful publisher/library/author copy |
| 28 | `lopez_de_prado_cpcv_2017` | book chapter | Combinatorial Purged Cross-Validation (CPCV) | Licensed Chapter 12 from the cataloged 2018 book edition |
| 29 | `kyle_1985` | paper | Continuous Auctions and Insider Trading | Lawful publisher/library/author copy |
| 30 | `amihud_2002` | paper | Illiquidity and Stock Returns | Lawful publisher/library/author copy |
| 31 | `lee_ready_1991` | paper | Inferring Trade Direction from Intraday Data | Lawful publisher/library/author copy |
| 32 | `almgren_chriss_2001` | paper | Optimal Execution of Portfolio Transactions | Lawful publisher/library/author copy |
| 33 | `corwin_schultz_2012` | paper | A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices | Lawful publisher/library/author copy |
| 34 | `harvey_2017_p_hacking` | paper | Presidential Address: The Scientific Outlook in Financial Economics | Lawful publisher/library/author copy |

## Admission gates

1. Record lawful acquisition basis, edition/version, local or Drive path, and SHA-256.
2. Extract text with page/chapter/section locators and record extraction method.
3. Index into the existing evidence/RAG store; do not create another vector database.
4. Create `CanonClaim@v1` candidates only from located source passages.
5. Require independent review before `REVIEWED`; quantitative decision-affecting claims proceed through hypothesis, shadow, and validation governance.
6. Keep all 34 entries `SOURCE_CLAIM_INCOMPLETE` until these gates pass. No source means no claim.

## Current capability statement

The catalog is an inventory, not a knowledge corpus. Current canon maturity receives catalog/provenance credit only. It receives no claim, methodology, or CIO-decision credit.
