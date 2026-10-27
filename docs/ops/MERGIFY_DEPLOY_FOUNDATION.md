Status: ACTIVE
as_of: 2026-10-26
Measured at: AGENTS.md 24.0.0 ACTIVE · Telegram go-signal (label=operator-merge)
Canonical repo path: docs/ops/MERGIFY_DEPLOY_FOUNDATION.md
Authority: operator-approved plan mergify_replace_train (2026-10-26); Telegram automation 2026-10-26
Supersedes: GitHub Approve-by-PatsKiller as Mergify gate; merge-ready as Mergify gate; train merge path
See also: docs/ops/AGENT_MERGIFY_HANDOFF.md · docs/ops/EMERGENCY_MANUAL_PROMOTE.md · docs/ops/MERGIFY_CUTOVER_CHECKLIST.md · AGENTS.md §25.10

# Mergify + host deploy — foundation

## One-sentence version

**Mergify merges green PRs after a Telegram Approve tap (host adds `operator-merge`) on a schedule; a thin host poller promotes exact `main` SHAs; emergency is operator host CLI + `release-write` naming the SHA.**

## Authority split

| Actor | May | Must not |
|---|---|---|
| Coding agents | Open ready PRs, push feature branches under push budget, apply `solo`/`shared-infra`, run `request_pr_merge_approve.py` | Merge, push `main`/`train/*`, promote, release, Approve on GitHub, add `operator-merge` by hand |
| Mergify | Merge eligible PRs when `label=operator-merge` + required checks green + not draft + schedule allows | Deploy, hold credentials beyond GitHub App merge, place broker/order work |
| Host `deploy_on_main` poller | Promote CURRENT to the new `origin/main` SHA when STOP is clear and deploy delegation is armed | Merge, push remotes, run without STOP/lock checks |
| Operator (phone) | Telegram **Approve merge** / Deny; emergency promote; STOP/resume; arm deploy delegation; install Mergify | Delegate live broker authority |

## Normal path

```
Ready PR opened (not draft; solo/shared-infra labels if needed)
         → CI green (cio-hardening, agent-governance, release-readiness, ci-gate)
         → Agent: request_pr_merge_approve.py --pr <N>
         → Operator Telegram Approve merge (one tap)
         → Host adds label operator-merge
         → Mergify queue (ET schedule windows)
         → squash-merge to main
         → deploy_on_main poller sees new origin/main SHA
         → STOP absent + GlobalReleaseLock + standing deploy delegation
         → cio_phase2_exact_main_deploy.sh prepare+promote
         → post_release_tester verify
         → DeployOnMainReceipt@v1 (path=poller)
```

Go signal in `.mergify.yml`: `label=operator-merge` + `draft=false`. Not GitHub Approve UI. The `merge-ready` label is **not** a queue condition.

## Standing deploy delegation

- Host record only (outside the repo), similar shape to ReleaseDelegation but **promote-only**.
- Arms the poller. Does **not** authorize Mergify, agents, or emergency promote.
- Emergency uses a separate `release-write` grant that names the exact SHA (and optionally PR).

## Shared STOP and lock

- Same latch as today: `STOP.json` under the release-window state dir (`scripts/lib/release_control.py`).
- Same global flock: `<state_dir>/.lock` (`GlobalReleaseLock`).
- Poller and emergency both refuse when latch is set or unreadable; both serialize on the lock.

## CI-outage emergency (still operator-only)

When required checks cannot run (Actions outage), Mergify will not merge. The operator may promote an already-known SHA from the host with:

1. Active `release-write` grant whose reason names that SHA (and PR if known).
2. Env `TRADEAI_EMERGENCY_RELEASE_SHA=<full_or_prefix_sha>` matching the grant.
3. `scripts/emergency_manual_promote.sh` (wraps the same promote path; writes `path=manual_emergency` receipt).

No agent, n8n job, or Mergify rule may set that env or consume that grant.

## What this retires

- Custom train controller live merge/push of `train/*`
- Release-train GitHub App as merge actor (Mergify’s App replaces it for merge)
- Ops → Controls **Run now** / Release train tab as a live force path
- `AI_WORK_POLICY.md` §28 train-push exception (replaced by Mergify merge + poller promote)
- GitHub Approve UI and `merge-ready` as Mergify go-signals

## Evidence

- Receipt schema: `DeployOnMainReceipt@v1` under persistent-state `data/runtime/deploy_on_main/`
- Poller unit: `tradeai-deploy-on-main.timer` → `scripts/deploy_on_main_poll.py`
- Telegram go-signal: `scripts/lib/pr_merge_telegram.py` · `scripts/request_pr_merge_approve.py` · `scripts/notify_pr_merge_ready.py`
- Notify timer (operator install §17): `config/systemd/user/tradeai-pr-merge-notify.{timer,service}`
- Config: `.mergify.yml` at repo root
