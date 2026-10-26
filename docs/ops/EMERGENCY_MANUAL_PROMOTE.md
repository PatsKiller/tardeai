Status: ACTIVE
as_of: 2026-10-26
Measured at: design for AGENTS.md 24.0.0 PROPOSED
Canonical repo path: docs/ops/EMERGENCY_MANUAL_PROMOTE.md
Authority: operator-approved plan mergify_replace_train (2026-10-26)
Supersedes: none (new path; replaces train emergency merge)
See also: docs/ops/MERGIFY_DEPLOY_FOUNDATION.md · AGENTS.md §25.10 · AI_WORK_POLICY.md §28

# Emergency manual promote

Operator-only. Agents never run this path.

## When to use

- GitHub Actions / required checks are down and Mergify cannot merge, **or**
- `main` already has the intended SHA (merged by Mergify or by the operator) and the poller is blocked / STOP must stay clear while you force one promote, **or**
- You need a one-shot promote of a known SHA under an explicit `release-write` grant.

## Preconditions

1. You are at a host TTY on ms01 (or equivalent), as the Trade AI operator user.
2. Release STOP latch is **absent** (`scripts/release_control_cli.py status` / no `STOP.json`).
3. Guard grant active:

```bash
"$GUARD_PATH" grant release-write --for 30m --uses 1 \
  --reason "emergency promote #<PR> <full_sha>"
```

The reason **must** contain the exact candidate SHA (at least 9 hex chars) so `ReleaseGrantBinding@v1` matches.

4. Export the same SHA:

```bash
export TRADEAI_EMERGENCY_RELEASE_SHA=<full_sha>
```

5. Run from CURRENT or the deploy worktree that will prepare that SHA:

```bash
bash scripts/emergency_manual_promote.sh
```

## What the helper does

1. Resolves `TRADEAI_EMERGENCY_RELEASE_SHA` and refuses if unset or not hex.
2. Checks grant binding against that SHA (`release_grant_binding`).
3. Refuses if STOP latch is set/unreadable.
4. Takes `GlobalReleaseLock` (non-blocking; busy = refuse).
5. Runs `cio_phase2_exact_main_deploy.sh` prepare + promote for that SHA.
6. Runs `scripts/post_release_tester.py` (or embedded verify) against CURRENT.
7. Writes `DeployOnMainReceipt@v1` with `path=manual_emergency`.
8. On verify failure: leaves STOP for operator review (does not auto-clear).

## Must not

- Set `TRADEAI_EMERGENCY_RELEASE_SHA` from cron, n8n, or an agent session.
- Promote without a grant that names the SHA.
- Use this as the normal path when Mergify + poller are healthy.

## Rollback

Same as any promote: re-point CURRENT to the previous good release directory and restart bound units (`docs/ops` promote/rollback runbooks). Quote the previous pin from the receipt’s `rollback_target` field.
