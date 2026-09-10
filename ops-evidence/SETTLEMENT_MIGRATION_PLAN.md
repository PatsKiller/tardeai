# SETTLEMENT_MIGRATION_PLAN — CommunicationEvent@v2 settlement identity

- **Date (America/New_York):** 2026-09-10 00:15
- **Campaign:** Grok-closure (`fix/grok-closure-engineering`)
- **Migration under review:** `migrations/2026_09_07_communication_event_v2_settlement.sql`
- **Satisfies:** SFR-B-003, closes validated defect 6 (legacy delivery rows lack provider settlement identity)
- **Worktree HEAD:** `c50cfe7836aa3274da937310cba6d45883266bc2`
- **Served CURRENT (origin/main):** `87e7325d2fbe29d9e663a0f5efd9ae52e848daa9`
- **Status:** ⛔ NOT YET APPLIED to live DB (settlement columns absent — verified 2026-09-10 00:12)

---

## 1. File identity

| Artifact | Path | SHA-256 |
|---|---|---|
| Migration (up, **corrected**) | `migrations/2026_09_07_communication_event_v2_settlement.sql` | `feb7f35784ee9808036829a7a5dc73544d7276177cbdb3e05d4102200284d381` |
| Migration (up, as-shipped in main) | same path @ `origin/main` | `7bce7579a099fdd3c3ccca032010922b78b76eb9` (git blob) |
| Rollback (down) | `migrations/2026_09_07_communication_event_v2_settlement.down.sql` | `a14476fdbe6f0f248d453863d3aa17e80bd2a693caae4386ed4403e9601cef63` |

