# Trade AI v12 — Documentation Index

**Updated:** 2026-05-26
**Protocol:** Any documentation change must follow `/docs/A1A.md` protocol.

---

## Active Documents

### Protocol
| Document | Purpose |
|----------|---------|
| `docs/A1A.md` | **Documentation due-diligence protocol** — non-negotiable rules for keeping docs current, accurate, and consistent |

### Primary Reference
| Document | Purpose |
|----------|---------|
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | **Authoritative system reference** — 22 sections covering architecture, pipeline, data sources, strategies, agents, LLM, API, frontend, notifications, scheduling, security, production readiness |
| `docs/SYSTEM_AUDIT_2026-05-11.md` | Full system audit: 43 pages, 280+ endpoints, 152+ crons |
| `docs/project/SYSTEM_ARCHITECTURE_COMPLETE.md` | Complete system architecture detail |
| `docs/ARCHITECTURE_OVERVIEW.md` | Executive architecture summary |

### LLM Fleet v4.1
| Document | Purpose |
|----------|---------|
| `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` | **LLM fleet architecture** — process types, GPU lifecycle, phased rollout, gemma3:27b overnight, model routing. Supersedes v3.4.1 |
| `docs/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md` | Execution prompt for LLM fleet deployment — gates, hard rules, authorized steps |
| `docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md` | Operator-facing runbook for LLM fleet phases |
| `docs/v4_1_deployment_log.md` | **Living deployment log** — gate results, phase completions, deviations, rollback commands |
| `docs/v4_1_phase1h_daily_deep_overnight_llm_window.md` | **Phase 1H** — deep overnight LLM queue (100-job nightly + 400-job Friday, 12 job types, event-driven requeue, gemma3 calibration loop) |

