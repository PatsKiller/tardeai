# ATM Full Lifecycle Map

**Generated:** 2026-05-26  
**Git Commit:** `915876f`  
**Purpose:** Map every stage of the automated trade-management lifecycle with code, data, API, UI, and monitoring evidence.

---

## 1. Universe / Scope

| Field | Value |
|-------|-------|
| **Owning Script** | `finviz_screener_runner.py`, `finviz_ingestion.py`, `candidate_discovery_orchestrator.py` |
| **Agent** | None dedicated |
| **Input** | Finviz screener configs, `config/screener_schedule.yaml`, `config/strategies/*.yaml` eligibility rules |
| **Output** | `finviz_screener_results` table, `ticker_catalog` |
| **API** | `/api/v2/screener-membership/summary`, `/api/v2/ticker-catalog/summary` |
| **Frontend** | Incubator page, TradeAI page |
| **Cron** | 7 runs/day (7,8,10,12,14,16,18 ET) |
| **Health Monitor** | `system_health_agent.py` checks finviz_screener_runner |
| **Alert** | CRITICAL escalation if screener stale |
| **Failure Mode** | Silent — no candidates enter pipeline if screener fails |
| **Missing Controls** | No explicit "universe approved" audit trail; no symbol blacklist enforcement in screener |

## 2. Screener / Candidate Discovery

| Field | Value |
|-------|-------|
| **Owning Script** | `trade_ai_orchestrator.py`, `classify_candidates.py`, `multi_strategy_classifier.py` |
| **Agent** | None |
| **Input** | Screener results, news events, social signals, portfolio context |
| **Output** | `strategy_signals` table |
| **API** | `/api/v2/trade-ai` (scored tickers) |
| **Frontend** | TradeAI page |
| **Cron** | Orchestrator at 0900, 1000, 1200, 1400, 1600, 1730 via safe_flock |
| **Health Monitor** | `system_health_agent.py` checks trade_ai_orchestrator |
| **Alert** | CRITICAL if orchestrator stale |
| **Failure Mode** | No signals generated → no proposals → pipeline dead |
| **Missing Controls** | No explainable "why this candidate was selected" record per candidate |

## 3. Enrichment / Research

| Field | Value |
|-------|-------|
| **Owning Script** | `finviz_enrichment.py`, `catalyst_enrichment.py`, `news_ingestion.py`, `web_research.py`, `auto_research.py` |
| **Agent** | Aegis (surveillance, synthesis), Alex (gov research) |
| **Input** | Candidate tickers, news sources, social feeds, SEC filings |
| **Output** | Enriched ticker data in DB, research_queue, intelligence tables |
| **API** | `/api/v2/research-topics`, `/api/v2/intelligence-*` |
| **Frontend** | IntelligenceHub, Research, IntelligenceSources |
| **Cron** | Multiple: news 3x/day, enrichment daily, social 2x/day |
| **Health Monitor** | system_health_agent checks news_ingestion |
| **Failure Mode** | Stale research → proposals based on old data |
| **Missing Controls** | No "research freshness" gate on proposals; no proof of article/source per proposal |

## 4. Scoring

| Field | Value |
|-------|-------|
| **Owning Script** | `trade_ai_orchestrator.py` (scoring engine), `scoring.py`, `content_scoring.py` |
| **Input** | Candidate + enrichment data, strategy YAML criteria |
| **Output** | `strategy_signals.score`, `strategy_signals.grade` |
| **API** | `/api/v2/trade-ai` |
| **Frontend** | TradeAI page |
| **Failure Mode** | Miscalibrated scores → bad proposals approved |
| **Missing Controls** | No single scorecard view showing all score components and cutoffs per signal |

## 5. LLM Critic / Scalp Critic

| Field | Value |
|-------|-------|
| **Owning Script** | `scalp_critic_agent.py`, `proposal_llm_reviewer.py`, `proposal_quality_reviewer.py` |
| **Input** | Candidate data, strategy criteria, float/RVOL/catalyst checks |
| **Output** | Critic verdict (PASS/FAIL/REVIEW), rejection reasons |
| **API** | None dedicated |
| **Cron** | Called inline by proposal pipeline |
| **Failure Mode** | LLM timeout → fallback or skip critic → unreviewed proposals |
| **Missing Controls** | No latency tracking, no timeout visibility, no fallback audit, no output quality check |

## 6. Strategy Signal Creation

| Field | Value |
|-------|-------|
| **Owning Script** | `trade_ai_orchestrator.py`, `signal_fusion.py` |
| **Input** | Scores, critic review, strategy fit |
| **Output** | `strategy_signals` table rows |
| **API** | `/api/v2/trade-ai` |
| **Failure Mode** | Duplicate signals, stale signals not cleaned |
| **Missing Controls** | No signal dedup enforcement; no signal-to-proposal link audit |

## 7. Proposal Generation

