# Disk-hygiene first-apply review — operator decision package

```
Status: ACTIVE
as_of: 2026-10-28
Measured at: worktree wt/resync-20261028 @ 47047eda7264078cb6eec49196456595614d9b6c
             (AGENTS.md Policy-Version 26.1.0). No script run against production state; this review
             describes the rules, not a live candidate manifest.
Canonical repo path: docs/audits/DISK_HYGIENE_FIRST_APPLY_REVIEW_2026-10-28.md
Authority: config/disk_hygiene_rules.json (DiskHygieneRules@v1, as_of 2026-10-18);
           scripts/disk_hygiene.py; config/n8n_run_allowlist.json; AGENTS.md §24.12 + §17;
           docs/governance/OPEN_ITEMS.md OI-096
See also: docs/ops/packets/disk-standing-apply-20261024/; docs/ops/packets/disk-hygiene-n8n-20261018/
```

## Purpose

The operator is receiving **"Disk 96.6% used (15.2GB free)"** alerts, and n8n is **not** reclaiming
root-disk space. This document is the first-live review AGENTS.md §24.12 requires before automated
deletion turns on, so the operator can give the one-line approval that enables real reclaim.

Root cause in one sentence: the `disk-hygiene` n8n lane is admitted at `live_arg: ["--plan"]` only
(manifest, no deletion), and `config/disk_hygiene_rules.json` → `standing_apply.enabled` is `false`
with `standing_apply.approval.status = "PENDING_OPERATOR_REVIEW"`.

---

## 1 · What the lane will delete if apply turns on

`standing_apply.rules` is `["A", "S", "W"]` — **three rule kinds, and only these** (the code validates
every standing rule against `RULE_KINDS = {A: archived_dump, S: rtc_scratch, W: git_worktree}` and
refuses anything else). Enabling `standing_apply` turns on the automated `--standing --apply` path for
these three, and nothing more.

### W — git worktrees (linked only, never clones, never force)

From `standing_apply.worktree` plus the base `git` rule G. A linked git worktree is a deletion candidate
**only when ALL of these hold**:

- **Owned** — its origin URL matches `git.owned_remote_patterns` (`PatsKiller/tardeai` or
  `PatsKiller/trade-ai*`). Another application's repo is never touched (AGENTS §24.4).
- **Clean** — `require_clean: true`; `git status --porcelain --untracked-files=all` is empty (no staged,
  unstaged, *or* untracked files).
- **Idle** — untouched ≥ `untouched_hours` (48 h) by newest mtime of the tree and its gitdir state.
- **Merged / fully pushed** — HEAD is merged into `origin/main`; a detached HEAD is a candidate only when
  `detached_requires_ancestor: "origin/main"` (HEAD is an ancestor of `origin/main`). No commit exists
  only on a local branch.
- **No open PR, no live claim** — `open_pr_and_live_claim_worklog: "must be proven absent"`: there is no
  open PR and no live claim/worklog referencing the worktree (checked against the GitHub PR reader and
  the coordination claim store).
- **Nothing references it** — not the served `CURRENT`, a release pointer file, a crontab line, a
  systemd unit/drop-in; and no running process has its cwd inside it (`/proc/*/cwd`).
- **Not locked, not credential-bearing** — not a locked worktree, and no ignored file whose name looks
  like a credential.
- **Never** (per `standing_apply.worktree.never`): a **standalone clone**, deletion of a branch/ref or
  commit, or a **force** removal. Removal is `git -C <main repo> worktree remove <path>` (never
  `--force`, never `rm -rf`); the branch is preserved in the main repo (`preserve_named_branch: true`).

### S — RTC scratch (`~/.cache/rtc`)

From `standing_apply.rtc`. Scratch directories under `~/.cache/rtc` idle > `idle_days` (7) are candidates,
**only after** `coordination_references` are resolved — all retained history and live coordination records
must be checked and must not reference the item. If that evidence is unavailable, the item is **held**,
never deleted.

