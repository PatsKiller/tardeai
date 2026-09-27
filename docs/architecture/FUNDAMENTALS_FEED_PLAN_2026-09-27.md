# Fundamentals Feed Plan: SEC company facts and 8-K into the living thesis

```
Status:    PROPOSED (operator 2026-09-27: "plan fundamentals")
Authority: READ_ONLY_ADVISORY; MBI_BEHAVIOR = 0; official SEC sources only (data.sec.gov)
Parent:    PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md (Wave 2: 8-K / 10-Q / macro)
```

## Why
DELL's first house thesis (`symbol_dell@v1`) said "insufficient data". Once circular evidence was removed
(#1291), it still had only headlines and social posts. It had no revenue, margin, backlog, cash-flow or
guidance numbers.

The platform stores **no fundamentals**:
- `sec_xbrl` has 0 rows;
- `sec_13f` has 0 rows;
- `sec_data_ingest.py --all` only fetches Form 4.

Every thesis for an operating company is therefore narrative-only. The CIO review keeps flagging "no
fundamental evidence", and the traceability rail cannot cite a single reported number.

## What already exists (reuse, do not rebuild)

| Piece | Path | State |
|---|---|---|
| SEC client: CIK resolve, submissions, filings list, company facts, company concept; UA + rate limit | `scripts/lib/financial_senses/sec_companyfacts_reader.py` | Built, read-only, 3 lab/smoke consumers |
| Like-for-like period comparison (annual / quarterly / YTD, fp, frame; `COMPARISON_UNAVAILABLE` rather than a wrong delta) | `scripts/lib/financial_senses/sec_filing_diff.py` | Built, not wired |
| Governed read-only provider wrapper | `scripts/lib/financial_senses/sec_provider.py` | Built |
| Honest freshness states (FRESH / PARTIAL / STALE / UNAVAILABLE / N/A for ETFs) | `scripts/fundamentals_freshness.py` | Built |
| Store shaped for per-metric, per-period rows | Postgres `sec_xbrl` (symbol, form_type, metric_name, metric_value, unit, period_start/end, filing_date, sec_url) | Exists, empty |
| Acquisition plan already names the step | `symbol_thesis_acquisition`: `sec_filings: submissions_recent, companyfacts_key_metrics` | Planned, never executed |
| Evidence gate counts `PRIMARY_REGULATORY` | `symbol_thesis_evidence.catalog_sufficiency` | Wired, nothing produces it |

## Design

### F1: company-facts projector (the core)
**New `scripts/sec_fundamentals_ingest.py`.** Dry run by default; `--apply` writes. It is the only writer of
`sec_xbrl`.
- **Universe (priority order):**
  1. open symbol-thesis priority requests;
  2. held operating companies;
  3. options-desk symbols;
  4. active watchlist.
  - ETFs and funds are skipped as `LEGITIMATELY_NOT_APPLICABLE`.
- **Metrics:** a fixed us-gaap concept map in config `fundamentals_feed.concepts`, with fallback concept
  names per metric:
  - Revenues (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`), GrossProfit,
    OperatingIncomeLoss, NetIncomeLoss, EarningsPerShareDiluted;
  - NetCashProvidedByOperatingActivities, PaymentsToAcquirePropertyPlantAndEquipment;
  - CashAndCashEquivalentsAtCarryingValue, LongTermDebt, CommonStockSharesOutstanding;
  - RemainingPerformanceObligation (backlog), where filed.
- **Rows:** one per (symbol, metric, period_end, form_type), with sec_url set to the filing's accession
  URL. Idempotent: unique on those four columns, and an upsert only replaces a restated value, never
  deletes.
- **Derived facts,** computed with `sec_filing_diff` and never across mismatched contexts:
  - latest quarter vs the same quarter last year;
  - trailing-four-quarter totals;
  - gross and operating margin.
- **Budget:** SEC fair-access rules (10 requests/s, declared User-Agent). About 2 requests per symbol, so
  the priority universe (~100 names) finishes in under a minute.
- **Schedule:**
  - daily 21:30 ET, weekdays, for tiers 1–3;
  - Sunday for the full watchlist.
  - Each run declares a lane-registry row with an output signal (the max `created_at` in `sec_xbrl`).

### F2: facts become evidence
`symbol_thesis_evidence.retrieve_structured_sources` reads the latest `sec_xbrl` rows for the symbol.
- Items are emitted as `PRIMARY_REGULATORY`, for example: "DELL revenue Q2 FY27 $X (+Y% YoY), 10-Q filed
  2026-09-0Z", with sec_url.
- The primary-evidence gap then clears on filings, not only on curated news.
- The synthesis packet carries the numbers as supplied facts, so the CIO traceability rail can cite them.

### F3: filing events (8-K / 10-Q / 10-K)
From the same submissions call, recent 8-K items (2.02 results, 1.01 material agreements, 5.02 officer
changes, 7.01 Reg FD) become dated `SecurityEvent@v1` rows in the catalyst graph. Their guids come from
`event_identity`.
- 10-Q and 10-K filings trigger an F1 refresh for the symbol.
- A new 8-K on a held symbol files a `material_change`, so Hermes research runs with the filing in hand.

### F4: freshness and SLA
- `fundamentals_freshness.classify` runs per symbol on the stored facts.
- The curation SLA monitor gains a fundamentals line. A breach is a held or priority operating company
  whose fundamentals are `UNAVAILABLE`, or `STALE` for more than 100 days after the fiscal quarter end.
- It auto-fixes by running F1 for that symbol, and alerts if the breach survives.

### F5: surfaces
Once F1–F2 run, the Company Intelligence Record (report §11) exposes a `fundamentals` block per symbol:
- the options card shows "Fundamentals: Q2 revenue +x% YoY (10-Q 09-05)" next to the thesis pin;
- holdings reviews show the same block;
- the analyst report reads it instead of Hermes prose.

## Out of scope
- 13F institutional holdings: a separate, lower-value feed.
- Estimates and consensus: not an SEC source.
- Transcripts.
- No paid data vendor.

## Delivery (each item is its own PR, dry run first)
1. **F1:** projector, config and tests (fixtures via the injected `fetcher`). Dry run on DELL, HOOD, V,
   NOC. Then the cron line, under a grant.
2. **F2:** evidence wiring. Proof: DELL's catalog shows `PRIMARY_REGULATORY` items; re-acquisition
   publishes a v2 thesis citing reported numbers.
3. **F3:** 8-K events into the catalyst graph and material-change triggers.
4. **F4:** freshness SLA line in the monitor.
5. **F5:** CIR fundamentals block on cards (with the Wave 1 read API).

## Verification
- **Unit:** the concept fallback map, restatement upserts, and that period mismatches produce
  `COMPARISON_UNAVAILABLE`, not a delta.
- **Live:**
  - `sec_xbrl` rows for DELL carry sec_url;
  - the DELL catalog `counts.primary_or_approved` includes filings;
  - the thesis v2 summary contains reported numbers that trace to `sec_xbrl`;
  - the next options CIO review for DELL cites them.
