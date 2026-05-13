# Trade AI v12 — Documentation Index

**Updated:** 2026-05-12
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
| `docs/v4_1_phase1h_daily_deep_overnight_llm_window.md` | **Phase 1H** — daily 23:00–03:00 deep overnight LLM queue window (gemma3-overnight, 70-job target, 75 hard max) |

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
| 2026-05-13 | A1A audit: Phase 0 migration (7 scripts to local_llm.generate), two-tier rebalance advisor. Updated MASTER_SYSTEM (process-type routing, rebalance routing). |
| 2026-05-12 | A1A audit: Goals 1-6 resolved (7/13 gaps fixed), PM pipeline crons, Phase 1H expansion (5 new job types), R-tiers in open_trade_monitor. Updated MASTER_SYSTEM (schedule, R-tiers), VERIFIED_ASSESSMENT (gap status), FOCUSED_PLAN (gaps 4-5 done, score 7.5). |
| 2026-05-12 | Added VERIFIED_MATURITY_ASSESSMENT_2026-05-12.md (browser-verified 7.51/10, 13 gaps, session prompt). |
| 2026-05-12 | A1A audit: Gaps 3/6/7 implemented. Updated MASTER_SYSTEM_DOCUMENTATION (revalidation alerts, R-multiple tiers, outcome provenance), SYSTEM_ARCHITECTURE_COMPLETE (provenance hook), FOCUSED_IMPROVEMENT_PLAN (gaps marked done). |
| 2026-05-12 | Added FOCUSED_IMPROVEMENT_PLAN.md (corrected architect assessment, 7 gaps, maturity path). |
| 2026-05-12 | Added A1A protocol, LLM fleet v4.1 docs, Phase 1H doc, test reports, discovery artifacts. Flagged v3.4.1 as superseded. |
| 2026-05-11 | Initial index (Session 29, Phases 1-8) |
