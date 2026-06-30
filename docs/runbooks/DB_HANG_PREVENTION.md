# DB-induced dashboard hang — prevention & recovery

**Symptom:** Command Center shows `⟳ Reconnecting to backend… showing last-known data`, all KPIs `—`,
`0 holdings · $0`. The server (`scripts/portfolio_server.py`, port 7777) is **alive but blocked** — the
port stays bound while HTTP requests time out.

## Root cause

A pile-up of long / idle-in-transaction queries on a hot table (most often `paper_trade_proposals`,
`paper_trades`, `catalyst_events`). The trigger pattern:

1. A code path runs `SELECT … FROM paper_trade_proposals` (or similar) and leaves the connection
   **idle-in-transaction** (e.g. holding the read open across a slow LLM call), holding an `AccessShareLock`.
2. An **additive `ALTER TABLE … ADD COLUMN IF NOT EXISTS`** (a 30-min curator / hot-path migration) needs an
   `AccessExclusiveLock`, so it **queues behind** the idle lock holder.
3. With `lock_timeout = 0` (unbounded — the old default), the ALTER waits indefinitely, and **every
   subsequent query on that table queues behind the ALTER**. The server's request threads block on those
   queries → the dashboard hangs.

## Fix (two layers)

### 1. Per-connection guards (code) — covers `db_adapter` connections
`scripts/db_adapter._get_conn()` sets, on every connection:
- `idle_in_transaction_session_timeout = '120s'` — a leaked read can't hold a lock forever.
- `lock_timeout = '3s'` — **the anti-cascade guard**: a query waiting on a lock fails fast instead of
  queuing the table behind a blocked DDL.
- `statement_timeout = '180s'` — a runaway query is killed rather than pinning a thread.

### 2. Role-level guards (DB config) — covers EVERY connection, incl. raw `psycopg2.connect()` (~300 scripts)
`db_adapter` only covers code that goes through it. Raw-connection callers need the same guards applied at
the **role** level so they are universal and require no per-script edits. Run once (as `trade_ai`):

```bash
# from the project root — applies to all FUTURE connections by the trade_ai role
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, 'scripts')
from db_adapter import _get_conn
conn = _get_conn(); conn.autocommit = True; c = conn.cursor()
c.execute("ALTER ROLE trade_ai SET lock_timeout = '3s'")
c.execute("ALTER ROLE trade_ai SET idle_in_transaction_session_timeout = '120s'")
c.execute("ALTER ROLE trade_ai SET statement_timeout = '180s'")
print("role-level DB guards applied")
PY
```

> Role-level `SET` only affects **new** connections. Restart long-lived daemons (the dashboard server) so
> they reconnect and inherit the guards: `bash linux_launchers/restart_server.sh`.

To confirm: `SHOW lock_timeout;` on a fresh connection should return `3s` (was `0`).

## Recovery (when it is hung right now)

1. **Identify** the pile-up:
   ```sql
   SELECT pid, state, now()-query_start AS dur, left(query,80)
   FROM pg_stat_activity
   WHERE datname=current_database() AND state<>'idle' AND now()-query_start > interval '30 seconds'
   ORDER BY dur DESC;
   ```
2. **Terminate** stuck idle-in-transaction holders (safe — they are doing nothing but holding locks):
   ```sql
   SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE state='idle in transaction' AND now()-state_change > interval '120 seconds';
   ```
3. **Restart** the server so wedged threads are cleared and connections inherit the guards:
   `bash linux_launchers/restart_server.sh` (user-level, no sudo).

## Don't

- Don't run additive `ALTER TABLE` on hot tables from a recurring hot path without a short `lock_timeout`
  (the role-level guard now covers this, but new code should still avoid hot-path DDL — run schema changes
  as one-shot migrations).
- Don't hold a DB transaction open across a slow LLM/network call. Read → commit → process → reopen to write.
