# Acceptance profile

Status:      ACTIVE
as_of:       2026-08-17T13:10:42-04:00
Measured at: efcc51365 / not measured

`FINANCIAL_SENSES_FOUNDATION_ACCEPTANCE` — 30 gates. Each gate is PASS (no
partial credit), or honestly `NOT_CONFIGURED` where a live credential is absent
but the contract/fixtures/docs are complete.

| Gate | Criterion | Status |
|---|---|---|
| FS-1 | dedicated worktree/branch isolation | PASS |
| FS-2 | no production runtime mutation | PASS |
| FS-3 | existing SEC pipeline inventoried | PASS |
| FS-4 | no duplicate SEC ingestion scheduler | PASS |
| FS-5 | SEC provider read-only | PASS |
| FS-6 | SEC company facts provenance | PASS |
| FS-7 | SEC filing diff deterministic | PASS |
| FS-8 | macro provider read-only | PASS |
| FS-9 | ALFRED decision-time vintage protection | PASS |
| FS-10 | instrument identity ambiguity fail-closed | PASS |
| FS-11 | no identity guessing | PASS |
| FS-12 | stress engine deterministic | PASS |
| FS-13 | no fabricated sensitivity | PASS |
| FS-14 | unmodeled portfolio value explicit | PASS |
| FS-15 | factor loadings sourced | PASS |
| FS-16 | theme/GICS distinction preserved | PASS |
| FS-17 | claim graph provenance required | PASS |
| FS-18 | contradictions retained | PASS |
| FS-19 | memory/reference node non-authoritative | PASS |
| FS-20 | critic shadow-only | PASS |
| FS-21 | critic cannot modify live decision | PASS |
| FS-22 | provider failure fail-soft | PASS |
| FS-23 | no arbitrary URL/shell/write | PASS |
| FS-24 | unit suite pass | PASS (256) |
| FS-25 | integration/contract suite pass | PASS |
| FS-26 | dry replay pass | PASS |
| FS-27 | documentation complete | PASS |
| FS-28 | AIF integration contract documented | PASS |
| FS-29 | merge overlap audited | PASS |
| FS-30 | READ_ONLY_ADVISORY | PASS |

`NOT_CONFIGURED` is acceptable only for live provider connectivity (FRED key,
OpenFIGI key) where the contract, fixtures, failure handling, and docs are
complete and honest — which they are.
