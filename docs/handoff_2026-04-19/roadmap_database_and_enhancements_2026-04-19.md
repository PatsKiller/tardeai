# Trade AI v12 — Database & System Roadmap

**Version:** 1.0  
**As-of:** 2026-04-19 (after 13 commits today, Phase 8D-3b shipped)  
**Audience:** Solo architect picking up where John & Claude left off  
**Companion docs:** `schemas_reference_2026-04-19.md`, `collaboration_handoff_2026-04-19.md`

This doc lays out **every remaining step** to fully implement the database migration and enhance the system. Each step has rationale, effort estimate, dependencies, and acceptance criteria.

---

## Where we are right now

**12 phases planned in `portfolio_ai_analyst_rewrite_scope.md`. Status:**

| Phase | Description | Status |
|---|---|---|
| 0 | Data freshness gate | Not started |
| 1 | Remove hardcoded numbers | Partial (8C did the personal stuff) |
| 2 | Three-tier model routing | Not started |
| 3 | Weekly-to-monthly aggregation | Not started |
| 4 | Smart cache invalidation | Not started |
| 5 | Intel Arc Pro B50 local LLM | Not started (hardware not yet purchased) |
| 6 | Portfolio theory (MPT/BL/MC) | Not started |
| 7 | ETF Intelligence + AI | Not started |
| 8 | Personal Situation modal editor | ✅ COMPLETE (8A through 8D-3c) |
| P0 | Activate Postgres adapter | ✅ COMPLETE |
| P1 | personal_history table + dual-write | ✅ COMPLETE |
| 11 | Historical Portfolio Reconstruction | Future (multi-day) |

This roadmap focuses on **database migration + immediate enhancement work**. Phases 5/6/7 are larger features deferred to their own discussion.

---

## Database migration roadmap

### Phase P2: Activate writes for existing tables (~4-6 hours)

**Goal:** The Postgres tables `run_summary`, `trade_ai_state`, `price_cache`, and `portfolio_snapshots` exist but are mostly empty. Wire the producers to actually write to them.

**Why now:** Without active writes, the tables are dead weight. Phase 11 (historical portfolio reconstruction) depends on `portfolio_snapshots` accumulating entries over time. The longer we delay, the longer Phase 11 has to wait for data.

#### P2-1: Activate `portfolio_snapshots` writes (~1 hr)

Wire the daily pipeline to call `db_adapter.save_snapshot()` after computing total portfolio value.

**Files to modify:**
- `scripts/portfolio_ai_analyst.py` — find where snapshot_index.json gets updated, add `db_adapter.save_snapshot(snapshot, state_dir)` call
- `scripts/db_adapter.py::save_snapshot` — verify it INSERTs to portfolio_snapshots table (probably already correct)

**Verification:**
- Run pipeline manually
- Query: `SELECT * FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 5`
- Should show today's snapshot

**Acceptance criteria:**
- Pipeline run inserts new row in portfolio_snapshots
- Idempotent (re-running same day uses ON CONFLICT to skip or update)
- No JSON write disruption (snapshot_index.json still writes)

#### P2-2: Activate `price_cache` Postgres mirror (~2 hrs)

Currently price_cache.json is the source of truth and Postgres mirror is dormant. Migrate to dual-write pattern.

**Files to modify:**
- `scripts/portfolio_repricer.py` — after price_cache.json write, call `db_adapter.save_price_cache(cache, state_dir)`
- `scripts/db_adapter.py::save_price_cache` — bulk INSERT with `ON CONFLICT (symbol, price_date) DO UPDATE`

**Backfill:** One-time script to populate price_cache table from existing JSON file (~5,000+ rows likely).

**Acceptance criteria:**
- Daily reprice writes to both JSON and Postgres
- Backfill loaded existing JSON cache
- Query: `SELECT COUNT(*) FROM price_cache GROUP BY symbol` shows expected coverage
- Yahoo Finance pulls back 2 years per symbol → significant data volume in DB

#### P2-3: Activate `run_summary` writes (~1.5 hrs)

