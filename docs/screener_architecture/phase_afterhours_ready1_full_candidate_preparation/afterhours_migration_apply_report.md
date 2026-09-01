# Migration: afterhours readiness tables

Status:      ACTIVE
as_of:       2026-05-19T21:01:07-04:00
Measured at: efcc51365 / not measured

Mode: **apply**

Table `afterhours_candidate_snapshot` existed: False

Table `afterhours_readiness_run` existed: False

## Actions
| Type | Object | Detail |
|------|--------|--------|
| create_table | afterhours_candidate_snapshot | executed |
| create_table | afterhours_readiness_run | executed |
| create_index | idx_acs_symbol | executed |
| create_index | idx_acs_readiness_status | executed |
| create_index | idx_acs_run_date | executed |
| create_index | idx_acs_top_strategy | executed |