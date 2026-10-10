# Feature-to-live deploy runbook (single-approval)

Status:      ACTIVE
as_of:       2026-10-09T21:00:00Z
Measured at: 9853e6b47f13b744287c588cc0dcb5bd8bfe0bf7 (steps 0–6, Fib chart declutter — PR #947 + #949); a8a62217e (step 7, PRs #998–#1001)
Verified:    exact-SHA gate at 8da0bd92b19519f4815c2b20ced2f1dfbd1eae96 (PRs #1442, #1443)
Authority:   AGENTS.md §Local gates / docs/GIT_HYGIENE.md / RELEASE_COORDINATOR boundary
See also:    scripts/cio_phase2_exact_main_deploy.sh, scripts/new-worktree.sh, bin/guard

## Purpose

Take a finished feature branch all the way to LIVE with **one operator approval**, instead of
stopping to re-grant `git-push` / `release-write` at each boundary. The operator approves the
whole scope set once; the agent drives push → PR → merge (exact green SHA) → prepare → promote →
identity verification, with automatic rollback on a failed promote. Completed successful
**push-to-main CI on the exact deployment SHA** is a separate activation gate after PR CI.
`AI_WORK_POLICY.md` still governs push budgets; a broad grant does not authorize unlimited
synchronization. Never infer a grant or enter the operator confirmation yourself.

## The one approval

```bash
GUARD=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard
"$GUARD" plan docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md \
  --scopes "git-push release-write" \
  --for 12h --uses 25
```

or, equivalently, the two explicit grants the plan expands to:

```bash
"$GUARD" grant git-push     --for 12h --uses 25 --reason "feature-to-live: push + merge exact green PR heads"
"$GUARD" grant release-write --for 12h --uses 25 --reason "prepare and promote #PR SHA. No broker writes."
```

The release-write reason has to name this release and the actions. `prepare` and `promote` must
both appear: a reason that only says "promote" refuses the prepare step. The reason must also
contain `#<PR number>` or the merge SHA (at least 9 hex characters). Set `TRADEAI_RELEASE_PR` to
that PR number on the prepare and promote commands. `TRADEAI_RELEASE_GRANT_BINDING` stays `enforce`.

`git-push` covers push + PR open + merge. `release-write` covers the immutable release write +
systemd promote. `maintree` is **not** required — the primary tree fast-forwards with a plain
`git merge --ff-only origin/main`, which is outside the maintree guard, and `checkout main` is an
allowed protected-branch operation.

## The procedure (what the agent runs after approval)

### 0. Work only in an isolated worktree

The primary tree is the LIVE hot-reload source and is shared with other sessions. All branch work
happens in a linked worktree:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
scripts/new-worktree.sh <name>          # → /home/johnclaw/tradeai-wt-<name> on wt/<name>
cd /home/johnclaw/tradeai-wt-<name>
# edit + commit HERE (explicit paths, never add-all)
```

### 1. Local gates before any push

```bash
cd /home/johnclaw/tradeai-wt-<name>/apps/command-center-v3
npx tsc --noEmit                        # typecheck clean
bash ../../scripts/check_design_tokens.sh   # design guard passes (no raw hex / sub-10px)
```

`tsc`/build need `node_modules`; symlink from the primary tree if absent, then remove it before
committing:

```bash
ln -sfn /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/apps/command-center-v3/node_modules node_modules
# ...typecheck... then:
rm -f node_modules
```

### 2. Push + PR

```bash
cd /home/johnclaw/tradeai-wt-<name>
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/agent-push -u origin wt/<name>
gh pr create --base main --head wt/<name> --title "..." --body "..."
```

### 3. Wait for green, merge exact SHA

The base-branch policy blocks merge until required CI passes. Poll until all green, then merge
and record the exact merge SHA (never trust a merge that returns nothing):

```bash
gh pr view <n> --json state,mergeable,statusCheckRollup   # until MERGEABLE + all SUCCESS
gh pr merge <n> --merge --subject "..." 
gh pr view <n> --json state,mergeCommit                    # confirm MERGED + capture oid
```

If `main` advanced while the branch was open, merge it in first and re-push:

```bash
git fetch origin main --quiet && git merge origin/main --no-edit
bin/agent-push -u origin wt/<name>    # then re-merge the PR
```

### 4. Resolve the exact main candidate and wait for post-merge CI

Use a clean isolated deployment worktree. Fetch main, record the full candidate SHA and compare
it with the merged PR and release grant. If peers advanced main, establish that the new candidate
is within the approved release scope before preparing it. Do not silently widen the grant or
reset the shared primary tree. Promote fast-forwards the dev tree after activation (step 7).

```bash
git fetch origin main --quiet
git checkout --detach origin/main
git rev-parse HEAD
git status --short    # must be clean
.venv/bin/python scripts/release_grant_preflight.py --ci-only --sha <full-candidate-sha>
```

`--ci-only` reads GitHub and consumes no release grant. Exit 0 means eligible at the time of the
read; exit 2 means blocked. The gate requires always-on `cio-production-hardening-ci.yml` and
`agent-governance.yml`, and checks the latest matching run/attempt for every workflow returned
for `event=push`, `branch=main` and the full candidate SHA. Each must be `completed` with
`conclusion=success`. Missing, pending, failed, cancelled, wrong-SHA or unavailable evidence
blocks promotion. An earlier success cannot hide a newer pending rerun; PR checks and old
receipts cannot substitute for this check.

The reader supports host `gh 2.46.0`: it decodes consecutive `gh api --paginate` pages and rejects
malformed/trailing output. API or network failure means unavailable evidence; resolve it and
repeat the read without weakening the gate. See the
[verified remediation release](VALIDATED_LEARNING_REMEDIATION.md#release-verification-observed-2026-10-05).

### 5. prepare then promote (never promote alone)

```bash
cd /home/johnclaw/tradeai-wt-<deployment-name>
TRADEAI_RELEASE_PR=<n> bash scripts/cio_phase2_exact_main_deploy.sh prepare
# must end "npm run build OK" + "PREPARE OK"
TRADEAI_RELEASE_PR=<n> bash scripts/cio_phase2_exact_main_deploy.sh promote
# must end "PROMOTE OK"
```

`prepare` is the moment the design-guard / pin-check / integrity-hook gates actually fire. A
`vite build only` fallback (design guard failure) is a **defect to fix before promote**, not a
signal to proceed. `prepare` checks exact main and grant binding; it does not itself enforce
post-merge CI. `promote` re-queries CI immediately before changing CURRENT, after the grant and
conformance checks. A CI refusal records `post_merge_ci_refused` and leaves activation untouched.
Both release actions consume a grant use; a refused promotion may already have consumed its use.

Archive `~/.local/state/cio-phase2-exact-main/post_merge_ci.json` and `deploy_receipt.json`
with the candidate validation. CI evidence records candidate SHA, workflow path/ID, run ID/attempt,
event, branch, status, conclusion and check time; the deploy receipt embeds it. These global files
are overwritten by subsequent deployments, not an append-only deployment ledger. Existing grant
checks and rollback behavior remain in force.

### 6. Verify live identity (do not trust "PROMOTE OK" alone)

```bash
R=~/trade-ai-releases/portfolio-server/CURRENT
readlink -f ~/trade-ai-releases/portfolio-server/CURRENT   # → <sha>-main-exact-phase2-<ts>
cat "$R/SOURCE_COMMIT"; cat "$R/BUILD_SHA"
git -C /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild rev-parse origin/main
systemctl --user show portfolio-server.service -p WorkingDirectory --value
curl -fsS --max-time 5 http://localhost:7777/api/v2/health | python3 -c 'import sys,json; print(json.load(sys.stdin).get("ok"))'
```

CURRENT, SOURCE_COMMIT, BUILD_SHA and each CURRENT-bound process directory must identify the
**candidate 40-character SHA** in the deployment receipt. Read `/proc/<MainPID>/cwd`, not only
unit configuration. Compare origin/main at deployment time; a later peer merge is a new source
candidate, not proof of a hybrid served release. API liveness must be `True`; separately record
overall health and unresolved findings. Observe the relevant natural scheduled receipt before
claiming that a repaired path ran.

### 7. Reach what `promote` does not

**Since 2026-09-14 `promote` also fast-forwards the dev tree** (`CANONICAL_SOURCE`, where cron and the
user units run) to the promoted commit, through `scripts/lib/ff_dev_tree.sh`. It handles one case itself:
files the new commit stops tracking that sit behind the `data/runtime` / `data/audit` symlinks into
persistent state (live copies hashed, paths removed from the index only, re-hashed). Anything else exits
non-zero *after* `PROMOTE OK` and names the blocking paths. The release is live either way; a non-zero
exit means the dev tree still needs attention. `CIO_DEPLOY_FF_DEV_TREE=0` skips the step.

`promote` restarts `portfolio-server` and the units in `TRADEAI_CURRENT_BOUND_UNITS` (default, from
`restart_root_frozen_units` in `scripts/cio_phase2_exact_main_deploy.sh`:
`tradeai-health-agent.service cio-governed-bridge.service tradeai-cio-telegram.service
tradeai-telegram-callback-poller.service tradeai-n8n-coordination-gateway.service
tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service tradeai-phone-status.service`). A bound
unit that is not installed or not running is skipped, not started. Promote
reads back each bound unit's `/proc/<pid>/cwd` and must match the new CURRENT dir — see
`docs/ops/BRIDGE_PIN_ALIGNMENT.md`. The desk bot is in that default because it keeps the code it
imported at start. After promote, its cwd must be the new CURRENT directory.

```bash
pid=$(systemctl --user show -p MainPID --value tradeai-cio-telegram.service)
readlink /proc/$pid/cwd        # must equal: readlink -f ~/trade-ai-releases/portfolio-server/CURRENT
```

Two things it does not do (`AGENTS.md` §9.3, §10):

1. **Install a new user unit.** A `config/systemd/user/*.timer` added by the PR is copied into the release
   but not into `~/.config/systemd/user`. Installing is operator-approved; the convention is
   `scripts/install_cio_operator_runtime.sh`:

   ```bash
   SRC=~/trade-ai-releases/portfolio-server/CURRENT/config/systemd/user
   install -m 0644 "$SRC/<unit>.service" "$SRC/<unit>.timer" ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now <unit>.timer
   systemctl --user list-timers <unit>.timer --no-pager
   ```

   Then confirm with `check_expected_services.py`, and wait for the lane's `output_signal` on its natural
   schedule. *2026-09-13: `tradeai-operator-answer-quality.timer` shipped in a promoted release and ran
   only after this step.* For the bridge unit after a unit-file change, a one-shot
   `install -m 0600` of `cio-governed-bridge.service` from CURRENT plus `daemon-reload` is enough
   before the next promote (or before a manual align restart — `docs/ops/BRIDGE_PIN_ALIGNMENT.md`).

2. **Declare a crontab edit.** Any crontab line changed alongside the deploy (a new `timeout`, a
   re-enabled job) needs its `config/lane_registry.json` row in the same PR, or
   `check_lane_registry.py --fail-on-new` fails `ai_local_acceptance`. Editing the crontab is operator-only.

3. **Turn on an opt-in mode of a bound unit.** Promote restarts `tradeai-n8n-run-executor.service` with the
   environment the installed unit already has. The repo unit sets no `TRADEAI_N8N_EXECUTOR_WORKERS`, so the
   executor stays on the v1 serial drain (RunReceipt@v1) after every promote. Executor v2 (#1598: N workers,
   per-lane lock, reaper, RunReceipt@v2, limits in `config/n8n_executor.json`) starts only on an explicit
   value of 2 or more. Setting it is a grant-gated edit of the installed unit (`Environment=TRADEAI_N8N_EXECUTOR_WORKERS=3`,
   then `daemon-reload` and a restart of that unit). Rollback is in `docs/ops/ROLLBACK_COMMANDS.md`.

## Failure / rollback

A `prepare` refused with `CURRENT pin check tree_diff:N` means the release overlay and the commit differ.
2026-10-09: the overlay's `--exclude=data/` dropped the tracked `docs/implementation/n8n-maturity/data/`
files (`tree_diff:4`). #1620 includes `docs/**/data/` before the excludes. Root `data/` (runtime) stays
excluded. Find the differing paths before retrying. Do not retry blind.

`promote` already auto-rolls back to `PREV_RELEASE` on a failed health check. Manual rollback
restarts the bound units and rewrites the expected-release pin. See `docs/ops/ROLLBACK_COMMANDS.md`.

```bash
bash scripts/cio_phase2_exact_main_deploy.sh rollback
```

## Invariants to preserve

- Never `prepare`/`promote` a hybrid SHA (HEAD must equal origin/main; the script refuses).
- Never merge without green CI on the exact PR head.
- Never activate without freshly queried, completed successful push/main CI on the exact candidate SHA — the one exception is the governed CI-provider-outage path below (proven outage + tree-bound local evidence + `release-emergency` grant + reconciliation). Real red never uses it.
- Never reintroduce raw hex / sub-10px fonts — `check_design_tokens.sh` is a frozen ratchet.
- `secret` and `gate` are **never** grantable; this runbook touches neither.

## CI provider outage — emergency release

Added 2026-10-05, during a GitHub Actions incident in which hosted-runner assignment failed and every required job was cancelled before running a step. The operator asked for "an emergency path for situations like this. Because this is not in our control." The normal gate is unchanged: promote requires completed, successful push/main CI on the exact SHA. This path substitutes that evidence only when every condition below is machine-verified. Code: `scripts/lib/ci_outage_emergency.py`, CLI `scripts/ci_outage_emergency_release.py`, config `config/ci_outage_emergency.yaml`.

**When it applies:**

1. GitHub's status page has an unresolved incident naming **Actions**.
2. Every required push/main workflow that is not green has jobs that **never started**: no runner and no executed step.
   - A required job that ran and failed blocks this path. Real red stays red.
   - So does a job that is still running.

**What it requires:**

| Condition | How it is verified |
|---|---|
| Local evidence | The required workflows' own `run:` steps are replayed from the workflow file **at the candidate SHA**, in a throwaway local clone (its own `.git/config`), plus the extra suites in the config (full CI profile, `npm run build` with the design guard, Active Trader Playwright). Logs are sha256-hashed into a manifest bound to the commit's **tree hash**, and are valid for 12 h. A step that cannot be replayed (unknown `if:` or `${{ }}`) and is not skipped with a reason in the config blocks the path. |
| Operator authority | A **`release-emergency`** grant (Telegram) whose text names the SHA **and** the incident id, in addition to the normal `release-write` grant. `TRADEAI_EMERGENCY_RELEASE_SHA` alone grants nothing. |
| Commit rule | The SHA is on `origin/main`. If required checks block the merge itself, the SHA may be a local merge of `origin/main` with PR branches **already pushed to GitHub**. Unpushed commits block. The release is then labelled `PENDING_RECONCILIATION`. |
| Record | `~/.local/state/cio-phase2-exact-main/emergency/ledger.jsonl` (EMERGENCY_CHECK, EMERGENCY_PROMOTED, reconciliation states). The deploy receipt note is `promote_ok_emergency_pending_reconciliation`. |

**Operator steps** (dev tree `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`, venv python):

```bash
# 0. Confirm it is a provider outage, not red code
.venv/bin/python scripts/release_grant_preflight.py --ci-only --sha <SHA>       # fails: not_successful / missing
# 1. Put the dev tree on the candidate (on main, or a local merge of main + pushed PR branches)
git checkout --detach <SHA>
# 2. Local evidence (long: replays the required workflows + full profile + build + Playwright)
.venv/bin/python scripts/ci_outage_emergency_release.py evidence --sha <SHA>
# 3. Ask for authority (Telegram): release-emergency naming SHA + incident id; plus the usual
.venv/bin/python scripts/ci_outage_emergency_release.py request-grant --sha <SHA>
.venv/bin/python scripts/guard_request_approval.py release-write --for 2h --uses 4 --reason "Deploy <SHA> (emergency, GitHub incident <id>)"
# 4. Dry check: every condition, as JSON; exit 0 only when all hold
.venv/bin/python scripts/ci_outage_emergency_release.py check --sha <SHA>
# 5. Prepare + promote with the emergency SHA named
TRADEAI_EMERGENCY_RELEASE_SHA=<SHA> bash scripts/cio_phase2_exact_main_deploy.sh prepare <worktree-or-dev-tree>
TRADEAI_EMERGENCY_RELEASE_SHA=<SHA> bash scripts/cio_phase2_exact_main_deploy.sh promote <release-dir>
# 6. When GitHub recovers: merge the PRs normally, then reconcile (dry run first)
.venv/bin/python scripts/ci_outage_emergency_release.py reconcile
.venv/bin/python scripts/ci_outage_emergency_release.py reconcile --apply
.venv/bin/python scripts/ci_outage_emergency_release.py status
```

**Reconciliation outcomes:**

- **RECONCILED:** push/main CI is green on the deployed SHA, or on the main commit with the identical tree.
- **RECONCILE_FAILED:**
  - required CI ran and failed on that content; or
  - the PRs merged but main carries a different tree (local conflict resolution diverged).
  - Either way it pages the operator through `telegram_alert.send_telegram`.
  - Rollback via `cio_phase2_exact_main_deploy.sh rollback <prev>` runs only when `auto_rollback: true` is set in the config. The default records a dry run.
- **RECONCILE_OVERDUE:** not reconciled within `reconcile_within_h` (24 h). It pages, with a cooldown.

The path cannot ship itself: this change merges and deploys through the normal gate once GitHub recovers.
