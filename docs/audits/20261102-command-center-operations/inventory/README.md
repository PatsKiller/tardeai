# Command Center inventory — frozen capture (2026-11-02T18:45:27Z)

> **Snapshot, not current state.** Captured **2026-11-02T18:45:27.608050Z (UTC)** from the lane
> registry blob `60a4c9461ae50c24281e9454235dec99a0c44363449adab2e8ddbfc9be63dba4`
> (1,441,163 bytes), the missed-run watchdog snapshot and a bounded `safe_flock` window. A lane
> added, retired, re-owned or re-scheduled after that instant is **not** represented here.

## Refresh

On the host, from the repository root:

```bash
# 1. Is the capture still a fair description of the registry?
python3 scripts/build_command_center_audit_inventory.py --check
# exit 0 = no drift; exit 2 = drift, with every added/removed/re-owned lane named

# 2. Write a refreshed capture (never overwrites this frozen directory)
python3 scripts/build_command_center_audit_inventory.py --write --out <new-dir>
```

`--check` compares only the registry projection (`owner`, `registry_state`, `scheduler_kind`).
Runtime execution evidence — attempts, completions, receipts — is re-measured by the served
Jobs reader (`scripts/lib/jobs_health.py`); the refresh tool preserves that evidence and never
runs a lane, reads a credential or invents a success.

Files: `inventory.json` (687 rows), `inventory.csv`, `summary.json`, `coverage.md`,
`runtime_orphans.csv`, `ticket_groups.json` and `evidence_manifest.json` (original hashes).
