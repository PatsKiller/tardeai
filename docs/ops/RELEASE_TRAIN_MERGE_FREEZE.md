# Release train: the merge freeze, enforced

Status: BUILT, 2026-10-25. Follows the arming PR #2099. The GitHub check reports from the first merge, but it
blocks a merge only after the operator makes it a required check (§6).

## 1. The rule

AGENTS.md §25.3 says: from `merge_freeze.starts_min_before_window` (30) minutes before a window opens until that
window's train is terminal (verified, rolled back or stopped), nothing but the train merges to `main`. The delegation
declares it as `merge_freeze: {starts_min_before_window: 30, ends: train_terminal, applies_to:
all_non_train_merges_to_main}`. Until this change, no code enforced it.

The schedule comes from `config/release_train_policy.json` `windows[].days`, read by the same
`release_train_window_view.policy_window` the request lane and the controller use:

| Days | Windows (ET) | Freeze starts |
| --- | --- | --- |
| Mon–Fri | 12:00, 18:00 | 11:30, 17:30 |
| Sat | 06, 09, 12, 15, 18, 21 | 30 min before each |
| Sun | 00, 03, 06, 09, 12, 15, 18, 21 | 30 min before each (Sat 23:30 for Sun 00:00) |

There are no Saturday or Monday 00:00 / 03:00 windows. Only an armed policy schedules a freeze. Each window is a
wall-clock time in America/New_York. The freeze starts 30 minutes of real time before it, so across a DST change it
starts at 01:30 EST before a 03:00 EDT spring-forward window, never at a 02:30 that does not exist.

## 2. When it ends

`scripts/lib/release_train_freeze.py` (stdlib, read-only) works out the freeze from the clock, the policy, the freeze
settings (`config/release_train_merge_freeze.json`) and, on the host, the train's own records in the release-window
state dir:

| Code | Freezes while |
| --- | --- |
| `PRE_WINDOW` | the clock is in `[start − 30 min, start)` |
| `AWAITING_REQUEST` | the window is open, no request `rtw-<date>-<HHMM>-win` exists yet, and the time is still within `request_grace_min` (15, the n8n `grace_min`). After that the window was skipped (no catch-up), so the freeze ends. |
| `WINDOW_TRAIN_PENDING` | the request is in the spool, unclaimed and not expired. An expired request with no receipt ends the freeze and raises a warning. |
| `WINDOW_TRAIN_RUNNING` | the receipt is `ACKNOWLEDGED`, for up to `stale_after_min` (240) after the window opened. |
| `TRAIN_IN_FLIGHT` | any live `trains/<id>/state.json` has no `outcome` and its `updated_at` is under `stale_after_min` old, at any time. This covers operator-forced canary runs and the phases after the receipt. |
| `BATCH_PR_OPEN` | (CI) an open `train/<id>` PR into main exists |
| `POLICY_UNREADABLE` | the schedule cannot be read, so no layer can rule a freeze out |

Terminal means a receipt in `COMPLETED` (any outcome, `NO_OP` included), `REFUSED`, `EXPIRED` or `FAILED`.

**Nothing freezes indefinitely.**
* An unreadable train state file is a warning, not a freeze.
* A train that is still `ACKNOWLEDGED` 240 min after its window, or a live train whose state has not moved for
  240 min (or that has no `updated_at`), is **stale**. It stops freezing and is listed in the verdict's `stale`.
* Each stale train raises a P1 through the existing operator alert path (`telegram_alert.send_telegram`,
  `priority="P1"`, deduped for 6 h; `release_train_freeze.alert_stale`). The alert fires when `check-pr` or the
  Tier 2 merge evaluates the freeze, so the operator hears about it at the moment it stops holding a merge.
* Reconcile a stale train with `release_train_controller` `train-orphan-resolve` / reconcile.

A SET STOP latch means the operator stopped the train (§25.3: "unless the operator first stops the train"). It lifts
`PRE_WINDOW`, `AWAITING_REQUEST` and `WINDOW_TRAIN_PENDING`; stale trains are lifted with or without STOP. A
train that is still moving is settling, and it freezes until it is terminal. An UNREADABLE latch lifts nothing.

## 3. Exemptions

* **The train's own batch PR.** This is how the train is recognised. `GhCliWriter` and `GitHubAppWriter` open it with
  head `train/<train_id>` (`release_capability.TRAIN_RE`) from this repository, base `main`. All of these must hold:
  * the head, the repository and the base match;
  * the author is in `train_pr_authors`. It is set to `tradeai-release-train[bot]`, the public author of the App's
    batch PR #2069; no host config file was read. GraphQL reports the login as `tradeai-release-train` (a Bot) and
    `gh pr view` as `app/tradeai-release-train`; both are normalised. **An empty list exempts nothing**: a branch
    name alone can be spoofed;
  * on the host (`check-pr`, Tier 2), the PR's train id is also a live train in `<state>/trains` with no outcome yet.
