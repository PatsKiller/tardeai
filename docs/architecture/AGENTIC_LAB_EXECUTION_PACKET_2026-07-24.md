# Agentic MVL Disposable LAB Execution Checklist — 2026-07-24

**Scope:** PR #163 only  
**Authority:** LAB/SHADOW evidence only  
**Production target:** `127.0.0.1:5432`, database `trade_ai`, data directory `/var/lib/postgresql/17/main` — FORBIDDEN  
**LAB candidate:** `127.0.0.1:5433`, process owner `johnclaw`, data directory `/home/johnclaw/tradeai-lab/pg17`

## Current disposition

`LAB_CANDIDATE_IDENTIFIED — DISPOSABILITY CLASSIFICATION PENDING`

The supplied process inventory proves that port 5433 is a separate user-owned PostgreSQL 17 cluster. It does not yet prove that a database on that cluster is empty, disposable, free of production or sensitive data, and safe to remove.

The operator shell defines a `psql` alias that points to production. That alias is prohibited for this work. Every approved LAB command must use the absolute executable path and explicitly identify loopback port 5433.

## Required classification evidence

Before any write, preserve sanitized metadata proving:

- the server reports port 5433 and a data directory beneath `/home/johnclaw/tradeai-lab`;
- database names, owners, sizes and connection status;
- non-system schema names and relation counts, without reading row contents;
- role names and non-secret attributes;
- whether an explicitly disposable database already exists or may be created;
- whether any production-derived, operator or sensitive data is present;
- whether existing `agentic_runtime` evidence requires preservation;
- the exact cleanup scope and authorized LAB administrator.

If authentication requires a credential not already available through an approved host-local LAB path, stop with `BLOCKED_LAB_AUTH`. Never preserve a password, token, DSN, URI or environment value.

## Static preflight

Use `scripts.agent_runtime.lab_preflight` before constructing database commands. The module performs no network access. It rejects:

- production port 5432;
- database `trade_ai` and administrative/template databases;
- targets not explicitly named as LAB;
- the production data directory;
- data directories outside `/home/johnclaw/tradeai-lab`;
- incorrect migration, reader or writer role names;
- missing `DISPOSABLE_LAB_NO_PRODUCTION_DATA` acknowledgement.

## Planned LAB-only identities

- `agentic_lab_migrator` — migration executor restricted to the disposable LAB and never used by runtime code;
- `trade_ai_shadow_ro` — LOGIN plus SELECT only on approved synthetic LAB canonical views;
- `agentic_runtime_lab_rw` — LOGIN plus required runtime DML only inside `agentic_runtime`, with no CREATE or writes elsewhere.

The denial target must be a synthetic LAB-only protected schema. Production tables are never used for denial tests.

## Migration proof after classification and provisioning

- apply `0001_mvl.up.sql` only to the disposable LAB;
- verify exactly eight tables, ownership and grants;
- verify UPDATE and DELETE rejection on append-only evidence tables;
- verify producer/reviewer and producer/scorer separation;
- verify reader SELECT success and write denial;
- verify writer DML only inside `agentic_runtime` and denied writes elsewhere;
- apply `0001_mvl.down.sql` and confirm complete isolated cleanup;
- replay `0001_mvl.up.sql` and compare schema/migration hashes;
- prove the migration executor is absent from runtime configuration and source.

## Evidence contract

Preserve timestamps, Git and migration hashes, logical target name, non-secret role attributes, object names, owners, grant matrix, PASS/DENY summaries, table counts, cleanup scope and replay result. Do not preserve credentials, DSNs, data rows, secret values, account identifiers, broker information, orders, approvals or 2FA material.

## Non-authorization

This checklist does not authorize production database access, production-data cloning, services, schedules, OpenClaw, Hermes, providers, channels, brokers, orders, trades, approvals, 2FA, secrets or production configuration. PR #163 remains draft.
