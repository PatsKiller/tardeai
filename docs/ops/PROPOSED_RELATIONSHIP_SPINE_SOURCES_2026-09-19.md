# PROPOSED — operator decision required (AGENTS.md §17 / §7A)

```
Status: PROPOSED
as_of: 2026-09-19T21:20:00-04:00
Authority: propose-and-stop — adding a data source or writer of an authoritative store is operator-only
Subject: Relationship memory spine — first granted sources (no call sites until approved)
```

## Finding

AEC four-spine memory (`strategic` / `operational` / `relationship` / `learning`) is live.
Strategic and learning are fed by the AEC cycle; operational gains `cio_cycle_status` via #1106.
**Relationship remains empty by design** until sources carry an operator `approval` in
`config/data_source_authority.json` (§7A). Ledger row: `PARTIAL-relationship-spine-data` ◆.

## Proposal (do not apply without operator grant)

Candidate **same-question** sources for relationship facts (counterparty / broker-house /
analyst-firm / peer-set links that are **not** security identity and **not** macro):

1. **Schwab instrument `description` peer clusters** — already on disk via
   `lib/schwab_instrument_evidence` (4,997 instruments). Scope: issuer peer labels only;
   never mint CUSIP/identity; never size.
2. **Existing `document_mentions` with `role=mentioned`** — already tagged; relationship
   edge = "document about A mentions firm B as source". Writer would project mentions →
   relationship spine facts; no new provider host.
3. **Operator-curated counterparties** — manual store (like `private_company_proxies`):
   `writer: operator`, `no_coverage: refuse_up_front`.

**Not proposed:** scraping new social/graph APIs, inventing ticker→firm maps, or giving
macro series an issuer.

## Required grant shape (DataSourceAuthority@v2)

For whichever candidate is accepted, the PR that lands **only** the registry row must carry:

- `approval.approved_by: operator`
- `approved_on`, `reference` (this note / Telegram / PR)
- `scope` one-liner of what the source may supply
- single writer module, cadence, `no_coverage`, backup (same question only)

**No call site** until that row is granted (`UNAPPROVED_SOURCE` fails the build).

## Why not auto-close

§7A / §17 — agents propose registry rows and stop. This file is the proposal.
