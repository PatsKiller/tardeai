# COGX Wave 1 · tranche 1 — foundations shipped in SHADOW

```
Status:      ACTIVE
as_of:       2026-09-27T19:45:00-04:00
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

## What is NOT in tranche 1 (tranche 2, same wave)
- Wiring the façade into `WakeEngine.run`, `HermesWorker._process_one` and the other five producers (shadow receipts at the chokepoints).
- The GIR projector (batch + bus consumer) and the breach detector body; the four lanes stay NEVER_SCHEDULED until then.
- `security_guid` re-key of the ticker graph and beliefs (09-27 W1 item).
- Counterfactuals in the memory shadow measure.
- Per-package guard-grant minting on APPROVED (13 §6) in the callback poller.
- Identity standard measurement in the conformance report (UNMEASURED by design in v0).

## Operator-executed prerequisites (unchanged)
1. Rotate the plaintext DSNs (BWS edit → render → ALTER ROLE).
2. One superuser session on production: `CREATE ROLE intelligence_reader NOLOGIN; CREATE ROLE intelligence_writer NOLOGIN;`
   then `psql -d trade_ai -f migrations/2026_09_27_intelligence_v1.sql`, then the GRANT lines from the migration header.
   Rollback: `migrations/2026_09_27_intelligence_v1.down.sql` (safe); full revert is the operator's reviewed `DROP SCHEMA`.

## Closeout format (AGENTS.md §14) — filled at wave exit
Shipped: this PR. Found: `report_docs_inventory` indexes only tracked files (git add before `--write-index`); `pg_tables` has no `forcerowsecurity` column (use `pg_class.relforcerowsecurity`). Closed as already merged: none. Stopped: none. Unpublished: nothing deployed. Operator-only list: unchanged (2 prerequisites above + the 09-27 inherited items).
