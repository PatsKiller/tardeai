# Trade AI v12 — Documentation Index

**Updated:** 2026-05-13
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
| `docs/v4_1_phase1_pilot_report.md` | Phase 1 pilot: gemma3:27b BATCH_OVERNIGHT test (1 symbol) |
| `docs/v4_1_phase1c_controlled_expansion_report.md` | Phase 1C: 2-symbol expansion test |
| `docs/v4_1_phase1d_limit5_report.md` | Phase 1D: 5-symbol expansion test |

### Operational Guides
| Document | Purpose |
|----------|---------|
| `docs/project/TRADE_SUPERVISION_METHODOLOGY.md` | **Trade supervision methodology** — monitoring frequency, metrics, stop/target rules, after-hours research, overnight pipeline |
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
