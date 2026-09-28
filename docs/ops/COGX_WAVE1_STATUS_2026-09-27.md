# COGX Wave 1 · tranches 1–3 — foundations, shadow wiring, lane artifacts

```
Status:      ACTIVE
as_of:       2026-09-27T20:45:00-04:00
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

## What tranche 3 adds (same PR #1305)

| Deliverable | Where | Proof `[VERIFIED]` |
|---|---|---|
| Projector: ticker research graph source (RESEARCH:ARTIFACT, re-keyed to SEC: projection-side) + `--incremental` (source fingerprints in a state file; a bus consumer replaces it in Wave 2) | `scripts/gir_projector.py` | dry run on production state: 141,293 entities / 250,076 edges; 12,293 artifacts, 83 with an unresolved symbol; incremental test green |
| Approval reminders +4 h / +12 h and expiry (dry-run default; `--send` through the Telegram chokepoint) | `scripts/approval_package_reminder.py` | 1 hermetic test (once-each reminders, expiry marks items) |
| Unit files for the two systemd lanes + the two cron lines | `config/systemd/user/tradeai-supervisor-breach-detector.{service,timer}`, `tradeai-gir-projector.{service,timer}`, `docs/ops/COGX_WAVE1_CRONTAB_LINES.txt`; lane rows now name their schedulers | validators green |
| Operator runbook: every command only the operator can run, in order, with expected outputs and rollbacks | `docs/ops/COGX_WAVE1_OPERATOR_RUNBOOK_2026-09-27.md` | — |

## Findings fixed (operator: "fix findings", 2026-09-27 evening) `[VERIFIED by triage; fixes in this PR]`

**25 NO_OUTPUT breaches → 2 broken jobs, 15 wrong signals, 6 weekday lanes judged on a Sunday, 2 not yet due.**

| Root cause | Fix |
|---|---|
| The detector never queried the database, so every `db_max` lane read as silent | `supervisor_breach_detector` passes a read-only `db_query` (BEGIN READ ONLY … ROLLBACK) to `observe_signal` |
| The detector judged "3 × cadence" every day, so weekday/market-hours lanes breached every weekend | `scripts/lib/cron_schedule.py` (dependency-free 5-field cron parser); NO_OUTPUT now means "the last scheduled fire that had `max_run` to finish produced nothing"; `active_days` extends the cadence window; a declared `first_due` (e.g. `llm-spend-report-monthly` → 2026-10-01) is honoured |
| Signals that only move when the lane has work (outbox, lineage, candidates, notified_at) | pointed at the real per-run artifact (`cio_defer_revisit_last.json`, `logs/identity_sweep.log`, `logs/material_change_notify.log`, `logs/advisory_lessons.log`, dormant-lane consumers' own log); `cio-delivery` keeps its pinned outbox with a 24 h cadence; new signal kind `systemd_result` (last successful exit of a oneshot unit) for future use |
| Five signals pointed at absolute dev-tree log paths, stale since the crontab `PROJ` moved to CURRENT at 10:45 ET | made state-root-relative (`logs/…`): options thesis lifecycle, options memory projector, options runtime export, both alpaca stop managers |
| `instrument-belief-writer` signal read a count (`written_beliefs`) instead of a timestamp | key → `as_of` |
| `governed-agent-flash-market` still ACTIVE though its crontab line was retired (W0-7) | RETIRED with evidence |
| **JOB_BROKEN** `watch-review-workers`: every run refused `CONTAINMENT_REQUIRED:containment_not_active` since the operator's 09-15 "agents clear" archived the containment flag | `agent_jobs_containment.containment_cleared()` (the W0-1 precedent) and the watch-review policy gate honours the operator-cleared tripwire |
| **JOB_BROKEN** `indicator-cache-refresh`: 0 of ~800 symbols updated on three weekdays — yfinance "Too Many Requests" on every call, no backoff | `indicator_engine._history_with_backoff`: throttle, exponential backoff, and a run-level cooldown after 5 consecutive refusals (env-tunable) |

**19 unresolvable symbols → three causes, no hand-built map (AGENTS §7).**
- AIFF, GLND, HASI, SDOT: Schwab evidence (CUSIP + description) arrived with Saturday's sweep, after Friday's mint → the Monday 05:50 mint promotes them to CONFIRMED. Nothing to change; verify Monday.
- ABOVE, BLD, CXMT, EKSO: asked Schwab, `broker_returned_no_identifier`; the sweep's resume skips recorded misses. Re-ask is a sweep option (`--no-resume`), left to the Saturday lane or the operator.
- BOOK (53 artifacts), DYNC, EUDA, FUBO, IRTC, RIBB, STLN, SVCC, WBTN, YHNA, YXT: never entered the registry because the mint's symbol sources were holdings, watchlist and decision tables only. `mint_identity_registry._intelligence_surface_rows()` adds the symbol-thesis projection and the ticker research graph as additive sources; the Monday mint registers them UNRESOLVED and the Saturday sweep asks Schwab.

## What is NOT in Wave 1 yet (after the operator runbook)
- The `memory.delta` bus consumer (Wave 2) — until then the projector is hourly-incremental by source fingerprint.
- The operator steps in the runbook: credential rotation, roles + migration, merge + deploy, grants, lane install, first real runs.
- Post-deploy validation (stage 6) and marking the package items EXECUTED / VALIDATED.
- Per-package guard grants stay manual (classifier refusal).

## Operator-executed prerequisites (unchanged)
1. Rotate the plaintext DSNs (BWS edit → render → ALTER ROLE).
2. One superuser session on production: `CREATE ROLE intelligence_reader NOLOGIN; CREATE ROLE intelligence_writer NOLOGIN;`
   then `psql -d trade_ai -f migrations/2026_09_27_intelligence_v1.sql`, then the GRANT lines from the migration header.
   Rollback: `migrations/2026_09_27_intelligence_v1.down.sql` (safe); full revert is the operator's reviewed `DROP SCHEMA`.

## Closeout format (AGENTS.md §14) — filled at wave exit
Shipped: this PR. Found: `report_docs_inventory` indexes only tracked files (git add before `--write-index`); `pg_tables` has no `forcerowsecurity` column (use `pg_class.relforcerowsecurity`). Closed as already merged: none. Stopped: none. Unpublished: nothing deployed. Operator-only list: unchanged (2 prerequisites above + the 09-27 inherited items).
