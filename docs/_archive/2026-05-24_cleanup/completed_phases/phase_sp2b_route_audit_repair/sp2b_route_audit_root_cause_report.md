# Route Audit Root Cause Report

83 proposals, 74 missing route audit (89.2%)

## Root Causes

### auto_proposal_generator does not call multi_setup_router
- Evidence: auto_proposal_generator.py exists=True, calls_router=False
- Path: screener → signal → proposal

### incubator_proposal_promoter does not call multi_setup_router
- Evidence: incubator_proposal_promoter.py exists=True, calls_router=False
- Path: incubator → proposal

### multi_setup_router.store_setup_matches only runs in manual --pending-proposals mode
- Evidence: store_setup_matches is never called from proposal creation pipeline
- Path: all proposal creation paths

## Recommended Fix

Call route_symbol + store_setup_matches after proposal INSERT in both auto_proposal_generator and incubator_proposal_promoter (SP-2C)