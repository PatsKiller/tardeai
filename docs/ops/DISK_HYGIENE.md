# Disk Hygiene

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 5614-5687 -->
## Moved from AGENTS.md (25.0.1 lines 5614-5687)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **Scope: one script, two callers, no hand deletion.** Only `scripts/disk_hygiene.py`, reading
  `config/disk_hygiene_rules.json`, may remove anything under this exception, and only when the n8n lane
  `disk-hygiene` runs it (weekly, through the relay and the gateway like every lane, §23.3) or the operator runs it
  from the CLI. No agent deletes by hand: no `rm`, `git worktree remove`, `git clean`, `find -delete` or other route
  around the script, and no agent runs its apply mode outside the lane. An agent may run the dry run and read its
  manifests and receipts. No other deletion code is covered by analogy. *Cause (§20): operator directive 2026-10-18,
  "i approve automatic deletion would need an AGENTS.md amendment"; §0 rule 3 — the exception is one code path, so
  a refusal elsewhere is never routed through it.*
- **Named addition (20.0.0): the host `/tmp` hygiene lanes.** Besides `scripts/disk_hygiene.py`, exactly these may
  remove items under this exception: `scripts/tmp_hygiene_auto.py`, run on the host by the systemd user timers
  `tradeai-tmp-hygiene-apply` (hourly) and `tradeai-tmp-hygiene-pressure` (every 5 minutes; it acts only at 85% or
  more `/tmp` inode use, and at most once per 15 minutes). They remove only items the reviewed `tmp.*` rules in
  `config/disk_hygiene_rules.json` select, and only under `/tmp`; they never run under the n8n executor. The
  standing approval is `tmp.auto_apply.standing_approval` and the kill switch is `tmp.auto_apply.enabled`; a manual
  `scripts/tmp_hygiene.py --apply` still needs the grant. They never touch a dirty, unpushed or unregistered
  worktree, never run `git worktree remove --force`, and never touch a `tmp.never_touch_globs` path (including
  `tradeai-*`); every run writes a deletions ledger and a `LaneRunReceipt`. These lanes are named here; nothing
  broader is added, and no other deletion code is covered by analogy. *Cause (§20): operator 2026-10-22,
  verbatim: "It needs to be able to delete it. Just looking at it won't do anything." (`/tmp`, a tmpfs, at 99%
  inodes while the tmp lane ran plan-only), and "approve all" for the 20.0.0 package; PR #1954.*
- **What is reclaimable — two kinds of item, and only these.** (a) A git clone or worktree, only when its working tree
  is clean, it has no untracked files and no commit unpushed to its upstream, its HEAD is merged into `origin/main`,
  nothing references it (the served `CURRENT` release, a systemd unit, a crontab line), no running process has its
  cwd inside it, and it has been idle for more than the rule's day count. (b) A portfolio-server release directory,
  keeping `CURRENT`, the previous release and the newest N (N from the rules file). The script evaluates every check;
  a check it cannot evaluate (a git error, an unreadable `/proc` entry, a missing upstream) makes the item
  ineligible, never eligible. *Cause (§20): measured 2026-10-18 — root disk at 89%, about 100 GB in stale clones and
  worktrees and 36 GB in old releases; a clone with uncommitted or unpushed work may be the only copy of that work
  (§0 rule 5).*
- **Never touched, whatever the rules say — enforced in code.** The script refuses any path inside or under
  `db_backups`, `persistent-state`, `models`, any `.env`, credential, cookie or token path, `~/.ssh`, `~/.config`, and
  Docker and n8n volumes, and refuses the served `CURRENT` target and the previous release. The list lives in the
  script, is checked before and again after the rules select, and is pinned by its tests; a rule cannot widen what
  is removable past it. A candidate it matches is recorded in the manifest as refused. *Cause (§20): §24.7
  (credentials are operator-only); §0 rule 6 (backups and state are the records that rule protects); §18 (no off-box
  backup of `persistent-state` exists).*
- **Changing the rules or the never-touch list is operator-only.** Any change to `config/disk_hygiene_rules.json` or
  to the never-touch list is an operator-approved config change: a reviewed PR and a `config-write` grant that names
  it (§17, entry added by the ratifying edit). Lowering a keep count, an idle threshold or a cap, or adding an item
  kind, is such a change. *Cause (§20): §17 "deleting anything" is operator-only; the exception holds only because
  the operator reviewed what the rules select.*
- **Every apply: a fresh manifest, re-validation, caps and a receipt.** An apply removes only items listed in a
  manifest that a dry run of the same rules version wrote in the same run (never a stale manifest); immediately
  before removing each item it re-runs every eligibility and never-touch check and skips the item if any result
  changed; it stops at the per-run byte and item caps in the rules file; and it writes a `LaneRunReceipt@v2` listing
  each removed path with its size, the rule that selected it and the evidence for each check, and each skipped or
  refused item with its reason. A path with no receipt row was not removed by this lane. *Cause (§20): §0 rules 7
  and 8; §9.3.*
- **The first live apply is reviewed by the operator.** The lane enters n8n as a dry run (its `live_arg` off). The
  operator reviews a dry-run manifest; only then does the lane's `live_arg` turn on apply (a `config-write` grant),
  and the first live run's receipt goes to the operator before the next live run. *Cause (§20): §0 rule 7; operator
  directive 2026-10-18.*
- **Kill switch.** Either edit stops removal without a code change: remove `disk-hygiene` from the relay's live list
  `TRADEAI_N8N_RELAY_LIVE_LANES` (the lane then runs dry), or set `auto_apply` to `false` in
  `config/disk_hygiene_rules.json` (the script then refuses apply from the lane). Each is a `config-write` change and
  needs no amendment. *Cause (§20): §23.3 — live is reachable only through the relay live list; a deletion lane must
  be stoppable faster than a PR.*
- **Not in scope — rule 6 still applies.** Data files, stores, backups, database rows, archives, logs, credentials
  and anything that is not a clone, a worktree or a release directory are never in scope; deleting them stays under
  "Never delete. Archive with a tripwire" and is an operator-only decision (§17). Database rows keep their own
  guarded routes. *Cause (§20): the directive concerned stale clones and releases; rule 6 protects records whose loss
  cannot be undone.*
- **Open gaps, stated.** `scripts/disk_hygiene_enforcer.py` already removes release trees and backups under
  `--apply` (`--releases-only`, `--backups-only`; `config/disk_hygiene_policy.yaml`) and is named as the
  `disk_critical` remedy in `config/health_agent_policy.json`. It predates this section and is not covered by this
  exception: its backups path is out of scope, and it is retired (archived with a tripwire) or folded into
  `scripts/disk_hygiene.py` by its own PR. `scripts/disk_hygiene.py` and `config/disk_hygiene_rules.json` arrive in
  their own PR (`feat/disk-hygiene-n8n-20261018`) and are not on main at this writing; the `disk-hygiene` lane is
  not yet in the allowlist or the relay live list. *Cause (§20): measured 2026-10-18 at `a2aef7b4d` (grep of
  `scripts/disk_hygiene_enforcer.py` and `config/health_agent_policy.json`; the script and rules file absent).*
- **Retire path.** The exception ends with an amendment that removes the §0 rule 6 sentence and this section. Until
  then, the kill switch stops removal at once, and archiving `scripts/disk_hygiene.py` with a tripwire and removing
  the lane from n8n stops it for good; neither needs a grant beyond `config-write` for the live list. *Cause (§20):
  §20; every exception in §0 keeps a way back.*
