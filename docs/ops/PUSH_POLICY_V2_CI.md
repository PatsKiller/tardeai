# Push policy v2 — the CI half: draft PRs are cheap, ready PRs run everything

```
Status:      PROPOSED (this PR); the hook half is an operator-applied package (AI_WORK_POLICY.md §29, PROPOSED)
as_of:       2026-10-23T14:15-04:00 (rebased onto origin/main c04a09498, after release batches 8, 9 and 10)
Measured at: origin/main 53aa1b619 (run sample); workflow set re-checked at c04a09498
```

Operator 2026-10-23: "redesign the push policy then. And how does the push policy actually coincide with the new
train?" AGENTS.md rule 11 (ACTIVE since 20.0.0) asks agents to keep work recoverable across vendors with draft PRs. A
draft PR push must therefore cost almost nothing on GitHub. This change makes that true in the workflows. Who may push,
how often, and with which reason is the pre-push hook's job (the operator package, not this PR).

## What a push now starts

| PR state | workflows that run | about |
|---|---|---|
| **draft** | `draft-quick-check` (syntax of changed files, secrets scan) and `agent-governance` (always-on SOP gate) | 2 runner-min |
| **ready for review** (or marked ready) | the full fleet: `cio-hardening`, `cio-full-suite-sharded` / `ci-gate`, `release-readiness`, `agent-governance`, `aif-financial-senses-integration`, `provider-cost`, plus path-filtered suites | ~60-80 runner-min (estimate, 2026-10-23 sample) |
| push to an agent branch with no PR | nothing (no push trigger fires on agent branches any more) | 0 |
| push to `main` | unchanged: every post-merge run, one concurrency group per SHA | unchanged |

Measured basis for the estimate: 200 `pull_request` runs on 2026-10-23 12:08-13:38Z covered 27 PR pushes; median wall
time per run was cio-hardening 9.2 min, cio-full-suite-sharded 6.9 min (11 jobs), aif-financial-senses 2.8 min,
release-readiness 2.1 min, agent-governance 1.3 min, provider-cost 1.0 min (`gh run list --event pull_request`).

## The mechanics

1. **Draft guard.** Every job a pull request can start carries
   `if: github.event_name != 'pull_request' || github.event.pull_request.draft == false`
   (combined with its existing condition). `ci-gate` uses `always()`, so it carries the guard too. A skipped job's
   check reads "skipped". A draft cannot be merged, and the release train refuses drafts
   (`release_train_controller._pre_exclusion` returns `DRAFT`) and counts only checks that are exactly `success`
   on the candidate SHA (AGENTS.md §25.2), so a skip never qualifies anything.
2. **Ready re-runs.** Every `pull_request` trigger lists `types: [opened, synchronize, reopened, ready_for_review]`.
   Marking a draft "Ready for review" starts the full fleet on the same head, with no new push.
3. **Superseded runs are cancelled.** Every pull_request workflow has a concurrency group per workflow and ref. It
   cancels in progress for `pull_request` events only. Pushes to `main` get one group per SHA, the pattern from
   `tests/test_ci_push_run_per_sha_20261021.py`.
4. **No push trigger on agent branches.** Push triggers that also fired on `fix/**`, `feature/**`, `wt/**`, `aif/**`,
   `hardening/**` or on every branch (path filter only: `defense-sectors-ci`, `options-lifecycle-ci`) now fire on
   `main` only. The PR run is the run. Before this change a continuity push of a `fix/*` branch ran
   `aif-financial-senses-integration` with no PR at all.
5. **Unchanged on purpose.** `agent-governance` (SOP Stage 7, always-on; its CONTROL7 proof pins the workflow blob)
   still runs on drafts. It is about one runner-minute, and it means a draft's required governance context is a real
   result. No path filter was added to a required context.

6. **One workflow pending.** `research-governance-ci.yml`: its PR scope guard fails any PR that changes it together
   with a file outside the research-governance allowlist, so its three hunks ship in a PR of their own. It is
   path-filtered, so it seldom fires on a draft. The test lists it in `PENDING_CLAIMED`, and a companion test fails
   once it gains the guard, so that PR also removes the entry.
   `agent-intelligence-foundation-ci.yml` and `financial-senses-ci.yml` were CRLF files and are now LF:
   `git diff --check` (active-trader-policy-ci `deterministic-policy`) reports every added CRLF line as trailing
   whitespace.

Required checks on `main` (read with `gh api .../branches/main/protection/required_status_checks`, 2026-10-23):
`cio-hardening`, `agent-governance`, `release-readiness`, `ci-gate`. Job names are unchanged. On a ready PR each one
runs exactly as before (none of them has a path filter). On a draft, `agent-governance` runs and the other three read
"skipped".

Tests: `tests/test_ci_draft_pr_skip_20261023.py` (CI gate `ci_draft_pr_skip_20261023`).

## How this meets the release train

The train only queues **ready, green** PRs. Drafts are excluded (`DRAFT`), so are held, stacked and conflicting PRs,
and so is any PR whose required checks are not exactly `success` on its head. An agent's lifecycle is:

```
local commits (hourly) → wip push to a DRAFT PR (draft-quick only) → … → mark READY (full CI once)
→ green → the train's next window takes it → train/<id> batch PR → main → release
```

A batch that changes `.github/workflows/**` stays on the manual path: the train's GitHub App has no Workflows write
(AGENTS.md §25.5). This PR is one of those.
