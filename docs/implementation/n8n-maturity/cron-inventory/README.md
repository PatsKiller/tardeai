Status:      ACTIVE
as_of:       2026-10-10T17:30:00-04:00 (change log); inventory data as last rebuilt (#1649)
Measured at: main 2aa2cc37d / live af292381c-main-exact-phase2-20261010-113824 (change log); data: main c4782f219 / live b7dbe6e60

# Cron inventory — system of record

Operator mandate (2026-10-09 ~21:50 ET): **no cron job, timer, health-tick step or n8n workflow is migrated, modified,
disabled, consolidated or retired until its row here is documented, classified, reviewed and approved.** This folder is
that record. It is updated **every time a job is retired, consolidated or cut over** (operator 2026-10-09 ~23:00 ET).

| File | What |
|---|---|
| `CRON_INVENTORY.md` | Every scheduled unit (676 at baseline), grouped by classification, with a detailed **notes** column (what to refactor, blockers, what must be proven, known issues) |
| `data/inventory.csv` | The same rows, all columns (SCHEMA.md + `x_*` provenance) — machine-readable source |
| `data/CRON_INVENTORY.xlsx` | Workbook: Read Me, Dashboard, Tracker, Inventory, Overlaps Top20, Duplicates, Consolidation, Critical Paths |
| `SCHEMA.md` | Column definitions and the six classifications |
| `REMEDIATION_PLAN.md` | Ranked fixes (P0–P3), decisions log, migration roadmap |
| `GOVERNANCE_ANALYSIS.md`, `DEPENDENCY_MAP.md` | Schedule overlaps, duplicates, consolidation tiers, dependency map, critical paths |
| `data/*.csv` | Duplicates, consolidation, critical paths, top-20 overlap windows (full minute-level data kept on the host) |

## How it is updated

1. A change (retire / consolidate / cut over) happens only after its row's `approval_status` is **Approved** and the
   named grant exists (AGENTS §9.3, §23.2, §23.12).
2. The builders on the host (`~/n8n-maturity-verification/cron-inventory/build_inventory.py` then `build_workbook.py`)
   re-read crontab, timers, the lane registry, the run ledger, logs and the enrichment files, and regenerate every file here.
3. The regenerated files land by PR (`n8nmat/cron-inventory-*`) with the change log entry below.

## Change log

| Date (ET) | Change | Rows | Evidence |
|---|---|---|---|
| 2026-10-09 22:54 | Baseline inventory (676 units; 560 active) | all | builder run; enrichment S1–S6 |
| 2026-10-09 22:30 | maturity-remeasure: n8n live workflow e18d7849b4142927 unpublished (operator option b); cron L1000 single scheduler | cron:L1000, n8n:e18d7849b4142927 | grant 26b8747d6cc949bb |
| 2026-10-09 22:55 | 16 RELAY_HOST shadow workflows archived (V8 F1) | 16 n8n rows | grant ee4dfdf11479cd3c; operator-run packets/archive-16.sh |
| 2026-10-10 09:47 | Retire batch 1 applied: 17 cron lines commented `# RETIRED`, 16 timers/services disabled (steph/morgan/alex kept); inventory rebuilt (95 Retired) | 33 units (#1638 registry) | cron grant e823cbea72948774; crontab backup n8n_cutover/crontab-before-retire-batch1-20261010T134726Z.txt; check_lane_registry clean rc 0; check_expected_services no new non-OK |
| 2026-10-10 12:54 | Dispatch shadow wave 1: 22 cron rows gain `stage: shadow` + `dispatch.mode: dry_run` (allowlist `live_arg: null`); cron lines unchanged and still do the work | 22 registry rows (cron:L220 L222 L526 L576 L389 L703 L217 L440 L502 L210 L671 L472 L642 L175 L204 L363 L626 L349 L369 L352 L549 L683) | merge #1656; per-lane dry runs from CURRENT, 52 receipt/signal files unchanged |
| 2026-10-10 13:07 | Executor v2 enabled (3 workers) for the n8n run executor; no cron line changed | systemd `tradeai-n8n-run-executor` drop-in `10-executor-v2.conf` | service grant eebd4ca0a6b31bd2; `packets/executor-v2-evidence/enable-20261010.log` |
| 2026-10-10 15:53 | W0: six generic n8n workflows imported inactive and published | n8n `tradeai-*` (6) | grant f9c459a230d3bc58; `packets/w0-import-six/apply-20261010.txt`, `publish-20261010.txt` |
| 2026-10-10 15:58 | W0 rolled back: the six unpublished (403 `bad_lane_filter`, 404 `POST /event`; RC8); rows kept inactive, never deleted | n8n `tradeai-*` (6) | same grant; `rollback-unpublish-20261010.txt`; fix #1663/#1664 |
| 2026-10-10 15:58 | Dispatch shadow waves 2+3: 14 more shadow rows; 19 R1 rows staged `r1_pending` (inert until activation) | 14 + 19 registry rows (wave 2: cron:L433 L435 L444 L1000 L1002 L969 L975 L137 L147 L161 L605 L908 L685 L686; wave 3: L381 L406 L420 L447 L750 L413 L504 L418 L553 L508 L552 L877 L409 L411 L551 L408 L318 L314 L427) | merge #1661; dry runs from CURRENT, 154,675-file snapshot unchanged |
| 2026-10-10 16:20 | `flock -n` added to crontab L318 (agent_outcome_linker), L314 (agent_calibration_engine), L427 (update_agent_performance) so their allowlist locks equal the cron locks | cron:L318 L314 L427 | cron grant 08c0bb77ec898136; backup `~/.local/state/tradeai/backups/crontab-20261010T202023Z-pre-wave23-flock.txt`; `packets/wave23-flock/` |
| 2026-10-10 16:27 | Gateway lane `n8n-workflow-error` allowed (relay `POST /event`); no cron line changed | systemd `tradeai-n8n-coordination-gateway` drop-in `20-workflow-error-lane.conf` | config-write 8c235faa82733127, service 7752d1c23506de55; `packets/gateway-lane-evidence/install-20261010.log` |
| pending | Wave-3 activation: the 19 staged R1 rows move to `stage: shadow` (`dispatch.mode: dry_run`) | 19 registry rows | #1665 (OPEN) |

Procedure for any n8n change that this log records: `../N8N_ONBOARDING_STANDARD.md`; configuration reference:
`../N8N_CONFIGURATION.md`.
