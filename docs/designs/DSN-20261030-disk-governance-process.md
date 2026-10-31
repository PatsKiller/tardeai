# DSN-20261030-disk-governance-process — repeatable disk governance on ms01-openclaw (design for approval)

Status: PROPOSED (design for operator approval — nothing ratified, nothing scheduled, nothing deleted)
as_of: 2026-10-30 11:47 ET
Measured at: 2026-10-30 11:31 ET (forensics below); runtime checks quoted in the PR body
Canonical repo path: docs/designs/DSN-20261030-disk-governance-process.md
Authority: AGENTS.md §0 rule 6, §17, §9.3, §24.12, §28.4; config/disk_hygiene_rules.json; scripts/disk_hygiene.py, scripts/disk_usage_monitor.py, scripts/backup_enforcer.py, scripts/agent_claim.py
Supersedes: none (consolidates the in-flight `DSN-20261030-disk-recovery` P1 reporting work and the proposed AGENTS.md 27.0.0 §0 rule-6 exception (c))
See also: docs/designs/DSN-20261030-disk-recovery.md · docs/ops/DISK_RECOVERY_20261030.md · docs/ops/DISK_HYGIENE.md · AGENTS.md §24.12

**What this is.** A single, repeatable process that closes the disk-governance loop on `ms01-openclaw` without any
agent ever hand-deleting production data. Four legs, in dependency order: (1) a **cadence** that measures several
times a day and pages only on a transition; (2) **agent self-cleanup** — the agent that wrote a cache removes it when
its task ends; (3) a **sweeper** — the standing disk-hygiene lane extended with an `agent_scratch` rule that catches
what self-cleanup missed; (4) **backup retention** — a hard cap on the `db_backups` archive. Legs 1–4 are proposed
here; only leg 2's enforcement script is implemented in this change (new files, dry-run by default). Every operator
decision comes back as the checklist in §5.

## 0 · State as measured (as of 11:31 ET 2026-10-30)

