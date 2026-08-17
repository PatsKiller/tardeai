# ADR-001 — Reuse the existing SEC pipeline

**Status:** Accepted

## Context

Trade AI already has SEC EDGAR ingestion (`scripts/sec_data_ingest.py`),
database tables (`sec_form4`, `sec_13f`, `sec_xbrl`), rate limiting, and
User-Agent conventions.

## Decision

Build `SecEdgarProvider` as a read-only adapter over that pipeline. Do not build
a second ingestion scheduler, a competing database, or another Form 4 crawler.
Company facts / filing metadata / filing diff are served through a bounded
read-only EDGAR extension only where the canonical store lacks them.

## Consequences

- One SEC truth / ingestion path; multiple governed read adapters.
- No production SEC writes from this branch; no second scheduler.
