# Agentic Runtime MVL Migration

This migration is additive and must be applied only to an isolated LAB database until the architecture baseline and permission review are accepted.

## Files

- `0001_mvl.up.sql` — creates the separate `agentic_runtime` schema and eight MVL tables.
- `0001_mvl.down.sql` — one-step rollback that removes the isolated schema.
- `0002_roles.up.sql` — creates three least-privilege roles scoped to the
  `agentic_runtime` schema only: `agentic_runtime_lab_rw` and
  `agentic_runtime_shadow_rw` (append evidence, mutate only the run-control row,
  never DELETE) and `agentic_runtime_reader` (read-only Command Center). None has
  any broker / order / account / position / approval / 2FA / production-config
  access, and none holds superuser/createdb/createrole/replication/bypassrls
  (matching the runtime identity check in `scripts/agent_runtime/persistence.py`).
- `0002_roles.down.sql` — revokes grants and drops the three roles.
- `apply.sh` — **prepare-only** applier. It refuses to run without an explicit
  `--apply` flag (prints the plan and exits 3), and even with `--apply` refuses a
  missing or production-looking DSN. Passwords are never stored in the repo; the
  operator sets them out-of-band after apply.

## Prepare-only apply

```bash
# Prints exactly what it would run; applies nothing.
migrations/agentic_runtime/apply.sh

# Operator-authorized apply against an isolated LAB/SHADOW DSN:
TRADE_AI_LAB_DSN=... migrations/agentic_runtime/apply.sh --apply up
TRADE_AI_LAB_DSN=... migrations/agentic_runtime/apply.sh --apply down
```

## Required preflight

1. Confirm the target is not the production `trade_ai` database.
2. Confirm the database role has no broker, secret or production-service authority.
3. Record target host, port, database, role and schema hash.
4. Confirm there are no existing `agentic_runtime` objects that contain evidence requiring preservation.
5. Use a transaction and stop on the first error.

## Packet D / SHADOW_DSN

Packet D requires **`SHADOW_DSN=agentic_runtime_shadow_rw@trade_ai_agentic_lab`** (Bitwarden SM secret `SHADOW_DSN`; never print the value). After A1 roles apply, run:

```bash
.venv/bin/python scripts/secrets/ensure_shadow_rw_dsn.py          # create role + SM if needed
.venv/bin/python scripts/secrets/ensure_shadow_rw_dsn.py --rotate # if role exists but secret missing
.venv/bin/python scripts/secrets/render_env.py --now
```

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
