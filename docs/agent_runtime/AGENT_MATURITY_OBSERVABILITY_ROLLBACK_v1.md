# Agent Maturity Observability Rollback v1

Status:      ACTIVE
as_of:       2026-07-30T11:19:37-04:00
Measured at: efcc51365 / not measured

This tranche is additive and read-only.

Rollback scope:

- remove `/api/v3/agent-maturity` route handling from the Agent Runtime read dispatcher and portfolio server prefix gate;
- remove `scripts/agent_runtime/maturity_observability.py`;
- remove the Command Center v3 maturity scoreboard adapter and page section;
- remove the sanitized OpenClaw inventory schema/example and helper;
- remove the dry-run analyzer and added tests/docs.

No database migration exists.

No production configuration change exists.

No service or timer change exists.

No historical backfill exists.

No agent activation, promotion, authority grant, broker action, 2FA action, or deployment is part of this rollback.

Operator rollback if deployed later:

1. Restore the prior immutable release.
2. Restart only the affected portfolio-server service.
3. Verify `/v3` still serves.
4. Verify `/api/v3/agent-runtime` continues its prior GET-only behavior.
5. Confirm no production Agent Runtime, broker, order, approval, 2FA, or feature-flag state changed.