| Field | Value |
|-------|-------|
| **Owning Script** | `auto_proposal_generator.py`, `incubator_proposal_promoter.py` |
| **Input** | Strategy signals, strategy cards, incubator list |
| **Output** | `paper_trade_proposals` table rows |
| **API** | `/api/v2/paper-proposals` |
| **Frontend** | PaperProposals page |
| **Cron** | auto_proposal every 30min, incubator_promoter hourly |
| **Failure Mode** | No proposals generated if signals stale or generator fails |
| **Missing Controls** | No "why proposal was created or rejected" explainability record |

## 8. Proposal Approval (ATM Gate)

| Field | Value |
|-------|-------|
| **Owning Script** | `atm_auto_approver.py`, `proposal_decision_gate.py` |
| **Input** | Proposal, ATM config, classifier health, position limits, risk gate |
| **Output** | `atm_decision_log` table rows, proposal status update |
| **API** | `/api/v2/atm/decisions` |
| **Frontend** | AutomatedTradeMode page |
| **Cron** | `*/15 9-15 * * 1-5` via safe_flock |
| **Failure Mode** | Gate misconfigured → approves too many, or blocks everything |
| **Missing Controls** | No single view showing which gates passed/failed per proposal |

## 9. Risk Gate

| Field | Value |
|-------|-------|
| **Owning Script** | `risk_gate.py` |
| **Input** | Portfolio state, position limits, VIX, market regime |
| **Output** | PASS/FAIL + reasons |
| **API** | `/api/v2/risk` (indirect via other endpoints) |
| **Cron** | hourly `--test` mode, called inline by approval |
| **Failure Mode** | Risk gate bypass if not called or exception silenced |
| **Missing Controls** | No unified heat/concentration/cash-basis view; no per-symbol/per-sector cap visibility |

## 10. Capital Allocation

| Field | Value |
|-------|-------|
| **Owning Script** | `proposal_execution_readiness.py`, `paper_submit_readiness.py` |
| **Input** | Available cash, position sizing rules, max % per trade |
| **Output** | proposed_shares, proposed_dollar_size in proposal |
| **Failure Mode** | Oversized position if cash basis stale |
| **Missing Controls** | No real-time cash basis tracking; sizing based on stale account data |

## 11. Account Routing

| Field | Value |
|-------|-------|
| **Owning Script** | `atm_auto_approver.py`, proposal's `target_account` field |
| **Input** | `accounts` table, atm_config account overrides |
| **Output** | `proposed_account` / `target_account` in proposal |
| **Failure Mode** | Route to wrong account; disabled account receives trades |
| **Missing Controls** | No routing audit trail; no explicit "why this account" record |

## 12. Order Creation

| Field | Value |
|-------|-------|
| **Owning Script** | `proposal_paper_submitter.py`, `alpaca_paper_adapter.py` |
| **Input** | Approved proposal, account credentials |
| **Output** | Broker order, `paper_trades` row |
| **API** | None dedicated |
| **Failure Mode** | Silent failure if broker rejects; order type wrong for extended hours |
| **Missing Controls** | No order type visibility (limit vs market); no extended-hours logic visibility |

## 13. Fill Tracking

| Field | Value |
|-------|-------|
| **Owning Script** | `alpaca_paper_adapter.py`, `paper_execution_sweep.py` |
| **Input** | Broker order status |
| **Output** | Fill price, fill time in `paper_trades` |
| **Cron** | paper_execution_sweep `*/5 9-16` via safe_flock |
| **Failure Mode** | Unfilled orders stuck; fill not recorded |
| **Missing Controls** | No order lifecycle state machine visible in dashboard |

## 14. Slippage / TCA

| Field | Value |
|-------|-------|
| **Owning Script** | `paper_execution_quality.py`, `paper_execution_quality_analyzer.py` |
| **Input** | Intended entry vs fill price, bid/ask spread |
| **Output** | `paper_execution_quality` table |
| **API** | `/api/v2/execution-quality` |
| **Frontend** | ExecutionQuality page |
| **Cron** | `30 16 * * 1-5` + `0 17 * * 1-5` |
| **Failure Mode** | TCA not computed → no slippage visibility |
| **Missing Controls** | Timing fields mostly null (order_submitted_at, order_filled_at, time_to_fill_seconds) |

## 15. Initial Stop Creation

| Field | Value |
|-------|-------|
| **Owning Script** | `alpaca_paper_adapter.py` (places stop order), strategy YAML defines stop policy |
| **Input** | Proposal stop_loss, strategy YAML stop policy |
| **Output** | Broker stop order, stop_loss in `paper_trades` |
| **Failure Mode** | Stop not placed; stop placed at wrong level |
| **Missing Controls** | No broker stop order proof visible in dashboard; no orphan stop check |

## 16. Broker Stop Verification

