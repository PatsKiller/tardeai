# Disk hygiene + disk-usage monitor on n8n (PR #1863)

Operator 2026-10-18: "a script with rules that's repeatable, n8n should run this weekly; and also monitor when a
threshold is over 80%". Operator 2026-10-19: keep the weekly lane on `--plan` (manifest), not `--dry-run`.

## What each lane does

| Lane | When | n8n live run | Writes | Deletes |
|---|---|---|---|---|
| `disk-usage-monitor` | every 15 min | `disk_usage_monitor.py --apply` | band state file, receipt, one host comms intent per band change (warn 80%, critical 90%) | nothing |
| `disk-hygiene` | Sun 04:00 ET | `disk_hygiene.py --plan` | `DiskHygieneManifest@v1` (path, kind, size, rule evidence) + `LaneRunReceipt@v2` | **nothing** |

- `--plan` writes a manifest and a receipt only. It is not `--dry-run`, which writes nothing at all. The monitor's
  "reclaimable GB" estimate reads the latest manifest, and the first real cleanup needs a manifest to review.
- `--apply` (deletion) is never an n8n argv (AGENTS.md §23.14). `disk_hygiene.py` itself refuses `--apply` under
  the n8n executor. It runs only from the operator step `hygiene-apply`, with `TRADEAI_DISK_HYGIENE_GRANT`, a
  manifest written within the configured hours, a per-item re-validation, and the byte/item caps from
  `config/disk_hygiene_rules.json`.
- Automated deletion also needs AGENTS.md 15.0.0 (#1852), which is the operator's decision.

## Order

1. Merge and promote, so CURRENT serves the PR.
2. `bash cutover.sh pre`
3. `bash cutover.sh dry-manifest`
4. `bash cutover.sh relay --apply` (`TRADEAI_FABRIC_GRANT`)
5. `bash cutover.sh publish`
6. Wait one `*/15` slot, then `bash cutover.sh proof`.
7. After the first Sunday manifest: review it, then (operator only) `bash cutover.sh hygiene-apply --apply`.
8. Rollback: `bash cutover.sh rollback --apply`.

## Evidence

- `01_dry_run_20261019.txt`: the first read-only run against the real home dir. 113 candidates,
  18.58 GB reclaimable, nothing deleted.