* **The label `freeze-exempt`.** It counts only when the login that applied it (the newest matching `labeled` event in
  `issues/<n>/events`) is in `operator_logins` (`PatsKiller`). An empty list means the label counts for nothing.
  * The CI status and the Tier 2 merge (a passkey-authenticated operator act) honour it.
  * The agent merge helper **never** does: agents use the operator's gh identity, so who applied a label cannot be
    told apart.

  Create the label once:
  `gh label create freeze-exempt --repo PatsKiller/tardeai --color B60205 --description "Operator: merge during a release-train freeze"`.
* **A base other than `main`.** Stacked PRs are not merges to main.

The train selects its members from its own check manifest (`REQUIRED_CHECKS`) and the census, never from the freeze
context, so the freeze never stops the train selecting what it carries.

## 4. Decision: unreadable receipts

**The 30-minute pre-window freeze always holds. Once the window opens, an unknown train state does not freeze, and a
warning says so.**

* The pre-window freeze needs only the clock and the policy, so it can always be enforced.
* After the window opens, a merge that lands under the train is caught by the train itself. A move before the member
  freeze is `MAIN_MOVED_AT_FREEZE`, a quiet NO_OP. A move at merge time is `MAIN_MOVED_AT_MERGE`, which gives
  MERGED_NOT_LIVE plus a P1 alert. Either way the cost is one window.
* An open-ended freeze on an unreadable file would block every merge, with no end time and nobody to clear it.
* GitHub runners can never read the host's receipts, so the CI layer is always in this mode. It adds one fact it
  can see, the open batch PR, which covers the riskiest stretch: from the train's push to its merge.

## 5. Where it is enforced

1. **The `train-merge-freeze` commit status** comes from `.github/workflows/train-merge-freeze.yml`, which runs
   `scripts/release_train_freeze.py ci --apply`.
   * It runs on `pull_request` events into main (`opened`, `synchronize`, `reopened`, `ready_for_review`,
     `labeled`, `unlabeled`, `edited`), a scheduled sweep at `4,14,24,34,44,54 * * * *`, and `workflow_dispatch`.
   * It sets `pending` ("Merge freeze: …") or `success` on every open non-draft PR into main whose status differs,
     and always on the PR that triggered the event.
   * The status turns `pending` `ci_lead_min` (15) minutes before a freeze starts. GitHub's scheduled runs can be
     late, so a status set when the PR was pushed must not stay green into the freeze.
   * The workflow checks out **main's** code and policy, so a PR cannot vouch for itself.
   * Its token has `statuses: write` and nothing more. Commit statuses are latest-per-context, so the newest
     evaluation wins.
   * Until this file is on `main`, the scheduled sweep does not run. A PR that is retargeted to main before then
     fails the job, because main's checkout has no script yet, and that PR gets no status.
2. **The agent merge helper.** `scripts/agent_merge_pr.sh` runs `release_train_freeze.py check-pr <PR>` first. Exit 3
   means refused, and the message names the window and says that the freeze ends when its train is terminal. If the
   check itself fails, the helper also refuses: an agent merge is never urgent.
3. **The Tier 2 merge.** `work_pipeline_tier2.merge_preconditions` refuses `MERGE_FREEZE`, or `MERGE_FREEZE_UNKNOWN`
   when the verdict cannot be computed. It uses the host verdict, which reads the receipts, and the same exemptions,
   with the label only when an operator login applied it.
3a. **The train itself.** Before the merge capability is issued, the controller waits up to 300 s, never past the
   window, for `train-merge-freeze` to read `success` on the batch head (`GhCliReader.commit_status`, a GET;
   `TrainController._wait_freeze_status`). The batch PR is exempt, so the wait only absorbs Actions latency. If the
   status is still not success after the wait, the merge proceeds: GitHub accepts it when the context is not
   required and refuses it when it is, and the existing pre-merge failure path then applies.
4. **Raw `gh pr merge`.** Once the status is a required check (§6), GitHub refuses the merge for every actor.
   The guard hook's existing `remote.pr_merge` detector (`scripts/hooks/agents_guard_pretooluse.py`) is the place to
   add an agent-side refusal. That is an operator-applied guard patch, so it is not made here.
