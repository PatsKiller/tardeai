# COGX Wave 1 · tranches 1 and 2 — foundations and shadow wiring

```
Status:      ACTIVE
as_of:       2026-09-27T20:20:00-04:00
Measured at: cbf603526 (origin/main base) / served 8f2a178d5-main-exact-phase2-20260927-171004; nothing deployed yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Every artifact here is a read, a receipt or a declaration.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1 (all 14 items, operator 2026-09-27)
```

## What tranche 1 delivers (09 §3 Wave 1, first half)

| Deliverable | Where | Proof `[VERIFIED]` |
|---|---|---|
| Façade: `open_context` / `retrieve_or_generate` / `commit` (reads + receipts; SHADOW) | `scripts/lib/intelligence_client.py` | 13 hermetic tests (`tests/test_intelligence_client_facade.py`) |
| Ring 1 memory chokepoint linter + shrink-only baseline | `scripts/check_memory_chokepoint.py`, `config/memory_chokepoint_baseline.json` | baseline: 71 files / 137 direct silo imports; ratchet test green |
| `intelligence` schema migration + safe rollback | `migrations/2026_09_27_intelligence_v1.sql` / `.down.sql` | lab proof on a throwaway DB: up = 11 tables + RLS, re-run idempotent, down = 0 policies, DB dropped |
| Heartbeat helper (file fallback + optional Postgres upsert) | `scripts/lib/supervisor_heartbeat.py` | 3 tests incl. pg absent/written/error paths |
| SLA seed from the lane registry (dry-run default) | `scripts/seed_supervisor_sla.py` | 149 lanes; heuristics tested |
| Conformance report v0 (measure only) + silo map | `scripts/report_platform_conformance.py`, `config/platform_silos.json` | dry run on this tree: 45 UNMEASURED standards, 10 silos scored (the governance-debt baseline, 05 §8) |
| Approval-package ledger + CLI + Telegram button branch (from_id verified) | `scripts/lib/approval_package.py`, `scripts/approval_package_cli.py`, `scripts/telegram_callback_handler.py` (`pkgapprove`/`pkgdeny`/`pkgshow`) | 5 tests (chain, transitions, parser, render) |
| Contracts + drift manifest | `docs/contracts/{MemoryContext,RetrievalReceipt,ApprovalPackage,LaneHeartbeat}_v1.md`, `config/contract_manifest.json`, `scripts/check_contract_manifest.py` | checker OK (4) |
| Declarations | 4 lanes `NEVER_SCHEDULED` in `config/lane_registry.json`; 5 writer rows in `config/data_source_authority.json`; CI gate `cogx_w1_foundations` in `run_cio_hardening_ci.py`; `intelligence_client` in `KNOWN_CONSUMERS` | both validators green; coverage gate: 0 new unlisted |

## What tranche 2 adds (same PR #1305)

| Deliverable | Where | Proof `[VERIFIED]` |
|---|---|---|
| Shadow hooks at the seven chokepoints: `WakeEngine.run` (DECIDE), `HermesWorker._process_one`, `hermes_external_researcher.main`, `generate_row_opinion` (ADVISE), `options_thesis_lifecycle.request_research`, `process_watchlist_agent_jobs.process_jobs`, `run_symbol_thesis_acquisition.run_one` | `shadow_open` / `observe_generation` / `shadow_commit` in the façade; each hook is fail-soft and changes no output | existing suites for those modules: 82 passed; façade tests 16 passed |
| Live proof of the façade on production state (read-only copy of `aif_memory.jsonl`, symlinked theses/results/contradictions/registry; receipts to the scratchpad; production retrievals file mtime unchanged) | subject V | `open_context` 650 ms, not degraded, `SEC:d1871bc6…` CONFIRMED, 6 facts, thesis v25 CURRENT, 2 beliefs, **7,676 open contradiction candidates**; ladder 107 ms → HIT_FRESH (step 2 thesis field + step 6 version; step 7 not installed) |
| GIR projector v1 (batch; dry-run default; `--apply` needs the migration) with the projection-side re-key (HELD:<tkr> → SEC:) | `scripts/gir_projector.py` | dry run on production persistent-state: 129,000 entities / 5,803 envelopes / 237,866 edges; 52 of 53 instrument records re-keyed; 16 theses and 0 holdings with an unresolved symbol; 118,027 contradiction entities |
| Breach detector (detect + record; no ladder action) | `scripts/supervisor_breach_detector.py`, `docs/contracts/Breach_v1.md` | dry run with a seeded SLA file against live output signals: **25 of 115 ACTIVE lanes NO_OUTPUT** (cio-delivery, cio-defer-revisit, portfolio-repricer, indicator-cache-refresh, identity-sweep-stage0, material-change-notifier-stage2, watch-review-workers, material-change-digest, due-diligence-questions, document-mentions-backfill, morning-brief-0730, …) — silent failures the health agent does not flag today; without the seed all 115 are UNGOVERNED |
| Counterfactual section in the memory shadow measure | `agent_memory_shadow_measure.run_measure` → `memory_counterfactual` | honesty tests green |
| Identity standard in conformance v0.1 (from context receipts) | `report_platform_conformance.py` | test green |
| Contradiction cap in contexts (25 rows carried, exact count always) | façade | the V context row was 1.8 MB before the cap |
| Declarations | 2 more DSA writer rows (`intelligence_gir_projection`, `supervisor_breaches`); `on_gap` chains end with `operator_ask`; lane rows carry `reason_evidence`; dark-contract declarations on the two new entrypoints; `docs/SOURCE_OF_TRUTH.md` + AGENTS §7A table re-rendered | validators green; PR-profile hardening re-run in the PR comments |

**Dropped from tranche 2, deliberately:** automatic per-package guard-grant minting on APPROVED (13 §6). The auto-mode classifier refused the change that would let the callback mint `bin/guard` grants; grants stay a manual operator action (`bin/guard grant … --reason "pkg:<id> pr:<n> sha:<sha> campaign:…"`), and the ledger records `GRANT_*` notes by hand. Revisit only on the operator's explicit instruction.

## What is NOT in Wave 1 yet (tranche 3)
- The GIR bus consumer (incremental projection) and the projector's Postgres `--apply` on production (needs the migration + roles).
- Installing the four lanes (operator cron/service grant) and the first real nightly conformance + detector runs.
- `security_guid` on the ticker research graph rows (the projection re-keys instrument records; the graph rows still carry `ticker_guid` only).
- Approval reminders (+4 h / +12 h) and expiry handling.
- Per-package guard grants (manual until the operator says otherwise).

## Operator-executed prerequisites (unchanged)
1. Rotate the plaintext DSNs (BWS edit → render → ALTER ROLE).
2. One superuser session on production: `CREATE ROLE intelligence_reader NOLOGIN; CREATE ROLE intelligence_writer NOLOGIN;`
   then `psql -d trade_ai -f migrations/2026_09_27_intelligence_v1.sql`, then the GRANT lines from the migration header.
   Rollback: `migrations/2026_09_27_intelligence_v1.down.sql` (safe); full revert is the operator's reviewed `DROP SCHEMA`.

## Closeout format (AGENTS.md §14) — filled at wave exit
Shipped: this PR. Found: `report_docs_inventory` indexes only tracked files (git add before `--write-index`); `pg_tables` has no `forcerowsecurity` column (use `pg_class.relforcerowsecurity`). Closed as already merged: none. Stopped: none. Unpublished: nothing deployed. Operator-only list: unchanged (2 prerequisites above + the 09-27 inherited items).
