# ROOT CAUSE MATRIX — Command Center Reliability Fix (2026-05-23)

Status:      HISTORICAL
as_of:       2026-05-23T21:05:52-04:00
Measured at: efcc51365 / not measured

## Builds on prior data integrity fixes (commit 3a8de84)

This round focuses on operational reliability: false-green pipeline, data product freshness, alert taxonomy, and system health visibility.

## P0 Fixes

| # | Issue | Root Cause | Fix | File:Line |
|---|-------|-----------|-----|-----------|
| 1 | False-green pipeline health | Never-run stages marked green on weekends | Never-run is now always gray/amber, never green | api_v2.py:14578-14587 |
| 2 | No data product freshness checker | No script to verify dashboard data SLAs | Created check_data_product_freshness.py with 19 product checks | scripts/check_data_product_freshness.py |
| 3 | System health missing freshness | system-health endpoint only checked services | Added data_freshness summary to system-health response | api_v2.py:5099 |
| 4 | Alerts missing system alerts | Alerts only showed trading events from DB | Added synthetic stale-data alerts when holdings/risk are stale | api_v2.py:3144 |

## P1 Fixes

| # | Issue | Root Cause | Fix | File:Line |
|---|-------|-----------|-----|-----------|
| 5 | Topic Monitor vs Research Topics contradiction | Different tables (topic_monitor vs user_research_topics) | Added cross-reference note and topic_monitor_count to research-topics endpoint | api_v2.py:11784 |
| 6 | Agent Calibration misleading 0% | Empty table shows 0 accuracy without explanation | Added insufficient_sample flag and explanatory note | api_v2.py:10377 |
| 7 | WebSocket console error | Browser logs connection refused even with JS fallback | Added HTTP probe before WS connection attempt | ScalpLiveFeed.tsx:103 |

## Previously Fixed (commit 3a8de84)

| # | Issue | Status |
|---|-------|--------|
| B | Attribution phantom "258" | FIXED |
| D | Rebalance income $0/$0 | FIXED |
| F | CIO decisions duplicates | FIXED |
| A | Snapshot source labels | FIXED |
| E | Retirement snapshot delta | FIXED |
| N | AI Analyst staleness | FIXED |

## Deferred to Future Sessions

| # | Issue | Reason |
|---|-------|--------|
| Route duplication (governance/journal/paper-*) | UX/IA decision requiring operator input on page purposes |
| Technical page enhancement | Feature addition, not reliability fix |
| Weekly learning scheduler | Needs operator decision on cadence |
| Incubator promotion diagnostics UI | Needs frontend component work |
| Paper proposals stale-quote alerting | Auto-enrichment pipeline already handles this |
| ENTRY_MISSED root cause table | Enhancement to existing working lifecycle |
| Reports Finviz images | External service issue, needs policy decision on proxying |

## Data Product Freshness Registry

See DATA_PRODUCT_FRESHNESS_REGISTRY.md for full registry of 20+ data products with:
- Owner script, schedule, max stale age
- Source table/file
- Downstream pages affected
- Operator remediation command
