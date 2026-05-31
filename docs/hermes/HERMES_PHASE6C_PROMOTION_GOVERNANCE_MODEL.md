# Hermes Phase 6C — Promotion Governance Model

**Date:** 2026-05-31
**Status:** GOVERNANCE RULES ONLY

---

## Core Rule

**Hermes promotion must remain manually approved and capped until a future explicit phase approves automation. No autonomous loop may promote directly to production targets.**

---

## Promotion Tiers

| Tier | Description | Approval | Current Status |
|------|-------------|----------|----------------|
| 1. Staged | Research in hermes_research_intelligence | Automatic (via ingestion script) | ACTIVE |
| 2. Embedded | In content_embeddings for RAG retrieval | Manual batch (embedding worker) | ACTIVE (7 rows) |
| 3. Promoted Advisory | In llm_intelligence_cache as advisory | Manual capped batch | ACTIVE (7 rows) |
| 4. Dashboard-Visible | Shown on Hermes Intelligence page | Automatic (reads staging + promoted) | ACTIVE |
| 5. Operator-Reviewed | Flagged for operator action | Manual | NOT YET |
| 6. Production Decision Input | Influences proposal/trade decisions | NOT APPROVED | FUTURE ONLY |

## Allowed Promotion Targets

| Target | Tier | Safety |
|--------|------|--------|
| llm_intelligence_cache (hermes_* sections) | 3 | HIGH — advisory only |
| content_embeddings (hermes_research) | 2 | HIGH — RAG, no execution trigger |
| agent_intelligence_rules (hermes_* rule_type) | 3 | MEDIUM — namespaced |
| research_insights (source_type=hermes) | 3 | MEDIUM — if provenance clear |

## Forbidden Promotion Targets

| Target | Reason | Permanently Forbidden? |
|--------|--------|----------------------|
| paper_trade_proposals | Execution pathway | YES |
| paper_trades | Execution state | YES |
| trade journal tables | Trade record | YES |
| holdings | Portfolio state | YES |
| broker_* tables | Broker state | YES |
| accounts / account_* | Account state | YES |
| system_controls | System config | YES |
| personal_* tables | Sensitive data | YES |

## Auto-Promotion Prohibition

- **NO** autonomous loop may INSERT into production targets
- **NO** timer/cron may run promotion scripts with --apply
- **NO** Hermes agent may change row status to 'promoted' without operator review
- **NO** Hermes finding may auto-create a proposal or trade instruction
- All promotions require: dry-run → operator review → --apply

## Audit Requirements

Every promotion must create a `hermes_promotion_audit` record with:
- source_table, source_id
- target_table, target_id
- promotion_type
- approved_by (must be 'operator')
- rollback_sql

## Rollback Requirements

Every promotion batch must have:
- Exact DELETE SQL for promoted rows
- Exact UPDATE SQL to reset source row status
- Exact DELETE SQL for audit records
- Documented in docs/hermes/

---

## Governance Review Schedule

| Review | Frequency | Scope |
|--------|-----------|-------|
| Daily operator check | Daily | journalctl + row count |
| Weekly quality review | Weekly | Review 7-day staged rows |
| Monthly promotion review | Monthly | Review all promoted content freshness |
| Quarterly governance audit | Quarterly | Full drift + safety audit |