The Trade AI scalp pipeline (separate from portfolio system) currently writes JSON only. Wire to Postgres.

**Files to modify:**
- Find the Trade AI scan output writer (likely `scripts/trade_ai_*.py`)
- After scan completes, save run summary to both JSON and Postgres via `db_adapter.save_run_summary(summary, path)`

**Acceptance criteria:**
- Each scan run inserts row in run_summary
- Date+label uniqueness handled (ON CONFLICT)
- Historical scan results queryable via SQL

#### P2-4: Activate `trade_ai_state` (delta tracking) writes (~1.5 hrs)

Per-ticker state tracking for Trade AI signal persistence.

**Files to modify:**
- Find the Trade AI delta tracker
- After updating ticker state, save to Postgres via `db_adapter.save_state()`

**Acceptance criteria:**
- Each scan updates per-ticker rows
- (run_date, ticker) uniqueness handled
- Can query "ticker X consecutive_go count over past N days"

---

### Phase P3: Migrate JSON files that benefit from Postgres (~6-9 hours)

**Goal:** Move time-series and queryable JSON files into Postgres tables.

#### P3-1: `performance_history.json` → `performance_history` table (~3 hrs)

This file tracks long-term portfolio performance. Currently a JSON list. Will benefit from SQL aggregations (rolling returns, sharpe over windows, drawdown analysis).

**New schema:**
```sql
CREATE TABLE performance_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL UNIQUE,
    total_value numeric(14,2) NOT NULL,
    benchmark_spy_close numeric(10,4),
    benchmark_qqq_close numeric(10,4),
    portfolio_return_pct numeric(8,4),
    spy_return_pct numeric(8,4),
    alpha_pct numeric(8,4),
    sharpe_30d numeric(6,3),
    sharpe_90d numeric(6,3),
    max_drawdown_pct numeric(8,4),
    data jsonb,                       -- additional metrics, sector returns, etc.
    created_at timestamptz DEFAULT now()
);
```

**Migration steps:**
1. Create table via `db_setup.sql` addition
2. Add `db_adapter.save_performance_entry()` and `load_performance_history()`
3. Backfill from existing JSON
4. Wire daily pipeline to dual-write
5. Add `/api/performance/history?days=N` endpoint for new charts

**Acceptance criteria:**
- Backfill complete, row count matches JSON length
- Daily pipeline writes new entry
- Can query rolling returns: `SELECT date, AVG(portfolio_return_pct) OVER (ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) FROM performance_history`

#### P3-2: `intel_brief_status.json` → `intel_briefs` table (~2 hrs)

C2 Autopilot v3.16 produces intel briefs. Currently each brief generation overwrites status. Migrate to historical record.

**New schema:**
```sql
CREATE TABLE intel_briefs (
    id serial PRIMARY KEY,
    brief_date date NOT NULL,
    brief_type varchar(20) NOT NULL,         -- 'monthly'|'special'|'rebalance'
    fund varchar(20) NOT NULL,                -- 'aiww3'|'autopilot'|'consolidated'
    docx_path text,
    word_count integer,
    sections jsonb NOT NULL,                  -- structured brief content
    triggers jsonb,                           -- what conditions triggered this brief
    created_at timestamptz DEFAULT now(),
    UNIQUE(brief_date, brief_type, fund)
);
```

**Migration:** Brief generation script writes to both file system (DOCX) and Postgres metadata table.

#### P3-3: Action signals time-series (~3-4 hrs)

Currently `action_signals.json` always has CURRENT signals. We lose the history. Add a separate `action_signals_history` table.

**Why this matters:** Want to query "how often was LMT a GO over the past month?" or "which signals correlate with subsequent gains?"

**New schema:**
```sql
CREATE TABLE action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    ticker varchar(10) NOT NULL,
    action varchar(10) NOT NULL,              -- 'BUY'|'SELL'|'HOLD'|'TRIM'
    score numeric(5,2),
    confidence varchar(20),
    triggers jsonb,
    rationale text,
    UNIQUE(signal_date, ticker)
);
CREATE INDEX idx_signals_date ON action_signals_history(signal_date DESC);
CREATE INDEX idx_signals_ticker ON action_signals_history(ticker);
```

