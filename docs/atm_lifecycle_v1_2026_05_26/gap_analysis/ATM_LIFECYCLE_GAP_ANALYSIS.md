# ATM Lifecycle Gap Analysis

**Generated:** 2026-05-26  
**Commit:** `915876f`  
**Author:** Claude Code (Chief Architect role)  

---

## A. Executive Summary

The system has **strong individual components** covering most lifecycle stages, but lacks **unified traceability, a single control-room view, and several critical enforcement mechanisms**. The pipeline can generate proposals, approve them, execute paper trades, and manage stops. But the operator cannot easily trace a single trade from "why was this picked?" through "what happened?" to "what did we learn?"

**Key verdict:** The system is not ready for live trading graduation. Paper mode should continue. The gap is not in any single missing piece — it's in the lack of end-to-end integration, verifiable controls, and operator-accessible traceability.

**Top 5 gaps by severity:**
1. **DANGEROUS** — No single traceability key from candidate → exit → learning
2. **DANGEROUS** — 10 intraday positions held overnight with no enforcement
3. **PARTIAL** — Risk/capital gates exist but no unified view; cash basis may be stale
4. **PARTIAL** — Broker stop verification runs only 2x/day; no real-time proof
5. **MISSING** — No unified control-room dashboard

---

## B. Full Lifecycle Coverage Table

| # | Stage | Code | Data | API | UI | Monitor | Alert | Status | Gap |
|---|-------|------|------|-----|----|---------| ------|--------|-----|
| 1 | Universe/Scope | finviz_screener_runner | finviz_screener_results | /screener-membership | Incubator | system_health_agent | CRITICAL escalation | PARTIAL | No symbol blacklist enforcement |
| 2 | Candidate Discovery | trade_ai_orchestrator | strategy_signals | /trade-ai | TradeAI | system_health_agent | CRITICAL | PARTIAL | No "why selected" audit |
| 3 | Enrichment/Research | finviz_enrichment, news_ingestion | intelligence tables | /research-topics | IntelligenceHub | system_health_agent | CRITICAL | PARTIAL | No research freshness gate on proposals |
| 4 | Scoring | orchestrator scoring | strategy_signals.score | /trade-ai | TradeAI | None | None | PARTIAL | No scorecard breakdown view |
| 5 | LLM Critic | scalp_critic_agent | inline verdict | None | None | None | None | PARTIAL | No latency/timeout tracking |
| 6 | Signal Creation | orchestrator + signal_fusion | strategy_signals | /trade-ai | TradeAI | None | None | PARTIAL | No dedup enforcement |
| 7 | Proposal Generation | auto_proposal_generator | paper_trade_proposals | /paper-proposals | PaperProposals | system_health_agent | Via health agent | COMPLETE | Minor: no "why created" record |
| 8 | Approval Gate | atm_auto_approver | atm_decision_log | /atm/decisions | AutomatedTradeMode | system_health_agent | CRITICAL | PARTIAL | No per-proposal gate pass/fail view |
| 9 | Risk Gate | risk_gate.py | inline in approval | /risk (indirect) | None dedicated | None | None | PARTIAL | No unified heat/concentration view |
| 10 | Capital Allocation | proposal_execution_readiness | proposal fields | None | None | None | None | PARTIAL | Cash basis may be stale |
| 11 | Account Routing | atm_auto_approver | proposal.target_account | None | None | None | None | PARTIAL | No routing audit trail |
| 12 | Order Creation | proposal_paper_submitter | paper_trades | None | None | None | None | PARTIAL | No order type visibility |
| 13 | Fill Tracking | alpaca_paper_adapter | paper_trades.entry_price | None | PaperStatus | sweep cron | None | PARTIAL | No order lifecycle state |
| 14 | Slippage/TCA | paper_execution_quality* | paper_execution_quality | /execution-quality | ExecutionQuality | None | None | PARTIAL | Timing fields null |
| 15 | Initial Stop | alpaca_paper_adapter | paper_trades.stop_loss | None | None | None | None | PARTIAL | No broker stop proof |
| 16 | Broker Stop Verify | reconcile_stop_v21 | reconciliation report | None | None | Reconciler 2x/day | None | PARTIAL | Only 2x/day, no real-time |
| 17 | Trailing Stops | unified_stop_supervisor | updated stop_loss | None | None | system_health_agent | CRITICAL | PARTIAL | No per-position trail history |
| 18 | Time-Stop Review | strategy_trailing_policy | P0.5B API only | /execution-integrity | SystemHealth | P0.5B | None | PARTIAL | Review-only, no enforcement |
| 19 | Exit Management | paper_trade_closer | paper_trades exit fields | None | None | None | None | MISSING | No exit reason taxonomy |
| 20 | Post-Trade Review | journal_agent_coach | trade_lesson_memory | Journal endpoints | JournalHub | None | None | PARTIAL | No API for outcomes |
| 21 | Backtesting | enterprise_backtester | backtest tables | None | Backtesting | None | None | PARTIAL | Not linked to live config |
| 22 | Learning Feedback | feedback_loop_processor | calibration tables | None | None | None | None | PARTIAL | No visible feedback loop |
| 23 | Agent RACI | config only | agent_raci.yaml | /agent-collaboration | AgentCollaboration | None | None | PARTIAL | Not enforced |
| 24 | Dashboard | 6+ pages | All | All | Scattered | N/A | N/A | MISSING | No unified control room |
| 25 | Alerting | telegram_alert + 63 others | system_health_events | /alerts | AlertsDashboard | system_health_agent | Telegram | PARTIAL | 64 direct senders, no ack |

