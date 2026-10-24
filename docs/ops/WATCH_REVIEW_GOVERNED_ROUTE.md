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