### Phase 1 Test Reports (LLM Fleet)
| Document | Purpose |
|----------|---------|
| `docs/llm_fleet/phase2_embedding_ab/00_README.md` | **Phase 2 index** — read order, current gate status, next steps |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_a1a_scope.md` | Phase 2A A1A scope |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_preflight.md` | Phase 2A preflight gates |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_rag_embedding_discovery.md` | RAG architecture discovery |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_candidate_model_check.md` | Candidate model check (installed, tested) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_embedding_ab_queries.md` | 40 A/B queries across 20 categories |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_embedding_ab_report.md` | A/B results (nomic 23ms vs candidate 295ms) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_embedding_ab_results.json` | Raw JSON results |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_parallel_index_design.md` | Phase 2B design (NOT APPLIED) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_hybrid_retrieval_design.md` | Phase 2C design (NOT APPLIED) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2d_embedding_promotion_checklist.md` | Phase 2D checklist (BLOCKED) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_scope.md` | Phase 2B expansion scope (1K→5K) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_preflight.md` | Phase 2B expansion preflight |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_coverage_gap.md` | Source coverage gap analysis |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_build_report.md` | Build report (3,897 added, 0 fail) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_build_results.json` | Build results JSON |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_parallel_retrieval_report.md` | 5K parallel retrieval (QWEN3_BETTER) |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b_expand_5000_parallel_retrieval_results.json` | Parallel results JSON |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_expand_5000_hybrid_retrieval_report.md` | 5K hybrid retrieval report |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_expand_5000_hybrid_retrieval_results.json` | Hybrid results JSON |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2b2_expand_5000_evaluation_report.md` | **5K evaluation: QWEN3_BETTER, recommend offline pilot** |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_offline_integration_scope.md` | Phase 2C offline integration scope and safety |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_offline_integration_pilot_report.md` | Phase 2C 5-job pilot report |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_offline_integration_pilot_results.json` | Pilot results JSON |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_nightly_enable_scope.md` | Phase 2C nightly enablement scope |
| `docs/llm_fleet/phase2_embedding_ab/crontab_pre_phase2c_nightly_hybrid_enable.txt` | Pre-change crontab |
| `docs/llm_fleet/phase2_embedding_ab/crontab_post_phase2c_nightly_hybrid_enable.txt` | Post-change crontab |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_monitoring_rollback_fix.md` | Monitoring/rollback fix note |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2c_friday_hybrid_enable.md` | Friday extended hybrid enablement |
| `docs/llm_fleet/phase2_embedding_ab/crontab_pre_phase2c_friday_hybrid_enable.txt` | Pre-Friday crontab backup |
| `docs/llm_fleet/phase2_embedding_ab/crontab_post_phase2c_friday_hybrid_enable.txt` | Post-Friday crontab backup |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2d_bounded_offline_promotion.md` | **Phase 2D bounded offline promotion (approved)** |
| `docs/llm_fleet/phase2_embedding_ab/v4_1_phase2_final_closeout_report.md` | **Phase 2 final closeout** |
| `docs/v4_1_phase1_pilot_report.md` | Phase 1 pilot: gemma3:27b BATCH_OVERNIGHT test (1 symbol) |
| `docs/v4_1_phase1c_controlled_expansion_report.md` | Phase 1C: 2-symbol expansion test |
| `docs/v4_1_phase1d_limit5_report.md` | Phase 1D: 5-symbol expansion test |

### Operational Guides
| Document | Purpose |
|----------|---------|
| `docs/project/TRADE_SUPERVISION_METHODOLOGY.md` | **Trade supervision methodology** — monitoring, alert routing (AUTO/MANUAL), extended hours, trailing stops V2.4 |
| `docs/project/ROOT_CAUSE_ATM_DEAD_2026_05_26.md` | **Root cause: ATM dead 4 days** — 5 root causes, System Health Agent design, validation results |
| `docs/CHEAT_SHEET.md` | Operator quick reference |
| `docs/RESTORE_GUIDE.md` | Disaster recovery procedures |
| `docs/GPU_OLLAMA_SETUP.md` | Intel Arc B50 GPU setup for Ollama |
| `docs/COST_MODEL.md` | Cloud operating cost model |
| `docs/LLM_DATA_DICTIONARY.md` | **LLM data dictionary** — how data flows to every model call, 6 context types with source tables, anti-hallucination spec |

### Improvement Plans & Assessments
| Document | Purpose |
|----------|---------|
| `docs/project/VERIFIED_MATURITY_ASSESSMENT_2026-05-12.md` | **Browser-verified maturity assessment** — 12-domain scorecard (7.51/10), 13 confirmed gaps, session prompt for Goals 1-6 |
| `docs/project/FOCUSED_IMPROVEMENT_PLAN.md` | **Active improvement plan** — 7 verified gaps (3 done, 1 already resolved, 2 deferred), current score 7.0/10 |

### Strategy & Agent Configuration
| Document | Purpose |
|----------|---------|
| `docs/project/SKILLS.md` | **Skills & capabilities reference** — all agents, OpenClaw skills, system pipelines, LLM routing |
| `docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md` | 23 strategy definitions |
| `docs/project/agents_bible.md` | Agent behavior rules, G1-G10 global rules |
| `docs/project/project_openclaw.md` | OpenClaw gateway configuration |

### Reference (may need freshness check)
| Document | Purpose |
|----------|---------|
| `docs/project/SYSTEM_FACTS_LATEST.md` | System facts snapshot (check freshness) |
| `docs/IMPROVEMENT_PLAN_2026-05-11.md` | 8-phase improvement plan (all phases complete — historical) |

### Execution Safety — Phase 6
| Document | Purpose |
|----------|---------|
| `docs/execution_safety/phase6_market_revalidation/00_README.md` | **Phase 6 index** — market revalidation gate status, block conditions, commands |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_scope.md` | Phase 6A scope — approval flow, block conditions, safety gates |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_code_review.md` | Code review — fail-closed analysis, bypass search |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_test_results.md` | Unit test results (24/24 passed) |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_api_validation_report.md` | API mock validation (7/7 passed) |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_safety_audit.md` | Safety audit — 15 checks all passed |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6a_operator_runbook.md` | Operator runbook — troubleshooting, rollback, emergency procedures |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6b_session_policy_scope.md` | Phase 6B scope — market session policy gate |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6b_session_policy_test_results.md` | Unit tests (17/17) + API mock (9/9) |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6b_session_policy_safety_audit.md` | Safety audit — 19 checks |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6b_session_policy_runbook.md` | Operator runbook — session policy |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_trail_scope.md` | Phase 6C scope — approval audit trail |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_schema_report.md` | Audit schema (2 tables, 10 indexes) |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_trail_test_results.md` | Unit tests (12/12) + API mock (6/6) |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_trail_safety_audit.md` | Safety audit — 17 checks |
| `docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_trail_runbook.md` | Operator runbook — querying, troubleshooting |

### Governance & Maturity
| Document | Purpose |
|----------|---------|
| `docs/governance/phase_gov1_scheduled_facts_a1a/00_README.md` | **GOV-1** — Scheduled system facts + A1A compliance checks |
| `docs/governance/phase9c_scheduled_maturity_board/00_README.md` | **Phase 9C** — Scheduled maturity board + operator readiness |

### Frontend (Paper Proposals)
| Document | Purpose |
|----------|---------|
| `docs/frontend/phase_pp_ux1_paper_proposals_decision_packet/00_README.md` | **PP-UX-1** — Decision packet redesign: sector, thesis, rationale, guided workflow |
| `docs/frontend/phase_pp_ux2_proposal_trust_audit/00_README.md` | **PP-UX-2** — Trust audit: quote source, strategy fit, Fib/ORB/backtest evidence |

### Strategy Proof & Maturity
| Document | Purpose |
|----------|---------|
| `docs/strategy_proof/phase_sp2c_route_audit_pipeline_wiring/00_README.md` | **SP-2C** — Route audit wired into all 4 proposal creation paths |
| `docs/strategy_proof/phase_sp2b_route_audit_repair/00_README.md` | **SP-2B** — Route audit backfill, invalid strategy, config drift |
| `docs/strategy_proof/phase_sp2_strategy_watch_horizon_finviz_audit/00_README.md` | **SP-2** — Watch horizon, screener quality, assignment engine audit |
| `docs/maturity_hardening/` | Phase 9A/9B maturity reports, control board latest |
| `docs/governance/` | GOV-1 A1A results, governance status |

### Discovery Artifacts
| Document | Purpose |
|----------|---------|
| `docs/v4_1_discovery/` | LLM fleet v4.1 discovery: crontab backups, LLM reference scans, service units, schedule audits |

## Superseded (archive candidates)
| Document | Superseded by | Action |
|----------|---------------|--------|
| `docs/llm_fleet_strategy_v3_4_1.md` | `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` | Archive — v3.4.1 is superseded by v4.1 Final |

## Archived
All session-specific docs (Sessions 27-37) and dated operational briefs are in `docs/_archive/`.
Retained for historical reference but no longer authoritative.

## Change Log
| Date | Change |
|------|--------|
| 2026-05-16 | Phase 2 early install review added. Observed 2 Phase 1 scheduled runs and 1 Phase 2 scheduled run, safety remains green, no unsafe strings, dashboards/APIs return 200, freeze remains active. Added review and runbook docs under docs/project. |
| 2026-05-18 | **ALERT-3**: Dedicated proposal channel routing + Proposal Alerts page under Trading. 14 tests. Frontend build clean. |
| 2026-05-18 | **MISS-1**: Missed opportunity audit. 32 proposals, 8 rebuild, 12 missed. DWSN = avoided bad trade. 10 tests. |
| 2026-05-18 | **ALERT-2**: Telegram callbacks — approve/reject/rebuild/watch. DWSN approve blocked (5 gates). 17 tests. |
| 2026-05-18 | **ALERT-1**: Telegram proposal decision alerts. DWSN blocked alert generated. Blocked = no approve. 15 tests. |
| 2026-05-18 | **PROMOTE-1**: Pre-promotion readiness gate. R:R/price/spread/strategy checks before proposal creation. DWSN root cause fixed. 15 tests. |
| 2026-05-18 | **B-1E**: Nav audit — 5 orphan pages added to menu. Bucket 3 validated. Frontend build clean. |
| 2026-05-18 | **Q-1**: Proactive quote refresh. Provider trust policy, cron scheduled, 6 targets. 20 tests. |
| 2026-05-18 | **R-2**: Family + liquidity gates. 1,162 incompatible blocked. Distribution: momentum_scalp 51, swing_trade 25. 15 tests. |
| 2026-05-18 | **R-5**: YAML scoring_weights wired into router. earnings_post_momentum domination eliminated. Shadow: 78/81 top-match changed. 15 tests. |
| 2026-05-18 | **STRAT-ARCH-1**: Architecture due diligence — 5 areas, 22 gaps, prioritized roadmap. YAML weights unused by router (R-5 critical). 15 tests. |
| 2026-05-18 | **PAR-1**: Parallel hardening — quote freshness, route mismatch, source attribution, watchpool, regression runner, morning packet. 15 tests. |
| 2026-05-18 | **B-1C**: Bucket 2 watchpool operational, scalp boundary clean, migration dry-run no blockers. 13 tests. |
| 2026-05-18 | **A-5 Monday Observation**: Day 3, 22 proposals, 9 closed trades, SP-2C awaiting live exercise. NOT final A-5. |
| 2026-05-18 | **SP-2C**: Route audit wired into all 4 proposal creation paths. Future proposals get 23-strategy evaluation automatically. 17 tests. |
| 2026-05-18 | **SP-2B**: Route audit repair. Root cause: proposal generators bypass router. 74/83 missing, 46 mismatches, 6 invalid strategy. Backfill applied (72 proposals). 17 tests. |
| 2026-05-18 | **SP-2**: Strategy watch horizon + Finviz screener audit. 1,139 candidates audited. 74/83 proposals missing route audit. 13 strategies never selected. 16 tests. |
| 2026-05-18 | **PP-UX-2**: Proposal trust audit — quote source eligibility, strategy fit with YAML rule pass/fail, Fib/ORB/backtest evidence. 21 tests. |
| 2026-05-18 | **PP-UX-1**: Paper proposals decision packet redesign — sector, strategy thesis, entry rationale, guided workflow, approval blockers. 20 tests. |
| 2026-05-18 | **Phase 9C**: Scheduled maturity board + operator readiness reports. 14 tests. Cron at 07:55/08:00 M-F + Sunday. |
| 2026-05-18 | **BR-2A**: GOG/Drive offsite target validated. GPG ready. rclone NOT required. Encrypted backup path ready. |
| 2026-05-18 | **Phase 9B**: Maturity control board 7.1/10. Phase readiness gates. Live trading BLOCKED. 168 tests. |
| 2026-05-18 | **GOV-1**: Scheduled system facts + A1A checks. Cron at 07:40/07:45/07:50 M-F + Sunday 18:00. 157 tests. |
| 2026-05-18 | **SP-1**: Strategy proof governance. Evidence funnel + A-5 readiness. All 11 strategies blocked (A-5 incomplete). 145 tests. |
| 2026-05-18 | **DOC-CLEAN-1C**: 7 byte-identical duplicates deleted. 769 docs remaining. 0 non-identical deletes. |
| 2026-05-17 | **DOC-CLEAN-1B**: 401 files archived. Active tree: 246 docs. Archive: 526 docs. Duplicates deferred. |
| 2026-05-17 | **DOC-CLEAN-1**: 767 docs inventoried. 123 active, 490 archive candidates, 7 duplicate groups. Hygiene score 3.5/10. |
| 2026-05-17 | **Drive sync fix**: folder hierarchy + deletion cleanup. 774 files synced to Trade_AI_Docs_v2 with proper subdirectories. |
| 2026-05-17 | **BR-1**: Backup readiness 5.3/10. Daily DB healthy (867MB, 13.8h). P0: no offsite (rclone unconfigured). RPO/RTO + restore runbooks created. |
| 2026-05-17 | **Phase 9A**: Maturity hardening. System facts, sample governance, agent evidence gate, data fragility. All strategies BLOCKED (insufficient). Auto-learning BLOCKED (weak evidence). |
| 2026-05-16 | **Phase 8C**: Lifecycle dashboard reporting. 3 read-only API endpoints, report script, 7 tests. 114 total regression. |
| 2026-05-16 | **Phase 8B**: Lifecycle outcome scoring. 23 outcomes backfilled, 6 strategy scorecards (all preliminary/insufficient). Human-review only. |
| 2026-05-16 | **Phase 8A**: Lifecycle discovery. 83 proposals → 11 linked → 9 closed with full data. Joins strong. Phase 8B ready after A-5. |
| 2026-05-16 | **Phase 7**: Approval simulator. Read-only gate simulation, CLI + API endpoint, 15 tests, 98 total regression. No trades/orders/mutations. |
| 2026-05-15 | **UI stabilization sweep**: TaxLots React #310, StrategyDesk Decimal, MorningBriefBot timeout, scoreboard PF, plan adherence 0→11.1%. Session docs archived. |
| 2026-05-15 | **Screener config modal**: 18 screeners in DB, CRUD API, 4-tab modal (list/coverage/gaps/add), strategy coverage matrix, 0 gaps. |
| 2026-05-15 | **6 gap-fill screeners**: earnings_catalyst_pre, high_yield_bdc, bond_income_defensive, defense_aerospace, core_growth_compounders, core_index_etfs. All 20 strategies covered. |
| 2026-05-15 | **Promoter quality gates**: Spread > 3% blocks promotion. Momentum/scalp min price raised $1 → $3. 5/7 bad proposals would have been caught. |
| 2026-05-15 | **Post-A-4 Day 1**: Pipeline producing hourly proposals (4 in 4h). 19 scan signals. 1/5 activated strategies has proposal. A-5 deferred pending 3-5 day observation. |
| 2026-05-15 | **Phase 6E**: Scheduled stale sweeper. Pre-market dry-run (08:15), apply (08:25), EOD report (16:10). Wrapper with flock+safety gates. Rollback script. 12 tests, 83 total regression. |
| 2026-05-15 | **Phase 6D**: Proposal stale-time sweeper. Strategy-aware freshness thresholds, sweeper script (dry-run default), freshness gate before session/revalidation. 18 unit tests, 71 total regression. |
| 2026-05-15 | **RSI gate fix**: `screener` strategy added to momentum RSI gate group (>= 80 blocks). FLYW at RSI 83 would have been blocked. RSI now stored on proposal at promotion. |
| 2026-05-15 | **Phase 6B**: Market session policy gate. Approvals blocked outside regular hours (9:30-16:00 ET Mon-Fri non-holiday). 17 unit tests, 9 API mock scenarios. Wired into Phase 6C audit trail. |
| 2026-05-15 | **Phase 6C**: Paper approval audit trail. Every approval attempt recorded with gate-by-gate outcomes. 2 tables, helper module, 12 unit tests, 6 API mock scenarios, report script. Fail-closed on audit failure. |
| 2026-05-15 | **Phase 6A**: Paper approval market revalidation hardened. Live quote gate before risk gate. Blocks stale/unfavorable conditions. 24 unit tests, 7 API mock scenarios passed. Dashboard patched. Safety audit passed. Production unchanged. |
| 2026-05-14 | Phase 2 FINALIZED: Friday hybrid enabled. Phase 2D bounded offline promotion approved. Global embedding promotion blocked. Phase 2 closeout report written. |
| 2026-05-14 | Phase 2C nightly enablement: daily 23:00 deep queue now uses --enable-hybrid-rag with two-stage lifecycle. Friday unchanged. Cron updated. Production RAG/embeddings unchanged. |
| 2026-05-14 | Phase 2C offline integration pilot: hybrid_rag_context_adapter.py created, queue runner updated with --use-hybrid-rag opt-in. 20/20 jobs passed. RAG context added where none existed. No production changes. |
| 2026-05-14 | Phase 2B-Expanded: qwen3 index expanded 1K→4,897. Verdict upgraded QWEN3_BETTER (sim 0.647 vs 0.612, diversity 3.0 vs 1.4). Hybrid diversity 2.73. Recommend Phase 2C offline pilot. No production changes. |
| 2026-05-14 | Phase 2C: Hybrid retrieval pilot. 40 queries, HYBRID_MARGINAL verdict. Qwen3 finds 56.5% unique items but consensus only 2.5% (limited by 1K index). Recommend expanding to 5K. No production changes. |
| 2026-05-14 | Three-tier alert architecture deployed. 17 alert types classified (URGENT/DIGEST/DASHBOARD_ONLY). Digest crons at 8 AM + 4 PM. /v2/alerts page. Live facts: 344 tables, 401 scripts, 85 crons, 76 pages. |
| 2026-05-14 | Phase 2B: 1000-doc parallel index built with qwen3-embedding:8b. 40-query comparison: HYBRID_RECOMMENDED. Top-5 overlap 0.6%, source diversity +50%. No production changes. |
| 2026-05-14 | Phase 2 docs moved to docs/llm_fleet/phase2_embedding_ab/ (10 files). Created 00_README.md index. Cross-referenced from LLM_FLEET_STRATEGY. File paths updated in doc index. |
| 2026-05-14 | Documentation standards protocol created (DOCUMENTATION_STANDARDS.md). Export/backup and system facts regeneration scripts. Live counts: 341 tables, 397 scripts, 83 crons, 75 pages, 14786 embeddings. |
| 2026-05-14 | Phase 2A complete: qwen3-embedding:8b pulled and tested. 4096d, 295ms. Baseline nomic 768d, 23ms. Phase 2B GO recommended. No production changes. |
| 2026-05-14 | Session 35: Self-healing gap resolver scheduled (hourly+pre-overnight+weekly cron). Overnight dashboard v2 with parsed gemma3 outputs. Phase 1 finalized (quotas, health checks, reporter). Docs updated: MASTER §5.5, ARCH, CHEAT_SHEET, RESTORE_GUIDE. |
| 2026-05-13 | Session 34 hotfix: overnight queue crash — _safe_cc_float for LLM range strings, stuck job reset, timeout 180→300s, RAG SQL ingested_at fix. 23:00 window safe. |
| 2026-05-13 | Session 33: Strategy YAML patch — 22 strategies patched (vix_rules, technical_indicators, performance_context), 3 new strategies (fib_retracement_bounce, earnings_pre/post), 8 new screeners, earnings_catalyst deprecated, nightly perf cron. |
| 2026-05-13 | SESSION 31 END (55 commits): Strategy intelligence API, performance feedback in agent prompts, YAML audit exported. LLM context engine, data dictionary, broker source of truth, time stop, proposal card rebuild, RSI gate, 27 screeners. 4 trades closed, +$28.26. |
| 2026-05-13 | llm_context_engine.py: 6 context types (strategy/trade/risk/recovery/CC/proposal). All overnight prompts enriched. 129 jobs requeued. Time stop intraday fix. max_per_symbol=1. Duplicate symbol guard. Site audit fixes. |
| 2026-05-13 | paper-journal endpoint win rate fixed (14%→33%), empty positions API guard prevents phantom closes, GCTS phantom-close root cause fixed. Full audit: Alpaca=DB=API verified. |
| 2026-05-13 | Win rate fix: excludes phantom $0 breakevens (17%→33.3%). Reconciler reads actual exit price from broker order history. real_trade_count in API. |
| 2026-05-13 | Architectural fix: broker as source of truth. No paper_trades row before fill confirmation. broker_confirmed generated column. Integrity guards in monitor + journal API. PM crons --allow-underfilled. |
| 2026-05-13 | Paper trades data audit: fixed 5 stale R-multiples, INFU #21 stop/target from Alpaca, confirmed BLBD #15 cancelled not real loss. Alpaca = source of truth. |
| 2026-05-13 | TIME STOP auto-close: per-strategy max hold days (scalp 0d, swing 21d, sector 56d, income none). Verdict from P&L. INFU closed manually today; time stop would catch at day 21. |
| 2026-05-13 | Fix: stop recalculation on fill (GCTS ran unprotected — stop $1.52 > fill $1.49). Adapter now recalculates stop to 5% below fill. Pending→open promotion in sync. |
| 2026-05-13 | risk_gate _safe_float fix, manual pipeline test confirmed all bugs fixed, GCTS trade approval audit passed end-to-end (proposal→paper_trade→Alpaca fill). |
| 2026-05-13 | Fix: 3 pipeline bugs — screeners.yaml missing PM run_windows (1200/1400/1600/1730), db_adapter get_connection alias, risk_gate conn confirmed fixed. |
| 2026-05-13 | RSI overbought auto-block: _check_rsi_gate at promotion (>=80 momentum, >=75 swing), auto-expiry Rule 5, rsi_flag/rsi_flag_blocks_approval in API, red OVERBOUGHT badge in UI. Income/recovery exempt. |
| 2026-05-13 | Fix: proposal quality — price/RSI fallback from snapshots, data-driven thesis_display, strategy-group dedup (max 1/group), penny stock filter, multi-strategy warning in UI. |
| 2026-05-13 | Fix: stop breach auto-block (BLOCKED verdict, approve disabled), specific verdict reasons confirmed, orchestrator risk_gate conn bug fixed (was failing silently every run). |
| 2026-05-13 | Proposal card complete rebuild: 6-row layout (verdict/prices/metrics/timestamps/thesis/actions), specific verdict reasons in API, 2053→932 lines. Operator decision in 5 seconds, no clicks. |
| 2026-05-13 | Proposal operator UX: operator_verdict (READY/NEEDS_REVIEW/STALE/MISSED) per proposal, age display, verdict sort. Approval re-verification: RSI/RVOL/catalyst/VWAP/news live checks at approval time (2 new blocks, 5 warnings). |
| 2026-05-13 | Proposal pipeline: auto-expiry (3 rules), strategy-aware gate (20 global/5 per-strategy), Finviz 7x/day, promoter 5x/day, strategy perf in proposals API. |
| 2026-05-13 | Fix: paper_trades lifecycle_state never transitioning to 'closed' — 5 of 6 close paths missing lifecycle_state update. Fixed 5 scripts + migrated 17 stuck rows. Automated Journal now shows closed trades correctly. |
| 2026-05-13 | Strategy-aware overnight: 3 new job types (income Mon/growth Wed/reversion Sat), strategy-aware incubator grader (4 prompt groups), 7 new screeners (27 total), 16 static bond/BDC/cash symbols. All 20 strategies now have proposal pipeline path. |
| 2026-05-13 | LLM Queue Manager page (/v2/ops), 9 new API endpoints, event-driven requeue engine, 4 new Finviz screeners, strategy_opportunity_scan job, gemma3 calibration loop, Friday extended cron, updated Phase 1H doc + deployment log. |
| 2026-05-13 | Fix: deep overnight queue cap 70→100 (expansion job types were starved). Fix: .env quoting for FINVIZ_USER_AGENT/COOKIE + 5 direct parser scripts. Updated deployment log, Phase 1H doc. |
| 2026-05-13 | A1A audit: Phase 0 migration (7 scripts to local_llm.generate), two-tier rebalance advisor. Updated MASTER_SYSTEM (process-type routing, rebalance routing). |
| 2026-05-12 | A1A audit: Goals 1-6 resolved (7/13 gaps fixed), PM pipeline crons, Phase 1H expansion (5 new job types), R-tiers in open_trade_monitor. Updated MASTER_SYSTEM (schedule, R-tiers), VERIFIED_ASSESSMENT (gap status), FOCUSED_PLAN (gaps 4-5 done, score 7.5). |
| 2026-05-12 | Added VERIFIED_MATURITY_ASSESSMENT_2026-05-12.md (browser-verified 7.51/10, 13 gaps, session prompt). |
| 2026-05-12 | A1A audit: Gaps 3/6/7 implemented. Updated MASTER_SYSTEM_DOCUMENTATION (revalidation alerts, R-multiple tiers, outcome provenance), SYSTEM_ARCHITECTURE_COMPLETE (provenance hook), FOCUSED_IMPROVEMENT_PLAN (gaps marked done). |
| 2026-05-12 | Added FOCUSED_IMPROVEMENT_PLAN.md (corrected architect assessment, 7 gaps, maturity path). |
| 2026-05-12 | Added A1A protocol, LLM fleet v4.1 docs, Phase 1H doc, test reports, discovery artifacts. Flagged v3.4.1 as superseded. |
| 2026-05-11 | Initial index (Session 29, Phases 1-8) |

---

## 2026-05-22 ATM / Proposal / Execution Safety Context

| Document | Path | Status |
|----------|------|--------|
| ATM_V1_BUILD_PROMPT | `docs/prompts/ATM_V1_BUILD_PROMPT.md` | canonical |
| ATM_RUNBOOK | `docs/operator/ATM_RUNBOOK.md` | canonical |
| ATM_V1_BUILD_2026-05-22 | `docs/sessions/ATM_V1_BUILD_2026-05-22.md` | canonical |
| SUPPLY_TRIAGE_2026-05-22 | `docs/audits/SUPPLY_TRIAGE_2026-05-22.md` | canonical |
| PROPOSAL_SUPPLY_AUDIT_2026-05-22 | `docs/audits/PROPOSAL_SUPPLY_AUDIT_2026-05-22.md` | canonical |
| ATM_V1_DAY1_DASHBOARD_2026-05-22 | `docs/sessions/ATM_V1_DAY1_DASHBOARD_2026-05-22.md` | canonical |
| ATM_PRE_ACTIVE_FIXES_2026-05-22 | `docs/sessions/ATM_PRE_ACTIVE_FIXES_2026-05-22.md` | canonical |
| AUTO_ENRICHMENT_2026-05-22 | `docs/sessions/AUTO_ENRICHMENT_2026-05-22.md` | canonical |
| ATM_APPROVE_FAILED_2026-05-22 | `docs/audits/ATM_APPROVE_FAILED_2026-05-22.md` | canonical |
| STOP_MGMT_DISCOVERY_2026-05-23 | `docs/audits/STOP_MGMT_DISCOVERY_2026-05-23.md` | canonical |
| Context Sync 2026-05-22 | `docs/project/context_sync_2026_05_22/` | canonical (directory) |
| CURRENT_PROJECT_CONTEXT | `docs/project/CURRENT_PROJECT_CONTEXT.md` | canonical |

**Note:** `docs/current_state/SYSTEM_FACTS_LATEST.md` is a stale duplicate of `docs/project/SYSTEM_FACTS_LATEST.md`.
