# Agentic Runtime MVL Migration

This migration is additive and must be applied only to an isolated LAB database until the architecture baseline and permission review are accepted.

## Files

- `0001_mvl.up.sql` — creates the separate `agentic_runtime` schema and eight MVL tables.
- `0001_mvl.down.sql` — one-step rollback that removes the isolated schema.

## Required preflight

1. Confirm the target is not the production `trade_ai` database.
2. Confirm the database role has no broker, secret or production-service authority.
3. Record target host, port, database, role and schema hash.
4. Confirm there are no existing `agentic_runtime` objects that contain evidence requiring preservation.
5. Use a transaction and stop on the first error.

## Lab proof sequence

```bash
psql "$TRADE_AI_LAB_DSN" -v ON_ERROR_STOP=1 -f migrations/agentic_runtime/0001_mvl.up.sql
pytest -q tests/test_agent_runtime_migration_contract.py tests/test_agent_runtime_mvl.py
psql "$TRADE_AI_LAB_DSN" -v ON_ERROR_STOP=1 -f migrations/agentic_runtime/0001_mvl.down.sql
psql "$TRADE_AI_LAB_DSN" -v ON_ERROR_STOP=1 -f migrations/agentic_runtime/0001_mvl.up.sql
```

Preserve sanitized schema inventory and test output. Do not place the DSN or any credential in an artifact, prompt, journal or repository file.

## Non-authorization

The presence of these tables does not enable an agent, OpenClaw, Hermes, a model route, a channel, a scheduler or any financial action.