| Path / category | Size | Owner (who is allowed to act) |
|---|---|---|
| `/` | **98% used, ~12G free, still declining** | the disk-usage monitor (leg 1) pages; reclaim is legs 2–4 |
| git worktrees | ~91G across **414+** (up 32 in 48h) | disk-hygiene rule G (clean+merged+idle), sweeper rule W |
| `~/.cache` | 75G total — `agent-tmp` 43G/**119 dirs**, `rtc` 23G/**646 dirs** | agent self-cleanup (leg 2) + sweeper rule T/S (leg 3) |
| `~/db_backups` | 44G, ~3G/day **uncapped archive** | backup_enforcer cap (leg 4); never hand-deleted |
| `.hermes/state.db` | 13.6G live DB | **never auto-delete** (DB retention ladder only, operator) |
| `.codex` | 8.7G | report only |
| `.npm` | 4.7G | cache rule C (default disabled); report only |

The single live-DB line (`.hermes/state.db`) is the reason the process is conservative: the reclaimable mass is
worktrees + scratch + backups, never the live store. Every leg below is scoped so it cannot reach the live DB or the
never-touch list.

## 1 · Cadence — monitor multiple times a day, page only on a transition

**Measurement** stays on the existing `disk-usage-monitor` lane (`scripts/disk_usage_monitor.py`, `*/15`), which
already bands `used%` and inode use per mount and dedupes by band change (per `(mount, metric)`), never by raw
percent. No change to that layer here — the in-flight `DSN-20261030-disk-recovery` P1 workers are finishing the
bounded-measurement refresh; treat it as the monitoring layer.

**Checkpoints (proposed, operator-installed — §17, §9.3).** Six reviews a day so a fill is seen within hours, not on
a Sunday: `00:00`, `06:00`, `08:00` (pre-market), `12:00`, `18:00` ET, plus the already-running `*/15` band monitor.
At each checkpoint the process evaluates two things:

- **Band transitions** — warning `80%`, critical `90%` used (inode bands match; `host_backstop_pct` `95%` already in
  `config/disk_hygiene_rules.json` `monitor`). These are already handled by the monitor's band-transition dedupe.
- **24h growth-rate trigger (new).** The monitor state already records `checked_at` + `last_pct` per mount. The
  checkpoint computes trailing-24h growth and, when the current rate would exhaust available space within **48h**
  (rate × 48h ≥ available), it raises the *about-to-fill* page. This is the trigger that catches "12G free and
  declining" before the `95%` backstop.

**Alerting (deduped, transition-only).** Through `scripts/telegram_alert.send_telegram` (the module is
`scripts/telegram_alert.py` — there is no `scripts/lib/telegram_alert.py`):

| Condition | Call | Stable dedupe key |
|---|---|---|
| about-to-fill (growth-rate trigger) | `send_telegram(text, priority="P1", dedupe_minutes=0, producer="disk_governance")` | `disk_governance:about_to_fill:<mount>` (P1 dedupe off; repeats bounded by transition-only) |
| warn / critical band transition | `send_telegram(text, priority="P2", dedupe_minutes=360, producer="disk_governance")` | `disk_governance:<band>:<mount>` |
| recovery (back under 80%) | `priority="P3"` digest | `disk_governance:recovered:<mount>` |

P1 is "about to fill" only; everything else is P2/digest, matching §9.1 (P1 = operator must act, dedupe off, and the
message is *accepted for interrupt delivery*, never *sent*).

## 2 · Agent self-cleanup — "if an agent writes caches, it cleans up afterwards" (enforced)

**Contract.** The agent that created a scratch tree removes it when its task ends. Scratch is, by construction
(`docs/ops/DELIVERY_LIFECYCLE.md` "Build"): `TMPDIR=$HOME/.cache/agent-tmp/<task>` plus any worktree scratch the agent
names. This is the proposed AGENTS.md 27.0.0 §0 rule-6 exception (c) — the third "never delete" exception, alongside
the disk-hygiene lane and the `/tmp` hygiene lane.

**Hook points** (where the contract fires):

- `scripts/agent_claim.py` **`release`** (`cmd_release`) — claim close (`done`/`abandoned`).
- `scripts/agent_claim.py` **`takeover`** (`cmd_takeover`) — a new owner assumes the work and the old owner's scratch
  becomes stale.
- **`task done`** (`cmd_task`, `done`/`--evidence-only`) — the task board's close.
- **session-end** — the same script run by hand (`python3 scripts/agent_scratch_cleanup.py --task <id>`) when a
  session stops without a formal close.

**Enforcement — implemented in this change (`scripts/agent_scratch_cleanup.py`, NEW).** Default-safe (dry-run):
it prints exactly what it would delete and deletes nothing; `--apply` removes only after every check passes. A path
is removed only when it is: inside an allowed scratch root (`~/.cache/agent-tmp`, `~/.cache/rtc`, `/tmp`) and not the
root itself; not a symlink; not on the never-touch list (mirrored from `config/disk_hygiene_rules.json` — `db_backups`,
`persistent-state`, models, `.ssh`, `.config`, `.docker`, `.gnupg`, `.aws`, `.n8n`, the dev repo, `CURRENT`, any
`.env`/credential/cookie/token/key name); not this session's recorded claim worktree and not referenced by any live
claim; not the cwd or an open fd of any live process (`/proc/<pid>/cwd`, `/proc/<pid>/fd`). A linked git worktree is
removed with `git worktree remove` (never `--force`); a standalone clone is refused.

The claim-board hook call is wired in this change as **report-only** (dry-run) and clearly commented: it flips to
`--apply` only after the operator ratifies rule-6 exception (c) — see §5.

## 3 · The sweeper — the standing lane extended with rule-T `agent_scratch`

**What it is.** Self-cleanup is best-effort (a session can die). The standing disk-hygiene lane
(`scripts/disk_hygiene.py` `--standing`, rule set A/S/W today) is extended with a **rule-T `agent_scratch`** arm so
something goes around and sweeps what was left behind.

**Rule-T eligibility (proposed).** A directory under `~/.cache/agent-tmp/<task-id>` is a candidate only when ALL hold:

- idle past **48h** by newest mtime (the same `untouched_hours` bound the standing rule W uses);
- **no live process** has its cwd or an open fd inside it (the existing `/proc/*/cwd` + `/proc/*/fd` scan);
- **no live claim** references it — the task-id/session does not appear in any `active` claim's `paths`, `worktree` or
  `worklog` under `~/trade-ai-releases/persistent-state/data/coordination` (the `coordination()` evidence the standing
  apply already collects);
- not on the never-touch list, and not a symlink.

**This is a config + rule-logic change to `config/disk_hygiene_rules.json` (the `agent_scratch` rule-T entry) and
`scripts/disk_hygiene.py` (a `T` arm beside A/S/W).** Both are **operator-only** (§17 "changing the disk-hygiene
rules", §24.12), so this document proposes them and does not apply them. The existing `rtc` scratch rule S already
covers `~/.cache/rtc` (idle 7 days); rule T is the `agent-tmp` counterpart at a tighter 48h.

## 4 · Backup retention — cap the `db_backups` archive to the newest N=2

**Problem.** `scripts/backup_enforcer.py` already archives (never unlinks) finished dumps and caps the **live** dump
count, but the **archive** grows ~3G/day uncapped (44G today). The in-flight P1-T2 worker is reporting the archive
bytes separately from the live cap; this leg proposes the cap itself.

**Proposed change (operator-only — §17 "deleting anything", §24.12).** Extend `scripts/backup_enforcer.py` so the
archive keeps the **newest N=2** completed dumps and archives (moves, never unlinks) the rest to the existing
archive/held path with a tripwire — consistent with its existing "never unlink, move to `archive/`" behavior and the
`TRIPWIRE.txt` it already writes. The exact retention is config, not a hard-coded literal, and the change ships with a
test that asserts the byte count and the "no unlink, only archive" invariant (matching the in-flight
`tests/test_backup_enforcer.py`). The live-dump cap and the Drive prune are unchanged.

## 5 · Operator-approval checklist (verbatim)

Each item is a §17 operator-only decision. None is performed by this change.

1. **Ratify governance** — the AGENTS.md 27.0.0 MAJOR that adds §0 rule-6 exception (c) (agent self-delete) and the
   05:00 daily disk-hygiene purge. Type, in this session, once the PR and its 40-hex head SHA exist:

   ```
   APPROVE_AGENTS_POLICY_27_0_0 <pr> <head_sha>
   ```

   (`<pr>` = the ratification PR number; `<head_sha>` = the full 40-hex SHA of that PR's head. This is the same
   `APPROVE_AGENTS_POLICY_*` token form as 15.0.0/26.0.0/26.2.0.)

2. **Install the schedules (operator-only, §17/§9.3):** the six daily checkpoints (`00:00, 06:00, 08:00, 12:00,
   18:00 ET`) for the growth-rate trigger + digest, and the `05:00` daily disk-hygiene purge. Agent built the lane;
   operator installs the cron/n8n/timer rows.

3. **Confirm thresholds:** warning `80%`, critical `90%`, host backstop `95%`, and the 24h growth-rate trigger that
   pages P1 when the current rate projects exhaustion within 48h.

4. **Confirm the namespace** the self-cleanup and sweeper may act on (nothing else): `~/.cache/agent-tmp`,
   `~/.cache/rtc`, `/tmp` — never `db_backups`, `persistent-state`, models, `.hermes/state.db`, `.codex`, or any
   `.env`/credential path.

5. **Approve the backup-retention cap:** `db_backups/archive` keeps the newest N=2 via `scripts/backup_enforcer.py`
   (archive-move with tripwire, never unlink).

6. **Arm the enforcement hook:** flip the `scripts/agent_claim.py` self-cleanup hook from report-only (dry-run) to
   `--apply` — the single line, clearly commented in `cmd_release`/`cmd_takeover` — only after item 1 is ACTIVE.

**Non-goals of this design.** No agent deletes production data by hand; no live DB is ever touched; no scheduler is
installed by an agent; the broker/order/stop/sizing rails are untouched (`MBI_BEHAVIOR = 0`).
