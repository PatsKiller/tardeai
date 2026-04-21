# OpenClaw Phase A1 — Advisor-Memory Foundation Plan

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Estimated effort:** 3-4 hours implementation + verification

---

## 1. Executive Summary

### What Phase A1 is

The smallest durable foundation for OpenClaw's advisor memory: two new Postgres tables (`dividend_history` and `advisor_observations`) plus a lightweight local observation writer that records portfolio findings from existing data sources on every pipeline run.

### Why this is the right first slice

1. **Dividend history starts accumulating immediately** — yield data has compounding value over time (literally). Every day of delay is a day of lost history.
2. **Observations are the atomic unit of advisor intelligence** — everything later (recommendations, escalation, forecasts) builds on observations.
3. **Zero external dependencies** — uses only data already flowing through the pipeline. No new APIs, no external models, no Gmail.
4. **Proven pattern** — follows the exact same dual-write approach as Tasks 1-12. No new infrastructure.
5. **Independently testable** — after Phase A1 ships, you can query "what has the advisor noticed this week?" from Postgres.

### What it intentionally excludes

- No external model escalation (Sonnet/GPT-4o)
- No Gmail or email notifications
- No recommendation generation or action queue
- No analyst/social ingestion
- No forecast engine
- No article indexing
- No autonomous write-back beyond append-only history

---

## 2. Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| `dividend_history` table + writer | `advisor_recommendations` table |
| `advisor_observations` table + writer | `advisor_forecasts` table |
| Local rule-based observation generation | External model calls |
| Reading from existing JSON/Postgres sources | New API integrations |
| Appending history rows | Modifying existing pipeline behavior |
| Recording what IS, not what SHOULD BE | Generating recommendations or actions |

**Hard rule:** Phase A1 observes and records. It does NOT recommend, alert, or act.

---

## 3. Proposed Tables

### `dividend_history`

**Purpose:** Track dividend yield and payment data per ticker over time. Enables "SCHD yield 6 months ago vs today" and "has CSWC cut its dividend?" queries.

```sql
CREATE TABLE IF NOT EXISTS dividend_history (
    id serial PRIMARY KEY,
    record_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    annual_yield_pct numeric(6,3),       -- e.g., 3.580
    quarterly_amount numeric(10,4),       -- per-share quarterly dividend
    annual_income numeric(10,2),          -- portfolio-level annual $ from this position
    ex_div_date date,                     -- next/most-recent ex-div
    pay_date date,                        -- next/most-recent pay date
    source varchar(30) DEFAULT 'pipeline', -- 'pipeline'|'manual'|'yahoo'
    data jsonb,                           -- extra fields (payout_ratio, growth_yoy, etc.)
    created_at timestamptz DEFAULT now(),
    UNIQUE(record_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_dividend_history_date ON dividend_history(record_date DESC);
CREATE INDEX IF NOT EXISTS idx_dividend_history_symbol ON dividend_history(symbol);
```

**Column rationale:**

| Column | Why needed now |
|--------|---------------|
| `record_date` | Time-series key — one snapshot per day |
| `symbol` | Per-ticker tracking |
| `annual_yield_pct` | Core metric for yield deterioration detection |
| `quarterly_amount` | Detects actual dividend cuts/raises |
| `annual_income` | Portfolio-level income from this position (shares × quarterly × 4) |
| `ex_div_date` | Track upcoming ex-div for timing signals |
| `source` | Provenance |
| `data` | Future fields (payout_ratio, growth_yoy, consecutive_raises) without schema change |

**Deferred:** `growth_yoy_pct`, `payout_ratio`, `consecutive_raises` — store in `data` JSONB for now, promote to columns when query patterns emerge.

---

### `advisor_observations`

**Purpose:** Append-only memory of what the agent noticed. Each row is one atomic finding. No recommendations, no actions — just observations with evidence.

```sql
CREATE TABLE IF NOT EXISTS advisor_observations (
    id serial PRIMARY KEY,
    observed_at timestamptz DEFAULT now(),
    observation_date date NOT NULL,        -- logical date (pipeline run date)
    symbol varchar(20),                    -- NULL for portfolio-level observations
    category varchar(20) NOT NULL,         -- 'dividend'|'concentration'|'risk'|'signal'|'performance'|'freshness'
    observation text NOT NULL,             -- human-readable finding
    evidence jsonb NOT NULL,               -- supporting data (machine-readable)
    source varchar(50) NOT NULL,           -- 'pipeline:dividend_calendar'|'pipeline:action_signals'|etc.
    confidence numeric(3,2) DEFAULT 1.00,  -- 1.00 for rule-based (no model uncertainty)
    model varchar(30) DEFAULT 'rule',      -- 'rule'|'ollama:qwen3:1.7b'|future models
    freshness_hash varchar(12),            -- holdings_hash at time of observation (links to freshness)
    UNIQUE(observation_date, symbol, category, source)
);
CREATE INDEX IF NOT EXISTS idx_observations_date ON advisor_observations(observation_date DESC);
CREATE INDEX IF NOT EXISTS idx_observations_symbol ON advisor_observations(symbol);
CREATE INDEX IF NOT EXISTS idx_observations_category ON advisor_observations(category);
```

