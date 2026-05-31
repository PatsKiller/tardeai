# Hermes Phase 4A — Promotion Architecture

**Date:** 2026-05-31
**Status:** DESIGN + DRY-RUN ONLY — no promotion applied

---

## Purpose

Define how Hermes staged intelligence gets promoted into Trade AI production surfaces, with full provenance, rollback, and operator review gates.

## Safe Promotion Principles

1. Hermes intelligence is advisory — it cannot trigger execution
2. Every promoted row carries `source='hermes'` provenance
3. Promotion requires operator review (dry-run → approve → apply)
4. Promoted rows are reversible via hermes_promotion_audit
5. Promotion never targets execution/mutation tables

## Recommended First Target: `llm_intelligence_cache`

| Attribute | Value |
|-----------|-------|
| Table | llm_intelligence_cache |
| Safety | HIGH — advisory cache, no execution trigger |
| Mechanism | Namespaced sections: `hermes_{research_type}_{symbol}` |
| Collision risk | LOW — unique section names |
| Reversibility | HIGH — DELETE by section name |
| Dashboard visibility | Existing LLM intelligence surfaces can show it |

### Why llm_intelligence_cache

- Already used for advisory LLM outputs (portfolio risk, rebalance suggestions, etc.)
- Has `section`, `content`, `metadata` fields — maps cleanly from Hermes
- No execution triggers read from this table
- Namespaced `hermes_*` section names prevent collision

## Eligible Source Rows

| Criterion | Value |
|-----------|-------|
| source | 'hermes' |
| status | 'staged' |
| confidence_score | >= 0.3 |
| model_used | local (gemma3:12b) |
| evidence_json | present |
| limitations | present |
| symbol or topic | populated |
| not smoke/test | true |
| not rejected | true |

**Result: 10/11 eligible, 1 rejected (TELO id=9, confidence 0.2)**

## Forbidden Targets

| Table | Reason |
|-------|--------|
| paper_trade_proposals | Execution table |
| paper_trades | Execution table |
| trade journal tables | Execution table |
| holdings | Portfolio state |
| broker_* tables | Broker state |
| accounts | Account state |
| system_controls | System config |
| personal_* tables | Sensitive data |

## Mapping Rules

```
hermes_research_intelligence → llm_intelligence_cache
  section = "hermes_{research_type}_{symbol}"
  content = "[Hermes Advisory] {summary}" 
  metadata = {"source": "hermes", "source_id": id, "confidence": score, "research_type": type}
  generated_at = NOW()
```

## Promotion Workflow

```
hermes_research_intelligence (status=staged)
  → operator selects rows for promotion
  → promotion script --dry-run
  → operator reviews dry-run output
  → promotion script --apply
  → INSERT into llm_intelligence_cache
  → INSERT into hermes_promotion_audit
  → UPDATE hermes_research_intelligence SET status='promoted'
```

## Rollback Strategy

```sql
-- Delete promoted rows from target
DELETE FROM llm_intelligence_cache WHERE section LIKE 'hermes_%';

-- Reset source rows
UPDATE hermes_research_intelligence SET status='staged', promoted_to_table=NULL, promoted_to_id=NULL
WHERE status='promoted';

-- Delete audit records
DELETE FROM hermes_promotion_audit WHERE source_table='hermes_research_intelligence';
```

## Phase 4 Approval Gates

| Gate | Scope | Status |
|------|-------|--------|
| **4A** | Architecture + dry-run (this) | COMPLETE |
| **4B** | First capped promotion (≤3 rows) | NOT APPROVED |
| **4C** | Dashboard visibility of promoted content | NOT APPROVED |
| **4D** | Ongoing promotion automation | NOT APPROVED |

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Promoted content misleads operator | LOW | Advisory badge, provenance in metadata |
| Cache section collision | LOW | Unique namespaced sections |
| Bulk promotion floods cache | LOW | Row cap per promotion batch |
| Rollback incomplete | LOW | Promotion audit tracks every row |