**Migration:** When current action_signals.json is written, also INSERT each signal into history table.

**Backfill:** None — start fresh. Historical signals from before this phase are lost (acceptable).

---

### Phase P4: Snapshot completeness pass (~3-4 hours)

**Goal:** Ensure every state file has either a Postgres mirror OR a documented decision to remain JSON.

**Steps:**
1. Audit `data/portfolios/state/` directory — every file
2. For each file, document: producer, consumer(s), update frequency, query needs, decision (migrate / stay JSON / deprecated)
3. Update `schemas_reference.md` with decisions
4. Migrate any borderline files identified

**Files needing audit (from current state):**
- `bond_intelligence.json`
- `etf_intelligence.json`
- `news_cache.json`
- `analyst_data.json`
- Various `*_signal_*.json` files
- Any `*_history.json` file not yet migrated

---

### Phase P5: Database admin and operational tooling (~3-4 hours)

**Goal:** Make the database operationally healthy long-term.

#### P5-1: Backup automation (~1 hr)

Currently no automated backups. Configure `pg_dump` to write to local backup directory daily, retain 30 days.

```bash
# /etc/cron.daily/pg_backup_trade_ai
#!/bin/bash
BACKUP_DIR=/home/johnclaw/db_backups
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PGPASSWORD='...' pg_dump -U trade_ai -h localhost trade_ai \
    > "$BACKUP_DIR/trade_ai_$TIMESTAMP.sql"
find "$BACKUP_DIR" -name "trade_ai_*.sql" -mtime +30 -delete
```

#### P5-2: VACUUM and ANALYZE schedule (~30 min)

PostgreSQL needs periodic maintenance. Configure auto-vacuum aggressively for high-write tables (`personal_history`, `holdings`).

#### P5-3: Monitoring and alerts (~1.5 hrs)

Add a `/api/db/health` endpoint that returns:
- Connection pool status
- Row counts per table
- Largest table size
- Recent write latency
- Replication lag (if applicable)

Wire into existing Telegram alert system. Alert on: connection failure, dramatic row count drop, disk full warning.

#### P5-4: Schema migration tooling (~1 hr)

Currently schema changes are ad-hoc SQL applied manually. Adopt **Alembic** or simpler **migration scripts** with version tracking.

```
linux_port_v2/linux/migrations/
├── 001_initial_schema.sql
├── 002_add_personal_history.sql
├── 003_add_performance_history.sql      # P3-1
├── 004_add_intel_briefs.sql             # P3-2
├── 005_add_action_signals_history.sql   # P3-3
└── _migration_log.sql                    # tracks which have been applied
```

---

## Beyond database — system enhancement roadmap

### Phase 11: Historical Portfolio Reconstruction (13-19 hours, multi-day)

Already scoped in `portfolio_ai_analyst_rewrite_scope.md`. Summary:
- 11A: Snapshot accumulation (passive, happens automatically as P2-1 ships)
- 11B: `/api/portfolio/as_of/<date>` endpoint (~3-4 hrs)
- 11C: Transaction import from broker CSVs (~5-8 hrs)
- 11D: Pre-P0 historical reconstruction via transaction replay (~3-4 hrs)
- 11E: Time-travel UI integration (~2-3 hrs)

**Cannot start until:** 30-60 days of automatic snapshots accumulated AND broker CSVs gathered.

### Phase 0: Data freshness gate (4-6 hours)

From scope doc. The system currently has no concept of "are all my state files from the same run?" Different files might be from different days, leading to inconsistencies. Phase 0 adds a single refresh entrypoint and freshness checks.

**Why prioritize:** Foundation for trustworthy AI prompts. Without freshness gates, AI sees stale data and gives bad advice.

### Phase 1: Remove remaining hardcoded numbers (3-4 hours)

8C completed personal_situation hardcoded values. But other functions in `portfolio_ai_analyst.py` still have hardcoded benchmark thresholds, scoring weights, etc.

