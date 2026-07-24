# Agentic LAB Provisioning Checkpoint — 2026-07-24

**Scope:** PR #163 only  
**Disposition:** `BLOCKED_LAB_PROVISIONING — NO DATABASE WRITE`

## Evidence reviewed

The sanitized host inventory in PR #169 is sufficient to close the host-inventory prerequisite. It verifies:

- production PostgreSQL is bound to loopback on port 5432;
- the production database is `trade_ai`;
- a separate listener exists on port 5433 but its ownership and data classification were not established;
- the production repository worktree is dirty and must not be used for migration work;
- `hermes_readonly` and `hermes_staging_writer` have scoped grants but cannot log in;
- pgvector is absent, but PR #163 migration `0001_mvl.up.sql` does not require the extension;
- no disposable LAB database identity, LAB migration executor, LAB credentials, or safe denial-test target was verified.

## Missing prerequisites

Provisioning stopped before any database connection or write because all of the following remain unverified:

1. **Disposable target identity** — confirm whether port 5433 is disposable and contains no production or operator data, or create a separate empty user-owned PostgreSQL cluster/database on a distinct loopback-only port.
2. **Role-creation authority** — an authorized LAB administrator capable of creating database-local identities without altering production roles.
3. **Migration executor** — a LAB-only login restricted to the disposable database and not used by runtime code.
4. **Reader identity** — `trade_ai_shadow_ro` with LOGIN and SELECT only on approved LAB canonical views.
5. **Runtime writer identity** — `agentic_runtime_lab_rw` with LOGIN, USAGE on `agentic_runtime`, and DML only on approved `agentic_runtime` tables; no CREATE or writes elsewhere.
6. **Safe denial target** — a dummy LAB-only guard schema/table used to prove denied writes, rather than any production table.
7. **Credential delivery path** — non-repository secret provisioning for LAB credentials; no passwords, DSNs, tokens, or secret values in GitHub evidence.
8. **Rollback location** — explicit disposable target cleanup path and confirmation that `0001_mvl.down.sql` can only affect the LAB target.

## Required read-only terminal probe

Before any write, collect sanitized output for:

```bash
command -v psql createdb initdb pg_ctl docker podman
pg_lsclusters 2>/dev/null || true
ss -ltnp | grep -E ':(5432|5433|55432)\b' || true
ps -ef | grep '[p]ostgres'
```

Then identify the owner, database list, and purpose of the port-5433 instance without exposing credentials or connecting with production-write authority.

## Safety confirmation

No database connection, database or role creation, grant, migration, package installation, service restart, OpenClaw/Hermes change, agent activation, provider call, broker/order/approval/2FA path, production configuration, secret value, or production data was accessed or changed.

PR #163 must remain draft. The database-isolation proof and persistence slice are not authorized until the missing prerequisites above are evidenced.
