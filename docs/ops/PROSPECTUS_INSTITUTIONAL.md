# Ticker Prospectus — institutional ("Street") blocks and the validation badge

```
Status:      DRAFT
as_of:       2026-10-27T18:00:00Z
Measured at: branch feat/prospectus-institutional-20261027, stacked on feat/prospectus-news-methodology-20261027 (not live)
```

Operator 2026-10-27: "does it also have analyst reviews and what are analysts saying along with catalysts? … Do another
look at the prospectus and make sure that it's thorough … something I can use on the Goldman desk, Citadel, anywhere."
And, the same day: "there's a lot of citations … We don't need to see it on the frontend … If it's been validated,
that's good."

Code: `scripts/lib/prospectus/street.py` (blocks), `scripts/lib/data_broker/street_detail.py` (the read projection),
`scripts/lib/prospectus/tables.py` (`street_top_tables`, `positioning_tables`, `valuation_tables`, `street_tables`),
`scripts/lib/prospectus/presentation.py` (`validation`), `apps/command-center-v3/src/components/prospectus/StreetBlocks.tsx`.
READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): nothing here sizes, orders, stops or weights.

## What the report now carries

Every number is computed in Python from house stores and handed to the writer as a cited fact. The writer never does
arithmetic and never names a firm that no fact names.

| Block | Contents | House source (read through `data_broker.street_detail`) |
|---|---|---|
| `analyst_coverage` | Rating distribution (strong buy … strong sell) now and three months ago, buy-rated share and its change; mean / median / low / high target, analyst count, rating mean, dispersion, upside; target trend 30 / 60 / 90 days; the **analyst action log** (date, firm, action, old → new rating, old → new target, link) and a 90-day tally | `yahoo_analyst_targets_history` (daily rows + `data.extended`), `analyst_data_history` (monthly counts recorded before that provider was retired; shown with its age), `catalyst_events` analyst items |
| `estimates` | Next-quarter, FY1 and FY2 EPS and revenue consensus with the number of estimates, range and growth; EPS trend 7 / 30 / 60 / 90 days; up / down revisions 7 / 30 days; the last 8 quarters of EPS beat / miss with the 1-day and 5-session price reaction | `data.extended` (`earnings_estimate`, `revenue_estimate`, `eps_trend`, `eps_revisions`, `earnings_dates`) + house closes |
| `catalyst_calendar` | Forward 120 days: next earnings with its time and the **options-implied move**, ex-dividend (recorded, the fund estimate, or the ex-date cadence, labelled "estimated"), FOMC decisions, macro releases when the calendar file exists. Backward: past earnings and high / critical catalysts with their 1-day and 5-session reaction | `data.extended.earnings_dates`, `symbol_profiles`, `options_chain_snapshots` term structure, `ticker_dividends`, `ticker_dividend_data`, `config/macro_calendar_overrides.json`, `catalyst_events` |
| `positioning` | Short interest and days to cover; institutional ownership and change; insider Form 4 buys / sells and net dollars over 90 days (where the store covers the symbol); 13F holders (when ingested); put/call by open interest and volume (and 30 days ago), 25-delta skew, ATM IV, IV rank and percentile (at least 60 stored sessions), IV term structure | Finviz enrichment cache, `sec_form4`, `sec_13f`, `option_chain_snapshots`, `options_chain_snapshots` |
| `valuation_history` | Trailing P/E now against its own range (low / median / high, percentile, vs median), forward P/E, trailing four-quarter EPS | house closes ÷ reported EPS (`data.extended.earnings_dates`, else SEC XBRL diluted EPS by filing date) |
| `fundamentals_xbrl` | The last 6 quarters: revenue, YoY, operating income and margin, net income, operating cash flow, net debt (long-term debt − cash). A quarter is the 10-Q quarter, else YTD − prior YTD, else FY − the three stated quarters (marked "derived") | `sec_xbrl` |

Funds: `analyst_coverage`, `estimates`, `valuation_history` and `fundamentals_xbrl` do not apply and are hidden;
the catalyst calendar and options / short positioning stay.

**Rendering.** HTML, PDF and Word render the same tables (`tables.top_tables`). The page renders
`presentation.street` (the same table shapes) with `StreetBlocks.tsx`: a card per table on desktop and stacked row
cards on the phone (≤ 820 px), so nothing scrolls sideways. A report built before this change keeps its original
estimates card.

**Writer prompt.** One added instruction: use the Street facts in analyst view (distribution, target trend, named
actions), financials (consensus, revisions, beat / miss, SEC quarters), catalysts (dated events, implied move, past
reactions) and valuation (P/E in its own range). When the prompt is over its byte budget, news, peer, social, research,
journal, lineage, momentum and relative-performance facts are trimmed before anything else.

## Print-proof fixes (coordinator review of #2234)

- **EPS-surprise chart.** It is drawn only with 3 or more quarters: in new reports, in stored reports at render time,
  and on the page. One quarter used to draw a page-wide bar. The earnings-history table always lists every quarter.
