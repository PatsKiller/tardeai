# Guard grants at the operator's keyboard

```
Status:  ACTIVE (procedure); moved here from AGENTS.md 25.0.1 lines 2205–2343 by AGENTS.md 26.0.0
as_of:   2026-10-27
Owner:   operator (grants); platform (bin/guard)
```

**Read this first: what changed since this procedure was written.**

- **Deployment does not use a grant any more.** Under AGENTS.md §25.10 the host deploy poller promotes merged `main`
  under the standing deploy delegation; no agent requests `release-write` for a deploy. `release-write` remains only
  for the operator's emergency manual promote (`scripts/emergency_manual_promote.sh`, AGENTS.md §25.10).
- **Grants come only from the keyboard (`bin/guard`) or Ops → Controls** (passkey and typed phrase). Telegram
  `/approve` grants are retired (AGENTS.md §17, 23.0.0 folded into 26.0.0). An approval relayed by another agent never
  counts (AGENTS.md §28.4).
- **Pushes under an operator-approved plan** follow AGENTS.md §0 rule 4 and `AI_WORK_POLICY.md` §3; where a guard hook
  is installed it may still ask for a `git-push` grant, and this procedure is how the operator issues one.

The procedure below is unchanged from 25.0.1 and stays fail-closed: absolute guard path, minimum scopes, the operator
types the approval, revoke and show at the end.

## Operator approval for remote push and live deployment

Agents cannot grant themselves authority. The human operator must explicitly approve every
guarded scope through the native interactive guard prompt. A general instruction to continue,
finish, or deploy is not a guard approval.

Before requesting authority, the agent must:

1. Resolve and print the physical repository or worktree root.
2. Locate `<repo_root>/bin/guard`, verify that it is the executable guard for that resolved root,
   and use its absolute path.
3. Prove the exact branch, HEAD SHA, intended remote, PR state, CI status, deployment target, and
   rollback release.
4. Complete all required local validation.
5. State exactly why each requested scope is necessary.

Never invoke `bin/guard` as a relative path unless the command itself first changes to the proven
repository root. Prefer this form:

```bash
GUARD_PATH="<absolute_repo_or_worktree_root>/bin/guard"
test -x "$GUARD_PATH"
"$GUARD_PATH" show
```

Request only the minimum required scopes:

- `git-push` only when a validated local commit must be pushed.
- `release-write` only after the exact merged commit is ready for governed deployment.
- Neither scope may be requested during discovery, implementation, ordinary testing, or
  read-only validation.
- Never request force-push, history rewriting, production data mutation, credential mutation,
  scheduler mutation, broker mutation, or trading authority unless a separate task explicitly
  authorizes that exact action.

The agent must present the native interactive approval request to the operator. The operator types
`APPROVE` at that prompt. The agent must never type, pipe, simulate, automate, or infer `APPROVE`.

Use a short expiration and the fewest practical uses. The standard examples are 30 minutes and no
more than three uses:

```bash
"$GUARD_PATH" grant git-push --for 30m --uses 3 --reason "<specific PR purpose>"
"$GUARD_PATH" grant release-write --for 30m --uses 3 --reason "<specific exact-SHA deployment purpose>"
```

Immediately after the operator approves, run:

```bash
"$GUARD_PATH" show
```

Verify the requested scopes, remaining duration, remaining uses, and reasons before performing
any mutation. An absent, expired, mismatched, or overbroad grant is a hard stop.

Push and deployment are separate stages. `git-push` does not authorize merge or deployment, and
`release-write` does not authorize Git operations. Deployment may begin only after required CI is
green for the exact PR head and the exact merge SHA is known; deploy only that exact merge SHA
through the canonical release mechanism.

Live deployment must capture the current release as the rollback target, prove that the candidate
embeds the exact merge SHA, verify persistent-state mappings before promotion, promote atomically,
perform semantic live acceptance, and automatically roll back if any required acceptance check
fails. Files copied or services restarted are never sufficient evidence of deployment success.

Use this safe path-resolution example from an arbitrary starting directory. The candidate path is
resolved by the agent at runtime; it is not a historical worktree path:

```bash
CANDIDATE_PATH="/known/candidate/path"
REPO_ROOT="$(git -C "$CANDIDATE_PATH" rev-parse --show-toplevel)"
GUARD_PATH="$REPO_ROOT/bin/guard"
test -x "$GUARD_PATH"
"$GUARD_PATH" show
```

In a `finally` or cleanup path, whether the operation succeeds, fails, or rolls back, revoke
unused grants and show the final state:

```bash
"$GUARD_PATH" revoke git-push
"$GUARD_PATH" revoke release-write
"$GUARD_PATH" show
```

The evidence package must retain redacted guard grant, use, revocation, push, PR, merge,
deployment, acceptance, and rollback receipts, including timestamps, scopes, reasons, exact SHAs,
release IDs, and exit codes. Never include secrets.

A `release-write` grant names the SHA or PR it releases; a generic grant is refused (`ReleaseGrantBinding@v1`):
§24.8 (4.6.0, ACTIVE).

If `<repo_root>/bin/guard` is absent or non-executable, stop and report the exact resolved path
and failure. Do not guess another guard path or bypass governance.

---

# 8A · Testing standards

Tests never touch production state: §24.6 (4.6.0, ACTIVE).

Scattered rules, consolidated. Each states the failure that produced it.

- **Every test file is registered in the CI allowlist.** `test_ci_test_coverage_gate.py` enforces
  it. An unregistered test is invisible — the "wired to nothing" defect the guard exists to
  prevent. *Cause: it caught the §0 drift guard in #734, which would otherwise have been a parity
  test nobody ran, guarding against drift in four files while drifting silently itself.*
- **Assert on behaviour, never on source strings.** A test that greps its subject's source passes
  when the source is wrong in a different way. *Cause: a PR shipped broken past a test that only
  read source text.*
- **A test whose expected value comes from the artifact under test validates nothing.** Regenerate
  or delete; never update the literals — see §5.
- **Pin floors, not adjudications.** A floor forbids every alternative, so pinning it is right. An
  adjudication permits them, so a pin fires only when someone corrects the record. *Cause:
  `assert status == "DONE"` went red on an honest downgrade — a test that fails when someone tells
  the truth.*
- **Mutation-test every guard.** Break the thing, confirm red; restore, confirm green; check the
  exit code for the specific expected value. **A guard that has never been shown to fail is a
  guard nobody has tested.** *Cause: a dark-contract gate returned exit 0 on a file that could not
  compile, having read its own required declaration out of a `SyntaxError`.*
- **Positive-control every detector before publishing a zero.** Inject a known instance and confirm
  the detector finds it. §7 has the class; this is the obligation it implies. *Cause: an
  origination scan returned zero because generated prose is maximally variable and could never
  land in an invariance bucket.*
- **A producer that can fail needs a preserve-on-failure test.** Assert that a failed run leaves
  the prior value intact, and mutation-test it by neutering the guard — a fail-open write and a
  fail-closed write are indistinguishable on a successful run, so a test exercising only the happy
  path proves nothing. See §7 "Caches and derived stores".
- **A skipped test is a failure wearing better manners.** Fix the name guess or delete it; never
  leave a green skip. *Cause: a "no fake alpha" test was wrapped in `if alpha is not None`, so the
  gate was green precisely when there was no alpha.*

---

# 9 · Standard operating procedures

These are the recurring operations. Every agent performs them the same way, or the system
accumulates the divergence this document exists to remove.
