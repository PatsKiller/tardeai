-- Hermes Phase 29 Rollback — Remove safe views for journal/backtest/screener/catalyst
-- Date: 2026-06-01

BEGIN;

REVOKE SELECT ON hermes_v_journal_learning_context FROM hermes_readonly;
REVOKE SELECT ON hermes_v_backtest_results_context FROM hermes_readonly;
REVOKE SELECT ON hermes_v_screener_context FROM hermes_readonly;
REVOKE SELECT ON hermes_v_catalyst_quality_context FROM hermes_readonly;

DROP VIEW IF EXISTS hermes_v_journal_learning_context;
DROP VIEW IF EXISTS hermes_v_backtest_results_context;
DROP VIEW IF EXISTS hermes_v_screener_context;
DROP VIEW IF EXISTS hermes_v_catalyst_quality_context;

COMMIT;
