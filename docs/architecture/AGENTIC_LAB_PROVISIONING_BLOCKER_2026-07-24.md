# Agentic LAB Provisioning Checkpoint — 2026-07-24

Status:      HISTORICAL
as_of:       2026-07-24T18:22:19-04:00
Measured at: efcc51365 / not measured

**Scope:** PR #163 only  
**Disposition:** `PASS_LAB_CANDIDATE — NEW EMPTY TARGET AUTHORIZED — EXECUTION PENDING`

## Sanitized evidence reviewed

The host inventory in PR #169 and the operator-supplied read-only PostgreSQL probes establish:

- production PostgreSQL is cluster `17/main`, owned by `postgres`, on loopback port `5432`, data directory `/var/lib/postgresql/17/main`;
- the LAB PostgreSQL 17 cluster is a separate `johnclaw`-owned postmaster on loopback port `5433`, data directory `/home/johnclaw/tradeai-lab/pg17`;
- the LAB socket is `/home/johnclaw/tradeai-lab/sock`, with local peer authentication and TCP SCRAM-SHA-256;
- peer-authenticated metadata access succeeds as `johnclaw`;
- `johnclaw` has LAB-side `SUPERUSER`, `CREATEDB` and `CREATEROLE` authority;
- the shell `psql` alias points to production and remains prohibited.

Every approved command uses `/usr/bin/psql`. Administrative work uses only the verified LAB socket. Reader/writer proof uses explicit TCP target `127.0.0.1:5433`.

## Database classification

| Database | Owner | Approximate size | Non-system inventory | `agentic_runtime` | Disposition |
|---|---|---:|---|---|---|
| `postgres` | `johnclaw` | 7,706,291 bytes | `public`: 0 tables, 0 views, 0 sequences | absent | administrative database only |
| `trade_ai_test` | `trade_ai_lab` | 12,097,203 bytes | `public`: 25 tables, 0 views, 7 sequences | absent | non-empty and unclassified; reuse and deletion forbidden |

No application rows or data values were read. Because `trade_ai_test` is non-empty and its data provenance is unknown, it is excluded regardless of its name.

## Authorized disposable target

The authorized target is a **new empty database**:

`trade_ai_agentic_lab`

It must be created only on the isolated port-5433 cluster. It must never be cloned from, restored from, or linked to production or `trade_ai_test`.

The cleanup boundary is limited to:

- database `trade_ai_agentic_lab`;
- roles `agentic_lab_migrator`, `trade_ai_shadow_ro` and `agentic_runtime_lab_rw`;
- synthetic schemas and objects created inside that database;
- host-local proof credentials and sanitized evidence created by the operator script.

Cleanup must not remove or alter the PostgreSQL cluster, `postgres`, `trade_ai_test`, existing LAB roles, production roles, production databases or service configuration.

## Identity design

- `agentic_lab_migrator` — `NOLOGIN`; owns the disposable database and migration objects; used only through an explicit LAB-admin `SET ROLE` session.
- `trade_ai_shadow_ro` — `LOGIN`; may connect only for proof/runtime reading and receives `SELECT` only on the approved synthetic canonical view.
- `agentic_runtime_lab_rw` — `LOGIN`; receives `USAGE`, `SELECT`, `INSERT` in `agentic_runtime` plus column-limited run-control updates; no schema creation, DELETE, TRUNCATE or writes elsewhere.

SCRAM credentials for the two login roles are generated at execution time and written only to `/home/johnclaw/tradeai-lab/secrets/agentic-runtime` with directory mode `0700` and file mode `0600`. Passwords, DSNs and secret values are never printed or committed.

## Synthetic denial surface

The proof uses no production data. It creates:

- approved read-only view `approved_canonical.v_agentic_market_snapshot`, containing constants only;
- synthetic denial schemas `public`, `trade`, `broker`, `account`, `position`, `approval`, `configuration` and `lab_protected`;
- one harmless `denial_target` table in each non-public denial schema.

## Eight-stage execution packet

`scripts/agent_runtime/lab_evolve_1_to_8.sh` performs, only after the exact disposable acknowledgement:

1. create the new empty database;
2. create the three separated identities;
3. preserve host-local secrets and an explicit rollback file;
4. create the synthetic approved-view and denial surfaces;
5. prove reader and writer access through explicit TCP port 5433;
6. apply the migration and verify exactly eight tables, owners and grants;
7. prove append-only triggers, producer/reviewer/scorer separation and clean down migration;
8. replay the up migration and require an identical schema-manifest hash.

Static tests prohibit service management, package installation and target drift.

## Authorization boundary

`PASS_LAB_CANDIDATE` authorizes only execution of the committed LAB packet against the new empty target. It does not by itself prove the database migration. The persistence slice remains gated until sanitized output ends with:

`final_status|PASS_DB_PROOF`

PR #163 remains draft. No service, schedule, OpenClaw, Hermes, agent, model route, channel, broker, order, approval, 2FA, production configuration or production database action is authorized.