### A — archived Postgres dumps (`~/db_backups/archive`)

From `standing_apply.archive`. This is a narrow, code-enforced carve-out of the otherwise-untouchable
`~/db_backups` path. Old dump archives are pruned to:

- `keep_daily: 7` — keep the 7 most recent daily dumps;
- `keep_weekly_sunday: 4` — keep the 4 most recent weekly-Sunday dumps;
- `date_basis` is original file mtime, America/New_York;
- **never**: a live dump, the hold directory, a partial/young dump, a symlink, or a hardlinked file.
  (Only regular files directly under the exact configured archive path qualify.)

### R — releases (NOT part of standing apply — see gap note)

The `releases` rule is evaluated in the weekly `--plan` manifest but is **not** in `standing_apply.rules`
(A/S/W), so enabling standing apply does **not** automate release-dir deletion. For completeness, Rule R
keeps, in `~/trade-ai-releases/portfolio-server`: the `CURRENT` target, every pointer-file target
(`EXPECTED_RELEASE`, `ACTIVE_RELEASE`), the previous served release, and the newest `keep_newest` (3);
and in `~/trade-ai-releases/archive/releases_20260915`, the newest 3 `*.tar.zst` archives, with
`hold_until: 2026-12-14` honoured from the tripwire README. Release removal would require the manual
`--apply` path under a `TRADEAI_DISK_HYGIENE_GRANT`.

---

## 2 · What it will NOT touch

The hard never-touch list is enforced in code **before any rule runs and again at apply time**. A path
equal to / inside / containing one of these is never a candidate.

**`protected_paths.paths`** (never a candidate; a candidate containing one is also excluded):

- `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild` (the dev repo cron and units execute from)
- `~/tradeai-exact-main-20260827`
- `~/trade-ai-releases/train-checkout`
- `~/trade-ai-releases/portfolio-server/CURRENT` (the served release pointer)

**`never_touch.paths`** (whole paths):

- `~/db_backups` · `~/trade-ai-releases/persistent-state` · `~/llama-cpp-vulkan` · `~/.ssh` ·
  `~/.config` · `~/.docker` · `~/.gnupg` · `~/.aws` · `~/m8m-bakeoff-lab` · `~/n8n-agent-hardening` ·
  `/var/lib/docker`

**`never_touch.names`** (any path component):

- `db_backups` · `persistent-state` · `llama-cpp-vulkan` · `.ssh` · `.config` · `.docker` · `docker` ·
  `.gnupg` · `.aws` · `.n8n` · `n8n_data` · `n8n-data`

**`never_touch.name_globs`** (any matching filename):

- `.env`, `.env.*`, `*.env`, `*credential*`, `*cookie*`, `*token*`, `*secret*`, `*.pem`, `*.key`,
  `id_rsa*`, `id_ed25519*`

**`never_touch.report_only`** (measured and printed, never deleted):

- `~/llama-cpp-vulkan` (model weights) · `~/db_backups` (owned by backup_enforcer) · `~/.cache` ·
  `~/.npm` (cache roots)

Rule A carves out only the exact configured archive path `~/db_backups/archive` for regular, non-symlink,
non-hardlinked dump files; every other `db_backups` path remains untouchable.

---

## 3 · Current state

- **Allowlist (operative):** lane `disk-hygiene`, `live_arg: ["--plan"]`, `dry_run_arg: ["--dry-run"]`,
  `lock /tmp/tradeai_disk_hygiene.lock`, `timeout_s 1800`, `output_signal data/runtime/disk-hygiene_last.json`
  (receipt v2). The `--apply` flag "is never an argv here" (AGENTS §23.14 keeps destructive retention off n8n).
- **Allowlist (proposed):** a `pending_changes.disk-hygiene-standing-apply-20261024` entry carries
  `live_arg: ["--standing", "--apply"]` / `dry_run_arg: ["--standing", "--dry-run"]` at status
  `PENDING_OPERATOR_REVIEW_DISABLED`.
