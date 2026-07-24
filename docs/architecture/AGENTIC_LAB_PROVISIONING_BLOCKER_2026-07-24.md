# Agentic LAB Provisioning Checkpoint — 2026-07-24

**Scope:** PR #163 only  
**Disposition:** `LAB_CANDIDATE_IDENTIFIED — CLASSIFICATION PENDING — NO DATABASE WRITE`

## Evidence reviewed

The sanitized host inventory in PR #169 closes the broad host-inventory prerequisite. The operator subsequently supplied a read-only process and listener probe that verifies:

- production PostgreSQL is cluster `17/main`, owned by `postgres`, bound to loopback port 5432, with data directory `/var/lib/postgresql/17/main`;
- a second PostgreSQL 17 server is bound to loopback port 5433;
- the port-5433 process is owned by `johnclaw` and uses `/home/johnclaw/tradeai-lab/pg17`;
- the two servers have separate postmaster processes, owners, ports and data directories;
- `/usr/bin/createdb` and Docker are available;
- the interactive shell defines a `psql` alias that points to production `trade_ai` on port 5432.

The alias is prohibited for LAB work. Every future command must use `/usr/bin/psql` with explicit host `127.0.0.1` and port `5433`.

## What is now proven

Port 5433 is no longer an unidentified listener. It is a credible user-owned LAB-cluster candidate, physically separated at the PostgreSQL-cluster level from production `17/main`.

## What remains unproven before writes

1. Database names, owners, sizes and connection status on port 5433.
2. Whether any selected database contains production-derived, sensitive or operator data.
3. Non-system schema names and relation counts, without reading row contents.
4. Whether any existing `agentic_runtime` objects contain evidence requiring preservation.
5. The exact LAB administrator and role-creation authority.
6. An explicitly disposable database name and cleanup scope.
7. A non-repository credential-delivery path for the three LAB identities.
8. A synthetic canonical-view surface and synthetic protected schema for safe denial tests.

## Planned identities after classification PASS

- `agentic_lab_migrator` — restricted to the disposable LAB and never used by runtime code;
- `trade_ai_shadow_ro` — LOGIN and SELECT only on approved synthetic LAB canonical views;
- `agentic_runtime_lab_rw` — LOGIN and required DML only inside `agentic_runtime`, with no CREATE or writes elsewhere.

## Repository guardrail added

`scripts/agent_runtime/lab_preflight.py` now validates the declared LAB target without connecting to PostgreSQL. It fails closed on port 5432, database `trade_ai`, production data directories, paths outside `/home/johnclaw/tradeai-lab`, incorrect role names or missing disposable/no-production-data acknowledgement. Focused tests cover these refusals.

## Next decision

Run the read-only classification packet against port 5433. Record `PASS_LAB_CANDIDATE` only if a database is explicitly disposable and contains no production or sensitive data. Otherwise record `BLOCKED_LAB_CLASSIFICATION` and stop before any database or role creation.

## Safety confirmation

No database connection, database or role creation, grant, migration, package installation, service restart, OpenClaw/Hermes change, agent activation, provider call, broker/order/approval/2FA path, production configuration, secret value or production data was accessed or changed by this repository update.

PR #163 remains draft. The migration proof and persistence slice remain gated on completed LAB classification and role provisioning.
