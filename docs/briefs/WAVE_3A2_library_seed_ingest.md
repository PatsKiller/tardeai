<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3A.2 — library seed + ingest

**Status:** recovered verbatim
**Source:** session transcript, operator message 012

---

Claude Code — WAVE 3A.2 library seed + ingest.
CURRENT must contain #636. Extend cio_research_library / cio_corpus_index.
Do NOT create a second freshness table. research_source_index.decide() stays the law.
READ_ONLY_ADVISORY. MBI=0. No notify. No ROTATE. No cio_run LLM.
Prefer official URL, SSRN, NBER, Fed, Wiley, or a file already on disk.

Seasonality series MUST leave tests/fixtures/us_equity_monthly_sample.csv
(Wave 3A.1). If that move is not done, do it in this PR first.

════════════════════════════════════════
GRADE LAW (pin in code + tests)
════════════════════════════════════════
A/B: independently reproduced. Risk-modifier / context only. Never a standalone sell.
C: challenge-prompt / context only. Cannot corpus_hit.
D: must not be treated as a Trade AI fact. Cannot corpus_hit.
X: reproduction contradicts the claim.
corpus_hit ONLY if grade A/B AND dimension_scope=context.
Entity-level (bear_case, what_is_priced_in, ticker thesis) NEVER corpus-closed
by almanac / war / tariff / month-of-year / options textbook.

Each registry row:
  source_id, family, title, authors, year, isbn_or_doi, official_url,
  path_or_MISSING, content_hash, as_of, evidence_grade, application_law,
  dimension_scope (context|entity), refresh (event|weekly|static),
  notes.

════════════════════════════════════════
FAMILY A — calendar / election / month
════════════════════════════════════════
Ingest or register:
- Hirsch, Stock Trader's Almanac 2026 (Wiley ISBN 978-1-394-36268-4)
  https://www.stocktradersalmanac.com/AboutUs.aspx
  Grade C until OUR monthly series reproduces the named effect; then B
  for that named effect only.
- Bouman & Jacobsen 2002 Halloween / Sell-in-May (AER) — B
- Plastun et al. Halloween US history SSRN 3362154 — B/C
- Mohamed 2024 Time-Based Trading Patterns SSRN 5101935 — C
Facts to EXTRACT as structured rows (not prose dump), each with
reproduced=yes/no against our 1950→ monthly file:
  january_barometer
  santa_claus_rally
  best_six_months / halloween_nov_apr
  worst_six_months_may_oct
  turn_of_month
  pre_holiday
  september_weakness
  midterm_year_pattern          (Q2–Q3 weak / Q4 sweet spot — C until reproduced)
  post_election_year
  presidential_4yr_cycle
  midterm_bottom_picker
If we cannot reproduce on our series: grade C, reproduced=false.
NEVER write “sell in May” as an action. Store as calendar_context.

════════════════════════════════════════
FAMILY B — index level / breadth / regime (SPX vs NDX)
════════════════════════════════════════
Register + ingest public data:
- Ken French Data Library FF3/FF5/Mom + industry
  https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html  GRADE A
- Fama French 1993 JFE, 2015 five-factor — A
- Carhart 1997 — A
- FRED: SP500, NASDAQCOM, FEDFUNDS, T10Y2Y, CPIAUCSL, UNRATE, VIXCLS
  https://fred.stlouisfed.org  GRADE A
- CBOE VIX white paper — B
- Baker Bloom Davis EPU — policyuncertainty.com — A/B
Structured FACT rows to compute from FRED/French (do not invent):
  spx_vs_ndx_relative_strength (12m, 3m) as context
  yield_curve_invert_then_12m
  vix_regime  (<15, 15-25, >25) historical next-3m SPX — B only if we compute it
  breadth / FF momentum as regime label
Do not store “NDX at X → sell.” Store conditional historical distributions
with sample size and as_of. Grade D if n is tiny.

════════════════════════════════════════
FAMILY C — war / tariffs / geopolitics (historical context)
════════════════════════════════════════
Official / academic:
- NBER / academic event studies: wars, embargoes, tariff shocks
  (Smoot-Hawley, 2018–19 tariffs, Gulf War, 9/11, Ukraine 2022)
- Fed / Treasury / USTR primary documents when a live tariff event hashes
- Baker Bloom Davis EPU geopolitical subindices if available
Grade: primary docs A; event-study papers B; op-eds D.
dimension_scope=context. A tariff headline is an EVENT that overrides
SKIP_FRESH. It does not mint a TRIM.

