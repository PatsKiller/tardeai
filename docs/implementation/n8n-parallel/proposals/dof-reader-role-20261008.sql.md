# Proposal — `dof_reader`: a read-only role for the DOF queue and enrichment views (2026-10-08)

```
Status:      DRAFT — PROPOSAL ONLY. The operator approved the role on 2026-10-08; nothing is applied.
             The operator runs this SQL as the Postgres superuser and sets the password out-of-band.
as_of:       2026-10-08T12:00:00-04:00
Measured at: /home/johnclaw/nyc-dof-auction (dof_server.py, enrichment_queue.py, scripts/db_migrate.py,
             scripts/migrate_v2.0.py, scripts/migrate_v2.1.py) as read 2026-10-08; live table count from
             docs/implementation/n8n-parallel/09-live-audit-20261007.md (22 `dof_*` tables).
Policy:      AGENTS.md §2A (no production DSN or role in n8n), §7A rule 1, §17 (DB grant); proposal S2.
Password:    NEVER in this file, a workflow, a doc or a chat. Set with psql `\password` (not echoed, not in
             history), stored in Bitwarden SM, rendered by render_env.py if a host process needs it.
```

## What the schema actually is

There is no separate DOF database. The DOF tables live in the production `trade_ai` database, schema
`public`, under the production `trade_ai` role (DSN default in `dof_server.py:26` and
`scripts/db_migrate.py:185`). That is why the role must be scoped to named objects and never to
`ALL TABLES IN SCHEMA public` — the same schema holds every Trade AI table. There are **no views** today;
the "queue/enrichment views" are created here so the role reads status, never plates, VINs or lookups.

Tables referenced by the DOF code (19 names; the live DB holds 22): `dof_auction_runs`, `dof_pdf_history`,
`dof_vehicles`, `dof_vin_appearances`, `dof_vehicle_targets`, `dof_price_snapshots`, `dof_ticket_events`,
`dof_judgment_checks`, `dof_ticket_lookups`, `dof_dmv_lookups`, `dof_vehicle_prices`, `dof_vehicle_scores`,
`dof_manual_queue`, `dof_enrichment_queue`, `dof_vehicle_enrichment`, `dof_manual_overrides`,
`dof_vinaudit_results`, `dof_nicb_results`, `dof_auction_history`. Queue and enrichment objects, from the code:

| object | role in the pipeline | columns the views use (measured in code) |
|---|---|---|
| `dof_enrichment_queue` | the enrichment work queue (244 pending on 10-07) | `source`, `status`, `scheduled_for`, `attempts`, `completed_at`, `error_msg` (`enrichment_queue.py:71-87`, `dof_server.py:1127-1200`) |
| `dof_manual_queue` | plates that failed automation (1,775 on 10-07) | `queue_type`, `resolved`, `attempts`, `last_attempt`, `created_at` (`scripts/db_migrate.py:170`) |
| `dof_auction_runs` | one row per PDF extraction run | `run_id`, `run_date`, `auction_date`, `auction_location`, `vehicles_extracted`, `status` (`scripts/db_migrate.py:19`) |
| `dof_vehicle_enrichment` | enrichment results per vehicle guid | counted only (`dof_server.py:90`); column list NOT VERIFIED in repo DDL |

## The SQL (operator runs as superuser, in a transaction)

