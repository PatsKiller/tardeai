# OpenClaw Recommendation-Draft — Verification Report

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup_advisor.sql`, `scripts/db_adapter.py`, `scripts/portfolio_orchestrator.py`, `~/.openclaw/skills/steph-wealth-advisor/scripts/advisor_memory_reader.py`

---

## 1. Schema

```sql
CREATE TABLE IF NOT EXISTS advisor_recommendations (
    id serial PRIMARY KEY,
    recommendation_date date NOT NULL,
    symbol varchar(20),
    action varchar(30) NOT NULL,
    rationale text NOT NULL,
    confidence numeric(3,2) NOT NULL,
    model varchar(30) NOT NULL,
    escalation_ids integer[],
    observation_ids integer[],
    evidence_summary jsonb NOT NULL,
    status varchar(20) DEFAULT 'draft',
    expires_at date,
    dedupe_key varchar(100) NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(dedupe_key)
);
```

Dedupe key format: `{date}:{symbol or 'portfolio'}:{action}:{trigger_rule}`

## 2. Drafts Generated Today

| Symbol | Action | Confidence | Status | Yahoo Context |
|--------|--------|:---:|--------|:---:|
| (portfolio) | STOP_REVIEW | 0.90 | draft | — |
| V | ALLOCATION_REVIEW | 0.80 | draft | ✓ 35 analysts, mean $393, strong_buy |

### V Draft Rationale
> "V concentration at 15.7% exceeds 15% threshold. Yahoo analyst context: 35 analysts, mean target $393, consensus: strong_buy. Pending review (severity 2)."

### STOP_REVIEW Rationale
> "1 stop(s) currently triggered. Pending review (severity 1)."

## 3. Yahoo Analyst Data Integration

The V draft includes authoritative Yahoo analyst context:
- `number_of_analyst_opinions: 35`
- `target_mean_price: $393.43`
- `recommendation_key: strong_buy`
- `current_price: $313.94`

Finviz-derived `analyst_consensus_history` was NOT used as authoritative consensus in draft text.

## 4. Bridge Skill

`advisor_memory_reader.py recommendations` query type added:
```json
{
  "query_type": "recommendations",
  "filters": {"status": "draft"},
  "record_count": 2,
  "results": [
    {"symbol": null, "action": "STOP_REVIEW", "confidence": "0.90", "status": "draft"},
    {"symbol": "V", "action": "ALLOCATION_REVIEW", "confidence": "0.80", "status": "draft"}
  ]
}
```

## 5. Idempotency

Second pipeline run: still 2 rows (UNIQUE(dedupe_key) prevents duplicates).

## 6. Explicit Statements

| Question | Answer |
|----------|--------|
| Did drafts remain `draft` only? | **YES** — status='draft', no transitions |
| Was notification logic added? | **NO** |
| Was action/approval logic added? | **NO** |
| Was Yahoo analyst target data used when available? | **YES** — V draft includes Yahoo context |
| Were Finviz analyst placeholders treated as authoritative? | **NO** — only Yahoo data cited in draft rationale |

## 7. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| advisor_recommendations table created and applied | **PASS** |
| Today's qualifying drafts inserted | **PASS** (2 drafts from 2 severity 1-2 escalations) |
| Same-day rerun upserts without duplicates | **PASS** |
| Drafts remained status='draft' only | **PASS** |
| No notification/action logic added | **PASS** |
| Yahoo analyst target history used as supporting context | **PASS** |
