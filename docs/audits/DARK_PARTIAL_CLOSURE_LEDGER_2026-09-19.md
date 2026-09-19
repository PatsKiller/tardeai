# DARK / PARTIAL / UNWIRED closure ledger

```
Status: ACTIVE
as_of: 2026-09-19T13:45:00-04:00
Measured at: code census on origin/main@99c79ec17 + in-flight PRs #1081/#1082
Authority: operator /plan rail-to-full; shrink-only
Canonical: docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md
```

**Rule:** this table may only shrink or move rows to CLOSED with proof. Adding a row requires naming the evidence that it is dark/partial.

| id | status | evidence | closure path | proof required |
|---|---|---|---|---|
| DARK-load-by-subject-schedule | PARTIAL | cron `*/5` CURRENT + entrypoint load-by-subject [VERIFIED] 2026-09-19; log shows wakes with no_subject=5 so record_found=0 | Fix subject resolution on wake enqueue | OBSERVED record_found>0 unattended |
| DARK-bitemporal-m2-substrate | PARTIAL | schema v2 + CIOEnvelopeIntegrator on :55432; 211 correctness tests; EXPLAIN Index Scan fact_valid_spgist; production :5432 NOT applied | Organic wake schedule + operator shadow cutover grant | OBSERVED unattended write from served |
| DARK-OUTCOME-settlement | PARTIAL | AEC cycle calls `evaluate_commitment` → CommitmentOutcome@v1 | Organic observer + served schedule | OBSERVED CONFIRMED/REFUTED |
| DARK-AgentView-producer | PARTIAL | AEC cycle calls `produce_agent_view_v1` (2026-09-19); shadow cortex also produces | Schedule cycle / wake load | OBSERVED from served |
| DARK-AGENT_COMMITMENT-producer | PARTIAL | AEC cycle mints via `mint_commitment_from_view` when critic_pass | Persist commitment store + OUTCOME | OBSERVED settlement |
| DARK-librarian-index | CLOSED | [VERIFIED] persistent-state + CURRENT `research_source_index.json` ResearchSourceIndex@v1 n_sources=120 (mtime 2026-09-16) | — | file present on served path |
| DARK-hermes_advisory_event_enqueue | KNOWN DARK | AGENTS research table | Wire or RETIRE with reason | consumer or RETIRED row |
| DARK-KNOWN_DARK-cio_identity_resolver | KNOWN_DARK | test_identity_memory_module_wiring | Wire to decision path or retire | removed from KNOWN_DARK |
| DARK-KNOWN_DARK-cio_disposition_identity | KNOWN_DARK | same | Wire disposition path | removed from KNOWN_DARK |
| PARTIAL-telegram-CIO-stance | PARTIAL | PR #1082 | Merge+promote | live hold receipt |
| PARTIAL-bridge-pin-soak | PARTIAL | streak 1/3 | #1081 + promotes | soak_ready=YES |
| PARTIAL-quality-escalate-organic | PARTIAL | code on #1081; flag off | Flag on served + organic thin answer | receipt spilled_to/free climb |
| PARTIAL-soft-share-live-SLO | PARTIAL | hermetic PASS; live soft 0.22 stored | Promote fix + new agent rows | SLO ok on post-promote window |
| PARTIAL-M1-M5 | PARTIAL | reporter mostly NOT_OBSERVED | Organic proofs | all five OBSERVED |
| PARTIAL-CIO-Advisor-Narrator-mesh | PARTIAL/◆ | license granted; scaffold landing | This PR bus+spines+cycle | cycle dry-run + apply receipt |
| PARTIAL-memory-four-spines | ◆→PARTIAL | scaffold | Persist + load-before-decide on wake | wake reads spines |
| PARTIAL-relationship-spine-data | ◆ | no domain data yet | Operator-approved sources only | registry approval rows |
| PARTIAL-narrator-unprompted-telegram | PARTIAL | aec_narrator renders brief; cycle dry-runs; live notify is explicit-flag only | Schedule + --notify under telegram grant + COVERS | unprompted brief delivered |
| FORBIDDEN-broker | FORBIDDEN | §0/§2 | never | N/A |

## Closed this wave

| id | closed_at | proof |
|---|---|---|
| DARK-librarian-index | 2026-09-19 | research_source_index.json n=120 on CURRENT+persistent-state |
