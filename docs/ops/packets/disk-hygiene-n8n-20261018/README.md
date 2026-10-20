# Disk hygiene + disk-usage monitor on n8n (PR #1863)

Operator 2026-10-18: "a script with rules that's repeatable, n8n should run this weekly; and also monitor when a
threshold is over 80%". Operator 2026-10-19: keep the weekly lane on `--plan` (manifest), not `--dry-run`.

## What each lane does

| Lane | When | n8n live run | Writes | Deletes |
|---|---|---|---|---|
| `disk-usage-monitor` | every 15 min | `disk_usage_monitor.py --apply` | band state file, receipt, one host comms intent per band change (warn 80%, critical 90%) | nothing |
| `disk-hygiene` | Sun 04:00 ET | `disk_hygiene.py --plan` | `DiskHygieneManifest@v1` (path, kind, size, rule evidence) + `LaneRunReceipt@v2` | **nothing** |
| `tmp-hygiene` | daily 05:00 ET | `tmp_hygiene.py --plan` | `DiskHygieneManifest@v1` with `scope: "tmp"` (path, kind, file_count, size, rule evidence) + `LaneRunReceipt@v2` | **nothing** |

- `--plan` writes a manifest and a receipt only. It is not `--dry-run`, which writes nothing at all. The monitor's
  "reclaimable GB" estimate reads the latest manifest, and the first real cleanup needs a manifest to review.
- Destructive `--apply` is **unsupported under ACTIVE policy** in both Python APIs/CLIs and the
  `hygiene-apply --apply` / `tmp-apply --apply` packet commands. They refuse before manifest/rule reads,
  state writes or effects. No caller token, including `TRADEAI_DISK_HYGIENE_GRANT`, creates authority.
- AGENTS.md §0 rule 6 and §17 still apply. Proposed 15.0.0 (#1852) is not active authority, and even a
  future policy decision cannot enable these hard holds without a separately reviewed implementation.
  The planning rules/caps and historical records remain available; this change authorizes no deletion.

## Incident 2026-10-19: /tmp ran out of inodes, not bytes

At about 13:40 ET, /tmp (a tmpfs: 31G, 1,048,576 inodes) reached 97% of its inodes while 20G of bytes were free.
Tools failed with ENOSPC. The files sat in three places:

- ended Claude sessions' scratch dirs `/tmp/claude-<uid>/<project>/<uuid>/`. One held 207k files (git worktrees and
  pytest temp).
- `/tmp/pytest-of-johnclaw` (57k files).
- long-running campaign dirs such as `/tmp/n8n-campaign-20261018` (243k files, still in use).

Nothing caught it. The monitor checked bytes only, and the hygiene rules covered home-dir clones and releases only.
The operator approved a one-off manual cleanup (back to 55%) and this follow-up (2026-10-19):

- **Inode bands.** `disk_usage_monitor.py` now also bands inode use per mount (statvfs `f_files` / `f_ffree`), and
  `/tmp` is a monitored mount. Inode thresholds are separate from byte thresholds (`monitor.inodes`, warn 80, critical
  90). State and dedupe are per (mount, metric), so an inode alert never hides a byte alert or the reverse. The alert
  names the top `/tmp` dirs by file count (bounded scan: depth 3 at most, a time cap and an entry cap) and the latest
  `/tmp` plan's reclaimable inodes. It uses the same intent path as the byte alert (`CommsIntentStore`).
- **`tmp-hygiene` lane** (`scripts/tmp_hygiene.py`, rules `config/disk_hygiene_rules.json` `tmp`). Only two patterns
  are ever evaluated:
  - a session scratch dir is a candidate only if all of these hold: its whole tree is idle for more than 2 days;
    no process has its cwd inside; no process holds an open fd inside; its transcript
    `~/.claude/projects/<project>/<uuid>.jsonl` (when present) is older than 2 days; and every git tree inside is
    safe to drop. A registered worktree must be clean with no commit reachable only from its HEAD, and its registration is recorded in the plan. Existing low-level removal mechanics remain dormant; no public
    apply path may invoke them.
  - a `pytest-of-<user>/pytest-*` dir is a candidate when it is older than 1 day and nothing has a cwd or open fd
    inside.

  Every other /tmp entry (`n8n-campaign-*`, `tradeai-*`, `momentum-*` and so on) is never scanned and never a
  candidate. The manifest records `file_count` per item and reports inodes reclaimable alongside bytes.