**Column rationale:**

| Column | Why needed now |
|--------|---------------|
| `observation_date` | Logical date for dedup (one observation per source per ticker per day) |
| `symbol` | NULL = portfolio-level; non-NULL = position-specific |
| `category` | Fast filtering: "show all dividend observations this month" |
| `observation` | Human-readable text — what the agent noticed |
| `evidence` | Machine-readable JSON — the numbers behind the observation |
| `source` | Which pipeline step / data source produced this |
| `confidence` | 1.00 for rule-based (Phase A1). <1.00 reserved for model-scored (future). |
| `model` | 'rule' for Phase A1. Future: 'ollama:qwen3:1.7b', 'claude-sonnet-4', etc. |
| `freshness_hash` | Links observation to the specific portfolio composition state |

**UNIQUE constraint:** One observation per (date, symbol, category, source). Re-running the pipeline on the same day upserts, not duplicates.

**Deferred:** `expires_at`, `superseded_by`, `escalation_tier` — not needed until Phase D (escalation).

---

## 4. Observation Categories for First Pass

All observations are **rule-based** (confidence=1.00, model='rule'). No LLM needed.

### Category: `dividend`

| Observation | Source | Evidence JSON |
|-------------|--------|---------------|
| "SCHD annual yield is 3.58%, contributing $4,200/yr to portfolio income" | dividend_calendar.json | `{"yield_pct": 3.58, "annual_income": 4200, "ex_div_days": 12}` |
| "Total portfolio dividend income: $12,510/yr from 8 payers" | dividend_calendar.json | `{"total_annual": 12510, "payer_count": 8}` |
| "CSWC yield 10.5% — highest yield position" | dividend_calendar.json + holdings | `{"yield_pct": 10.5, "market_value": 9773}` |

### Category: `concentration`

| Observation | Source | Evidence JSON |
|-------------|--------|---------------|
| "V is 15.7% of portfolio across 2 accounts" | action_signals.json | `{"portfolio_pct": 15.7, "signal": "WATCH", "accounts": 2}` |
| "FID-CONTRA-F at 14.0% — above TRIM threshold" | action_signals.json | `{"portfolio_pct": 14.0, "signal": "TRIM", "rule": "R1"}` |

### Category: `risk`

| Observation | Source | Evidence JSON |
|-------------|--------|---------------|
| "BND within 5% of stop level" | risk_management.json | `{"distance_pct": 4.2, "stop_price": 69.50, "current": 72.50}` |
| "Portfolio heat: 8.5% of positions in danger/triggered zone" | risk_management.json | `{"heat_pct": 8.5, "triggered": 0, "danger": 1}` |

### Category: `signal`

| Observation | Source | Evidence JSON |
|-------------|--------|---------------|
| "4 positions at ADD signal (dividend gap): SCHD, CSWC, PFLT, DIV" | action_signals_history | `{"add_count": 4, "symbols": ["SCHD","CSWC","PFLT","DIV"]}` |
| "V signal changed from TRIM to WATCH (earnings suppression)" | action_signals_history | `{"prev_signal": "TRIM", "new_signal": "WATCH", "reason": "R11 earnings"}` |

### Category: `performance`

| Observation | Source | Evidence JSON |
|-------------|--------|---------------|
| "Portfolio YTD +3.8%, 1W +2.2%" | performance_daily | `{"ytd_pct": 3.8, "1w_pct": 2.2, "total_value": 1209000}` |
| "Portfolio at $1,209,000 — new high this month" | performance_daily + snapshots | `{"total_value": 1209000, "month_high": true}` |

### Category: `freshness`

| Observation | Source | Evidence JSON |
|-------------|--------|---------------|
| "Pipeline ran successfully, data is fresh (0.1h old)" | _freshness.json | `{"age_hours": 0.1, "holdings_hash": "ea4ff1a05707"}` |
| "Data is 26+ hours stale — pipeline may have missed scheduled run" | _freshness.json | `{"age_hours": 28, "status": "stale"}` |

---