5. **What the page shows.** On Releases & schedules (`GET /api/v2/ops/releases-schedules`, `windows.value.merge_freeze`),
   the header carries a chip: `MERGE FREEZE`, `merge freeze from HH:MM ET` or `merge freeze UNKNOWN`. The Next windows
   section shows the summary, the rule, the exemptions and any warnings.

Readers of main's required checks drop the context with `merge_freeze_context.without_freeze_context`. The
context is a timing gate, not a CI result:

* the census (`pr_hygiene_audit.required_contexts`): otherwise every PR reads PENDING during a freeze and the train
  selects nothing;
* tree-attested promote: a commit status is never a check run, so every promote would refuse `check_missing`;
* the claim lifecycle `ci_green`;
* the Work pipeline;
* the Tier 2 merge, which asks the freeze directly.

Operator commands:

```
python3 scripts/release_train_freeze.py status                 # FROZEN/OPEN, reasons, warnings
python3 scripts/release_train_freeze.py status --json --now 2026-10-26T11:45:00-04:00
python3 scripts/release_train_freeze.py check-pr 2101          # exit 0 may merge, 3 refused
gh workflow run train-merge-freeze.yml --repo PatsKiller/tardeai   # refresh every PR's status now
```

## 6. What the status is worth, and the GitHub settings step (operator, §17)

**Against agents, the commit status is advisory. The host `check-pr` is the real gate.**
* Any token with `repo` scope can post a commit status with any context. That includes the operator's gh token,
  which agents also use. Without an integration pin, an agent could post `train-merge-freeze: success` itself.
* The `freeze-exempt` label has the same weakness: an agent can add it as `PatsKiller`.
* The status therefore stops a merge only when the required check is **pinned to the GitHub Actions integration**
  (`integration_id` / `app_id` **15368**, the `github-actions` app). With that pin, only a status the workflow posted
  with its `GITHUB_TOKEN` can satisfy it.
* Even pinned, it is coarser than the host: after a window opens it sees only the batch PR, never the receipts.
* `scripts/agent_merge_pr.sh` → `check-pr` reads the receipts and ignores the label. Agents must merge through it;
  the guard hook's `remote.pr_merge` detector is the place to make that mandatory (an operator-applied guard patch).

**Not done by this PR.** Do it after this PR is on `main`, after the label exists (§3), and after one scheduled sweep
has posted a status to every open PR.

**Preferred: a ruleset** pinned to the Actions integration:

```
cat > ~/train-merge-freeze-ruleset.json <<'JSON'
{
  "name": "main-train-merge-freeze",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "bypass_actors": [],
  "rules": [{
    "type": "required_status_checks",
    "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [{"context": "train-merge-freeze", "integration_id": 15368}]
    }
  }]
}
JSON
gh api -X POST repos/PatsKiller/tardeai/rulesets --input ~/train-merge-freeze-ruleset.json
```

**Alternative: classic protection**, keeping the existing contexts and pinning only the new one:

```
gh api repos/PatsKiller/tardeai/branches/main/protection/required_status_checks \
  | jq '{strict: .strict, checks: ([.checks[] | {context, app_id}] + [{"context": "train-merge-freeze", "app_id": 15368}])}' \
  | gh api -X PATCH repos/PatsKiller/tardeai/branches/main/protection/required_status_checks --input -
```

Verify the pin on the first frozen PR:
* `gh api repos/PatsKiller/tardeai/commits/<head sha>/statuses --jq '[.[] | select(.context=="train-merge-freeze")][0].creator.login'`
  must print `github-actions[bot]`.
* A status posted with a personal token must leave the PR blocked.

To undo: delete the ruleset (`gh api -X DELETE repos/PatsKiller/tardeai/rulesets/<id>`), or PATCH the checks list
without the entry.

Do not put the release-train App on the ruleset's bypass list. Its batch PR is exempt by the workflow, and the
controller waits for that success (§5, 3a).

On GitHub, a PR that has no status yet waits for "Expected". The first sweep fills in every open PR within about
10 minutes.

## 7. Tests

`tests/test_release_train_merge_freeze_20261025.py` (CI gate `release_train_merge_freeze_20261025`) covers:

* window math across both DST changes;
* the weekend slots;
* terminal detection;
* unreadable inputs and STOP;
* exemptions: the App-author pin, the live-train match on the host, an empty list exempting nothing, the label
  counted only from an operator login and never by `check-pr`;
* stale and unreadable train state, and the P1;
* the controller's bounded wait for the status before the merge capability;
* the CI plan (posting only changes, skipping drafts, forcing the event PR, the lead window);
* each enforcement point;
* the readers that drop the context;
* the page and the workflow.