- `/tmp` has the same unconditional public apply hold as the home rules. A candidate is planning evidence,
  not deletion eligibility or authority.

## Order

1. Merge and promote, so CURRENT serves the PR.
2. `bash cutover.sh pre`
3. `bash cutover.sh dry-manifest`
4. `bash cutover.sh relay --apply` (`TRADEAI_FABRIC_GRANT` + `TRADEAI_FABRIC_SERVICE_GRANT`; see Grants)
5. `bash cutover.sh publish`
6. Wait one `*/15` slot, then `bash cutover.sh proof`.
7. After the first Sunday manifest: review it with `bash cutover.sh hygiene-apply` (read-only preview).
8. `/tmp`: `bash cutover.sh tmp-dry` (read-only) at any time. After the first daily `tmp-hygiene` manifest, review it,
   with `bash cutover.sh tmp-apply` (read-only preview).
9. Rollback: `bash cutover.sh rollback --apply` (drops all three lanes from the live list; same two grants).

## Grants

`relay --apply` and `rollback --apply` use main's bounded grant model (PR #1873, `scripts/lib/fabric_grant.py`).
Each step runs `fabric_grant.py authorize disk-hygiene.<step>` as a read-only check first. It then runs
`authorize disk-hygiene.<step> --consume` immediately before the live-list write. That call rechecks every required
grant and consumes one finite use of each, atomically under the guard lock. Dry runs consume nothing. A refused or
failed step refunds nothing. Each variable holds the full 32-hex ledger id (`bin/guard id <tier>`), never a label.

| Variable | Tier | The grant reason must name |
| --- | --- | --- |
| `TRADEAI_FABRIC_GRANT` | `config-write` | the action (`disk-hygiene.relay` or `disk-hygiene.rollback`), `disk-usage-monitor`, `disk-hygiene`, `tmp-hygiene`, `tradeai-dispatcher`, and the SHA256 of this `cutover.sh` |
| `TRADEAI_FABRIC_SERVICE_GRANT` | `service` | all of the above, plus `tradeai-n8n-run-relay.service`, `tradeai-n8n-coordination-gateway.service` and `restart` (both units are restarted) |

Every token must appear as a whole word. The action names the step, so a relay grant cannot authorize a rollback.
Any edit to `cutover.sh` changes its SHA256, so a grant must be issued against the packet bytes that will run.

`hygiene-apply --apply` and `tmp-apply --apply` now always refuse with
`destructive_apply_unsupported_by_active_policy`. They never inspect or consume a grant. The earlier
presence-only token was not a verified authority contract. No disk-hygiene grant tier is added here.
Planning, monitor behavior, existing independent host backstops and historical receipts remain unchanged.
Campaign workflow/live-list/owner cutover and release approval remain separate; this safety fix activates nothing.

## Evidence

- `01_dry_run_20261019.txt`: the first read-only run against the real home dir. 113 candidates,
  18.58 GB reclaimable, nothing deleted.
- `02_tmp_dry_run_20261019.txt`: the first read-only `/tmp` run, taken after the manual cleanup (/tmp at about 55%
  inodes). 16 candidates (ended session scratch dirs), 8.9k inodes and 0.34 GB reclaimable, nothing deleted.
  Excluded: 9 for recent activity (pytest dirs and live sessions, 55.2k inodes), 2 for an open fd, 1 for a live
  transcript, and 1 for a dirty git worktree. 17,991 entries match no rule and were never scanned (505 on the
  never-touch globs).