## 5. Proposed Write Path

### `dividend_history` writer

**Source:** `dividend_calendar.json` (produced daily by `portfolio_dividend_calendar.py`)

**Insertion point:** In `portfolio_orchestrator.py`, after the existing dividend_calendar write (step ~10b). Same pattern as performance_daily:

```python
# After dividend_calendar.json is written
try:
    from db_adapter import save_dividend_history
    save_dividend_history(dividend_calendar, holdings)
except Exception as e:
    print(f"  [dividend-history] Postgres write failed (pipeline continues): {e}")
```

The helper extracts per-ticker yield data from the calendar + current market values from holdings.

### `advisor_observations` writer

**Two options:**

**Option A (RECOMMENDED): Small companion function called at pipeline end**

Add a `write_advisor_observations(portfolio, signals, performance, risk, freshness, state_dir)` function that:
1. Reads existing pipeline outputs (all already in memory or freshly written to JSON)
2. Generates rule-based observations
3. Bulk-inserts to `advisor_observations` with ON CONFLICT upsert

Call it after the freshness manifest write (the last pipeline step), so all data is final.

**Option B: Separate script on its own timer**

A standalone `scripts/openclaw_observer.py` that reads state files and writes observations independently. More decoupled but adds a new timer/schedule.

**Recommendation:** Option A. It's 30-50 lines inside the existing orchestrator, follows the proven pattern, and fires at exactly the right time (after all data is final).

### JSON behavior unchanged

Both writers are append-only Postgres writes. They do NOT modify any JSON files. All existing consumers continue reading JSON as before.

---

## 6. Minimal Confidence / Provenance Model

For Phase A1 (local rules only), these fields are sufficient:

| Field | Phase A1 Value | Purpose |
|-------|---------------|---------|
| `source` | `'pipeline:dividend_calendar'`, `'pipeline:action_signals'`, etc. | Which data source produced this observation |
| `observed_at` | `now()` | When the observation was recorded |
| `observation_date` | Today's date | Logical dedup key |
| `confidence` | `1.00` | Rule-based observations are certain (data was X, so observation is X) |
| `model` | `'rule'` | No LLM used — pure data extraction |
| `freshness_hash` | From `_freshness.json` | Links observation to specific portfolio state |
| `evidence` | JSONB with numbers | Machine-readable proof — enables future models to verify |

**Why confidence is always 1.00 in Phase A1:**

Rule-based observations are deterministic: "V is 15.7% of portfolio" is a fact, not an inference. Confidence < 1.00 is reserved for model-scored observations (Phase C+), where the model's assessment introduces uncertainty.

---

## 7. Verification Strategy

### Table creation
```sql
SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('dividend_history', 'advisor_observations');
-- Expected: both present
```

### Sample rows after one pipeline run
```sql
SELECT record_date, symbol, annual_yield_pct, annual_income
FROM dividend_history WHERE record_date = CURRENT_DATE LIMIT 5;
-- Expected: rows for dividend-paying tickers (SCHD, CSWC, PFLT, DIV, etc.)

SELECT observation_date, category, symbol, observation
FROM advisor_observations WHERE observation_date = CURRENT_DATE
ORDER BY category, symbol LIMIT 10;
-- Expected: mix of dividend/concentration/risk/signal/performance observations
```

### Idempotency
```sql
-- After second pipeline run on same day:
SELECT COUNT(*) FROM advisor_observations WHERE observation_date = CURRENT_DATE;
-- Expected: same count as first run (UPSERT via UNIQUE constraint)
```

### No existing outputs broken
```bash
# After pipeline run, verify:
ls -la data/portfolios/state/dividend_calendar.json  # still written
ls -la data/portfolios/state/action_signals.json     # still written
ls -la data/portfolios/state/performance_history.json # still written
curl -s http://127.0.0.1:7777/api/freshness | python3 -m json.tool  # still returns fresh
```

### Append-only confirmed
```sql
-- Run pipeline day 1, then day 2:
SELECT observation_date, COUNT(*) FROM advisor_observations GROUP BY observation_date ORDER BY observation_date;
-- Expected: separate row counts for each date, both present
```

---

## 8. Recommended Implementation Order

| Step | What | Effort | Output |
|------|------|--------|--------|
| 1 | Add `dividend_history` + `advisor_observations` tables to `db_setup.sql` | 10 min | Schema file updated |
| 2 | Apply schema to live database | 2 min | Tables created |
| 3 | Add `save_dividend_history()` to `db_adapter.py` | 20 min | Bulk INSERT helper |
| 4 | Add `save_observations()` to `db_adapter.py` | 20 min | Bulk INSERT helper |
| 5 | Add dividend-history writer to orchestrator (after dividend_calendar) | 15 min | Daily yield snapshots accumulate |
| 6 | Add observation writer to orchestrator (after freshness manifest) | 45 min | Rule-based observations accumulate |
| 7 | Verify: run pipeline, check rows, check idempotency | 20 min | All passing |
| 8 | Write verification report | 15 min | Documentation |

