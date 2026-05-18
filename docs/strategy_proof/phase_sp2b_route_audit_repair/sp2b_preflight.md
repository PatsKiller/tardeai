# SP-2B Preflight

**Date:** 2026-05-18
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,193,001

## Root Cause Summary

Neither auto_proposal_generator.py nor incubator_proposal_promoter.py calls
multi_setup_router.store_setup_matches() when creating proposals.

### Code Paths

1. **auto_proposal_generator.py:527-611** — Creates proposals from signals. Does NOT
   call multi_setup_router. Uses signal's strategy_id directly.

2. **incubator_proposal_promoter.py:604-626** — Creates proposals from incubator.
   Does NOT call multi_setup_router. Uses incubator's strategy_id directly.

3. **multi_setup_router.py:274-298** — store_setup_matches() exists but is only
   called from --pending-proposals manual mode. Not in the creation pipeline.

4. **strategy_signal_sync.py:437-606** — Creates signals (not proposals). Does
   call route_candidate_to_strategies for signals, but this data is not transferred
   when proposals are later created from those signals.

### Why strategy_id='screener' exists

Some proposals inherit strategy_id from screener source metadata rather than
from YAML strategy evaluation. This is a fallback/default path issue.

### Fix Available

After create_auto_proposal() returns proposal_id, call:
  route_symbol(signal, configs) → store_setup_matches(conn, symbol, proposal_id, ...)

Similarly in incubator_promoter after INSERT.

SP-2B will NOT make this fix to the creation pipeline (that's SP-2C).
SP-2B will backfill existing proposals and add readiness blockers.