```sql
-- dof_reader: read-only status reader for the n8n coordination projection (AGENTS.md §23, proposal S2).
-- Run as the Postgres superuser against the trade_ai database. Idempotent where Postgres allows it.
BEGIN;

-- 1. The role. LOGIN, no password here: the operator sets it right after with  \password dof_reader
--    (psql prompts; nothing lands in shell history or this file). Every elevated attribute is off.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dof_reader') THEN
    CREATE ROLE dof_reader WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
      CONNECTION LIMIT 3;
  END IF;
END $$;
ALTER ROLE dof_reader NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3;
ALTER ROLE dof_reader SET default_transaction_read_only = on;
ALTER ROLE dof_reader SET statement_timeout = '5s';
ALTER ROLE dof_reader SET search_path = public;

-- 2. Start from nothing. (REVOKE on objects the role never held is a no-op, which is the point.)
REVOKE ALL ON DATABASE trade_ai FROM dof_reader;
REVOKE ALL ON SCHEMA public FROM dof_reader;
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM dof_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM dof_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM dof_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES    FROM dof_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM dof_reader;

-- 3. The two status views. Owned by the table owner (trade_ai), so dof_reader needs SELECT on the view
--    only and never touches the base tables. No plate, VIN, guid, lookup result or override is exposed.
CREATE OR REPLACE VIEW public.dof_queue_status_v AS
  SELECT 'enrichment'::text AS queue,
         q.source           AS kind,
         q.status           AS status,
         q.scheduled_for::date AS scheduled_for,
         COUNT(*)           AS rows,
         MAX(q.attempts)    AS max_attempts,
         MAX(q.completed_at) AS last_completed_at
  FROM public.dof_enrichment_queue q
  GROUP BY q.source, q.status, q.scheduled_for::date
  UNION ALL
  SELECT 'manual'::text,
         m.queue_type,
         CASE WHEN m.resolved THEN 'resolved' ELSE 'open' END,
         m.created_at::date,
         COUNT(*),
         MAX(m.attempts),
         MAX(m.resolved_at)
  FROM public.dof_manual_queue m
  GROUP BY m.queue_type, m.resolved, m.created_at::date;

CREATE OR REPLACE VIEW public.dof_enrichment_runs_v AS
  SELECT r.run_id, r.run_date, r.auction_date, r.auction_location, r.vehicles_extracted, r.status
  FROM public.dof_auction_runs r;

ALTER VIEW public.dof_queue_status_v     OWNER TO trade_ai;
ALTER VIEW public.dof_enrichment_runs_v  OWNER TO trade_ai;

-- 4. The whole grant.
GRANT CONNECT ON DATABASE trade_ai TO dof_reader;
GRANT USAGE   ON SCHEMA public      TO dof_reader;
GRANT SELECT  ON public.dof_queue_status_v, public.dof_enrichment_runs_v TO dof_reader;

COMMIT;
-- Then, still as superuser, out-of-band:   \password dof_reader
-- and put the value in Bitwarden SM (project trade-ai-prod) as DOF_READER_PASSWORD. Not in n8n.
```

Not granted, on purpose: SELECT on any base table (`dof_enrichment_queue`, `dof_manual_queue`,
`dof_vehicles`, …), any sequence, any function, `CREATE` on the schema, `TEMP` on the database. If the
projection later needs row-level queue detail, that is a new grant under §17, not an edit to this one.

## Verification (operator, after COMMIT)

```sql
-- a) attributes: every elevated flag false, connection limit 3
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolinherit, rolreplication, rolbypassrls, rolconnlimit
FROM pg_roles WHERE rolname = 'dof_reader';

-- b) exactly two SELECT grants, both on views
SELECT table_schema, table_name, privilege_type
FROM information_schema.role_table_grants WHERE grantee = 'dof_reader' ORDER BY 2, 3;

-- c) nothing else: no table outside the two views, no sequence, no function
SELECT count(*) AS stray_grants FROM information_schema.role_table_grants
WHERE grantee = 'dof_reader' AND table_name NOT IN ('dof_queue_status_v', 'dof_enrichment_runs_v');
SELECT count(*) AS seq_grants FROM information_schema.role_usage_grants WHERE grantee = 'dof_reader';
```

Expected: (a) one row, all `f`, `rolconnlimit = 3`; (b) two rows, both `SELECT`; (c) `0` and `0`.

Then as the role (`psql -U dof_reader -d trade_ai -h 127.0.0.1`, password prompted):

```sql
SELECT queue, kind, status, SUM(rows) FROM dof_queue_status_v GROUP BY 1,2,3 ORDER BY 1,2,3;   -- rows
SELECT count(*) FROM dof_enrichment_queue;        -- expected: ERROR: permission denied for table
INSERT INTO dof_manual_queue (plate_number, plate_state, queue_type) VALUES ('X','NY','tickets');
                                                  -- expected: ERROR: cannot execute INSERT in a read-only transaction
```

The two errors are the evidence that the grant is what it says; a role that can read the base table or
write anything is not `dof_reader` and the proposal is void until fixed.

## Where the role is used, and where it is not

- Used by: the host-side coordination projection (`scripts/lib/n8n_coordination_projection.py`,
  source `dof`) and the DOF monitor's queue-status receipt, both on the host, DSN rendered from SM.
- Never used by: n8n (no Postgres node, no DSN in n8n — AGENTS.md §2A, §23.5, lab `docs/AGENTS.md`), the
  DOF Flask app (it keeps its own role; proposal S2 step 1 binds it to loopback), or any writer.
- Rollback: `DROP VIEW public.dof_queue_status_v, public.dof_enrichment_runs_v; DROP ROLE dof_reader;` —
  no table changes, so nothing else moves.
