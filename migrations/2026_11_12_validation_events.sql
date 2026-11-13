-- validation_events — change events with FIXED / FIXED_UNPROVEN / MONITORING (LQ-20261107-2143).
-- DDL per HOME-BACKEND-SPEC-20261111 sec 2143. dedupe_key makes every write idempotent: a re-run of the same
-- window inserts nothing. Gate transitions are written by validation-gates-sync (2141); incident and lane
-- flips by home-change-events. LQ-2413 adds: waived, monitoring (a fix was recorded on an open gate), proven
-- (the proof window ended without a regress: label FIXED), refused (a declaration was refused; source_kind
-- 'declaration', deduped on the file's sha256 so a refusal is visible once, not every five minutes).
BEGIN;
CREATE TABLE IF NOT EXISTS validation_events (
  event_id         BIGSERIAL PRIMARY KEY,
  dedupe_key       TEXT NOT NULL UNIQUE,
  source_kind      TEXT NOT NULL CHECK (source_kind IN ('gate','incident','lane','data','declaration')),
  source_id        TEXT NOT NULL,
  category         TEXT NOT NULL,
  transition       TEXT NOT NULL CHECK (transition IN ('opened','regressed','resolved','passed','failed','overdue','recovered','waived','monitoring','proven','refused')),
  label            TEXT CHECK (label IN ('FIXED','FIXED_UNPROVEN','MONITORING')),
  proof_window_end TIMESTAMPTZ,
  occurred_at      TIMESTAMPTZ NOT NULL,
  detected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  relabeled_at     TIMESTAMPTZ,
  summary          TEXT NOT NULL,
  owner            TEXT,
  evidence         JSONB NOT NULL DEFAULT '{}',
  run_id           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS validation_events_time_idx ON validation_events (occurred_at DESC);
COMMIT;
