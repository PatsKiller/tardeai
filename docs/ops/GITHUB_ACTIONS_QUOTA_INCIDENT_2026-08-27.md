# GitHub Actions outage — repo visibility flip exhausted the private-repo minute quota

**Date:** 2026-08-27
**Duration:** ~13:23Z → ~14:31Z (68 min), all branches
**Impact:** 65 CI runs across 11 branches and `main` reported `failure`. No test actually ran. No production impact — CI-only.
**Root cause:** repository visibility was flipped from public to private, moving Actions onto the metered free tier; a burst of 18 PRs × 4–5 workflows exhausted the monthly minute allowance mid-run.

---

## Why this is worth a document

The failure mode is **indistinguishable from a test failure** in every UI surface an operator or agent normally looks at. `gh pr checks` shows red. `gh pr view` shows `FAILURE`. The PR is `BLOCKED`. Branch protection refuses the merge.

But `gh run view --log-failed` returns **nothing**, because there is no log — no runner was ever assigned. An agent that trusts the red check will conclude its own change broke the build and start "fixing" green code. That happened during this incident: 13 PRs were initially triaged as having failing tests.

## The signature — how to recognise it in one command

```bash
gh api "repos/PatsKiller/tardeai/actions/runs/<RUN_ID>/jobs" \
  --jq '.jobs[] | {name, conclusion, steps: (.steps|length), runner: .runner_name}'
```

A quota/billing block looks like this — and nothing else looks like this:

| Field | Quota block | Real test failure |
|---|---|---|
| `conclusion` | `failure` | `failure` |
| `steps` length | **0** | 8–14 |
| `runner_name` | **`""`** (empty) | `GitHub Actions <n>` |
| job duration | **2–5 s** | minutes |
| `runs/<id>/timing` → `billable.UBUNTU.total_ms` | **0** | > 0 |
| `--log-failed` | **empty** | assertion text |

**Zero steps + no runner + zero billable ms = the job was rejected before it started.** It is never a code problem. Stop debugging the diff.

## Timeline (all times UTC)

| Time | Event |
|---|---|
| 03:05 | Repo visibility flipped public → private (`updated_at` 2026-08-27T03:05:03Z) |
| 13:21:33 | Last successful run (`wt/rebalance-verify-before-notify`) — quota not yet exhausted |
| 13:23:42 | First rejected run (`33076592809`) — 3 s, 0 steps, no runner |
| 13:23 → 14:21 | 65 runs rejected across 11 branches and `main`, including post-merge runs on `main` |
| ~14:25 | Misdiagnosis window: 13 PRs triaged as "failing CI"; `--log-failed` empty on all of them |
| ~14:31 | Visibility restored to public (`gh api -X PATCH repos/PatsKiller/tardeai -F private=false`) |
| ~14:32 | Verified fixed: rerun assigned `GitHub Actions 1000008040`, 10 steps executing |
| 14:33 → 14:55 | All 65 runs re-triggered — **65/65 green. Zero real test failures.** |

## Fix applied

```bash
gh api -X PATCH repos/PatsKiller/tardeai -F private=false
```

Public repositories get unlimited free Actions minutes on GitHub-hosted runners; private repositories on a personal account get 2,000 min/month. Restoring public visibility removed the meter entirely. This also restored the repo's standing policy — `tardeai` is intended to be public (see below).

Then re-trigger everything that was rejected:

```bash
gh run list --limit 300 --json databaseId,conclusion,createdAt \
  --jq '[.[] | select(.conclusion=="failure") | select(.createdAt >= "<block-start>")] | .[].databaseId' \
  | while read -r id; do gh run rerun "$id"; done
```

## Invariant this establishes

**`tardeai` stays public.** It is not a cosmetic preference:

1. **Free CI.** Private-repo minutes are metered and the repo's 14 workflows burn them in bursts. One busy merge day exhausts a month's allowance, and the failure is silent and misleading.
2. **Standing operator policy** since 2026-07-18: the repo is public and is not to be flipped private at session close.

If the repo must ever go private, a non-zero Actions spending limit has to be set **first**, or CI will die exactly this way. Do not flip visibility as a "cleanup" step.

## Detection gap (open)

Nothing alerted on this. `main`'s own post-merge CI was failing for 68 minutes with no notification. A `gh run list --branch main` health probe that distinguishes a quota block (0 steps / no runner) from a genuine failure and alerts on the former would have caught it in minutes — it is not yet built.

## Secondary finding

While triaging, one check on PR #529 was found to be a **genuine intermittent failure** unrelated to the quota block, and it exposed a real bug in a safety gate. See PR #540 and `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` (§Closeout). The lesson generalises: a quota outage can mask real failures, so re-run and re-read every check after restoring CI rather than assuming the outage explains all of them.

---

**See also:** `AGENTS.md` → Non-obvious gotchas · `AI_WORK_POLICY.md` §13 Remote-cost awareness
