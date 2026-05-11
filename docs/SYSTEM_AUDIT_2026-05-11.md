# Trade AI v12 — Full System Audit Report
**Date:** 2026-05-11 | **Session:** 29 | **Standard:** Zero bias, grounded observations only

---

## I. System Scale (Verified)

| Dimension | Count |
|-----------|-------|
| Frontend pages (React routes) | 61 (all implemented, no stubs) |
| API endpoints | 271 (246 in api_v2.py + 21 in portfolio_server.py + 4 shared) |
| Telegram-sending scripts | 55+ (100+ unique send call sites) |
| Notification types in DB | 8 |
| Database tables | 300 |
| Cron jobs | 143 |
| Python scripts | 355 |

---

## II. Command Center Pages — Consolidation Candidates

### Pages That Should Be Merged

| Merge Target | Pages to Combine | Rationale |
|--------------|------------------|-----------|
| Portfolio Command | Portfolio + Portfolio Monitor + Portfolio Intelligence | One page with tabs. Three pages for the same positions. |
| Trade Journal | Journal + Journal Analytics + Journal Reports | One page with tabs. Three pages for trade review. |
| Paper Trading | Paper Outcomes + Paper Trade Intelligence + Paper Journal | One page with tabs. Three views of closed paper trades. |
| Pipeline Ops | Pipeline Health Master + Pipeline Controller | One page with tabs. Both monitor the same pipeline. |
| Alerts Hub | Alerts & Actions + Notifications + Action Center | One unified Inbox. Three pages for "things needing attention". |
| Governance | Live Governance + Paper Governance + Learning Governance + Approvals | One dashboard with sections. Four pages when system is paper-only. |
| System Ops | System Hub + Ops + Orchestration | One operations page. Three admin views with overlap. |
| Intelligence | Intelligence Sources + Entities + Whiteboard + Content Health | One hub with tabs. Four pages for the intelligence pipeline. |

**Potential reduction:** 61 → ~40 pages

### Pages That Could Be Eliminated

| Page | Route | Reason |
|------|-------|--------|
| Correlation | `/correlation` | Rarely actionable. Informational only. |
| Live Governance | `/live-governance` | Only shows "LIVE TRADING BLOCKED" during paper-only mode. |
| Forecast | `/forecast` | 3 closed trades — insufficient data for reliable forecasts. |

---

## III. Telegram Alert Noise

| Type | Count | Last Sent | Issue |
|------|-------|-----------|-------|
| urgent_alert ("Stop Triggered Present") | 18 | 2026-05-11 | Same alert daily for 18 days — no dedup |
| draft_alert ("Portfolio: STOP REVIEW") | 18 | 2026-05-11 | Duplicate of urgent_alert — same condition |
| aegis_morning_brief | 14 | 2026-05-10 | Valuable — keep |
| recovery_escalation | 10 | 2026-05-11 | Dashboard only — functional |
| stale_data_alert | 4 | 2026-05-10 | Appropriate — fires only when needed |

**Root cause:** portfolio_orchestrator.py fires both urgent_alert AND draft_alert for the same stop condition every daily run. No dedup gate.

---

## IV. Missing Intelligence Delivery

1. No dividend alerting (Visa paying this week — not surfaced)
2. Email digest stopped after May 6 with no failure alert
3. Rebalance stale 28 days — API credits depleted, no fallback, no alert
4. Proposals aging in PENDING — no alert for stale proposals
5. No alert when API credits are exhausted
6. Intelligence exists in DB but many pages don't query it

---

## V. UI/UX Consistency Issues

1. No consistent page layout template
2. Inconsistent staleness indicators across pages
3. No global alert banner for critical conditions
4. Inconsistent terminology (Prospects vs Trade AI vs Screener Results)
5. No "what to do now" prioritized action list on Overview
6. No unified morning briefing page as single starting point
