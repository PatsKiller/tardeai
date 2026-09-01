# Phase 7 — Institutional Report v2

Status:      HISTORICAL
as_of:       2026-08-13T18:27:19-04:00
Measured at: efcc51365 / not measured

**"Morgan Stanley completeness + Trade AI CIO intelligence."**

## Goal

Produce a professional, Trade AI–branded institutional report that uses the
operator's Morgan Stanley portfolio report as a *completeness benchmark* while
adding the intelligence a static wealth-management report cannot provide. The
report is Trade AI branded, not a Morgan Stanley imitation.

## Scope

The report has two parts plus two truth artifacts:

- **Part A — CIO Investment Committee front matter** (Trade AI's addition):
  CIO Letter / Executive Summary, Decisions Now, Capital Plan, Portfolio Posture,
  Opportunity Funnel, Counter-Thesis / Risks.
- **Part B — Institutional portfolio book** (Morgan Stanley completeness
  benchmark): accounts, summary, flows, performance, attribution, allocation,
  look-through, valuation, risk, income, tax/lots, realized, re-entry,
  watch/opportunity, rotation/defense, dispositions, methodology, disclosures.
- **Field-coverage matrix** — every required Morgan Stanley field mapped to one
  of `IMPLEMENTED_WITH_SOURCE_PROOF`, `EXPLICITLY_UNAVAILABLE`, or
  `DOCUMENTED_METHODOLOGY_SUBSTITUTE`, each carrying `source`, `as_of`,
  `coverage`, `quality`.
- **Immutable report manifest** — input hashes + source SHA + field counts,
  hash-pinned so any drift in inputs is detectable.

## Delivered

| Artifact | Path | Purpose |
| --- | --- | --- |
| Report engine (pure) | `scripts/lib/cio_report_v2.py` | coverage matrix, gap resolution, Part A composition, HTML render, manifest, Checkpoint 7 |
| Dry tests | `tests/test_cio_report_v2.py` | 25 tests over all pure logic |
| API endpoint | `GET /api/v2/cio/report-v2` (`api_v2.py`) | live report + coverage + manifest + checkpoint (HTML embedded) |
| Health block | `report_v2` in `/api/v2/watch/two-way-curation` | compact report summary |
| Sample output | `data/portfolios/reports/v2/report_v2.html` | generated from current canonical state |

## Report truth requirements

Every table/figure carries or exposes `source`, `as_of`, `coverage`,
`quality/methodology`. The coverage matrix is the canonical machine-readable
form; the HTML carries data-quality footnotes and per-field source/coverage.

A figure whose source is flagged inconsistent is never printed clean:
- `perf_3M` and `perf_1Y` are `account-aggregated` and internally inconsistent →
  reported with an explicit `flagged` badge and a footnote; snapshot-based
  periods (1W/1M/6M/YTD) are preferred.
- All `DOCUMENTED_METHODOLOGY_SUBSTITUTE` fields carry a `flagged` quality tag
  and a source note describing the substitute (never an estimate to fill a slot).

## Known-gap resolutions

Each prior-review gap resolves to exactly one status, encoded once in
`KNOWN_GAPS` so the matrix and the body can never disagree:

| Gap | Resolution |
| --- | --- |
| QTD return absent | `EXPLICITLY_UNAVAILABLE` — no quarter-start valuation snapshot; not estimated |
| True TWR previously a non-goal | `EXPLICITLY_UNAVAILABLE` — money-weighted CAGR is canonical |
| Incomplete per-lot adjusted basis / acquisition dates | `DOCUMENTED_METHODOLOGY_SUBSTITUTE` — `tax_lots.json` per-lot cost/date, partial coverage flagged |
| Weak fund/ETF valuation/style look-through | `DOCUMENTED_METHODOLOGY_SUBSTITUTE` — `fund_lookthrough.json` sector weights + top holdings |
| Inconsistent 3M/1Y account-aggregated fields | `DOCUMENTED_METHODOLOGY_SUBSTITUTE` + quality flag |
| No mature 3×3 style box | `EXPLICITLY_UNAVAILABLE` — market-cap/style exposure from buckets instead |

## Checkpoint 7 (verified against live canonical state)

```
fields_present:              32
fields_improved_vs_reference: 9   (two-way loop + capital-plan + risk heat + thesis)
fields_unavailable:          4   (perf_QTD, perf_3Y, perf_true_TWR, style_value_blend_growth)
quality_flags:              30   (substitute / flagged fields)
pdf_pages:                  null (renderer absent in this environment)
render_errors:              ["pdf renderer unavailable in this environment"]
source_traceability_pct:    100.0
```

Target source traceability is **100% of numerical report fields**; the matrix
reports `source_traceability_pct = 100.0` because every *reported* numerical
field carries a source, and the four unavailable fields are excluded rather than
estimated.

## Delivery map

- **HTML interactive report** — self-contained HTML embedded in the API response
  and written to `data/portfolios/reports/v2/`.
- **Print-perfect PDF** — the HTML carries `@page`/`@media print` rules (Letter,
  page numbers, no split rows, grayscale-safe); automated PDF uses the existing
  Playwright lane in `portfolio_report_ms.render_pdf` when a headless browser is
  present. This environment has no renderer, so `pdf_pages` is `null` and the
  render error is reported honestly.
- **Command Center report view** — `GET /api/v2/cio/report-v2` + `report_v2`
  compact block in the two-way curation health endpoint.
- **Monthly scheduled / ad-hoc** — the builder is idempotent and deterministic;
  it hooks into the existing CIO wake-job scheduler (ad-hoc + monthly) rather
  than introducing a second cron.
- **Telegram document delivery** — reuses the governed outbox lane already
  wired in `portfolio_report_ms.deliver` (`sendDocument` through the governed
  notification outbox). No new transport was created.
- **Immutable manifest** — `input_hashes` (SHA-256 of canonical input bytes),
  `source_sha` (git HEAD), and a self-referential `manifest_hash`.

## Authority

`READ_ONLY_ADVISORY`. The report composes canonical state and never promotes,
executes, or mutates. It does not constitute an order or solicitation.

## Phase 7 status

Complete.
