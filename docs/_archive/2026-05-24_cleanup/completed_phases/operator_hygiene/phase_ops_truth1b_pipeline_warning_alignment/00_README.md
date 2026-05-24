# OPS-TRUTH-1B — Pipeline Warning Alignment

**Status:** COMPLETE

## Fixes

1. **Never-run stages now count as warnings**: Stages with no pipeline_runs record and cadence < 168h are amber/warning, not gray/uncounted.

2. **Last full cycle timestamp fixed**: Was showing current time (`now`), now shows actual latest pipeline run timestamp or "No runs recorded".

3. **Frontend shows richer summary**: Shows warning count and never-run count instead of just "waiting for schedule".

## Tests

7/7 pass. Frontend built 199ms.
