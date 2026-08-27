# Universal Execution-Time Revalidation

**Date:** 2026-05-09  
**Status:** Implemented, paper-only, manual observation phase

## Problem Statement

When a paper trade recommendation is created at time T1 and admin approval/execution happens at T2, the system must NOT assume T1 data is still valid. A 10:00 AM recommendation reviewed at 2:00 PM may have materially different entry, stop, target, risk/reward, catalyst, spread, or volume conditions.

This applies to ANY delay — intraday drift, overnight, weekend, holiday, or slow admin review.

## State Machine

```
Recommendation Created → Approval/Review → Revalidation Required
                                              ↓
                              ┌────────────────┴───────────────┐
                              ↓                                ↓
                       Market Open?                     Market Closed?
                              ↓                                ↓
                    Revalidate against                 Set approved_pending_recheck
                    current conditions                 Queue for next session open
                              ↓
              ┌───────┬───────┼───────┬──────────┬────────────┐
              ↓       ↓       ↓       ↓          ↓            ↓
         VALID    UPDATED  DELAY  DOWNGRADE  CANCEL    BLOCKED
       ORIGINAL   NEEDS            TO_WAIT             SAFETY
                 REAPPROVAL
```

## Revalidation Outcomes

1. **VALID_ORIGINAL** — Original plan still valid, score >= 70
2. **UPDATED_PLAN_REQUIRES_REAPPROVAL** — Entry/stop/target/risk materially changed
3. **DELAY_EXECUTION** — Spread too wide, volume thin, session poor
4. **DOWNGRADE_TO_WAIT** — Setup no longer qualifies but worth watching
5. **CANCEL_OR_EXPIRE** — Thesis broken, risk gate failed
6. **BLOCKED_SAFETY** — Paper gate, broker mismatch, duplicate order, non-paper mode

## Freshness Thresholds

| Strategy | Max Age (minutes) |
|----------|-------------------|
| Intraday scalp | 10 |
| Momentum / day trade | 15 |
| Swing / mean reversion | 60 |
| Income / position / dividend | 1440 (1 trading day) |
| Unknown | 15 |

## Material Change Rules

- Entry price drift > 3% → block
- Entry price drift > 1.5% → warning
- Stop loosening > 20% of original risk → material change
- R:R degraded > 50% → material change
- Quote age > 15 min → stale warning
- Adverse news/catalyst → review required
- Duplicate order detected → blocked

## 10 AM Recommendation → 2 PM Review Example

1. Recommendation created at 10:00 AM (entry $50.00, stop $48.00, target $54.00)
2. Admin reviews at 2:00 PM (4 hours later)
3. System detects: recommendation age 240 min > threshold 15 min → STALE
4. Current price pulled: $51.50 → drift 3.0% → material change
5. New risk: $51.50 - $48.00 = $3.50 (was $2.00) → risk increased 75%
6. Status: `updated_plan_requires_reapproval`
7. Admin must approve updated plan or reject

## Weekend/Saturday Approval

1. Admin approves proposal Saturday afternoon
2. Market session = "weekend" → should_delay = true
3. Status: `delayed`, approved_pending_recheck = true
4. next_recheck_at = Monday 9:30 AM
5. On Monday open, revalidator runs automatically (if cron installed) or manually
6. Fresh quote pulled, plan revalidated against Monday conditions

## API Endpoints

- `GET /api/v2/paper-execution-rechecks` — list recent rechecks
- `GET /api/v2/paper-execution-rechecks/<id>` — single recheck detail
- `POST /api/v2/paper-execution-rechecks/run` — run revalidation
- `POST /api/v2/paper-execution-rechecks/<id>/approve-updated-plan`
- `POST /api/v2/paper-execution-rechecks/<id>/reject-updated-plan`
- `POST /api/v2/paper-execution-rechecks/<id>/execute-ready`
- `GET /api/v2/market-session` — current session status

## Telegram Commands

- `paper pending entries` — list pending proposals with recheck status
- `recheck paper entry <id>` — run revalidation for one proposal
- `approve updated paper entry <id> [reason]` — approve changed plan
- `reject updated paper entry <id> [reason]` — reject changed plan
- `execute ready paper entry <id>` — execute only if all gates pass

## Dashboard

Tab "Execution Rechecks" on `/v2/paper-trade-intelligence` showing:
- Market session status
- All rechecks with status, score, drift, material changes, reapproval status

## Pipeline Controller Stages

- `paper_execution_revalidation_scan` — scans all pending proposals
- `execution_readiness_check` — readiness verification

## No-Auto-Execution Rule

No broker order is submitted without:
1. Explicit admin approval of the proposal
2. Execution-time revalidation passing (valid_original)
3. No material change pending reapproval
4. Market is open (regular session)
5. Risk gate passes
6. Paper gate reports BLOCKED/PAPER
7. ALPACA_MODE = paper
8. Quote is fresh
9. No duplicate order
10. Explicit execute command (Telegram or API)

## Validation Results (2026-05-09)

22/22 tests passed:
- Holdings guard: PASS ($1,189,457)
- ALPACA_MODE=paper: PASS
- LIVE_TRADING absent: PASS
- Live trading gate BLOCKED: PASS
- Weekend simulation: delayed (correct)
- After-hours simulation: delayed (correct)
- 240min delay: stale detected (correct)
- 4% drift: material change (correct)
- Large drift: requires reapproval (correct)
- No auto-execution without flag: PASS
- No crontab installed: PASS