**Summary: 0 COMPLETE, 22 PARTIAL, 2 MISSING, 1 DANGEROUS (traceability)**

---

## C. Traceability Gaps

The system has these linkage columns across tables:
- `signal_id` — in paper_trade_proposals, paper_trades
- `proposal_id` — in paper_execution_quality
- `trade_plan_id` — in paper_trade_proposals, paper_trades
- `paper_trade_id` — in paper_execution_quality
- `strategy_id` — everywhere
- `source_signal_id` — in paper_trade_proposals

**What works:** proposal → paper_trade (via signal_id), paper_trade → execution_quality (via paper_trade_id/proposal_id)

**What's broken:**
- No candidate_id → signal link (candidates are ephemeral)
- No signal → enrichment/research link
- No exit → TCA automatic link
- No trade → journal/lesson automatic link
- No trade → backtest comparison link
- No single "lifecycle_event" table that tracks all state changes for one trade

**Verdict: DANGEROUS** — Cannot trace a single trade end-to-end without manual SQL joins across 5+ tables.

---

## D. Risk / Capital Gaps

| Gap | Severity |
|-----|----------|
| No real-time cash basis (uses account snapshot, may be hours old) | PARTIAL |
| No per-symbol concentration cap (only per-strategy and per-sector %) | PARTIAL |
| No portfolio heat metric (total risk as % of equity) | MISSING |
| Sector cap (35%) not verifiable from dashboard | PARTIAL |
| VIX/regime gate exists in code but no dashboard visibility | PARTIAL |

---

## E. Execution / Slippage / TCA Gaps

| Gap | Severity |
|-----|----------|
| Order type (limit vs market) not visible in any API | MISSING |
| Extended-hours order logic not documented or visible | MISSING |
| `order_submitted_at`, `order_filled_at`, `time_to_fill_seconds` all null | PARTIAL |
| No order lifecycle state machine (submitted → partial → filled → cancelled) | MISSING |
| TCA runs only at EOD, not near-real-time | PARTIAL |

---

## F. Stop / Trailing / Time-Stop Gaps

| Gap | Severity |
|-----|----------|
| No broker stop order proof visible in dashboard | MISSING |
| Broker stop reconciliation only runs 2x/day | PARTIAL |
| No per-position trailing tier history | MISSING |
| 10 intraday positions held overnight — time stop not enforced | DANGEROUS |
| No stop-limit vs stop-market distinction | MISSING |
| No "trailing stop ratchet event" log | MISSING |

---

## G. Backtesting / Learning Gaps

| Gap | Severity |
|-----|----------|
| Backtest results not linked to live strategy configs | PARTIAL |
| No "backtest vs paper result" comparison view | MISSING |
| Learning feedback loop exists but not visible to operator | PARTIAL |
| Agent calibration scores not surfaced in dashboard | PARTIAL |

---

## H. Agent RACI / Collaboration Gaps

| Gap | Severity |
|-----|----------|
| RACI defined in YAML but not enforced in code | PARTIAL |
| No escalation path enforcement | MISSING |
| Agent ownership is informational only | PARTIAL |
| No "who decided this?" audit trail per lifecycle event | MISSING |

---

## I. Dashboard / UX Gaps

| Gap | Severity |
|-----|----------|
| No unified control-room page | MISSING |
| Lifecycle scattered across 6+ pages | PARTIAL |
| No single-trade drilldown view | MISSING |
| No "what happened today" summary card | MISSING |
| Stale data not always visible | PARTIAL |
| Action buttons exist that could change trading state | PARTIAL |

---

## J. Prioritized Build Plan

### Priority 1 — Must Build (blocks graduation)

1. **Lifecycle traceability schema** — single `lifecycle_events` table or consistent FK chain
2. **Time-stop enforcement** — at minimum auto-alert, ideally auto-close for intraday
3. **Unified control-room dashboard** — ATMControlRoom.tsx
4. **Broker stop proof panel** — real-time stop order verification
5. **Per-proposal gate pass/fail view** — show exactly which gates approved/rejected

### Priority 2 — Should Build (high value)

6. Cash basis real-time tracking
7. Order lifecycle state machine
8. TCA timing field population
9. Per-position trailing tier display
10. Single-trade drilldown view

### Priority 3 — Nice to Have

11. Backtest vs paper comparison
12. Learning feedback dashboard
13. Alert acknowledgment tracking
14. Agent RACI enforcement
15. Candidate "why selected" audit