- **Rules:** `standing_apply.enabled = false`; `standing_apply.approval.status = "PENDING_OPERATOR_REVIEW"`
  (`approved_by`/`approved_at` null). The `approval.source` note requires the approval be the operator's own
  direct-session record, not a relayed one.
- **`tmp.auto_apply.enabled = true`** — the `/tmp` inode timers are already deleting. The open gap is
  specifically the **root-disk** lane: `standing_apply.enabled`.
- **Disk pressure:** operator alert "Disk 96.6% used (15.2GB free)". The `disk-usage-monitor` thresholds are
  warn 80% / critical 90% / host backstop 95%, so 96.6% is above the host backstop — a critical band.
- **Monitor gap signal:** `standing_apply.monitor` is configured to alert when `disk_used_pct_gt 85` and
  `planned_unapplied_bytes_gt 10 GiB` across `consecutive_distinct_runs 2` — i.e. the system can already see
  reclaim that is planned but never applied.

---

## 4 · Caps and safety

- **Per-run caps (standing apply):** `max_items_per_run = 150`, `max_bytes_per_run = 40 GiB`
  (`42949672960` bytes), with a redundant `max_gb_per_run = 40` / `byte_unit GiB` validation (code refuses
  any value outside `0 < gb <= 40`). (The manual `--apply` path's `apply` block is 150 items / 100 GiB.)
- **Manifest freshness:** `manifest_max_age_hours = 2`; the apply refuses a stale manifest, a manifest for
  a different `home`, a manifest whose `rules_sha256` no longer matches the rules file, or one whose schema
  is wrong.
- **Re-validation before every delete:** at apply time the script reloads the rules file and refuses if the
  rules changed mid-run (`rules_changed_during_apply`); it then re-evaluates **each item** and skips it if
  anything changed (`changed_since_manifest`, `rule_now_fails`, `no_longer_listed`, or a standing
  revalidation failure). A check the script cannot evaluate makes the item ineligible, never eligible.
- **No force, no `rm -rf` on worktrees:** worktrees are removed via `git worktree remove` (never
  `--force`); only non-symlink, non-directory-safe paths (`rtc_scratch`, `cache_entry`, `git_clone`,
  `release_dir`) use `rmtree`, and `archived_dump`/`release_file` are single `unlink`/`rmtree` after
  symlink checks.
- **Standing approval gate (code):** `--standing --apply` refuses with `standing_approval_pending` unless
  `approval.status == "APPROVED"` **and** `approved_by` is set and matches `approval.approved_by` **and**
  `approved_at` is set; and refuses `standing_apply_disabled` while `enabled` is not `true`.
- **Receipt:** every run writes a `LaneRunReceipt@v2` (`data/runtime/disk-hygiene_last.json`); an apply also
  writes a `DiskHygieneApplyReport@v1` under the manifest dir `data/runtime/disk_hygiene/`, listing each
  removed path, its rule and evidence, and each skipped/refused item with its reason.

---

## 5 · The exact operator approval needed

This is a **§17 operator-only decision** — an agent must **propose and stop**, never perform the flip.
Two §17 entries apply directly:

- "changing the disk-hygiene rules or never-touch list (§24.12 — a `config-write` grant and a reviewed PR)";
- "Reviewing the first live disk-hygiene apply and turning on lane apply or standing approval (§24.12)".

The one-line instruction the operator should give, after reviewing the first dry-run manifest, is
(conceptually):

> **APPROVE DISK_HYGIENE_STANDING_APPLY** — I have reviewed the first dry-run manifest. Turn on
> `standing_apply` (rules A/S/W) and activate the `--standing --apply` allowlist entry.

That single decision authorizes, in a reviewed PR plus a `config-write` grant (and, per the
`standing_apply.approval.source` note, recorded by the operator/root in the operator's own session — a
relayed approval is **not** ratification, §28.4), these three coordinated edits:

1. `config/disk_hygiene_rules.json`: `standing_apply.enabled` → `true`; `standing_apply.approval.status`
   → `APPROVED` with `approved_by` / `approved_at` set and `standing_apply.approved_by` set equal to it.
2. `config/n8n_run_allowlist.json`: activate the `disk-hygiene-standing-apply-20261024` pending entry
   (`live_arg: ["--standing", "--apply"]`, `dry_run_arg: ["--standing", "--dry-run"]`) out of
   `PENDING_OPERATOR_REVIEW_DISABLED`.
3. Confirm `disk-hygiene` remains on the relay live list (`TRADEAI_N8N_RELAY_LIVE_LANES`) so the live fire
   can run.

An agent may prepare these changes as a proposal; it never sets `enabled`, never edits the approval record,
and never touches the relay live list itself.

---

## 6 · Rollback / kill switch

Per AGENTS.md §24.12, either of these stops automated deletion without a code change:

- **Set `standing_apply.enabled` back to `false`** in `config/disk_hygiene_rules.json` — the script then
  refuses `standing_apply_disabled`; **or**
- **Drop `disk-hygiene` from `TRADEAI_N8N_RELAY_LIVE_LANES`** — the lane runs dry (its `--plan` path) and
  applies nothing.

(For the separate `/tmp` path, the equivalent switch is `tmp.auto_apply.enabled` → `false`; it is
currently `true` and is not the gap this review closes.)

---

## 7 · Recommended first-apply verification

1. **Read-only preview first.** Run `scripts/disk_hygiene.py --report` (or `--plan`) from the served
   release, **not** from the live server during market hours, and quote the manifest. **Mode note:** only
   `--dry-run` writes nothing at all (print-only, no manifest, no receipt); `--plan` and `--report` both
   write a manifest + `LaneRunReceipt` into `data/runtime/disk_hygiene/` but delete nothing. For a
   zero-side-effect operator preview, `--dry-run` is the write-free form; `--report` is the human-readable
   form that also records the manifest.
2. **Review the manifest the operator is actually approving** — `data/runtime/disk_hygiene/disk_hygiene_manifest_latest.json`:
   the exact candidate paths, sizes, rules and exclusion reasons. Approve that content, not a description
   of it.
3. **First live apply should be a small, bounded manifest.** After the flip, watch the first
   `--standing --apply` fire and confirm: `RUN_DONE`, a `LaneRunReceipt@v2` whose `ok_at` advanced after
   the trigger, an apply report listing each removed path with rule + evidence, and totals well under the
   150-item / 40 GiB caps. A `RUN_SKIPPED_LOCK` or a refusal is **not** the live proof.

---

## Gaps / unmeasured (stated plainly)

1. **This review was written without running the script** (per instructions, to avoid slow git/du scans and
   any production-state write). The live candidate set — which specific worktrees/rtc dirs/dumps and how
   many bytes — is **not measured here**; the operator must still review the actual latest manifest.
2. **`--report` vs `--plan` vs `--dry-run`:** `--dry-run` is the only write-free mode; `--report`/`--plan`
   write a manifest + receipt (non-destructive) to the runtime dir. The task's "`--report` is read-only"
   is true only in the "deletes nothing" sense, not the "writes nothing" sense.
3. **Releases are not automated by this approval.** `standing_apply.rules` is A/S/W only; Rule R (old
   release dirs and `releases_20260915` tarballs) is evaluated in the plan but needs the manual grant path.
   If the operator expects the ~36 GB of old releases to be reclaimed, that is a separate decision.
4. **Two coordinated config edits are required**, not one: the rules-file flip **and** the allowlist
   `pending_changes` activation — plus the relay live list. Flipping `standing_apply.enabled` alone does not
   make the lane apply while its operative `live_arg` is still `--plan`.
5. **Approval provenance is strict:** `standing_apply.approval.source` says a peer-relayed approval is not
   ratification; it must be the operator's own direct-session record (§28.4), and AGENTS §24.12 requires
   the operator to review the first live apply.
