---
id: DSN-20261030-workspace-lifecycle
title: 'Workspace lifecycle — no agent leaves garbage, and a recurring sweep proves it'
status: PROPOSED
approval: OPERATOR (AGENTS.md 29.0.0 MAJOR — §24.12/§24.14/§17; schedule activation §25.10.2)
source: operator 2026-10-30, verbatim — "this was a point in time cleanup you did. I need you to architect and create a methodology, an agent, or jobs in N8N, whatever you need to monitor this and do this daily, weekly, or when it gets to a certain size and make sure it's recursive. Moreover, we should have in the agents.md files the rules for doing all of this. It shouldn't just be leaving garbage all around."
summary: >
  Three layers. (1) Prevention: every workspace an agent makes is declared on its claim and closed by the agent when
  the claim ends (archive, then remove). (2) Recurring sweep: the n8n `disk-hygiene` lane applies the reviewed
  standing rules daily, re-runs itself under disk pressure until the target is met or nothing is reclaimable, and
  prunes its own archives weekly. (3) Monitoring: the 15-minute disk monitor triggers the pressure sweep and alerts
  with the held categories when the sweep cannot reach target. AGENTS.md §24.14 makes the lifecycle binding.
phases:
- id: DSN-20261030-workspace-lifecycle-P1
  title: Prevention — agents close what they open
  status: PROPOSED
  tasks:
  - id: DSN-20261030-workspace-lifecycle-P1-T1
    title: agent_claim.py `close` — archive-then-remove the claim's own worktree and scratch; run on done/release
    areas: [scripts/agent_claim.py, scripts/lib/workspace_closeout.py, tests/]
  - id: DSN-20261030-workspace-lifecycle-P1-T2
    title: new-worktree.sh sets a per-claim scratch root (TMPDIR under ~/.cache/agent-tmp/<claim-id>); pytest keeps only failed-test tmp dirs
    areas: [scripts/new-worktree.sh, pyproject.toml]
  - id: DSN-20261030-workspace-lifecycle-P1-T3
    title: Release prepare stops copying .env.* backups into every release
    areas: [scripts/cio_phase2_exact_main_deploy.sh]
- id: DSN-20261030-workspace-lifecycle-P2
  title: Recurring sweep — standing rules C and R, archive retention, pressure loop
  status: PROPOSED
  tasks:
  - id: DSN-20261030-workspace-lifecycle-P2-T1
    title: Rule C — abandoned worktree close-out (archive ref, then remove) in disk_hygiene standing path
    areas: [scripts/disk_hygiene.py, scripts/lib/workspace_closeout.py, config/disk_hygiene_rules.json]
  - id: DSN-20261030-workspace-lifecycle-P2-T2
    title: Rule R — release-only standing reclaim (= DSN-20261030-disk-recovery-P2-T1, operator-approved 2026-10-30)
    areas: [scripts/disk_hygiene.py, config/disk_hygiene_rules.json]
  - id: DSN-20261030-workspace-lifecycle-P2-T3
    title: Rule X — archive retention (closeout refs and rule-T bundles older than retention_days)
    areas: [scripts/disk_hygiene.py, config/disk_hygiene_rules.json]
  - id: DSN-20261030-workspace-lifecycle-P2-T4
    title: Pressure loop — --until-target re-plans and re-applies, bounded passes, alert when held
    areas: [scripts/disk_hygiene.py, scripts/disk_usage_monitor.py]
- id: DSN-20261030-workspace-lifecycle-P3
  title: Schedule and monitor on n8n
  status: PROPOSED
  tasks:
  - id: DSN-20261030-workspace-lifecycle-P3-T1
    title: disk-hygiene lane standing argv daily 03:30 ET; weekly Sunday retention; monitor-triggered pressure run
    areas: [config/n8n_run_allowlist.json, config/lane_registry.json, n8n/]
- id: DSN-20261030-workspace-lifecycle-P4
  title: Backups — one dump on host, N+1 on Drive, verified before removal
  status: PROPOSED
  tasks:
  - id: DSN-20261030-workspace-lifecycle-P4-T1
    title: backup_enforcer removes (not archives) the older host dump after the newer one is gzip-tested and its Drive object verified; Drive keeps drive_db.keep_n + 1
    areas: [scripts/backup_enforcer.py, scripts/backup_secrets_state.sh, config/backup_policy.yaml]
  - id: DSN-20261030-workspace-lifecycle-P4-T2
    title: Upload success requires the Drive object (name, size, md5) — subsumes DSN-20261030-disk-recovery-P2-T4
    areas: [scripts/backup_secrets_state.sh]
- id: DSN-20261030-workspace-lifecycle-P5
  title: Growth audit — twice weekly and on anomaly, every byte attributed
  status: PROPOSED
  tasks:
  - id: DSN-20261030-workspace-lifecycle-P5-T1
    title: disk-growth-audit lane (Tue/Fri + monitor anomaly) — per-root deltas, owner attribution, unattributed growth to the operator
    areas: [scripts/disk_growth_audit.py, config/disk_hygiene_rules.json, config/lane_registry.json]
- id: DSN-20261030-workspace-lifecycle-P6
  title: Move the .env-sourcing crons that the cutover directive covers to n8n
  status: PROPOSED
  tasks:
  - id: DSN-20261030-workspace-lifecycle-P6-T1
    title: Register finviz_industry_groups, sector_momentum_engine, warm_caches (undeclared schedulers, §9.3)
    areas: [config/lane_registry.json]
  - id: DSN-20261030-workspace-lifecycle-P6-T2
    title: Cut over the 10 PIPELINE/MERGE_INTO lanes that source ./.env to their n8n pipelines (governed env, not .env)
    areas: [config/n8n_run_allowlist.json, crontab via lane cutover]
