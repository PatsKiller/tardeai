Status:      ACTIVE
as_of:       2026-10-09T23:00:29-04:00
Measured at: main c4782f219 / live b7dbe6e60-main-exact-phase2-20261009-210323

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
