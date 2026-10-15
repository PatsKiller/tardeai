# 07 — DOF

DOF is not broker truth, not a trade thesis, not title status, and not a bid. Vehicle identifiers are omitted. Row counts are table sizes only.

## What is running

User service `dof-dashboard.service` listens on `0.0.0.0:7776` and returns HTTP 200. The process executes the dirty checkout's `dof_server.py`, whose sha256 does not match commit `5d3c39e`. Details are in `00-served-baseline.md` and D-DOF-003.

Committed tree on `master` has no `AGENTS.md`. Policy for edits is "do not touch the dirty checkout." A clean worktree is `/home/johnclaw/dof-wt-m8m-phase0` at `5d3c39e`, branch `wt/m8m-phase0-baseline-20261006`.

## Scheduled lines actually present

| Schedule | Command | Last evidence |
|---|---|---|
| `0 18 * * *` | `scripts/rescan_tickets.py` from `/home/johnclaw/nyc-dof-auction` | Log mtime 2026-10-05T22:00:01Z (18:00 ET). Auth failure. D-DOF-001. Next fire 2026-10-06 18:00 ET. |
| `0 20 * * 6` | `scripts/run_pipeline.py` | Log: 2026-10-03 20:00:03 ET, stages 1–6 exit 1. D-DOF-002. Next fire 2026-10-10 20:00 ET. |

`scripts/backup_dof.sh` is in the tree and not in this crontab. `logs/backup.log` last success is 2026-05-11. D-DOF-006.

## Database

There is no second Postgres database. `public.dof_*` tables are in `trade_ai`, owned operationally by the same login role as Trade AI. D-DOF-004.

| Table | Count | Note |
|---|---:|---|
| `dof_vehicles` | 4137 | `auction_date` max 2026-07-17 |
| `dof_vehicle_scores` | 4137 | |
| `dof_vehicle_enrichment` | 4137 | |
| `dof_auction_runs` | 110 | `run_date` max 2026-07-18 20:00:29-04:00 |
| `dof_ticket_lookups` | 3005 | `most_recent_ticket` max 2028-09-02 is a ticket date column, not a scan clock |
| `dof_ticket_events` | 87152 | |
| `dof_pdf_history` | 993 | |
| `dof_manual_queue` | 1716 | |
| `dof_enrichment_queue` | 226 | |
| `dof_dmv_lookups` | 1407 | |
| `dof_price_snapshots` | 1441 | |
| `dof_price_segment_cache` | 1757 | |
| `dof_auction_history` | 0 | |
| `dof_jobs` | 0 | |
| `dof_vinaudit_results` | 0 | |
| `dof_nicb_results` | 0 | |

July 18 is the newest auction-run clock found. October pipeline fires are failing, so this is not an October catalog. Human review queues have rows; that does not authorize a bid or a title conclusion.

`stage1.log` still ends on 2026-05-10 with a download summary. It is not the October 3 stage-1 record.

## Drive

No DOF documentation folder was found. The only folder returned for a DOF title search is `DOF-Auction-Backups`. It was not listed and was not used as a destination.
