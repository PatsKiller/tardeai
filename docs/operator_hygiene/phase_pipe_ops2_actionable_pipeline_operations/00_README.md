# PIPE-OPS-2 — Actionable Pipeline Operations

**Status:** COMPLETE

## What Was Delivered

1. **Stage owner map** (`pipeline_stage_owner_map.py`): 31 stages with ownership metadata — owning script, wrapper, cron pattern, log paths, output tables, dry-run command, failure hint, operator action.

2. **Actionability audit**: 6 ACTIONABLE, 23 PARTIALLY_ACTIONABLE, 2 ON_DEMAND. Never-run subtypes: 13 waiting_for_schedule, 16 cron_missing, 2 on_demand.

3. **API enrichment**: Each stage in pipeline-health-master now returns owner_script, cron_pattern, output_tables, recommended_action, never_run_subtype, failure_hint.

4. **Frontend enhancement**: Expanded detail drawer shows owner, cron pattern, output tables, never-run reason (highlighted), recommended action (blue), failure hint.

5. **No unsafe buttons**: Execution stages (risk_gate, alpaca_paper) cannot be run from Pipeline Operations.

## Tests

13/13 pass. Frontend built 208ms.
