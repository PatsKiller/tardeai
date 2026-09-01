# SEC EDGAR provider

Status:      ACTIVE
as_of:       2026-08-17T11:10:54-04:00
Measured at: efcc51365 / not measured

Read-only adapter over the existing SEC pipeline.

## Capabilities

- `sec.resolve_cik` — ticker → CIK via the canonical mapping.
- `sec.get_recent_filings` — recent EDGAR submissions (optionally filtered by form).
- `sec.get_form4_context` — recent insider (Form 4) rows from the canonical store.
- `sec.get_13f_context` — recent institutional (13F) rows from the canonical store.
- `sec.get_company_facts` — company facts (XBRL), read-only EDGAR extension.
- `sec.get_filing_metadata` — submissions metadata (name, tickers, CIK).
- `sec.compare_filing_facts` — deterministic fact comparison across two periods.
- `sec.get_decision_evidence` — assembled provenance-bound SEC evidence.

## Data sources

- Canonical store (`sec_form4`, `sec_13f`) via `db_adapter.get_connection()`.
- `data.sec.gov` read-only extension (`sec_companyfacts_reader.py`) with the
  canonical User-Agent and rate limit. No production writes.

## Missing-data states

`DATA_UNAVAILABLE` (store/network unavailable), `NOT_INGESTED` (table empty),
`NOT_APPLICABLE` (e.g. no CIK). Missing is never reported as zero.

## Aggregate decision-evidence status

`sec.get_decision_evidence` derives an honest aggregate from its component
sources (Form 4, 13F, recent filings): `OK` when all were successfully read,
`PARTIAL` when some succeeded and some were unavailable/not-ingested/
not-applicable, and `UNAVAILABLE` when no source could be read. The provenance
`source_ids` on the emitted `decision_evidence_subject` FACT name only the
sources that were actually consulted successfully — a failed read never
manufactures a fact from a source that was unavailable.
