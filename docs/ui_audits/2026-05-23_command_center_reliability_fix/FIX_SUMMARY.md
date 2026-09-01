# Command Center Reliability Fix Summary (2026-05-23)

Status:      HISTORICAL
as_of:       2026-05-23T21:05:52-04:00
Measured at: efcc51365 / not measured

## Scope
Full-prompt implementation of 15-theme visual audit findings. Builds on prior data integrity fixes (commit 3a8de84).

## Fixes Implemented This Round

### P0 — False-Green Pipeline Health
- **Before:** Never-run stages marked "green" on weekends (30/31 healthy)
- **After:** Never-run stages are always gray/amber (0/31 healthy on weekend with no recent runs)
- **File:** api_v2.py pipeline-health-master, lines 14578-14587

### P0 — Data Product Freshness Registry
- Created `DATA_PRODUCT_FRESHNESS_REGISTRY.md` with 20+ products
- Created `scripts/check_data_product_freshness.py` — automated checker with 19 product checks
- Checks files, DB tables, API endpoints, pipeline health, agent queue backlog, CIO dedup
- Output: PASS/WARN/FAIL per product with age, max stale hours, remediation commands

### P1 — System Health Freshness
- **Before:** system-health endpoint only checked LLM and table counts
- **After:** Includes data_freshness summary (X/5 fresh, Y stale) with per-product breakdown
- **File:** api_v2.py _system_health_dashboard()

### P1 — Alerts Missing System Alerts
- **Before:** Alerts page only showed trading events from DB (0 alerts in 24h despite stale data)
- **After:** Synthetic stale-data alerts injected when holdings/risk are stale, agent queue > 50
- **File:** api_v2.py _alerts() + _generate_stale_data_alerts()
- **Fix:** Also renamed `_alerts` local variable collision (line 15650) that caused UnboundLocalError

### P1 — Topic Monitor vs Research Topics
- **Before:** Research Topics said "no active topics" while Topic Monitor showed 17
- **After:** Research Topics endpoint includes `topic_monitor_count` and explanatory note
- **File:** api_v2.py research-topics endpoint

### P1 — Agent Calibration Misleading Zeros
- **Before:** All metrics showed 0% accuracy without explanation
- **After:** `insufficient_sample` flag and explanatory note when calibration data is empty
- **File:** api_v2.py _agent_calibration()

### P2 — WebSocket Console Error
- **Before:** Browser logged connection refused on ws://localhost:7778 every page load
- **After:** HTTP probe before WS connection attempt — no WS attempt if API unreachable
- **File:** apps/command-center-v2/src/components/ScalpLiveFeed.tsx

## Previously Fixed (commit 3a8de84)
- B: Attribution phantom "258" filtered
- D: Rebalance income $0 → $14,408
- F: CIO decisions deduplicated
- A: Snapshot source labels on 3 endpoints
- E: Retirement snapshot delta
- N: AI Analyst staleness indicator

## Deferred Items
| Item | Reason |
|------|--------|
| Route duplication (governance/journal/paper-*) | UX/IA decision |
| Technical page enhancements | Feature addition |
| Weekly learning scheduler | Ops decision |
| Incubator promotion diagnostics UI | Frontend component work |
| ENTRY_MISSED root cause table | Enhancement |
| Reports Finviz images | External service policy |
| Rebalance stale-input blocking | Requires freshness gating at recommendation layer |
| Tax-loss harvesting → AI Analyst | Enhancement |

## Test Results

### Consistency Check: 0 FAIL
```
PASS: 9  WARN: 1  FAIL: 0
```

### Freshness Check: Reflects Real State
```
PASS: 2  WARN: 7  FAIL: 10
```
(10 FAILs are genuine — weekend, no market data refresh, some tables empty)

### Playwright: 65/65 OK
```
OK: 65  Timeout: 0  Error: 0  Skipped: 2  Console errors: 2
```
(2 console errors: trade-ai WS — reduced by probe but browser may still log; reports Finviz — deferred)

### Frontend Build: Clean
```
✓ built in 257ms
```