Extract fact shape:
  event_class (war|tariff|embargo|sanctions)
  window (announcement, 1d, 5d, 21d, 12m)
  median/IQR SPX and NDX moves
  sample_n
  source_id
If sample_n < 8: grade C/D, cannot corpus_hit.

════════════════════════════════════════
FAMILY D — options / hedging / derivatives (desk context)
════════════════════════════════════════
Register (file on disk or official URL + ISBN):
- Natenberg, Option Volatility and Pricing — C/B methodology
- Hull, Options, Futures, and Other Derivatives — C
- McMillan, Options as a Strategic Investment — C
- Cohen, The Bible of Options Strategies — C
- Sinclair, Volatility Trading — C
- Gatheral, The Volatility Surface — B/C
- Taleb, Dynamic Hedging — C
Papers / official:
- CBOE white papers (covered call, put-write, VIX)
- Bollen & Whaley demand-pressure
- Bakshi Kapadia Madan risk-neutral skew
- Chicago Fed / OCC options open-interest explainers
Structured facts allowed:
  put_call_ratio as CONTEXT regime
  skew / vix term-structure labels
  covered_call / collar as HEDGE LANGUAGE for the operator product
    (option_id style, no order tickets)
Execution verbs still fail the shared imperative matcher.
Do not store strike-level playbooks for SCHD.

════════════════════════════════════════
FAMILY E — long-run / valuation / quality / income
════════════════════════════════════════
- Dimson Marsh Staunton Triumph of the Optimists / Yearbook — B
- Jorda Knoll Schularick Taylor QJE Rate of Return on Everything — A
- Siegel Stocks for the Long Run — C
- Ibbotson SBBI if owned — B
- Damodaran implied ERP official page — B for the series
- Graham & Dodd Security Analysis — C
- Goyal & Welch equity premium prediction RFS — A
- Bessembinder Do stocks outperform T-bills JF — A/B (concentration / S6 context)
- Arnott Asness dividend paper FAJ — B/C
- Fama French disappearing dividends — B

════════════════════════════════════════
FAMILY F — Fed / macro event cadence
════════════════════════════════════════
- federalreserve.gov FOMC statements, minutes, SEP — A primary
- Beige Book — A primary
- FRBSF WP 2025-30 USMPD FOMC event-study database PDF
  https://www.frbsf.org/wp-content/uploads/wp2025-30.pdf — B
- Nakamura Steinsson 2018 — A/B
- Bauer Swanson FOMC HF — A/B
Hash change on a new minutes/Beige Book = EVENT override.

════════════════════════════════════════
FAMILY G — liquidity / crash / intermediary
════════════════════════════════════════
- Adrian Etula Muir intermediary CAPM JF — B
- Brunnermeier Pedersen funding liquidity RFS — A/B
- Moreira Muir Volatility-Managed Portfolios JF — B
- CBOE VIX methodology — B

════════════════════════════════════════
WHAT TO DO IN CODE
════════════════════════════════════════
1) Census file docs/ops/CIO_LIBRARY_CENSUS_{date}.md
   every row above: FOUND_ON_DISK / OFFICIAL_URL_ONLY / MISSING / CANDIDATE
2) Relocate seasonality CSV. Test fails if resolve() still uses tests/.
3) Ingest this PR:
   - files already on disk
   - public series (French, FRED, Fed HTML/PDF)
   Cap: seasonality + French FF3 monthly + FRED 6 series
   + last 4 FOMC minutes + last 2 Beige Books + FRBSF 2025-30
   + structured calendar facts reproduced against our series
4) Register owned books as MISSING_FILE + official URL + ISBN when the file
   is not on disk yet.
5) CANDIDATE cap 3: Almanac 2026, DMS yearbook, Natenberg or Hull
   if not on disk.
6) ResearchNeedDecision@v2: corpus_hit only A/B + context.
   Add tests: midterm_year fact does not close a SCHD plan;
   VIX regime does not emit sell;
   tariff event overrides SKIP_FRESH but does not attach execution language.
7) Host dry: eligible job count stays collapsed (do not re-expand 36 S5 Flash).
8) Scoreboard WAVE3A.2. One or two PRs. Exact-main promote.
   /health /v3/cio 200. telegram_sent false.

STOP. No Wave 3B. No notify. No cap raise. No second cron.