- **Peers** (`blocks.size_matched_peers`). Peers come from the same industry, within `PEER_SIZE_BAND` (20x) of the
  subject's market cap, closest in size first. A row whose peer fields are less than `PEER_MIN_FILLED` (40%) filled is
  dropped. When fewer than 3 qualify, the same sector fills in, and the gap says so. When the cache is too thin for
  these rules, the closest-size industry members are shown, and the gap says that too.
- **Markdown tables.** Pipe tables in section text (`| a | b |`) render as tables in HTML, PDF, Word and on the page
  (`presentation.md_segments`, `mdBlocks`).

## The extended analyst capture (same writer, same store, same provider)

`scripts/pro_analyst_fetch.py` (the declared writer of `analyst_opinion`, daily 06:10) now records, for held and
actionable symbols only, the Yahoo analyst action history, EPS and revenue consensus, EPS trend and revisions, earnings
history and dates, and the recommendation trend into the same row's `data.extended` (`YahooAnalystExtended@v1`).

- Bounded: at most `EXTENDED_MAX` (120) symbols per run.
- Circuit breaker: after 3 consecutive rate-limited symbols the run stops capturing the extended set and records
  `extended_stopped_on_rate_limit`.
- `--no-extended` turns it off; `--dry-run` reports `would_capture_extended` and makes no call.
- No new provider, store, writer or schedule, so no registry row changes.

Until the first run after this merges, each block names what it is waiting for ("not captured yet for this symbol").

## Citations and the validation badge

Citations stay in the JSON: `sections[].citations`, the `[F7]` groups in `body_md`, and every fact. The gate, the
layer-3 post-write check and the accuracy auditor use them unchanged. The reader no longer sees them:

- No superscript numbers, no per-section "Sources (n)", no Sources appendix, and no footnotes or endnotes in the HTML,
  PDF or Word.
- Each citation group leaves only a hidden `data-fact-id` marker. The prose reads cleanly, with no brackets left behind.
- One line under the header, the same in all three files and on the page, comes from `presentation.validation`:
  - `✓ Validated — N figures checked against M sources · as of <time>`: the gate passed and every number in the text
    matched a cited figure.
  - `⚠ Partial — K figures not validated: <reasons>`: the gate flagged facts (SOFT / HARD), or the post-write check
    found numbers that match no cited figure.
  - `Checked against sources — …`: an older version with no gate record.
- On the page, tapping the badge opens a compact summary: figures by source type, and anything not validated. It shows
  no citation list.

## Still missing, and what would close it

| Gap | Free path (agent follow-up) | Paid path (operator decision) |
|---|---|---|
| Revenue beat / miss history | none | an estimates provider |
| Company guidance vs consensus | earnings-call notes cover it in prose | a transcripts or estimates provider |
| Insider Form 4 for every symbol | backfill the existing SEC Form 4 ingest (store covers only part of the universe) | — |
| 13F holders and QoQ changes | build the 13F ingest into the existing `sec_13f` store (SEC EDGAR) | — |
| Short-interest trend | FINRA bi-monthly short-interest files (new provider row) | — |
| EV/EBITDA, P/S, FCF-yield history; FCF, buybacks, segments | ingest more SEC XBRL tags (shares, D&A, capex, repurchases, segment dimensions) | — |
| 10-K / 10-Q risk-factor changes | ingest the risk-factor item text from EDGAR and diff it | — |
| CPI / payrolls / PCE dates | turn on `macro_calendar_refresh` (FRED release calendar) | — |
| Unusual options activity | none | an options-flow feed (Polygon was retired 2026-09-13) |
| ETF creations / redemptions | none | an ETF-flows feed |
| Investor days, FDA / legal dates, lock-ups, index rebalances | S-1 lock-up terms from EDGAR | a corporate-events calendar |
| Real earnings-call transcripts | none (YouTube transcripts are often rejected as not the call) | a transcripts provider |

The cost estimates for the paid rows are in the PR body and the private review
(`coordination/handoffs/prospectus-20261026/INSTITUTIONAL_REVIEW.md`).

## Gate checks

Layer 1 adds `check_street`: staleness the block does not label, units (implied move, IV, put/call, P/E), and
consistency (target trend vs the target fact, distribution count vs analyst count, surprise sign, net debt = debt −
cash, margin range). The codes are listed in `PROSPECTUS_QUALITY_GATE.md`.

## Tests

- `tests/test_prospectus_street_20261027.py`: synthetic blocks, reaction timing, derived XBRL quarters, fund hiding,
  facts, gate checks, HTML / PDF / DOCX with no citations and one validation line, and the extended capture's JSON shape
  and circuit breaker.
- `apps/command-center-v3/e2e/prospectus-street.spec.ts`: 1440 / 412 / 390.
- `prospectus-polish.spec.ts`: no superscripts or source lists, plus the badge.
