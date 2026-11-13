-- validation_gates — the Home "Pending validations" system of record (LQ-20261107-2141 / 2413).
-- DDL per HOME-BACKEND-SPEC-20261111 sec 2141, extended by LQ-2413 (source, fix_ref, label, proof window,
-- board_probe, tri-state blocks_trading). Written ONLY by the n8n lane validation-gates-sync; the endpoint
-- GET /api/v2/home/gates only reads. Additive and idempotent. Hand-applied (psql -f, SET ROLE trade_ai) by the
-- operator / lead; never by a worker.
-- The CHECKs are the last line of defence: PASSED/WAIVED need closed_at, WAIVED is operator-only, a
-- manual_evidence gate cannot be closed by the agent that declared it (no self-certification), and a label
-- cannot contradict the status (FIXED needs a recorded proof time; MONITORING needs a recorded fix).
-- blocks_trading NULL means "not declared": a reader must treat it as unknown, never as false.
BEGIN;
CREATE TABLE IF NOT EXISTS validation_gates (
  gate_id           TEXT PRIMARY KEY,
  title             TEXT NOT NULL,
  category          TEXT NOT NULL,
  lq_id             TEXT,
  source            TEXT NOT NULL DEFAULT 'declaration' CHECK (source IN ('declaration','board')),
  status            TEXT NOT NULL CHECK (status IN ('OPEN','OVERDUE','FAILED','PASSED','WAIVED')),
  blocks            TEXT NOT NULL,
  blocks_trading    BOOLEAN,
  due_at            TIMESTAMPTZ,
  opened_at         TIMESTAMPTZ NOT NULL,
  closed_at         TIMESTAMPTZ,
  owner             TEXT NOT NULL,
  declared_by       TEXT NOT NULL,
  closed_by         TEXT,
  check_kind        TEXT NOT NULL CHECK (check_kind IN ('lane_fresh','db_max','incident_absent','sql_threshold','manual_evidence','board_probe')),
  check_spec        JSONB NOT NULL DEFAULT '{}',
  evidence          JSONB NOT NULL DEFAULT '[]',
  fix_ref           TEXT,
  label             TEXT CHECK (label IN ('FIXED','FIXED_UNPROVEN','MONITORING')),
  proof_window_end  TIMESTAMPTZ,
  proven_at         TIMESTAMPTZ,
  last_evaluated_at TIMESTAMPTZ,
  last_eval_result  TEXT CHECK (last_eval_result IN ('PASS','FAIL','ERROR','NOT_EVALUABLE')),
  last_eval_detail  JSONB,
  decl_path         TEXT,
  decl_sha256       TEXT,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (status NOT IN ('PASSED','WAIVED') OR closed_at IS NOT NULL),
  CHECK (status <> 'WAIVED' OR closed_by = 'operator'),
  CHECK (check_kind <> 'manual_evidence' OR closed_by IS NULL OR closed_by <> declared_by),
  CHECK (label IS NULL OR label NOT IN ('FIXED','FIXED_UNPROVEN') OR status = 'PASSED'),
  CHECK (label IS NULL OR label <> 'FIXED' OR proven_at IS NOT NULL),
  CHECK (label IS NULL OR label <> 'MONITORING' OR (status IN ('OPEN','OVERDUE','FAILED') AND fix_ref IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS validation_gates_open_idx ON validation_gates (blocks_trading DESC, due_at)
  WHERE status IN ('OPEN','OVERDUE','FAILED');
COMMIT;
