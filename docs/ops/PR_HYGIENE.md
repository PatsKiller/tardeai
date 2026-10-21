# PR hygiene — the daily audit and the pre-build overlap check

```
Status:      PROPOSED (branch feat/pr-hygiene-audit-20261021; lane at SHADOW, contract REVIEWED by the operator 2026-10-21)
as_of:       2026-10-21T16:10:00-04:00
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Runbook-Id:  pr-hygiene-audit
Tests:       tests/test_pr_hygiene_audit_20261021.py (gate pr_hygiene_audit_20261021)
```

**Why.** On 2026-10-21 a backlog of 59 open PRs built up without anyone noticing. Clearing it took an ad-hoc
triage, and in the meantime #1906 re-did a fix that #1836 already carried. The operator approved a process plan the
same day: audit PR hygiene on every iteration, alert on it, and have agents check for overlapping PRs before they
build.

## 1. `scripts/pr_overlap_check.py` — run it before you build

```bash
python3 scripts/pr_overlap_check.py --files scripts/lib/cc_auth.py scripts/api_v2.py
python3 scripts/pr_overlap_check.py --keywords "step-up" reauth
python3 scripts/pr_overlap_check.py --files config/ --keywords hermes --json
python3 scripts/pr_overlap_check.py --files scripts/x.py --fail-on-overlap   # exit 3 when anything matched
```

The check lists every open PR that changes one of the files (a trailing `/` matches a whole directory) or that
mentions a keyword in its title, head branch, body, a changed path or a changed diff line. Read the PRs it lists
before you write code. Then extend, rebase or close the existing PR, or explain in your own PR why a second change
is needed. It is read-only: it uses `gh pr list` and GET-only `gh api`. Exit codes: 0 = the check ran, 1 = GitHub
could not be read, 2 = usage, 3 = overlaps found with `--fail-on-overlap`.
A later AGENTS amendment will make this check mandatory. That amendment is not part of this change.

## 2. `scripts/pr_hygiene_audit.py` — the daily audit

For every open PR, the audit records the PR's age, last update, draft state and hold markers
(DO-NOT-MERGE / PROPOSED in the title or body, or a do-not-merge label). It also records how many commits the PR is
behind main, whether it merges cleanly (`git merge-tree --write-tree --name-only origin/main <head>`), and whether
the required checks from branch protection passed on the head sha.

| Finding | Severity | Rule |
|---|---|---|
| CONFLICT | P2 | the head does not merge cleanly into main (`merge-tree` exit 1; without a clone, GitHub `mergeable == CONFLICTING`) |
| SUPERSEDED | P2 | the head is already contained in main (confidence **high**); or every non-ledger file the PR touches changed on main (first-parent) after the PR's last update. That second rule is a heuristic: confidence **low**, or **medium** if the PR also conflicts |
| DUPLICATE | P2 | two open PRs edit the same function (from the hunk header, in code files) or overlapping hunks of the same non-ledger file. Hunks whose +/- lines are identical in both PRs are treated as shared changes and set aside. Pairs in one stack are reported under `stack_families`, never as duplicates. A pair is in one stack when one PR says "stacked on #N" in its title or body, when one head is in the other's history, or when the two share unmerged commits |
| STACKED | P3 | the PR's base is another branch whose PR merged, whose branch is gone, or which moved after the PR was cut; or it declares "stacked on #N" and #N merged, closed, or is no longer in its history |
| STALE_HOLD | P3 | the PR is held (DO-NOT-MERGE / PROPOSED) and has not been updated for more than 3 days |
| UNPUSHED | P3 | a local branch in the main repo or its `.claude/worktrees/*` has commits on no remote branch. The audit reports only the branch name, commit count and last subject, never contents. Branches whose PR merged or closed (GitHub deleted the remote branch after a squash merge) are counted as `settled_local`, not reported as findings. UNPUSHED findings never trigger an alert |

Ledger files are excluded from DUPLICATE and from the SUPERSEDED file rule. These are the files that almost every PR
appends to: `docs/INDEX.md`, `scripts/run_cio_hardening_ci.py` and the cron-inventory README.

**Read-only by construction.** Every `gh` argv goes through `_assert_read_only_gh`, which allows only `pr list` /
`pr view` / `repo view` and `api` with no method or field flags; `graphql` is refused. Every `git` argv goes through
`_assert_read_only_git`, which allows only rev-parse, rev-list, merge-base, merge-tree, log, for-each-ref,
`worktree list`, cat-file and `remote get-url`. `fetch` runs only with `--fetch`, and never with prune or force.
Tests pin that `merge`, `close`, `comment`, `push`, `branch -D`, `POST` and `graphql` are refused before anything runs.
`merge-tree --write-tree` does write tree and blob objects that nothing references, and `git gc` collects them.

**GitHub access.** The audit lists PRs with `gh pr list --json` (GraphQL) first. If that fails, it falls back to the
REST API through `gh api` (`pulls?state=open`, `commits/<sha>/check-runs`), which uses the same existing gh auth.
The script never reads, names or prints a token.

**Without a local clone** (the lane runs from a release that is not a git checkout, unless
`TRADEAI_PR_HYGIENE_REPO` names a clone), the audit takes behind/contained from the compare API and mergeability
from GitHub. In that mode the SUPERSEDED file rule and the unpushed scan are not measured, and the receipt says so.

