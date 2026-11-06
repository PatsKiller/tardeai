# Watch review governed model route

Status: IMPLEMENTED; fixture acceptance only, runtime activation pending

Design-Task: DSN-20261024-conflicts-P0-T1

The scheduled producer is `run_watch_review_workers._execute_jobs`, which passes
`watch_review_policy_ledger` role specs to `run_watch_review_canary.run_agent_call`
and then `llm_consumption.gate_and_generate`. The obsolete model literals caused
the canonical client to reject the request before transport. The worker now uses
the existing model registry accessor: Maria FAST, CIO PRO_THINK, both currently
bound to `deepseek-flash`. Process IDs, authorization validation and consumption
caps remain in the governed path. CIO thinking metadata follows the logical
policy binding. Returned model mismatch or fallback refuses completion.

Before any child authorization or spend, the helper verifies the exact role,
process, model and logical-policy tuple. It requires an existing named parent
policy. It no longer creates a policy or overwrites an operator identity during
a provider call. A dry-run returns before the cap-DB initializer.

## Runtime boundary

Existing durable authorizations may allow only legacy models and PRO. They fail
closed with MODEL_MISMATCH against the corrected spec. Their approval scope is
not silently migrated by a source update. The operator must review and update
the named parent policy to permit the modern model and PRO_THINK, preserving
expiry, identity, caps and enabled state; no automatic reinstall or scope update
is included here. `build_intended_policy` describes the new route with workers
and the event watcher disabled, and is not persisted by this work.

Tests use fixture policies and a fake consumption gate. They cover valid role
admission, invalid/legacy model and process refusal before effects, missing or
insufficient policy, provider mismatch/fallback/missing request reference, and
write-free worker dry-run. No provider request, credential read, live policy
write, activation or pending-job drain is performed. The coordinator's measured
633 pending jobs and error count remain investigation inputs, not proof of a
new successful production review.

## The joint dispatch-authority invariant (2026-11-04)

One function — `watch_review_policy_ledger.dispatch_authority` — covers BOTH
boundaries that drifted apart twice in production: the runtime's registry
resolution and the persisted parent approval. Before any dispatch, from either
`create_execution_authorization` or `validate_execution_authorization`:

1. the record exists and **has not expired** — the clock outranks the status
   string (`validate_policy` checks `expires_at` before `authorization_status`;
   a live record read ACTIVE while `expires_at` was already a day in the past,
   so expiry is reported first, `POLICY_EXPIRED`). Status and revocation are
   checked after it; a record that is not ACTIVE is still refused, never
   merely downgraded. **Expiry is mandatory and unparseable means refused**:
   a missing, empty, null or non-timestamp `expires_at` is
   `POLICY_EXPIRES_AT_INVALID`, because a record that cannot demonstrate that
   it is current cannot authorise — inability to prove never resolves to
   permission;
2. the role's logical policy resolves through the canonical registry to exactly
   one model id, and a caller-supplied model that is not that id is refused
   (`MODEL_NOT_REGISTRY_CURRENT`) rather than substituted;
3. the record names that exact model and that logical policy in its member
   lists (`MODEL_MISMATCH`, `POLICY_MISMATCH`) — approval is explicit, never
   inferred from a range, prefix or alias;
4. the record carries an `authority_approval` digest over its authority-bearing
   fields (`authority_digest`), written only by `persist_policy`. Renaming an
   allowed model in the JSON in place changes the digest and grants nothing
   (`AUTHORITY_CHANGED_SINCE_APPROVAL`); the operator installer is the approval
   event. A child authorization records the digest it was issued under, so a
   parent edited after issue invalidates it at consume time.

Every refusal is a named, typed reason and no path returns a pass for an
unapproved model: the lanes fail closed by construction. `scripts/install_watch_review_policy.py --operator-id <id>`
is the only supported way to renew or widen the record; it reports the
approval digest it wrote. Renewing an expired parent is an operator decision
(D24), never an automatic migration.
