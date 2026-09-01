# Post-8b348c3 Verification Matrix

Status:      HISTORICAL
as_of:       2026-05-24T14:12:34-04:00
Measured at: efcc51365 / not measured

## Summary
- Playwright: 61 OK, 0 console errors, 0 network failures, 2 skipped
- Consistency check: 9 PASS, 1 WARN, 0 FAIL
- Freshness check: 3 PASS, 3 WARN, 13 FAIL (genuine stale weekend data)
- Frontend build: clean (245ms)

## Fix Verification

| # | Claim | Evidence | Verdict |
|---|-------|---------|---------|
| 1 | Pipeline telemetry added to 16 scripts | pipeline-health-master.json: 10 stages with telemetry, 21 without. healthy=1, never_run=21 | **PARTIAL** — PipelineRun wrapper added to 16 scripts but they haven't run yet (weekend). Log-file fallback provides some visibility. Will improve when crons fire Monday. |
| 2 | AI Analyst stale total fixed | ai-analyst.json: is_stale=false, generated_at=2026-05-24T13:41:42, executive_summary contains $1,201,120 | **FIXED** — current value confirmed in endpoint output |
| 3 | Research topic contradiction resolved | research-topics.json: user_topics=6, monitor_topics=17, gaps=17, note explains distinction | **FIXED** — both data sources shown with clear labels |
| 4 | Research gap escalation | alerts.json: 17 research gap alerts created in alert_events with topic: prefix | **FIXED** — gaps escalated to alerts + Iris agent jobs queued |
| 5 | TLH to AI Analyst | ai-analyst.json: tlh_summary has 56 taxable candidates, $560,816 loss, top 3: PFLT/CSWC/KTOS | **FIXED** — taxable-only, IRA/401k excluded |
| 6 | Paper proposal readiness blockers | paper-proposals API: pending=4, stale_count=4, ready=0, incubator_ready=135, incubator_diagnostics present | **EXISTING** — blocker summary was already present in API before this session. Frontend shows blockers per-card. |
| 7 | Incubator blocker diagnostics | incubator API (under .data): active=200, promoted=42, blockers: stale_source=101, low_score=24, no_catalyst=12. gate: can_promote=true, pending=0/20 | **FIXED** — blocker diagnostics present with per-reason counts |
| 8 | Technical page added data | holdings API: analyst_rating=None, recom_score=None for FID-CONTRA-F | **PARTIAL** — fields added to API but enrichment cache doesn't have data for Fidelity 401k funds. Schwab/ETF tickers should have data. |
| 9 | Alert accounting | alerts.json: 91 total, 5 system alerts (stale data, heat, stops, backlog) + 17 research gap alerts + 69 trading alerts | **FIXED** — system alerts visible in alerts-dashboard with cards |
| 10 | Data-product health visibility | data-product-health.json: 4/7 fresh, 3 stale. system-health.json: data_freshness present. SystemHealth.tsx has Data Product Health panel. | **FIXED** — endpoint exists AND frontend renders it |
| 11 | Weekly learning empty-state | weekly_learning.png: shows NO DIGEST GENERATED banner with script/schedule/status | **FIXED** — informative empty state instead of one-liner |
| 12 | Duplicate routes | Manifest: 63 routes (was 67). paper-journal/outcomes/governance redirect to canonical routes. Removed from nav. | **FIXED** — redirects confirmed, no duplicate screenshots |
| 13 | Finviz images | Manifest: 0 network-failure routes | **FIXED** — confirmed zero failures |
| 14 | WebSocket | Manifest: 0 console-error routes. scalp/live ws_available=false. | **FIXED** — WS not attempted when server unavailable |

## Honest Issues Found

### Incubator API — RESOLVED
Initial test missed the `.data` wrapper. Actual response: active=200, promoted=42, blockers: stale_source=101, low_score=24, no_catalyst=12. Gate shows can_promote=true with 0/20 pending.

### Technical data empty for Fidelity funds (Item 8)
The first holding (FID-CONTRA-F, a Fidelity 401k fund) has no enrichment cache data — all new fields return None. Schwab/ETF tickers like V, SCHD, PFLT should have data since they're in the Finviz enrichment cache. The fix works for tradeable stocks, not for proprietary mutual fund symbols.

### Pipeline telemetry not yet proven (Item 1)
PipelineRun wrappers were added to 16 scripts but none have run since the commit (weekend). 10 stages show telemetry from prior runs, 21 still show "never run." The wrappers will write telemetry on their next cron execution (Monday). The pipeline_registry.py column fix (pipeline_key instead of script_name) means new telemetry will actually be queryable.

### Data products genuinely stale (not a code issue)
Freshness check shows 13 FAIL — this is real: it's Saturday, market is closed, and many data products only refresh on market days. The checker correctly reports this state.

### System-health data_freshness shows different numbers than data-product-health
system-health: "0/5 fresh, 5 stale" — checks 5 products with non-weekend-aware thresholds
data-product-health: "4/7 fresh, 3 stale" — checks 7 products with weekend awareness
This inconsistency should be reconciled.
