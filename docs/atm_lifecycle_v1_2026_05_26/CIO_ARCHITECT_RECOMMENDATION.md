# CIO / Architect Recommendation

**Date:** 2026-05-26  
**Commit:** `915876f`  
**Role:** Chief Architect assessment for ATM lifecycle readiness  

---

## 1. Should ATM continue in paper mode?

**Yes.** Paper mode is the only appropriate operating mode. The system has proven it can generate proposals, execute paper trades, manage trailing stops, and produce TCA data. But the control-plane gaps (traceability, time-stop enforcement, broker stop proof, unified dashboard) mean the operator cannot verify trade quality with confidence.

## 2. What prevents expansion to live?

| Blocker | Why It Matters |
|---------|---------------|
| No end-to-end traceability | Cannot audit a single trade lifecycle from candidate to learning |
| Time-stop not enforced | 10 intraday positions held 12-19 days with no auto-action |
| Broker stop proof missing | Cannot verify broker has the stop order the DB thinks it placed |
| Cash basis may be stale | Position sizing based on potentially hours-old account snapshot |
| No unified control room | Operator must check 6+ pages to understand system state |
| Classifier health at 0.0 | Gate is effectively disabled — all strategies pass regardless of performance |
| 64 uncontrolled Telegram senders | Alert integrity cannot be guaranteed |

## 3. What must be built before graduation?

**Minimum viable graduation requirements:**

1. **Lifecycle event chain** — every trade traceable from signal to exit to lesson
2. **Time-stop enforcement** — at minimum operator alert, ideally auto-close for intraday
3. **Broker stop verification** — real-time or at least every 15 minutes
4. **Cash basis tracking** — real-time or synced with broker before each approval
5. **Classifier health gate** — restore to 0.50 once 3+ trades close per strategy, or implement visible burn-in countdown
6. **ATM Control Room** — single page showing full pipeline state
7. **Per-proposal gate audit** — show exactly which checks passed/failed

## 4. Which controls are already acceptable?

| Control | Assessment |
|---------|-----------|
| Position limits (max_concurrent, max_new_per_day) | ACCEPTABLE — enforced in code, config-driven |
| Strategy-family trailing stops | ACCEPTABLE — well-designed tier system, runs every 3 min |
| safe_flock observability | ACCEPTABLE — P0.5A solved this completely |
| System health agent | ACCEPTABLE — monitors 18 components, retries, escalates |
| Paper execution (Alpaca adapter) | ACCEPTABLE — fills verified, reconciler runs |
| Alert dedup/suppression | ACCEPTABLE — router + 2h dedup window works |
| ATM kill switch | ACCEPTABLE — manual_kill_switch_only prevents runaway |
| Daily loss hard pause | ACCEPTABLE — 0.25% threshold configured |
| Operating hours gate | ACCEPTABLE — 09:35-15:30 ET enforced |
| Drive sync | ACCEPTABLE — P0.5A fixed, hourly cron confirmed clean |

## 5. Which controls are unacceptable?

| Control | Problem |
|---------|---------|
| Time-stop enforcement | **UNACCEPTABLE** — 10 intraday positions overdue, no enforcement |
| Broker stop proof | **UNACCEPTABLE** — no real-time verification, only 2x/day reconciliation |
| Traceability | **UNACCEPTABLE** — cannot trace a trade end-to-end |
| Classifier health at 0.0 | **UNACCEPTABLE for graduation** — acceptable during explicit burn-in only |
| Cash basis freshness | **UNACCEPTABLE for live** — acceptable for paper with awareness |

## 6. What should be built today?

**Immediate next session (ATM Lifecycle v1):**

1. **ATMControlRoom.tsx** — unified page replacing the current scattered view
   - Opportunity pipeline (signals → proposals → decisions)
   - Open position management with stops, trailing tier, time-stop status
   - Risk/capital snapshot (positions, cash, heat, sector concentration)
   - Execution quality summary
   - Agent RACI ownership per stage
   - Alert/escalation feed

2. **Lifecycle traceability** — add `lifecycle_id` or consistent FK chain
   - Signal → Proposal → Decision → Trade → Stop → Exit → TCA → Lesson

3. **Time-stop auto-alert** — at minimum, Telegram alert when intraday position survives to EOD

4. **Per-proposal gate audit** — API field showing each gate's pass/fail for each proposal

## 7. What should be deferred?

| Item | Defer Until |
|------|------------|
| Live broker integration | After 30 clean paper days with all controls passing |
| Alert migration (64 senders) | P1 package after lifecycle v1 |
| Agent RACI enforcement | After RACI design review |
| Backtest vs paper comparison | After backtest infrastructure audit |
| Full order lifecycle state machine | After Alpaca API audit |

## 8. What should be blocked until after burn-in?

| Item | Block Until |
|------|------------|
| classifier_health restore to 0.50 | 3+ closed trades per active strategy |
| Live trading enable | All Priority 1 gaps closed + 30 clean paper days |
| Schwab/Fidelity account routing | Live trading prerequisites met |
| Position sizing increase beyond 10% | Capital allocation audit complete |

---

## Recommended Next Action

Build **ATM Lifecycle v1 — Control Room** as the next package. Start with the dashboard and traceability schema. Time-stop enforcement and broker stop proof can be integrated as the control room takes shape.

The control room is the right architectural move because:
1. It forces unification of scattered data
2. It makes gaps immediately visible to the operator
3. It creates the framework for adding enforcement later
4. It replaces the current "check 6 pages" workflow with one command center

**Estimated scope:** 1 large session for the control room dashboard + API consolidation. Follow-up sessions for enforcement, traceability schema, and alerting integration.