| Field | Value |
|-------|-------|
| **Owning Script** | `reconcile_stop_v21_broker_stops.py`, `alpaca_paper_reconciler.py` |
| **Input** | Broker open orders vs DB stops |
| **Output** | Reconciliation report |
| **Cron** | alpaca_reconciler at open/close |
| **Failure Mode** | DB says stop exists but broker doesn't; orphan broker stop |
| **Missing Controls** | No real-time broker stop proof panel; reconciliation runs only 2x/day |

## 17. Stop Replacement / Trailing

| Field | Value |
|-------|-------|
| **Owning Script** | `unified_stop_supervisor.py`, `strategy_trailing_policy.py` |
| **Input** | Open positions, current price, trailing tier rules |
| **Output** | Updated stop_loss in DB, broker stop order replacement |
| **API** | Via `/api/v2/execution-integrity` (indirect) |
| **Cron** | `*/3 9-16 * * 1-5` via safe_flock |
| **Failure Mode** | Trailing not applied; stop ratcheted wrong direction |
| **Missing Controls** | No per-position trailing history visible; no "current tier" display |

## 18. Time-Stop Review

| Field | Value |
|-------|-------|
| **Owning Script** | `strategy_trailing_policy.py` (defines policy), `api_v2.py` (surfaces status via P0.5B) |
| **Input** | Entry time, strategy family time-stop config |
| **Output** | time_stop_summary in execution-integrity API (P0.5B) |
| **Frontend** | SystemHealth trust panel (P0.5B) |
| **Failure Mode** | Intraday positions held overnight unnoticed (10 currently overdue) |
| **Missing Controls** | Review-only — no operator workflow; no auto-alert for approaching time stops |

## 19. Exit Management

| Field | Value |
|-------|-------|
| **Owning Script** | `paper_trade_closer.py`, `open_trade_manager.py` |
| **Input** | Stop hit, target hit, thesis broken, operator command |
| **Output** | exit_price, exit_reason in `paper_trades` |
| **Failure Mode** | Exit not recorded; reason not captured |
| **Missing Controls** | No "exit reason" taxonomy enforced; no exit-to-TCA link |

## 20. Post-Trade Review

| Field | Value |
|-------|-------|
| **Owning Script** | `closed_trade_postmortem_model.py`, `journal_agent_coach.py`, `trade_learning_engine.py` |
| **Input** | Closed trade data, R-multiple, strategy performance |
| **Output** | `trade_lesson_memory`, `strategy_lesson_rollup` |
| **API** | Journal endpoints |
| **Frontend** | AutomatedTradeJournal, JournalHub |
| **Failure Mode** | Lessons not generated for all trades |
| **Missing Controls** | No API endpoint for post-trade journal entries; no R-multiple outcome API |

## 21. Backtesting

| Field | Value |
|-------|-------|
| **Owning Script** | `enterprise_backtester.py`, `strategy_backtester.py`, `backtest_analyzer.py` |
| **Input** | Strategy config, historical data |
| **Output** | Backtest results (tables if present) |
| **Frontend** | Backtesting page |
| **Failure Mode** | Backtest disconnected from live config |
| **Missing Controls** | No comparison of live/paper results vs backtest expectations |

## 22. Learning Feedback

| Field | Value |
|-------|-------|
| **Owning Script** | `feedback_loop_processor.py`, `agent_calibration_engine.py`, `agent_outcome_scorer.py` |
| **Input** | Trade outcomes, agent predictions |
| **Output** | Calibration scores, agent performance metrics |
| **Cron** | feedback daily, calibration weekly |
| **Failure Mode** | Learning loop broken → system doesn't improve |
| **Missing Controls** | No visible feedback loop dashboard; no "what did the system learn" view |

## 23. Agent RACI

| Field | Value |
|-------|-------|
| **Config** | `config/agent_raci.yaml`, `config/agents.yaml` |
| **API** | `/api/v2/agent-collaboration` |
| **Frontend** | AgentCollaboration page |
| **Missing Controls** | RACI not enforced in code; no escalation path enforcement; agent ownership is informational only |

## 24. Operator Dashboard

| Field | Value |
|-------|-------|
| **Pages** | AutomatedTradeMode, PaperProposals, ExecutionQuality, SystemHealth, TradeAI, PipelineHub |
| **API** | All /api/v2/* endpoints |
| **Missing Controls** | No unified control-room page; lifecycle stages scattered across 6+ pages; no single-trade traceability view |

## 25. Alerting / Escalation

| Field | Value |
|-------|-------|
| **Owning Script** | `telegram_alert.py`, `telegram_alert_router.py`, `alert_dispatcher_unified.py`, `system_health_agent.py` |
| **Input** | All lifecycle events |
| **Output** | Telegram messages, `system_health_events` |
| **Failure Mode** | Alert fatigue; 64 direct senders bypass router; no ack tracking |
| **Missing Controls** | No alert acknowledgment; no SLA tracking; migration to central router incomplete |
