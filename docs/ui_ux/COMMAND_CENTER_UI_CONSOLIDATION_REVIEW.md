# Command Center UI Consolidation Review

Status:      ACTIVE
as_of:       2026-05-24T18:56:51-04:00
Measured at: efcc51365 / not measured

## Navigation Restructure (Implemented)

### Before: 8 groups, 40+ items
Home (4) + Portfolio (6) + Trading (13) + Strategy (10) + Retirement (3) + Journal (2) + Intelligence (6) + System (10)

### After: 10 groups, streamlined
Command (3) + Portfolio (4) + Risk & Alerts (4) + AI Analyst (4) + Research (5) + Pipeline & Health (3) + Paper Trading (5) + Tax & Rebalance (3) + Reports (3) + Admin (18 low-frequency)

### Key Changes
1. **Trading (13 items) → Paper Trading (5) + Admin (8)** — low-frequency items moved to Admin
2. **Strategy (10) → distributed** — Risk/Watchlist/CIO/Technical moved to their logical groups
3. **Intelligence (6) → Research (5)** — clearer name, topic monitor + research topics together
4. **System (10) → Pipeline & Health (3) + Admin (7)** — only health-critical items in primary nav
5. **Admin catches everything else** — governance, backtesting, correlation, forecast, etc.

## Tooltip Pass (Implemented)

### Global Tooltips
- Data age banner: "Data is Xh old — Weekend: market data refreshes Monday 07:00 ET"
- Pipeline warning badge: specific reason per stage
- Approval badge: "X pending CIO approvals" (amber, not red)

### Page-Specific Tooltips
- System Health: each data product shows stale_reason, owner, schedule, remediation
- Pipeline: each stage shows warning_reason
- Alerts: SYSTEM counter added, counters labeled (System/Sent/Suppressed/Queued/Dispatched)
- AI Analyst: "HISTORICAL NARRATIVE + CURRENT OVERLAYS" banner always shown
- Technical: Analyst rating, Fwd P/E, YTD visible on cards with N/A explanation for ETFs
- Paper Proposals: blocker summary with per-proposal readiness state
- Agent Calibration: "INSUFFICIENT DATA" banner with threshold explanation
- Weekly Learning: "NO DIGEST GENERATED" with script/schedule/status

## Empty State Improvements (Implemented)
- Agent Calibration: explains need for 10+ scored outcomes
- Weekly Learning: shows script name, schedule, and why no digest
- Execution Quality: "Run TCA analysis after paper trades fill"

## Visual Consistency
- Approval badge: amber (not red) — distinguishes from alerts
- System alerts: red severity badges with detail cards
- Pipeline: warning reasons inline (not just amber dots)
- Technical cards: 3-column grid with 6 metrics (RSI, SMA200, Analyst, Fwd P/E, YTD, Beta)

## Cross-Links Added
- AI Analyst → Tax page (TLH drill-through)
- AI Analyst → input_manifest (holdings/risk/dividend freshness)
- Research Topics → Topic Monitor Library + Research Gaps
- System Health → Data Product Health panel

## Pages Kept As-Is
- Portfolio, Dividends, Returns, Attribution — clean and functional
- Risk, Risk Regime — working with triggered stops
- Tax, Rebalance, Retirement — data-rich, properly labeled
- Journal, Journal Reports — no duplicates after redirect fix