The migration was introduced by `830e006c4` "integrate(m2-canary): unify lane
interfaces". **Preflight correction 2026-09-10:** the as-shipped file referenced
`occurred_at` in the settlement index, which is not a column on
`communication_events`; since the migration had never been applied to any DB
(verified: settlement columns absent from live schema), the index column was
corrected to `created_at DESC` (matching the ledger's existing index convention)
with an in-file dated correction note. The corrected file is what the db-write
grant is bound to.

---

## 2. DDL summary (columns / types / constraints / indexes)

Adds **8 net-new columns** to `communication_events` (all `IF NOT EXISTS`, all nullable — additive, no `NOT NULL` backfill risk):

| Column | Type | Purpose |
|---|---|---|
| `provider_message_id` | TEXT | Telegram message id(s), stamped only after ack |
| `provider_settled_at` | TIMESTAMPTZ | settlement timestamp |
| `provider_settlement_state` | TEXT | `UNSETTLED|SETTLED|FAILED|UNKNOWN_LEGACY` |
| `delivery_owner` | TEXT | `gateway|legacy` |
| `gateway_mode_at_dispatch` | TEXT | `OFF|SHADOW|CANARY|ACTIVE` |
| `curation_kind` | TEXT | deterministic / llm_curated |
| `curation_provenance` | JSONB | curation provenance envelope |
| `subject_guid` | TEXT | read-only from identity spine |

`thread_id` and `correlation_id` in the migration are **no-ops** — they already
exist on the ledger table (introduced by `2026_09_05_communication_event_ledger.sql`),
so `ADD COLUMN IF NOT EXISTS` skips them.

**Data statement (forward-only):**

```sql
UPDATE communication_events
   SET provider_settlement_state = 'UNKNOWN_LEGACY',
       delivery_owner            = 'legacy'
 WHERE provider_settlement_state IS NULL;
```

Every pre-existing row is legacy by definition (gateway has never owned delivery
— `COMMS_GATEWAY_MODE` resolves OFF). This is a statement of fact, not invented
identity. It does **not** mark anything `SETTLED`; no historical backfill.

**Constraints:**

- `communication_events_settlement_state_ck` — CHECK `provider_settlement_state IN ('UNSETTLED','SETTLED','FAILED','UNKNOWN_LEGACY')` (NULL allowed), `NOT VALID` (non-locking).
- `communication_events_delivery_owner_ck` — CHECK `delivery_owner IN ('gateway','legacy')` (NULL allowed), `NOT VALID`.

**Indexes:**

- `communication_events_settlement_idx` — `(provider_settlement_state, created_at DESC)`. NOTE: as-shipped this referenced `occurred_at`, a non-existent column; **corrected to `created_at` in the worktree before first application** (see §1).
- `communication_events_provider_msg_uq` — UNIQUE partial index on `(provider_message_id) WHERE provider_message_id IS NOT NULL`.

---

## 3. Additive / transaction-safety

- **Additive:** only `ADD COLUMN IF NOT EXISTS`, `NOT VALID` CHECK constraints, and `CREATE [UNIQUE] INDEX IF NOT EXISTS`. No `DROP`, no `TRUNCATE`, no `NOT NULL` on existing rows.
- **Transaction-safe:** PostgreSQL DDL is transactional; wrapping in one `BEGIN…COMMIT` makes the whole migration atomic. No lock-exclusive statements (`NOT VALID` + `CREATE INDEX` avoid a full-table rewrite). No `VACUUM`/`CONCURRENTLY` (which cannot run in a transaction) are used.

## 4. Idempotency

- `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`, and `ADD CONSTRAINT ... NOT VALID` (which itself errors "constraint already exists" only if a same-named constraint exists; the `IF NOT EXISTS` variant is not used for constraints, so a re-run must be gated). The `UPDATE ... WHERE provider_settlement_state IS NULL` is naturally idempotent (second run matches zero rows).
- **Constraint idempotency caveat:** `ADD CONSTRAINT` has no `IF NOT EXISTS`. Applying twice without the rollback would error on the second run. This is acceptable for a one-shot apply (the guard grant is single-use, `--uses 1`), and the rollback drops them. The live apply will be wrapped in a transaction and verified once.

## 5. Compatibility with served app

- The served app (commit `87e7325d2`) **already contains** the writer code (`scripts/lib/comms/event.py` `CommunicationEvent` dataclass carries all settlement fields; `gateway_settlement.py` calls `apply_provider_settlement`). Columns being nullable means the currently-running writer (which does NOT yet write these columns to `communication_events` — see §7) is unaffected by the schema change.
- No served-app restart is required for the schema change itself (columns are additive + nullable). The DDL will momentarily take `ACCESS EXCLUSIVE` on `communication_events`; see §6 for lock/availability analysis.

## 6. Restart / lock / availability risk

- `communication_events` is small (706 rows). `ADD COLUMN` with a constant default would be metadata-only in PG11+; here defaults are NULL, so column adds are near-instant. Index builds on 706 rows are milliseconds. `NOT VALID` constraints do not scan existing rows.
- ⚠️ **`occurred_at` index bug (RESOLVED before apply):** the as-shipped migration referenced `occurred_at`, which is not a column on `communication_events`. Because the migration had never been applied to any database, the index column was corrected to `created_at DESC` (with an in-file dated note) before first application. No shipped/live history is rewritten — the correction is to an un-applied file.
- No unrelated tables are touched (only `communication_events`; the `UPDATE`/indexes/constraints all target `communication_events` alone).

## 7. Does the gateway settlement code already write every column? — NO

Verified by reading the writer paths:

- `scripts/lib/comms/client.py::_persist_db` — the `INSERT INTO communication_events (...)` column list **does not include** `provider_message_id`, `provider_settled_at`, `provider_settlement_state`, `delivery_owner`, `gateway_mode_at_dispatch`, `curation_kind`, `curation_provenance`, `subject_guid`. It ends at `gateway_mode_at_write`.
- `scripts/lib/comms/delivery.py::settle_delivery` → `_mirror_event_settlement` stamps settlement **only into the in-memory `client._MEM` dict**, never an `UPDATE communication_events`.
- `scripts/lib/gateway_settlement.py::deliver_agent_outbound` mutates the in-memory `event` object via `apply_provider_settlement`, but nothing persists that to `communication_events`.

**Conclusion:** settlement identity is currently in-memory / in `communication_deliveries` only; the durable `communication_events` row is **not** made authoritative. This is the Phase 3 gap (`Make durable event row authoritative. Test by re-reading DB record after simulated ack`), closed by a separate additive migration + writer change — NOT by this Phase 1 schema migration.

## 8. Acceptance-contract field gap (feeds Phase 3)

The durable-gateway acceptance contract also requires `source_sha` and epoch/trigger `provenance` on the durable row. The live table has neither (`source_sha`/`provenance` exist only on the Python `CommunicationEvent` dataclass, §2 envelope extras). Phase 3 will add a **new additive migration** (`communication_event_v2_provenance`) for `source_sha TEXT` + `provenance JSONB`, never editing this shipped file.

## 9. Before-image (captured, read-only)

`SETTLEMENT_SCHEMA_BEFORE.json` (generated 2026-09-10 00:12, read-only SELECTs only):

| Table | Rows | Columns |
|---|---|---|
| `communication_events` | 706 | 52 |
| `communication_deliveries` | 705 | 25 |
| `communication_outbox` | 704 | 10 |
| `communication_entity_links` | 36 | 3 |

`settlement_columns_present: []` — none of the 8 settlement columns exist yet.
`schema_version` distribution: `CommunicationEvent@v2` × 706.

## 10. Apply / verify / rollback

**Apply (single transactional application, `--uses 1`):**

```
psql "$DB" -v ON_ERROR_STOP=1 -1 -f migrations/2026_09_07_communication_event_v2_settlement.sql
```

**Verify (re-read DB):**

```sql
SELECT column_name, data_type FROM information_schema.columns
 WHERE table_name='communication_events'
   AND column_name IN ('provider_message_id','provider_settled_at',
       'provider_settlement_state','delivery_owner','gateway_mode_at_dispatch',
       'curation_kind','curation_provenance','subject_guid');
SELECT COUNT(*) FROM communication_events;                       -- expect 706
SELECT COUNT(*) FROM communication_events
 WHERE provider_settlement_state = 'UNKNOWN_LEGACY';             -- expect 706
SELECT COUNT(*) FROM communication_events
 WHERE provider_settlement_state = 'SETTLED';                    -- expect 0 (no backfill)
```

**Rollback:** `SETTLEMENT_MIGRATION_ROLLBACK.sql` (drop indexes + constraints, retain columns; optional full-column-drop clearly gated).

## 11. Grant request

One native `db-write` grant, bound to this migration + SHA, `--uses 1`, issued via
`bin/guard request db-write` (Telegram). See §12.

## 12. Do NOT

- Backfill historical rows as `SETTLED` (forbidden — §9 verification asserts 0).
- Silently edit the shipped migration file (the `occurred_at` fix is a documented, in-file-noted correction of an un-applied file, not a silent edit).
- Claim live settlements until a real provider acknowledgement is durably written to `communication_events` (Phase 3).