**Total: ~2.5 hours implementation + verification**

---

## 9. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Noisy observations** | MEDIUM | Start with 5-10 observation types only. Can always add more later. UNIQUE constraint prevents duplicates. |
| **Duplicate observations** | LOW | `UNIQUE(observation_date, symbol, category, source)` prevents same observation twice per day. |
| **Stale source data** | LOW | Check `_freshness.json` age before writing. If stale, write a freshness observation noting staleness. |
| **Overcomplicated schema** | MEDIUM | Intentionally minimal: 2 tables, no FKs between them, no cascades. JSONB `data`/`evidence` absorbs future fields without migrations. |
| **Accidentally drifting into recommendation logic** | HIGH | Hard rule: observations state WHAT IS, never WHAT SHOULD BE. Review: if observation text contains "should", "recommend", "consider" → it's a recommendation, not an observation. Reject. |
| **Table growth** | LOW | ~50 observations/day × 365 = ~18K rows/year. ~10 dividend rows/day × 365 = ~3.6K/year. Trivial. |

---

## 10. Architect Recommendation

### Smallest high-value implementation plan

Build exactly what's described in Section 8: two tables, two helpers, two writers, one verification pass. Ship in a single task (~2.5 hours).

### What to build immediately after Phase A1 succeeds

**Phase A2: Observation enrichment via local Ollama.**

Once observations are accumulating, add a second pass that:
- Reads today's observations
- Asks Ollama: "Given these observations, are any of them noteworthy enough to highlight in a daily summary?"
- Writes a single `category='daily_summary'` observation with the highlights
- This is still observation-only (not recommendation), still local-only, still cheap

This naturally leads into Phase C (local-first monitor) from the broader plan.

### What remains explicitly deferred

| Deferred | Reason |
|----------|--------|
| `advisor_recommendations` table | Requires escalation logic (Phase D) |
| `advisor_forecasts` table | Requires external models (Phase F) |
| `article_index` table | Requires new ingestion pipelines (Phase B) |
| `analyst_consensus_history` | Requires new data source (Phase B) |
| `social_sentiment_history` | Requires Reddit/StockTwits API (Phase B) |
| `notification_log` | Requires Gmail integration (Phase E) |
| External model calls | Phase D |
| Gmail notifications | Phase E |

---

## Appendix: Sample Data

### Sample `dividend_history` row

```json
{
  "record_date": "2026-04-20",
  "symbol": "SCHD",
  "annual_yield_pct": 3.580,
  "quarterly_amount": 0.6250,
  "annual_income": 1420.00,
  "ex_div_date": "2026-05-15",
  "pay_date": "2026-06-10",
  "source": "pipeline",
  "data": {"shares": 158.0, "market_value": 39680.0, "cost_basis": 37200.0}
}
```

### Sample `advisor_observations` row

```json
{
  "observation_date": "2026-04-20",
  "symbol": "V",
  "category": "concentration",
  "observation": "V is 15.7% of portfolio across 2 accounts — above TRIM threshold (12%) but suppressed by earnings proximity",
  "evidence": {"portfolio_pct": 15.7, "signal": "WATCH", "rule": "R11", "accounts": ["schwab_roth", "schwab_rollover_ira"], "market_value": 189718},
  "source": "pipeline:action_signals",
  "confidence": 1.00,
  "model": "rule",
  "freshness_hash": "ea4ff1a05707"
}
```

### 5 Example Observations (Phase A1 local-only)

1. **dividend:** "Total portfolio dividend income: $12,510/yr from 8 payers (target: $28,000). Gap: $15,490/yr."
2. **concentration:** "V is 15.7% of portfolio — highest single-position concentration. Signal: WATCH (earnings in 7d)."
3. **performance:** "Portfolio YTD +3.8% ($43,665). 1-week: +2.2% ($26,192). Current value: $1,209,328."
4. **risk:** "BND within 5% of stop level ($69.50 stop, $72.50 current). Distance: 4.1%."
5. **signal:** "4 positions have ADD signal (R6: Dividend gap close): SCHD, CSWC, PFLT, DIV. Combined value: $28,990."

---

*Phase A1 foundation plan created 2026-04-20. Awaiting architect approval before implementation.*
