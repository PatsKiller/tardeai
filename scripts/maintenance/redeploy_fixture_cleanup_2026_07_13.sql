-- ============================================================================
-- PROPOSED CLEANUP — phase_e test-fixture pollution (P0 audit 2026-07-13)
-- STATUS: NOT EXECUTED. Requires explicit operator approval before running.
-- Companion audit: docs/audits/REDEPLOY_FIXTURE_AUDIT_2026-07-13.md
-- Companion JSON-bus cleaner: scripts/maintenance/redeploy_fixture_cleanup_outcome_bus.py
--
-- What happened: tests/test_redeploy_phase_e.py::test_idempotent_record_fill
-- committed real fills against live event 144 (FCNTX $107,023 sale) on every
-- run. Three runs on 2026-07-13 23:19–23:23 ET left synthetic evidence in
-- seven database locations plus the JSON outcome bus.
--
-- The rows are already QUARANTINED (environment='test' via migration
-- 2026_07_19_redeploy_data_integrity.sql) and excluded from all metrics.
-- This transaction performs the permanent deletion and resets the test
-- mutations on event 144 / plan 8.
--
-- Run inside a single transaction. Verify each pre-count before COMMIT.
-- ============================================================================

BEGIN;

-- Pre-verification (expected counts in comments):
-- SELECT count(*) FROM redeploy_stage_fills WHERE id IN (1,2,3) AND evidence_note='phase_e test fixture';  -- 3
-- SELECT count(*) FROM redeploy_monitor_snapshots WHERE id IN (1,2,3) AND deploy_event_id=144;             -- 3
-- SELECT count(*) FROM redeploy_monitor_audit WHERE id IN (1,2,3,4,5) AND deploy_event_id=144;             -- 5
-- SELECT count(*) FROM hermes_outcome_ledger WHERE id IN (77573,77574,77575) AND subject_type='redeploy_fill' AND verdict='pending';  -- 3
-- SELECT count(*) FROM deploy_oversight_runs WHERE id IN (1,2) AND deploy_event_id=144;                    -- 2

-- 1. Synthetic fills (quarantined environment='test', notes 'phase_e test fixture')
DELETE FROM redeploy_stage_fills
WHERE id IN (1, 2, 3)
  AND deploy_event_id = 144
  AND evidence_note = 'phase_e test fixture'
  AND idempotency_key LIKE 'test-%';

-- 2. Monitor snapshots derived from those fills (restoration 1.0/2.0/3.0 %)
DELETE FROM redeploy_monitor_snapshots
WHERE id IN (1, 2, 3)
  AND deploy_event_id = 144;

-- 3. Audit rows for the test actions (3× record_fill, 1× test lock, 1× oversight
--    triggered by the test lock). Full row content preserved in the audit doc.
DELETE FROM redeploy_monitor_audit
WHERE id IN (1, 2, 3, 4, 5)
  AND deploy_event_id = 144
  AND (idempotency_key LIKE 'test-%' OR action = 'oversight');

-- 4. Hermes outcome ledger entries emitted by the synthetic fills
--    (still verdict='pending' — never graded, never fed learning).
DELETE FROM hermes_outcome_ledger
WHERE id IN (77573, 77574, 77575)
  AND subject_type = 'redeploy_fill'
  AND verdict = 'pending';

-- 5. Oversight runs triggered by the test lock_plan call
DELETE FROM deploy_oversight_runs
WHERE id IN (1, 2)
  AND deploy_event_id = 144;

-- 6. Reset the test lock + oversight verdict on plan 8 (F v2)
UPDATE deploy_plans
SET locked_at = NULL,
    locked_by = NULL,
    oversight_status = 'pending'
WHERE id = 8
  AND deploy_event_id = 144;

-- 7. Reset event 144 test mutations: unlock, back to open review state,
--    strip phase_e fill metadata (fill_count / restoration_pct / last_fill_at).
UPDATE deploy_events
SET operator_status = 'open',
    locked_plan_id = NULL,
    locked_plan_version = NULL,
    plan_locked_at = NULL,
    metadata = metadata - 'phase_e',
    updated_at = NOW()
WHERE id = 144;

-- Post-verification before COMMIT:
-- SELECT count(*) FROM redeploy_stage_fills WHERE deploy_event_id=144;        -- 0
-- SELECT count(*) FROM redeploy_monitor_snapshots WHERE deploy_event_id=144;  -- 0
-- SELECT operator_status, locked_plan_id, metadata ? 'phase_e' FROM deploy_events WHERE id=144;  -- open | NULL | f
-- SELECT locked_at, oversight_status FROM deploy_plans WHERE id=8;            -- NULL | pending

COMMIT;
