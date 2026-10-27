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

### How the poller's prepare/promote is authorised (2026-10-27)

The native preflight (`scripts/release_grant_preflight.py`) refuses prepare/promote unless something binds the
release. A human `release-write` grant naming the SHA still works and is tried first. For the poller, the armed
standing deploy delegation itself is the authority, through `scripts/lib/deploy_delegation_binding.py`
(`matched_by: deploy_delegation`, `binding_source: deploy_delegation`, guard ledger not consumed). Before
2026-10-27 the poller had no binding of its own, so it promoted only when an unrelated human grant happened to name
the SHA; every poll from 13:34Z on 10-27 was refused with "no release-write grant names this PR/SHA/campaign".

The binding holds only when **all** of these are true:

1. Action is `prepare` or `promote`. `TRADEAI_EMERGENCY_RELEASE_SHA`, `TRADEAI_RELEASE_TRAIN_SHA` and
   `TRADEAI_RELEASE_CAMPAIGN` are unset (emergency and train keep their own rules).
2. The poller wrote a one-run ticket (`DeployDelegationTicket@v1`, `<release_window>/deploy_delegation_ticket.json`)
   while holding GlobalReleaseLock. The ticket names this exact SHA, is under 20 minutes old, and the nonce in the
   child environment hashes to the one in the ticket. The poller deletes the ticket when the run ends.
3. The ticket's pid is an ancestor of the preflight process, runs in the `tradeai-deploy-on-main.service` cgroup,
   and holds the GlobalReleaseLock flock (`/proc/locks`).
4. STOP is ABSENT. The delegation file is `status: ACTIVE` with `scope: promote_only`. The lab
   `TRADEAI_DEPLOY_DELEGATION_SOFT` switch never counts here.
5. The SHA equals `origin/main` in the canonical checkout, and main's required push checks are green for that SHA.
   Promote also runs its own exact-SHA CI gate, as it did before.

Agents, n8n and Mergify can't meet conditions 2 and 3 because they aren't the poller unit's process holding the
lock. Same-uid processes are not a hard security boundary on this host. This is fail-closed attribution, the same
standard the rest of the release path uses. Each poller receipt records `detail.matched_by` and
`detail.bindings.{prepare,promote}`.

### Poller run order (under the lock)

1. Re-check STOP and the delegation.
2. Read main's required checks. If they're pending or GitHub is unreachable, the outcome is `waiting_ci`. That
   isn't a failure: there's no alert and no streak. If they're red, the outcome is `deploy_failed` with reason
   `main_checks_red`.
3. **Checkout hygiene.** If the canonical checkout is dirty, the poller sends a P1 naming the dirty paths, deduped
   per SHA per hour. With `TRADEAI_DEPLOY_PRESERVE_DIRTY` set to `1` (the default), it then preserves the work and
   proceeds:
   - a patch at `persistent-state/data/runtime/deploy_on_main/dirty_checkout/<tag>.patch`
   - `git stash push --include-untracked -m <tag>`
   - a ref at `refs/deploy-on-main/autostash/<tag>`

   With the flag set to `0`, the poller refuses with `checkout_dirty`. It never discards anything.
4. Write the ticket, run `cio_phase2_exact_main_deploy.sh prepare` then `promote`, delete the ticket, then run
   `post_release_tester`.

### Alerting

- If the same SHA hits `deploy_failed` 3 or more times in a row, the poller sends **one** P1. The P1 names the
  commit subject, the failure count, when the streak started, the CURRENT pin and the reason line (for example the
  native `ERROR:` line). Further failures don't page again.
- When a P1'd streak recovers (the SHA is promoted or already served), the poller sends **one** OK note at P2.
- A verify failure after a promote still pages P1 straight away.
- `scripts/delivery_failure_alerts.page_p1` now records transport truth: `delivered` means Telegram returned a
  message id, and `delivery_status` is DELIVERED, HELD, ROUTED or FAILED. Before this change, `delivered: true`
  meant "accepted". On 10-26/27 the comms editor delivered the first `deploy_on_main failed` page (19:50Z) and held
  the next 386 as 20-hour duplicates, because its fingerprint strips hex SHAs. Every one of those was still
  receipted `delivered: true`, so the operator saw one page and then nothing. Streak pages now carry the commit
  subject and the reason, so each failing SHA gets its own fingerprint.

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
- Poller binding: `scripts/lib/deploy_delegation_binding.py` (consulted by `scripts/release_grant_preflight.py`); streak/dedupe state `deploy_on_main/alert_state.json`
- Telegram go-signal: `scripts/lib/pr_merge_telegram.py` · `scripts/request_pr_merge_approve.py` · `scripts/notify_pr_merge_ready.py`
- Notify timer (operator install §17): `config/systemd/user/tradeai-pr-merge-notify.{timer,service}`
- Config: `.mergify.yml` at repo root