```bash
python3 scripts/pr_hygiene_audit.py --report          # print only (same as --dry-run); writes nothing
python3 scripts/pr_hygiene_audit.py --report --json   # the full report
python3 scripts/pr_hygiene_audit.py                   # real run (the lane's live argv, once promoted)
```

A **real run** writes three things:

1. The receipt `<state root>/data/runtime/pr-hygiene-audit_last.json`: LaneRunReceipt with v2 output fields,
   `produced_count` = open PRs audited, and the full report under `summary`.
2. The alert state `data/runtime/pr_hygiene_audit_alert_state.json`.
3. At most two **host comms intents**, written straight into the coordination ledger's `comms_intents` table (the
   #1899 hermes-scorer pattern). The audit never calls a sender and never imports `lib/host_comms_intents`, whose
   closure reaches broker modules:
   - `agents/pr_hygiene_findings`, only when the alertable finding set **gained** a finding. An unchanged or
     shrinking set is silent. On top of this, the store dedupes identical subjects.
   - `agents/pr_hygiene_weekly_digest`, once per ISO week.

   Both routes are DIGEST (P2) in `config/host_comms_intent_routes.json`, with producer `pr_hygiene_audit`. The
   comms-intent consumer and the incident notifier deliver them (AGENTS.md §24.1).

The state advances only for an intent that was actually queued, so a refused intent (for example, ledger absent) is
retried on the next run. Exit codes: 0 = the audit completed (findings are output, not failures); 1 = GitHub
unreadable, in which case the receipt is written failed and `ok_at` is carried forward.

## 3. Needs action

`GET /api/v2/needs-action` has a tenth source, `pr_hygiene`. It is implemented by `needs_action.probe_pr_hygiene`
and `rule_pr_hygiene`, and it reads the receipt only:

- CONFLICT, SUPERSEDED and DUPLICATE are P2 items; STACKED and STALE_HOLD are P3 items. Each item's evidence
  carries the PR url. The first 12 findings are shown individually, and the rest are rolled up into one item.
- Unpushed local branches appear as one P3 rollup.
- No receipt yet appears as one P3 item. At shadow the lane runs dry and writes nothing, so this is normal until it
  is promoted.
- A failed run, or a last good run more than 36 hours ago, is P2.

See [`CC_NEEDS_ACTION_2026-10-21.md`](CC_NEEDS_ACTION_2026-10-21.md).

## 4. The n8n lane `pr-hygiene-audit`

- **Registry row:** `scheduler.kind: n8n`, `expression: dispatcher`, `stage: shadow`, and a `dispatch` block with
  mode `dry_run`, cron `30 6 * * *` America/New_York, class `monitor` and retry policy `transient-2`. You can also
  fire it on demand through `coordination/run`. There is no crontab line and no systemd unit (cron freeze).
- **Allowlist:** argv `$PY scripts/pr_hygiene_audit.py`, `dry_run_arg ["--dry-run"]`, `live_arg null`, and its own
  flock `/tmp/tradeai_pr_hygiene_audit.lock`. `env_names` holds no secret and no broker name. The gh CLI reads its
  own config under `HOME` (a base name).
- **Health contract:** **REVIEWED** by the operator 2026-10-21 ("yes approve pr-hygiene-audit too"), owner platform
  (AGENTS.md §23.19). The lane stays at shadow until the operator promotes it.
- **Reach:** the lane reaches no sender and no broker. `tests/test_lane_transitive_capabilities_20261015.py` and
  `tests/test_agents_policy_7_0_0_advisory_market_data.py` pass with no new exception, and this file's tests pin the
  closure.
- **Promotion to live is the operator's decision.** It needs a registry and allowlist PR that sets `live_arg []` and
  `dispatch.mode live`, plus a REVIEWED contract. For the merge-tree and unpushed scans, the operator also sets
  `TRADEAI_PR_HYGIENE_REPO` in the executor environment.

## 5. Measured 2026-10-21 16:09 ET (`--report`, read-only, origin/main `7faa8cddf`)

```
open_prs=30 drafts=0 held=8 conflict=18 superseded=0 duplicate=1 stacked=3 stale_hold=7 required_checks_failing=2 unpushed_branches=212
settled local branches (PR merged/closed, remote branch gone; not findings): closed 1, merged 2
```

- **DUPLICATE (high):** #1887 and #1907 both edit `.github/workflows/options-lifecycle-ci.yml` lines 56–58.
- **STACKED:** #1879, #1880 and #1881 sit on `wt/*-grant-census-20261019` bases that moved after the PRs were cut.
- **STALE_HOLD:** #1629 (DO-NOT-MERGE, idle 11.8 days) and the PROPOSED F09 batch #1795–#1802 (idle 5.9 days).
- **Stack families, not reported as duplicates:** #1795→#1802 and #1804→#1807 (declared "stacked on #N"), and
  #1880/#1881 (they share unmerged commits).
- **Calibration:** the first draft of the duplicate rule reported 28 pairs, 27 of them stacks. Treating identical
  hunks as shared changes and grouping stack families brought it down to 1.
