-- LQ-20261107-264 — agent_performance_history had no key over (agent, period_start, period_end).
--
-- Both writers inserted blindly: scripts/overnight_batch.py::record_agent_performance (Sunday, 7-day
-- window) and scripts/update_agent_performance.py (daily, 30-day window). Six duplicate rows remain for
-- the same period, each pair written 15 minutes apart on 2026-05-31 21:15:02 / 21:30:03 ET
-- (ids 11..22, agents iris, maria, maria_research, risk_agent, steph, tax_agent).
--
-- The Python writers now update-or-insert under a per-period advisory lock, so this lane cannot add a
-- duplicate. The unique index below is the guarantee for anything else that writes the table (a manual
-- INSERT, a future writer) — and it cannot be created until the existing duplicates are gone.
--
-- OPERATOR / LEAD ONLY. Nothing applies migrations automatically; this file is a proposal, not a run.
-- Rule 6: the DELETE removes only a row that duplicates its group's key. The surviving row is the one
-- with the highest id, i.e. the newest snapshot of the same period (the pairs differ only in counts taken
-- 15 minutes apart). Dry-run first — the SELECT in the DONE note names every id that would go.

BEGIN;

-- 1. Keep the newest row per (agent, period_start, period_end); drop only exact-key duplicates.
DELETE FROM agent_performance_history a
 USING agent_performance_history b
 WHERE a.agent = b.agent
   AND a.period_start = b.period_start
   AND a.period_end = b.period_end
   AND a.id < b.id;

-- 2. Make a second row for the same agent and period impossible. NULLs in any key column stay distinct
--    (standard UNIQUE semantics); both writers always supply all three, so a NULL-key row is an anomaly
--    worth seeing rather than silently folding into a real period.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_performance_history_period
    ON agent_performance_history (agent, period_start, period_end);

COMMIT;
