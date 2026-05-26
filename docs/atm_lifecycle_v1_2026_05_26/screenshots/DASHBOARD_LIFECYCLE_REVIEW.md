# Dashboard Lifecycle Review

**Generated:** 2026-05-26  
**Server:** http://127.0.0.1:7777  

## Page-by-Page Assessment

### /v2/automated-trade-mode (AutomatedTradeMode.tsx)

**Lifecycle stages:** ATM mode control, proposal approval, strategy health, queue preview, decisions
**Clear:** Mode status banner, account strips, decision log
**Confusing:** Where did a specific proposal come from? Which gates did it pass?
**Missing:** Per-proposal gate audit, lifecycle traceability, time-stop status per position
**P0.5B additions:** Classifier gate disabled banner (amber), working correctly
**Action buttons:** Mode change (enable/disable/pause/dry_run) — SAFE but powerful
**Stale visibility:** Market hours staleness warning present

### /v2/system-health (SystemHealth.tsx)

**Lifecycle stages:** Execution integrity, cron health, LLM router, DB state
**Clear:** Component health table, event log, LLM status
**P0.5B additions:** Control Plane Trust panel (safe_flock, time-stop, alert routing)
**Missing:** Stop proof panel, order lifecycle, exit management
**Action buttons:** Refresh only — SAFE

### /v2/trade-ai (TradeAI.tsx)

**Lifecycle stages:** Universe, scoring, candidate ranking
**Clear:** Scored ticker table, grades
**Missing:** "Why selected" explanation, enrichment proof, scorecard breakdown

### /v2/paper-proposals (PaperProposals.tsx)

**Lifecycle stages:** Proposal generation, approval status, enrichment data
**Clear:** Full proposal detail, targets, stops
**Missing:** Gate pass/fail, risk check result, capital allocation reasoning

### /v2/execution-quality (ExecutionQuality.tsx)

**Lifecycle stages:** TCA, slippage analysis
**Clear:** Fill quality grades, slippage percentages
**Missing:** Timing data (all null), order type, extended hours logic

### /v2/pipeline (PipelineHub.tsx)

**Lifecycle stages:** Meta — pipeline overview
**Note:** Minimal page (909 bytes), likely a hub/redirect

### /v2/alerts (AlertsDashboard.tsx)

**Lifecycle stages:** Alerting, escalation
**Missing:** Alert ack tracking, SLA status, delivery proof

### /v2/risk (Risk.tsx)

**Lifecycle stages:** Portfolio risk
**Missing:** ATM-specific risk gate view, concentration caps, heat metric

### /v2/agent-collaboration (AgentCollaboration.tsx)

**Lifecycle stages:** Agent RACI, mission tracking
**Clear:** Agent status, mission threads
**Missing:** RACI enforcement, per-stage ownership

### /v2/backtesting (Backtesting.tsx)

**Lifecycle stages:** Strategy backtesting
**Missing:** Live vs backtest comparison

## Overall Assessment

The dashboard has **good coverage of individual lifecycle stages** but **no unified view**.
An operator must check 6+ pages to understand current state. The right architectural
move is a single ATMControlRoom page that consolidates:

1. Pipeline funnel (signals → proposals → decisions → trades)
2. Open position grid (with stops, trailing tier, time-stop, P&L)
3. Risk/capital snapshot
4. Recent execution quality
5. Alert feed
6. Agent ownership per stage

**Screenshots:** Manual browser verification recommended. Playwright crawler available
at `scripts/capture_screenshots.py` for automated capture.
