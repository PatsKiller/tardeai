# Agentic LAB Provisioning Checkpoint — 2026-07-24

**Scope:** PR #163 only  
**Disposition:** `LAB_CLUSTER_AUTHORITY_VERIFIED — DATABASE CLASSIFICATION PENDING — NO DATABASE WRITE`

## Evidence reviewed

The sanitized host inventory in PR #169 closes the broad host-inventory prerequisite. The operator subsequently supplied read-only listener, process, authentication-configuration and peer-socket probes that verify:

- production PostgreSQL is cluster `17/main`, owned by `postgres`, bound to loopback port 5432, with data directory `/var/lib/postgresql/17/main`;
- a second PostgreSQL 17 server is bound to loopback port 5433;
- the port-5433 process is owned by `johnclaw` and uses `/home/johnclaw/tradeai-lab/pg17`;
- the two servers have separate postmaster processes, owners, ports and data directories;
- the LAB cluster listens only on `127.0.0.1`, publishes a Unix socket at `/home/johnclaw/tradeai-lab/sock`, uses peer authentication for local socket sessions and SCRAM-SHA-256 for TCP sessions;
- peer-authenticated metadata access succeeded as `johnclaw` against the LAB cluster's `postgres` database;
- `/usr/bin/createdb` and Docker are available;
- the interactive shell defines a `psql` alias that points to production `trade_ai` on port 5432.

The alias remains prohibited. Administrative classification may use only `/usr/bin/psql` through the verified LAB socket. Future runtime-role proof must use `/usr/bin/psql` with explicit TCP target `127.0.0.1:5433` after SCRAM credentials are provisioned through a non-repository secret path.

## Database metadata now proven

| Database | Owner | Approximate size | Connection allowed | Disposition |
|---|---|---:|---|---|
| `postgres` | `johnclaw` | 7,706,291 bytes | yes | administrative database; never the MVL target |
| `trade_ai_test` | `trade_ai_lab` | 12,097,203 bytes | yes | existing database; contents and relation inventory still unclassified, therefore not authorized for reuse |

No row contents were queried or preserved.

## LAB administrator and authority

The peer-authenticated `johnclaw` role is verified with:

- `LOGIN = true`;
- `SUPERUSER = true`;
- `CREATEDB = true`;
- `CREATEROLE = true`.

This proves role- and database-creation authority exists inside the isolated LAB cluster. It does not authorize any action on production port 5432.

Existing LAB roles:

- `trade_ai_lab` — LOGIN, not superuser, no CREATEDB, no CREATEROLE;
- `trade_ai_lab_ro` — LOGIN, not superuser, no CREATEDB, no CREATEROLE.

They are not substitutes for the three PR #163 identities because their current grants, intended use and credentials have not been proven against the MVL contract.

## Selected disposable target and cleanup boundary

The selected target name is:

`trade_ai_agentic_lab`

It does not yet exist and must be created empty on the isolated port-5433 cluster. Creating a new empty database avoids reusing `trade_ai_test`, whose contents remain unclassified.

The authorized cleanup scope, after evidence export, is limited to:

- database `trade_ai_agentic_lab`;
- roles `agentic_lab_migrator`, `trade_ai_shadow_ro` and `agentic_runtime_lab_rw`;
- objects created inside that database for synthetic canonical-view and protected-schema denial tests.

Cleanup must not remove the PostgreSQL cluster, its data directory, `postgres`, `trade_ai_test`, `trade_ai_lab`, `trade_ai_lab_ro`, production roles, production databases or any service configuration.

## What remains unproven before writes

1. Non-system schema and relation counts for `postgres` and `trade_ai_test`, without reading row contents.
2. Whether `trade_ai_test` contains production-derived, operator or sensitive structures. It remains out of scope regardless of the result.
3. Whether any existing `agentic_runtime` schema exists on either current LAB database and requires preservation.
4. A confirmed non-repository secret-delivery path for SCRAM credentials for the three new identities.
5. The exact synthetic canonical views and synthetic protected schema used for harmless denial tests.

## Repository guardrails

- `scripts/agent_runtime/lab_preflight.py` rejects production port 5432, database `trade_ai`, production data directories, paths outside `/home/johnclaw/tradeai-lab`, incorrect role names and missing disposable/no-production-data acknowledgement.
- `scripts/agent_runtime/lab_classify_readonly.sh` performs only metadata discovery through the verified LAB peer socket, refuses an unexpected data directory or port, does not reuse an existing database and proposes only the new empty target `trade_ai_agentic_lab`.
- `tests/test_agent_runtime_lab_classifier.py` statically forbids database/role/schema mutations and application-row reads in the classifier.

## Next decision

Run the committed read-only classifier and preserve its sanitized output. Record `PASS_LAB_CANDIDATE` only when schema/relation counts and `agentic_runtime` presence are known. The PASS authorizes creation of a new empty `trade_ai_agentic_lab`; it never authorizes reuse or deletion of `trade_ai_test`.

## Safety confirmation

No database or role creation, grant, migration, package installation, service restart, OpenClaw/Hermes change, agent activation, provider call, broker/order/approval/2FA path, production configuration, secret value, production data row or application row was accessed or changed by this repository update.

PR #163 remains draft. The migration proof and persistence slice remain gated on completed LAB classification and role provisioning.
