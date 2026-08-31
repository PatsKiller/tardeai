# Self-Improvement Page Enhancement Notes

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25
Operator note: "This page is good -- enhance only"

---

## Current State

**Route:** `/v2/self-improvement`
**Component:** `SelfImprovement.tsx`
**APIs:** 3 endpoints
- `/api/v2/self-improvement/status` -- overall status
- `/api/v2/self-improvement/review-queue` -- items needing review
- `/api/v2/self-improvement/component-health` -- per-component health

## What Works Well

1. **Unified operator view** -- single page aggregates safety, paper trading, learning, agent calibration, backtesting, and pipeline status
2. **Read-only aggregation** -- does not mutate state, safe to browse
3. **Navigation links** to deeper pages (risk, governance, calibration, backtesting, pipeline)
4. **Warning system** surfaces recommended actions
5. **Component health grid** shows status at a glance

## Enhancement Opportunities

### Visual Enhancements
- Add a top-level health score or "system maturity" badge (aggregate number)
- Add sparkline trends for key metrics (e.g., win rate over time)
- Color-code component health cards (green/amber/red)
- Add a "last updated" timestamp per section

### Functional Enhancements
- Add refresh button per section (currently page-level only)
- Add ability to mark warnings as "acknowledged" 
- Add a "since last visit" delta indicator
- Show the most recent self-improvement action taken by each agent
- Add a mini timeline of recent system improvements

### Data Enhancements
- Pull in `/api/v2/self-improvement/warnings` for active warnings
- Pull in `/api/v2/self-improvement/operator-actions` for recent actions
- Show count of queued items vs completed in the last 7 days
- Surface the latest weekly learning digest summary

### Layout
- Current layout is card-based grid -- works well
- Consider a 2-column layout: left = status summary, right = review queue
- The review queue could benefit from sortable/filterable table

## Do NOT Change
- The read-only nature of this page
- The cross-linking navigation to deeper pages
- The overall card-based structure
- The operator-focused language and tone
