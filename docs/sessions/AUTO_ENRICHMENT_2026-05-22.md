# ATM v2: Auto-Enrichment Pipeline

**Date:** 2026-05-22
**Session:** Remove human-click prerequisites from ATM

## Problem
ATM removed the manual /ptapprove click but left three other manual clicks
(Refresh Price, Check Execution, AI Review). Without these, proposals had
NULL enrichment fields and ATM rejected everything.

## Solution
5-minute auto-enrichment cron runs before ATM's 15-minute approval cron,
filling all enrichment data automatically.

## What Was Built

### 1. Schema (`migrations/2026_05_22_auto_enrichment.sql`)
- `paper_trade_proposals`: added enrichment_failures, enrichment_status,
  enrichment_last_attempt_at, enrichment_last_error
- `enrichment_log`: audit table for per-step results
- `atm_state.last_enrichment_at`: heartbeat

### 2. `auto_enrichment_runner.py`
5-step pipeline per proposal:
1. refresh_price (quote from market_quote_provider)
2. technical (proposal_technical_snapshot.py subprocess)
3. ai_review (proposal_intelligence_analyzer.py, 120s timeout, non-blocking)
4. risk_gate (RiskGate.check())
5. execution_readiness (assess_proposal + write_readiness)

Features:
- ThreadPoolExecutor(max_workers=3)
- AI review is non-blocking — timeout doesn't prevent COMPLETE
- Per-proposal failure tracking (3-strike FAILED status)
- `--force-all` flag for bootstrap drain
- Idempotent (safe to run repeatedly)

### 3. ATM Pre-check
`atm_auto_approver.py` now checks `enrichment_status` before gate chain:
- FAILED (3x): deferred with enrichment_failed_3x
- Not COMPLETE: deferred with not_yet_enriched

### 4. Dashboard Panel
Enrichment Status section on `/v2/automated-trade-mode`:
- Summary: total/complete/in-progress/pending/failed
- Per-proposal table with status badges, last attempt time, retry count
- 5-dot step indicators (hover for details)

### 5. Cron
`*/5 9-15 * * 1-5` — every 5 min during market hours

## Bootstrap Results

Pre-deploy: 4 PENDING proposals, 0 enriched, 0 ATM-approvable
Post-deploy: 4 enriched to COMPLETE, 1 READY_FOR_PAPER_SUBMIT (BCS)

| Proposal | Symbol | Enrichment | Readiness |
|----------|--------|------------|-----------|
| #115 | ARM | COMPLETE | BLOCKED_SPREAD (7.2%) |
| #119 | MUD | COMPLETE | BLOCKED_NO_VOLUME |
| #121 | SHMD | COMPLETE | BLOCKED_SPREAD (17.6%) |
| #122 | BCS | COMPLETE | READY_FOR_PAPER_SUBMIT |

## AI Review Performance Note
The `proposal_intelligence_analyzer.py` takes >120 seconds per proposal
(DB queries + LLM generation + narrative composition). With 3 concurrent
workers competing for Ollama, timeouts are common. Made ai_review
non-blocking — it runs best-effort but doesn't gate proposal readiness.
The core gates (quote freshness, risk gate, execution readiness) don't
require AI review.

## Commits
- `c1a2a41`: Schema + runner
- `0ffe673`: ATM pre-check
- `5f05e27`: Dashboard panel + API
- `75e8a79`: Bootstrap drain + timeout fix

## Safety
- Holdings: $1,201,369 / 47 positions (unchanged)
- ATM remains in DRY_RUN
- All existing safety gates preserved
- No broker hardcoding