**Audit:** `grep -n "= [0-9]" scripts/portfolio_ai_analyst.py | grep -v "^#"` finds candidates.

### Phase 4: Smart cache invalidation (5-7 hours)

Currently caches are TTL-based. Phase 4 adds invalidation triggers (e.g., when holdings change, invalidate sector mix cache).

### Phase 7: ETF Intelligence + AI Integration (8-12 hours)

Already scoped. Pulls ETF holdings/expense ratios/yields from external APIs, injects into AI context for ETF-specific advice.

---

## Recommended execution order

If you have ~40-60 hours of total work to do, here's the order of maximum value:

### Tier 1 — High value, builds foundation (~10-15 hrs)
1. **Finish 8D-3c** (1 hr) — last 8D piece
2. **P2-1: portfolio_snapshots writes** (1 hr) — starts data accumulation for Phase 11
3. **P2-2: price_cache Postgres mirror** (2 hrs) — large data volume, valuable backup
4. **P5-1: pg_dump backups** (1 hr) — operational safety
5. **Phase 0: Data freshness gate** (4-6 hrs) — foundation for trustworthy AI

### Tier 2 — Database completeness (~10-12 hrs)
6. **P2-3: run_summary writes** (1.5 hrs)
7. **P2-4: trade_ai_state writes** (1.5 hrs)
8. **P3-1: performance_history migration** (3 hrs)
9. **P5-2/P5-3: monitoring + maintenance** (2 hrs)
10. **P3-2: intel_briefs table** (2 hrs)

### Tier 3 — Forward-looking features (~15-20 hrs)
11. **Phase 1: Remove hardcoded numbers audit** (3-4 hrs)
12. **Phase 4: Smart cache invalidation** (5-7 hrs)
13. **P3-3: action_signals history** (3-4 hrs)
14. **P4: snapshot completeness pass** (3-4 hrs)

### Tier 4 — Wait until data accumulates (~13-19 hrs)
15. **Phase 11: Historical Portfolio Reconstruction** — only after 30-60 days of P2-1 snapshots

### Deferred (need hardware/scope discussion)
- Phase 5: Intel Arc Pro B50 (need hardware purchase)
- Phase 6: Portfolio theory (need to scope out which models actually deliver value)
- Phase 7: ETF Intelligence (substantial new feature)

---

## Total remaining effort estimate

**Database migration completion:** 16-23 hours  
**System enhancement (Phases 0/1/4):** 12-17 hours  
**Phase 11 (when data ready):** 13-19 hours  
**Phases 5/6/7 (deferred):** 30-50 hours

**Total roadmap:** ~70-110 hours of focused engineering across many sessions.

Done at the pace of today (12 commits in ~10 hours), that's roughly **6-10 more full sessions** to complete everything currently scoped.

---

## What's NOT in this roadmap

- **Frontend rewrites** — command_center.html is 11K lines and works. No appetite for SPA migration.
- **Multi-user support** — system is single-user (John). Adding auth/multi-tenant is a different system.
- **Cloud deployment** — runs on local MS-01 server. Cloud migration would be its own project.
- **Mobile apps** — out of scope.
- **Real-time streaming** — current architecture is batch/poll. Real-time would need WebSockets + significant restructuring.

---

## Questions to revisit periodically

These shape future direction:

1. **Are we generating too many JSON files?** Audit annually.
2. **Does the dual-write pattern still hold up at 10x data volume?** Re-evaluate at 100K+ rows in personal_history.
3. **Should Trade AI (scalp pipeline) and Portfolio AI (analyst) merge?** Currently separate codebases sharing some libs.
4. **At what data volume does Postgres → TimescaleDB migration make sense?** Probably never for personal use, but flag at 10M rows.
5. **Should we adopt Pydantic / dataclasses for type safety?** Currently dict-based. Type hints help but aren't enforced.

---

*Roadmap last updated 2026-04-19 after Phase 8D-3b ship. Next update should incorporate Phase 8D-3c completion.*
