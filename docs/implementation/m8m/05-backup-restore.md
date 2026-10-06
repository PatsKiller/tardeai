# 05 — Backup and restore

A green timer is not a restore. This pass did not restore anything and did not delete a dump.

## Trade AI Postgres dump

| Field | Value |
|---|---|
| Live timer | `tradeai-portfolio-backup-cadence.timer`, enabled, `OnCalendar=*-*-* 02:30:00`, timezone America/New_York |
| Last trigger | Tue 2026-10-06 02:30:00 EDT |
| Next trigger | Wed 2026-10-07 02:30:00 EDT, then Thu 2026-10-08 02:30:00 EDT |
| Unit | `tradeai-portfolio-backup-cadence.service`, `WorkingDirectory` `portfolio-server/CURRENT`, `ExecStart` that release's `scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence backup --apply` |
| Artifact | `/home/johnclaw/db_backups/trade_ai_20261006_023000.sql.gz` |
| Bytes | 2972023720 |
| mtime | 2026-10-06T06:50:44Z |
| sha256 | `f01a399c8ead203abc957c7e6ad2482bf2f25402160ff32fa6e0b451d4e28d0d` |
| Log | `db_backups/backup.log` last line: retention cleanup done, 1 backup retained, `total_bytes` 2972023720, `over_bytes` false |
| Legacy timer | `portfolio-backup.timer` `OnCalendar` 02:00, **disabled**, inactive |
| Enforcer | `tradeai-backup-enforcer.timer` hourly, last 2026-10-06 11:00 ET, next 12:00 ET. Its code pin is the rebuild tree (D-SCHED-004). |

Catalog, read-only, role `trade_ai`:

| Schema | Tables | RLS | FORCE RLS |
|---|---:|---:|---:|
| public | 696 | 0 | 0 |
| intelligence | 11 | 7 | 7 |
| memory_r10_m2 | 6 | 6 | 6 |

`run_pg_backup.sh` on the freeze pin excludes data from `intelligence.*` and `memory_r10_m2.*` and refuses a gzip under 1.5GB. The dump is above that floor. The gzip was not opened, so excluded-table absence is **NOT_MEASURED**. Offsite upload receipt is **NOT_MEASURED**. Isolated restore is **NOT_RUN**. Restoring this file over production is out of scope.

`memory_r10_m2` counts returned 0 to role `trade_ai`. Under FORCE RLS that is not proof the tables are empty.

## DOF application backup

`/home/johnclaw/nyc-dof-auction/logs/backup.log` is 291 bytes, mtime 2026-05-11T05:50:02Z, last line a success stamp at 01:50 EDT that day. No later receipt. The Trade AI dump includes `public.dof_*` only to the extent `pg_dump` of database `trade_ai` includes `public`. That is a shared-database side effect, not a DOF-owned backup plan. DOF secret recovery was not tested. Tarball names under the DOF checkout were not opened.
