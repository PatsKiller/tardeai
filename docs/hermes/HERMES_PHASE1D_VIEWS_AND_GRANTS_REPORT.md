# Hermes Phase 1D: Safe Views and Read Grants — 2026-05-30

Status:      HISTORICAL
as_of:       2026-05-30T17:43:12-04:00
Measured at: efcc51365 / not measured

## Status: APPLIED

## Views Created (8)
| View | Rows | Source Tables |
|------|------|---------------|
| hermes_v_ticker_context | 33,625 | ticker_snapshot_daily + intelligence_entities + fused_signals |
| hermes_v_proposal_context | 145 | paper_trade_proposals (account masked to type) |
| hermes_v_trade_reflection_context | 157 | paper_trades + trade_closed (account masked) |
| hermes_v_news_research_context | 4,994 | news_articles (raw_payload excluded) |
| hermes_v_agent_results_context | 9,006 | watchlist_agent_results (raw_response excluded) |
| hermes_v_pipeline_health_context | 2,973 | pipeline_runs + pipeline_definitions |
| hermes_v_rag_context_metadata | 25,979 | content_embeddings (embedding vector excluded) |
| hermes_v_portfolio_context | 13 | stopped_out_watch (account masked) |

## Security Measures
- Account names masked to types: IRA / Roth / 401k / Taxable
- Large blobs excluded: raw_payload, raw_response, embedding vectors, tfidf_terms
- Credentials never exposed
- Views are read-only (no INSERT/UPDATE/DELETE)

## Grants Applied
- 8 view grants to `hermes_readonly`
- 32 direct table grants to `hermes_readonly` (tables with no sensitive columns)
- All grants are SELECT only

## Fix Applied
- `hermes_v_pipeline_health_context` had column name mismatch (`pipeline_id` → `pipeline_key`, `completed_at` → `finished_at`). Fixed in SQL draft and re-created.

## Rollback
```sql
-- Drop views
DROP VIEW IF EXISTS hermes_v_ticker_context CASCADE;
DROP VIEW IF EXISTS hermes_v_proposal_context CASCADE;
DROP VIEW IF EXISTS hermes_v_trade_reflection_context CASCADE;
DROP VIEW IF EXISTS hermes_v_news_research_context CASCADE;
DROP VIEW IF EXISTS hermes_v_agent_results_context CASCADE;
DROP VIEW IF EXISTS hermes_v_pipeline_health_context CASCADE;
DROP VIEW IF EXISTS hermes_v_rag_context_metadata CASCADE;
DROP VIEW IF EXISTS hermes_v_portfolio_context CASCADE;

-- Revoke grants (run as table owner or superuser)
-- REVOKE SELECT ON <table> FROM hermes_readonly;
-- (full list in HERMES_PHASE1C_READ_GRANT_DRAFTS.sql)
```

## Safety
- No production tables modified
- No INSERT/UPDATE/DELETE grants
- No credential exposure
- No trade execution impact
- Gateway online: http://127.0.0.1:18790/health → ok
