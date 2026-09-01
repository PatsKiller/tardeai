# Context Sync Preflight — 2026-05-22

Status:      ACTIVE
as_of:       2026-05-22T16:02:12-04:00
Measured at: efcc51365 / not measured

## Time / Git
- Date: Fri May 22 15:57:23 EDT 2026
- HEAD: de74a20 fix(nav): move ATM to Trading, Backtesting to Strategy, add missing pages
- 20 recent commits span ATM v1 build, enrichment, supply audit, pre-active fixes, approve_proposal_failed fix, nav fix

## Safety Gates — ALL PASSED
- ALPACA_MODE=paper ✓
- LLM_DISABLE_LIVE_EXECUTION=true ✓
- Holdings: $1,201,120 / 47 positions ✓ (>$1,000,000 guard passed)

## ATM Status
- ATM API endpoint: 404 (endpoint not registered as `/api/v2/atm-status`)
- ATM state in DB: mode=active (set by dashboard at 11:25 ET)
- ATM was NOT modified during this context sync

## Core Endpoints
- /api/v2/overview: 200 ✓
- /api/v2/paper-proposals: 200 ✓
- /api/v2/atm-status: 404 (not a registered endpoint)
