# M2 production memory shadow — R10.10 closeout

**Date:** 2026-08-25  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Status:** SOURCE + TESTED isolated (`:55432`). **Production `:5432` schema NOT applied** (no production-sql-write grant).  
**Labels:** SHADOW_ONLY · CANONICAL_READERS_UNCHANGED · NO_TRADING_AUTHORITY · NO_CUTOVER

CIO L5 remains NATURALLY_PROVEN on runtime `1afb1479`. This program does not re-prove it.

## What was built

Isolated schema `tradeai_memory_shadow` (Postgres 16.15 + pgvector 0.8.6) on `tradeai-m2-shadow` `127.0.0.1:55432`.

One-way projector: canonical JSONL → MemoryFact@v2. JSONL SHA unchanged. CIO/Advisory/Telegram still read JSONL only.

Tx-time: `statement_timestamp()+version_seq`. CURRENT = `upper_inf(tx_period)`. FORCE RLS. Writer `NOBYPASSRLS`. Composite FK `(tenant_id, identity_guid)`.

## Isolated proof (live canonical counts, not hardcoded)

| metric | value |
|---|---|
| eligible | 428 |
| projected | 428 |
| replay new rows | 0 |
| parity SCHD/SCHG/CSCO/ANET/NOC/PRSO | 100% |
| dark-read CIO_influence | 0 |
| canonical_untouched | true |
| production_sql_applied | false |

PRSO remains unresolved (null security_guid); still projected on ticker_guid. No fabricated GUID.

## Production apply plan (NOT executed)

Requires explicit `production-sql-write` grant. Then:

1. Create roles `tradeai_memory_shadow_owner` (NOLOGIN), `_writer`, `_reader` (NOBYPASSRLS).
2. Apply `sql/r10_tradeai_memory_shadow_isolated.sql` **without** `DROP SCHEMA` against a dedicated database — never financial-truth schemas.
3. Run `scripts/memory_shadow_project.py --root CURRENT` as writer.
4. Replay must be no-op.
5. Dark-read telemetry only.
6. Do not point CIO at Postgres.

Rollback: stop projector; `DROP SCHEMA tradeai_memory_shadow`. Canonical JSONL untouched.
