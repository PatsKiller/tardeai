# Agent-scratch purge — the disk-hygiene standing path on a daily host timer (2026-10-30)

```
Status:        PROPOSED (branch wt/agent-scratch-purge-20261030); inert until the operator installs the timer
Owner:         platform
Authority:     DSN-20261030 + AGENTS.md 27.0.0 §24.13 (PROPOSED, held-class); install is operator-only (§17)
Supersedes:    the plan-only posture of n8n lane disk-hygiene for the scratch namespaces (~/.cache/agent-tmp,
               ~/.cache/rtc, stale worktrees)
Evidence:      01_dry_run_offline_hermetic_20261030.txt, 02_dry_run_host_fail_closed_20261030.txt
Tests:         tests/test_disk_standing_apply_20261024.py (test_agent_scratch_purge_lane_and_units_are_staged_never_scheduled
               + the rule-T standing tests)
```

## Why

Agent scratch piled up because §0 rule 6 forbade agents deleting anything:

- `~/.cache/agent-tmp` = **43 GB across 119 per-task agent scratch dirs** (2026-10-25 → 10-30).
- `~/.cache/rtc` = **23 GB / 646 dirs**.
- `~/tradeai-wt-*` + `~/wt-*` + `~/worktrees` ≈ **91 GB** of stale worktrees.

Until ENOSPC truncated `holdings.json`. The operator asked for agents to clean up after themselves and
something to purge on schedule. AGENTS.md 27.0.0 §0 rule 6 gains exception (c) (agent self-delete of its own
scratch) and §24.13 (this scheduled purge). This packet builds the scheduled purge that §24.13 proposes.

## What it deletes (and never touches)

`scripts/disk_hygiene.py --standing --apply` runs the reviewed `standing_apply` rules from
`config/disk_hygiene_rules.json` — **A/S/T/W**:

| rule | kind | what | candidate only when |
|---|---|---|---|
| **A** | `archived_dump` | `~/db_backups/archive/trade_ai_*.sql.gz` | a completed, non-hold, non-symlink, single-hardlink dump older than 2 h, keeping the newest daily (7) + Sunday (4) recovery points |
| **S** | `rtc_scratch` | `~/.cache/rtc/<dir>` | idle > 7 days, no `/proc/*/cwd` or `/proc/*/fd` inside, no coordination reference |
| **T** | `agent_scratch` | `~/.cache/agent-tmp/<task-id>` | idle > 2 days, no cwd/open fd inside, no live claim or worklog reference, owning branch/PR merged or abandoned |
| **W** | `git_worktree` | a linked worktree off a branch the agent owns | clean, unlocked, untouched > 48 h, branch preserved, no open PR / live claim / worklog, HEAD ancestor of `origin/main` (or detached + ancestor) |

Every item is **re-validated at apply time** against the same rules and the item's fingerprint; anything changed
is skipped. Before deleting, the run reads the claim board, worklogs, open GitHub PRs and process cwds/fds, and
**refuses outright while any process is opaque** (cwd/fds not readable by this user) or any evidence source is
incomplete/stale. Deletion stops at `max_items_per_run` / `max_bytes_per_run` (40 GiB) caps. It **never** runs
under the n8n executor (`TRADEAI_RUN_ID`); a live store, the DB, holdings, identity, lineage, the
InstrumentRecord store, `persistent-state`, credentials, or another agent's active/claimed work are never
deletable (§0 rule 6, §24.13).

## The units

`linux_launchers/systemd/tradeai-agent-scratch-purge.service` (oneshot, dev-tree venv, `TRADEAI_RUN_ID`
set so the reviewed-standing authorization applies without a per-run grant):

```ini
[Service]
Type=oneshot
WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TRADEAI_RUN_ID=agent-scratch-purge
ExecStart=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/disk_hygiene.py --standing --apply
TimeoutStartSec=1800
Nice=10
IOSchedulingClass=idle
```

`linux_launchers/systemd/tradeai-agent-scratch-purge.timer` (daily 05:00 ET, after the close, off-peak):

```ini
[Timer]
OnCalendar=*-*-* 05:00:00 America/New_York
Persistent=true
RandomizedDelaySec=120
```

## Activation — the exact 4 operator acts to arm

The `--standing --apply` path is gated in code by four independent conditions; arming is four operator acts:

1. **Ratify + merge the policy.** `APPROVE_AGENTS_POLICY_27_0_0 <pr> <head_sha>` in the operator's own session,
   then merge the held-class PR (§25.10). Until then §0 rule 6(c), §24.13 and the §17 entry are PROPOSED.
2. **Approve the standing_apply block** in `config/disk_hygiene_rules.json` (a `config-write` grant naming the
   file + a reviewed PR): set `standing_apply.approval.status = "APPROVED"`,
   `standing_apply.approval.approved_by` and `standing_apply.approval.approved_at` (aware ISO-8601), **and** the
   top-level `standing_apply.approved_by` to the same value. Otherwise the run refuses `standing_approval_pending`.
3. **Enable it.** Set `standing_apply.enabled = true` (same reviewed config change). Otherwise the run refuses
   `standing_apply_disabled`.
4. **Install the units.**
   `cp linux_launchers/systemd/tradeai-agent-scratch-purge.{service,timer} ~/.config/systemd/user/ &&
   systemctl --user daemon-reload && systemctl --user enable --now tradeai-agent-scratch-purge.timer`
   (a new production systemd entry is operator-only, §17).

After the first natural fire, flip the `agent-scratch-purge` lane row to `ACTIVE` in a follow-up registry PR
(§8.1, §9.3).

**Kill switch:** `standing_apply.enabled: false` or `systemctl --user disable --now
tradeai-agent-scratch-purge.timer`.
**Rollback:** stop the timer; nothing else depends on it.

## Dry-run evidence

The scheduled command in dry-run form is `scripts/disk_hygiene.py --standing --dry-run`. Two runs are quoted:

- **Hermetic, mutation-tested** (`01_dry_run_offline_hermetic_20261030.txt`): with an offline evidence snapshot
  and a tiny scratch home holding one `~/.cache/agent-tmp/task-abc123` and one `~/.cache/rtc/rtc-old`, the dry
  run reports **2 candidates — `S:rtc_scratch` (1) and `T:agent_scratch` (1)** — and writes nothing. The report
  changes with the state under it, so it keys on the scratch it claims to purge.
- **Live host, fail-closed** (`02_dry_run_host_fail_closed_20261030.txt`): against the real host, the dry run
  **refuses** with `evidence_incomplete:coordination` (`claim_unreadable`) — a malformed claim file in the
  coordination tree. This is the §24.13 rail working: an evidence source it cannot prove makes the plan
  ineligible, and nothing is deleted. **Pre-flight note for the operator:** a malformed claim file in
  `~/trade-ai-releases/persistent-state/data/coordination/claims/` will keep the purge refusing on arming day
  until that claim is fixed or aged out.

## Lane registry row

`config/lane_registry.json` gains `agent-scratch-purge` (`kind: systemd`,
`expression: tradeai-agent-scratch-purge.timer`, `match: scripts/disk_hygiene.py --standing --apply`,
`state: NEVER_SCHEDULED`). Its `output_signal` is the standing-apply report
(`data/runtime/disk_hygiene/disk_hygiene_standing_apply_latest.json` → `finished_at`) — the artifact only the
`--standing --apply` run writes, distinct from the `disk-hygiene` --plan lane's receipt, so a --plan success can
never hide a standing-apply failure.
