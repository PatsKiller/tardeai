-- LQ-20261107-2148 rollback. Only the lane-health-snapshot lane writes this table and only
-- GET /api/v2/home/schedulers (not built yet) reads it. Operator/lead act; archive first
-- (\copy lane_health_current TO '<archive>.csv' CSV HEADER) per AGENTS.md rule 6.
BEGIN;
DROP TABLE IF EXISTS lane_health_current;
COMMIT;