---

# Workspace lifecycle

## Why (measured 2026-10-30)

The disk reached 99.75% on 10-29. Read-only plans that day: **646 git worktrees**, of which 332 were abandoned
(59.6 GiB); `~/.cache/agent-tmp` 43 GB across 153 dirs; release prepares ~32 GiB per 48 h. The reviewed rules
reclaimed ~2 GiB because they were plan-only, broken (`claim_unreadable` on every `--standing` plan), or held
anything with a nested repo or a recent fixture timestamp. An operator-run close-out freed 76.6 GiB (91% → 73%) —
a point-in-time fix. Nothing in the system closes what an agent opens.

## Layer 1 — prevention (agents close what they open)

| What | Rule | Mechanism |
|---|---|---|
| Worktree | created only by `scripts/new-worktree.sh`, recorded on the claim (`worktree`) | `agent_claim.py close` archives + removes it when the claim ends |
| Scratch | only under `~/.cache/agent-tmp/<claim-id>/`; `TMPDIR` points there | `close` removes it (it is the claim's own; §24.13) |
| Test temp | pytest keeps only failed-test dirs (`tmp_path_retention_policy = "failed"`) | pytest itself |
| Secrets | a worktree never holds a copied secret; `.env` is a symlink only when asked | release prepare excludes `.env.*` |

`close` runs automatically from `agent_claim.py done` and `release`, and from the claim lifecycle when a claim's
PR merges or is closed. It refuses (and reports) when a process is inside the path or another live claim names it.

**Archive, then remove** (one helper, `scripts/lib/workspace_closeout.py`, used by `close` and rule C): every tracked
change, untracked non-ignored file and HEAD is committed with a temporary index (no hooks, never pushed) to
`refs/archive/closeout-<date>/<slug>-<hash>`; then `git worktree remove --force`. Ignored files (build output,
venvs, caches, `.env` links) are not kept — by definition rebuildable. Branches, remote branches and PRs are not
touched. Restore: `git worktree add <path> <ref>`.

## Layer 2 — recurring sweep (n8n `disk-hygiene` lane, standing path)

| Rule | Takes | Holds |
|---|---|---|
| S | `~/.cache/rtc` scratch idle > 7 d | references, processes |
| T | `~/.cache/agent-tmp/<entry>` idle > `idle_days`; nested unique commits bundled first | references, processes, registered worktrees, dirty nested repos |
| W | clean, merged, idle worktrees | existing W checks |
| **C** | abandoned worktrees: no open PR, no claim heartbeat in `claim_fresh_days`, no change in `idle_days`, no process, not locked, untracked ≤ `max_archive_mb` — archived first | credential-like ignored files that are **real files** (symlinks are fine), canonical/release trees |
| **R** | release dirs beyond CURRENT, previous and the newest N | release lock, any pointer/unit/cron reference |
| **X** | `refs/archive/closeout-*` and rule-T bundles older than `archive_retention_days` | nothing else |

Cadence:

- **Daily 03:30 ET** (after the nightly backup, off-peak): `disk_hygiene.py --standing --apply`.
- **Weekly Sunday 04:00 ET**: same plus rule X.
- **Pressure** (from the 15-minute monitor): at ≥ `pressure_pct` (80) the monitor requests an out-of-cycle run with
  `--until-target <target_pct>` (75). The run re-plans and re-applies — recursively — until usage ≤ target, a pass
  removes nothing, or `max_passes` (5) is reached. Every pass re-collects evidence; caps bind per pass.
- If the sweep ends above `alert_pct` (85), the monitor alerts once with the top held reasons (bytes per reason), so
  the operator sees *why* space is held (e.g. "207 worktrees on fresh claims, 48 with credential files").

All thresholds live in `config/disk_hygiene_rules.json` and are operator-only (§17). Kill switch: `standing_apply.enabled = false`.

## Layer 3 — monitoring

- Receipts: `persistent-state/data/runtime/disk_hygiene/` (plan, apply, progress) — the durable proof (§0 rule 8).
- The daily digest carries one line: used %, reclaimed today, held top 3.
- The monitor's existing `held_above_10gb_two_runs` alert stays.

## Backups (operator 2026-10-30, verbatim: "we should keep one copy on the server, the latest copy, and we should keep n plus one on Google Drive and then delete it. Make sure that that methodology is enforced.")

- Host: one dump, the latest. The previous dump is **removed**, not moved to `db_backups/archive` (a same-disk move
  frees nothing), and only after the new dump passes `gzip -t` and its Drive object is verified by name, size and md5.
- Drive: `drive_db.keep_n + 1` dumps (default N = 1, so 2). Older Drive dumps are deleted after the newest is verified.
- Failure modes keep data: unverified upload → keep the old host dump and alert; no successor → never remove.
- `hold-prerecovery` and the September `m5_*` snapshots are recovery holds: they stay until the operator releases them.
- This resolves DSN-20261030-disk-recovery-P2-T2 by operator direction.

## Growth audit (operator: "investigate at least a few times a week … or when we see the disk growing when it shouldn't be")

`disk-growth-audit` runs Tue and Fri, and whenever the monitor sees growth above `growth_alert_gib_per_day`. It
measures fixed roots (home depth 2, `~/.cache`, `/tmp`, `~/trade-ai-releases`, `~/db_backups`, docker/pg where
readable), diffs against the last run, attributes each new or grown path to a lane, claim, release or agent, and
reports unattributed or fast-growing paths with owner and age. It never deletes.

## Not in scope

- The empty `.env` found 2026-10-30 — an incident: restored from the 10-25 backup in-session; writer under investigation.
