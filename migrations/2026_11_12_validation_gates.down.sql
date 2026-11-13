-- Down for 2026_11_12_validation_gates.sql. Nothing else reads this table except GET /api/v2/home/gates.
BEGIN;
DROP TABLE IF EXISTS validation_gates;
COMMIT;
