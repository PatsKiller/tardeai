# Feature-to-live deploy runbook (operator-approved, exact-SHA)

Status:      ACTIVE — reconciled to current release workflow 2026-10-22
as_of:       2026-10-22T03:44:00Z
Measured at: 9853e6b47f13b744287c588cc0dcb5bd8bfe0bf7 (steps 0–6, Fib chart declutter — PR #947 + #949); a8a62217e (step 7, PRs #998–#1001)
Verified:    exact-SHA gate at 8da0bd92b19519f4815c2b20ced2f1dfbd1eae96 (PRs #1442, #1443)
Authority:   AGENTS.md §Local gates / docs/GIT_HYGIENE.md / RELEASE_COORDINATOR boundary
See also:    scripts/cio_phase2_exact_main_deploy.sh, scripts/new-worktree.sh, bin/guard

## Purpose

This procedure describes the guarded path from a finished feature to a verified live release.
It does not bundle push and deployment authority into one broad or long-lived grant. `git-push`
and `release-write` are separate scopes, and each is requested only when its exact action is
ready. `AI_WORK_POLICY.md` still governs push budgets; never infer or extend a grant.

## Current operator approval and grant rules

Before any guarded remote or release action, present the guard's native interactive approval
request to the operator. The operator must type **`APPROVE`** at that prompt. The agent must never
type, pipe, simulate, automate, or infer that word. A plan is a proposal only until this interactive
approval occurs; elapsed time and an earlier grant are not approval.

Use the shortest practical lifetime and fewest practical uses. Current standard examples are
**30 minutes and no more than 3 uses**. Request scopes separately, bound to the precise work:

```bash
GUARD=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard
"$GUARD" grant git-push --for 30m --uses 3 --reason "<branch/PR and exact push or merge purpose>"
"$GUARD" grant release-write --for 30m --uses 3 --reason "<PR #NNN or exact SHA; prepare, promote, rollback for this release>"
```

These are syntax examples, not standing authorization. Reduce uses when fewer suffice. The
`release-write` reason must bind to the exact PR number and/or target SHA and identify the allowed
actions; the `git-push` reason must bind to the exact branch/PR and push/merge purpose. Each grant is
for one release. A generic campaign grant does not qualify. Keep
`TRADEAI_RELEASE_GRANT_BINDING=enforce` and set `TRADEAI_RELEASE_PR` for prepare/promote when a PR
binding is used. Immediately after operator approval, inspect `guard show` and verify every scope,
reason, SHA/PR binding, use count, and expiry before proceeding.

`git-push` authority does not imply `release-write`, and `release-write` does not imply push or PR
authority. `maintree` is not required by this deployment path. Do not combine scopes merely for
convenience.

## Current exact-SHA CI requirements

Before merge, require successful `agent-governance`, `cio-hardening`, and `release-readiness`
checks on the exact PR head SHA, plus the applicable recorded review. After merge, require fresh,
completed, successful main/push checks on the exact merged SHA for
`.github/workflows/cio-production-hardening-ci.yml`, `.github/workflows/agent-governance.yml`, and
`.github/workflows/release-readiness.yml`. Missing, pending, failed, cancelled, wrong-SHA, stale, or
unavailable evidence blocks promotion. A previous green SHA does not qualify a later merge.

**Implementation parity gap:** `scripts/release_grant_preflight.py` currently declares only the
first two push workflows in `REQUIRED_PUSH_WORKFLOWS`; it does not itself enforce
`release-readiness.yml` in that set. Until that checker is reconciled, explicitly verify the
third workflow on the exact merged SHA as a separate release gate and record its run/attempt ID,
conclusion, and checked SHA. Do not interpret the helper's exit 0 as proof of the third workflow.

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

Proceed only under a current, operator-approved `git-push` grant bound to this branch/PR and
the exact push/merge purpose. This grant does not authorize prepare or promote.

```bash
cd /home/johnclaw/tradeai-wt-<name>
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/agent-push -u origin wt/<name>
gh pr create --base main --head wt/<name> --title "..." --body "..."
```

### 3. Wait for green, merge exact SHA

Confirm `agent-governance`, `cio-hardening`, and `release-readiness` are successful on the exact
PR head SHA and record the applicable review before merge.

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

This phase requires a separate, current operator-approved `release-write` grant bound to the exact
merged SHA/PR and intended release actions. Verify guard scope and reason before calling prepare;
do not reuse the push grant as deployment authority.

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
scripts/cc_curl.sh -fsS --max-time 5 http://127.0.0.1:7777/api/v2/health | python3 -c 'import sys,json; print(json.load(sys.stdin).get("ok"))'
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

**Release-pinned daemons (since 2026-10-10).** A user unit can be pinned to one concrete release by a
one-off drop-in (`<unit>.service.d/20-exact-sha-release.conf` or `10-user-exact-sha.conf` with
`WorkingDirectory=<release dir>`). Promote used to rewrite only portfolio-server's, so
`chatgpt-oauth-proxy`, `grok-oauth-proxy`, `heartbeat-receiver` and `tradeai-active-trader-motion` ran
`a032116e7` (2026-10-06) for four days (packet `unit-code-roots`). Promote now runs
`scripts/release_pin_daemons.py` through `release_pin_step`:

- **before activation**, a dry-run plan (`pins:` lines in the promote log);
- **after the health check, before the bound-unit restart**, `apply`: every user unit whose *effective*
  `WorkingDirectory` / `ExecStart*` / `Environment` names a `portfolio-server/<release>` other than the new
  one gets those pins rewritten into one managed drop-in, `90-release-pin.conf`. Pin-only one-offs are
  archived under `~/.config/systemd/user/.release-pin-archive/<ts>/` next to a `TRIPWIRE.README`
  (never deleted). A one-off that also carries other directives is kept, and the managed file overrides
  it. Then one `daemon-reload`.
- **Broker-adjacent units are never touched.** A unit whose code path matches the broker execution file
  set (`broker.execution_code_edit` path globs in `config/agents_guard_hook_rules.json`, e.g.
  `scripts/active_trader/**`, `scripts/brokers/**`) or is listed in `config/release_pin_daemons.json` is
  reported `pinned-broker-adjacent: operator action`.
- **Restarts.** Bound units (above) are restarted by the deploy as before. A unit on `restart_allowlist`
  in `config/release_pin_daemons.json` (default empty) is restarted by the pin step. Every other rewritten
  unit is reported `restart pending`: the new pin lands on its next restart.
- `portfolio-server.service` is excluded (the deploy writes its drop-in itself). A pin a later drop-in
  already overrides (e.g. `95-code-root-current.conf`) is reported `SHADOWED` and left alone. A stale pin
  in a mixed drop-in that sorts after `90-release-pin.conf` is `BLOCKED: operator action`.

The receipt (`ReleasePinReceipt@v1`) is `~/.local/state/cio-phase2-exact-main/release_pins/apply-<ts>.json`
(each archived file with its sha256). The deploy receipt names it in `release_pin_receipt`.
`TRADEAI_RELEASE_PIN_MODE=warn` lists stale pins without rewriting them; `off` skips the step and says so.
`apply`/`restore` refuse the real systemd user dir under `TRADE_AI_CI=1`.

```bash
bash scripts/cio_phase2_exact_main_deploy.sh pins            # DRY RUN vs CURRENT; writes nothing
bash scripts/cio_phase2_exact_main_deploy.sh pins <release>  # DRY RUN vs a prepared release
python3 scripts/release_pin_daemons.py tripwire              # a live unit must not reference the archive
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
   environment the installed unit and its drop-ins already have; it never reinstalls a unit. The repo unit sets no
   `TRADEAI_N8N_EXECUTOR_WORKERS`. **Since 2026-10-10 13:07 ET executor v2 runs with 3 workers** from the installed
   drop-in `~/.config/systemd/user/tradeai-n8n-run-executor.service.d/10-executor-v2.conf` (service grant
   eebd4ca0a6b31bd2), so it survives every promote. The gateway likewise takes `TRADEAI_N8N_GATEWAY_EXTRA_LANES`
   (incl. `n8n-workflow-error`) from the drop-in `tradeai-n8n-coordination-gateway.service.d/20-workflow-error-lane.conf`
   (2026-10-10 16:27 ET). Changing either is a grant-gated edit of the drop-in (`config-write`), then `daemon-reload`
   and a restart of that unit (`service`). Reinstalling a unit file from CURRENT keeps its `.service.d/` drop-ins.
   Rollback is in `docs/ops/ROLLBACK_COMMANDS.md`; the full n8n configuration is
   `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md`.

4. **n8n workflows are not part of promote.** A release that changes the relay, the gateway or `coordination/due`
   is promoted first; publishing or re-publishing a generic workflow is a separate step under a `cron` grant naming
   the workflow ids (`N8N_ONBOARDING_STANDARD.md` §5). When more than one workflow calls the gateway in the same
   minute, publish **one at a time** and read the relay log for `relay_gateway_unreachable` between them — the
   one-call-at-a-time relay contract check missed RC11 (2026-10-10 17:14–17:20 ET; fixed by #1667, released in
   `8ddf2ad59`, then the three routers were re-published 18:40, 18:44 and 18:47 ET).

5. **A promoted flag-gated feature is still off.** `8ddf2ad59` carries the scalp hot tier with `SCALP_HOT_TIER`
   unset (and a kill file path, `persistent-state/data/runtime/SCALP_HOT_TIER_DISABLED`); the search routing engine
   (#1676) ships behind `SEARCH_ROUTING_ENGINE`; step 1's broker read path has kill switches
   `DIRECTIVE_ENRICH_VIA_BROKER=0` and `DIRECTIVE_ENRICH_PREFETCH=0`. Turning a flag on in a crontab line or unit is
   its own operator step under a `cron` or `config-write` grant, from its packet, after the release that carries the
   code is live — never inside the promote.

6. **Scheduled jobs never push.** Since #1672 `coder_dispatch` (L556) and `backup_generated_docs.sh` (L541) commit
   locally only; a release does not add a push path to any cron line, timer or n8n lane.

## Production readiness checklist (added 2026-10-14)

Answer every line with evidence (a command output, a receipt path, a PR link) before asking for the approval above.
"n/a" needs a reason. Status words as in
`docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md` §0.

**A. Identity and release**
- [ ] The change is merged on `main`; the candidate SHA has green push-to-main CI (step 4).
- [ ] After promote, `curl -s 127.0.0.1:7777/v3/build-meta.json` names the SHA (step 6); the change is **LIVE**, not
      MERGED-NOT-SERVED. Nothing was edited inside a release directory; if an operator containment edit was made
      there (2026-10-14 18:11, `config/health_agent_policy.json`, `config-write` grants `96a0ab8c`/`d3a80ca0`), this
      release must carry the same content so served identity and running files agree again (done for that edit by
      5aa61048d, which serves #1737).
- [ ] Bound units restarted onto CURRENT (step 7); `systemctl --user --failed` empty.

**B. Safety rails**
- [ ] No broker, order, stop, credential, live-flag or 2FA path touched without the named grant (AGENTS.md §0, §22).
- [ ] If the change can reach a broker write: the change calls `assert_trading_unlocked` (the lock is LIVE @5aa61048d)
      (`tests/test_trading_lock_coverage_20261014.py`).
- [ ] New HTTP routes are classified in `config/cc_auth.yaml` (service, CSRF, step-up) and covered by its tests.
- [ ] No secret value in code, config, logs or docs (`scripts/check_no_secrets.py`).

**C. Observability and alerting**
- [ ] Every new scheduled job has a registry row with `output_signal` and a receipt (AGENTS.md §9.3).
- [ ] It has a health contract (REVIEWED for business-critical work) and appears in a monitor (breach detector or a
      health-tick step).
- [ ] Its failure reaches the operator through the chokepoint at the right priority (P1 if money or notification is at
      risk); quoted dry run of the alert path.
- [ ] Sends go through `send_telegram` / notification intents only (`scripts/check_comms_gateway_enforcement.py` green).

**D. n8n workflows (in addition)**
- [ ] The workflow is a business process (AGENTS.md 10.0.0 §23.23 (2)), not a timer-only leaf lane while the freeze is in
      force; it uses the fabric Run Lane and `tradeai-fabric-error`, and any sub-workflow it calls is published.
- [ ] The framework card of `N8N_ONBOARDING_STANDARD.md` §0 is in the PR; every element of the six areas
      (`N8N_CONFIGURATION.md` §0.4) is met or has an accepted exception.
- [ ] Drift check OK after import; activation grant names the workflow ids (`scripts/check_n8n_activation_grants.py`).
- [ ] No double run with a live cron line: cron commented in the same step, or the lane is idempotent by a semantic
      effect key (`CANARY_DOUBLE_EFFECT_AUDIT.md` §4).
- [ ] Live authority agrees in all gates: registry `dispatch.mode`, allowlist `live_arg`, relay live list (on 2026-10-14
      eleven registry-live canary rows ran dry because the relay list did not include them).

**E. AI / LLM**
- [ ] Model calls go through the governed bridge with a registered process id and caps; outputs have a schema; no
      LLM output can select an action outside the allowlist; a human gate precedes any side effect.

**F. Recovery**
- [ ] Rollback is one command and was dry-run (`ROLLBACK_COMMANDS.md`); data written by the change can be re-derived
      or is backed up (`config/backup_coverage_manifest.json`).
- [ ] The incident path for its failure is named (`docs/runbooks/INCIDENT_RESPONSE.md` class).

## Failure / rollback

A `prepare` refused with `CURRENT pin check tree_diff:N` means the release overlay and the commit differ.
2026-10-09: the overlay's `--exclude=data/` dropped the tracked `docs/implementation/n8n-maturity/data/`
files (`tree_diff:4`). #1620 includes `docs/**/data/` before the excludes. Root `data/` (runtime) stays
excluded. Find the differing paths before retrying. Do not retry blind.

`promote` already auto-rolls back to `PREV_RELEASE` on a failed health check (the pin step has not run
yet at that point, so no drop-in changed). Manual rollback restarts the bound units, rewrites the
expected-release pin and restores the drop-ins the undone promote archived. See
`docs/ops/ROLLBACK_COMMANDS.md`.

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
.venv/bin/python scripts/guard_request_approval.py release-write --for 30m --uses 3 --reason "Deploy <SHA> PR #<n> (emergency, GitHub incident <id>; prepare promote rollback)"
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
