# Trade AI v12 — Documentation Index

**Updated:** 2026-05-31
**Protocol:** Any documentation change must follow `/docs/A1A.md` protocol.

---

## Active — Authoritative Documents

### Protocol & Architecture
| Document | Purpose |
|----------|---------|
| `docs/A1A.md` | **Documentation due-diligence protocol** — non-negotiable |
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | **Authoritative system reference** — 22+ sections, model routing corrected, Hermes sidecar section added (rewritten 2026-05-31) |
| `docs/ARCHITECTURE_OVERVIEW.md` | ARCHIVED — consolidated into MASTER (2026-05-31) |
| `docs/project/SYSTEM_ARCHITECTURE_COMPLETE.md` | ARCHIVED — consolidated into MASTER (2026-05-31) |
| `docs/project/MASTER_REWRITE_AND_ARCHIVE_REPORT_2026_05_31.md` | Master rewrite report — 50+ corrections, 2 docs archived |

### Operational Guides
| Document | Purpose |
|----------|---------|
| `docs/CHEAT_SHEET.md` | Operator quick reference |
| `docs/RESTORE_GUIDE.md` | Disaster recovery procedures |
| `docs/GPU_OLLAMA_SETUP.md` | Intel Arc B50 GPU setup for Ollama |
| `docs/COST_MODEL.md` | Cloud operating cost model |
| `docs/LLM_DATA_DICTIONARY.md` | LLM data dictionary — 6 context types, anti-hallucination spec |
| `docs/MONDAY_BURNIN_CHECKLIST.md` | Monday morning burn-in checklist |
| `docs/operator/ATM_RUNBOOK.md` | ATM operator runbook |
| `docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md` | LLM fleet operator runbook |

### Strategy & Agent
| Document | Purpose |
|----------|---------|
| `docs/project/SKILLS.md` | **Skills & capabilities reference** — agents, pipelines, LLM routing (updated 2026-05-31) |
| `docs/project/agents_bible.md` | Agent behavior rules (G1-G10) |
| `docs/project/project_openclaw.md` | OpenClaw gateway configuration |
| `docs/AGENT_ROSTER.md` | Agent roster |
| `docs/AGENT_PAGES_DETAIL.md` | Agent page details |
| `docs/COMMAND_CENTER_PAGE_MATRIX.md` | Command Center page matrix |
| `docs/DOCS_ROSTER.md` | Documentation roster |
| `docs/APPENDIX_E_SCRIPT_ROUTING_MATRIX.md` | Script routing matrix |

### LLM Fleet v4.1
| Document | Purpose |
|----------|---------|
| `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` | LLM fleet architecture — phased rollout, model routing |
| `docs/llm_fleet/phase2_embedding_ab/` | Phase 2 embedding A/B — 25+ test reports, QWEN3_BETTER verdict |

### Execution Safety (Phase 6)
| Document | Purpose |
|----------|---------|
| `docs/execution_safety/phase6_market_revalidation/` | Phase 6A-C — market revalidation, session policy, audit trail (24+17+12 tests) |

### Governance & Maturity
| Document | Purpose |
|----------|---------|
| `docs/governance/` | GOV-1 A1A compliance + Phase 9C maturity board |
| `docs/maturity_hardening/` | Maturity reports and control board |

### Strategy Proof
| Document | Purpose |
|----------|---------|
| `docs/strategy_proof/` | SP-2, SP-2B, SP-2C — route audit, screener quality, watch horizon |

### Frontend
| Document | Purpose |
|----------|---------|
| `docs/frontend/` | PP-UX-1 (decision packet) + PP-UX-2 (trust audit) |

### Session 2026-05-29/30 — Classifier, Proposals, Hermes
| Document | Purpose |
|----------|---------|
| `docs/project/SESSION_2026_05_29_FINAL_SUMMARY.md` | **Session summary** — 40+21 commits, classifier 100%, proposals P0/P1, ATM audit, Hermes P0-P1D |
| `docs/project/MEMORY_NOTES_FOR_NEXT_SESSION_2026_05_29_FINAL.md` | Durable memory notes |
| `docs/project/NEXT_SESSION_RUNBOOK_2026_05_29_FINAL.md` | Runbook — preflight, visual check, remaining work |
| `docs/project/SYSTEM_HEALTH_AGENT_ARCHITECTURE.md` | System health agent architecture with Claude Code escalation |
| `docs/atm_lifecycle_v1_2026_05_29/` | Classifier completion, SHFS 860, proposal fixes, backtesting UI, ATM audit (46 files) |

### Hermes Sidecar (v4)
| Document | Purpose |
|----------|---------|
| `docs/hermes/Hermes_Sidecar_Strategy_for_Trade_AI_v4.md` | Strategic design — 6 pods, 24 agents, research desk |
| `docs/hermes/HERMES_COMPATIBILITY_AUDIT.md` | Compatibility audit — no blockers |
| `docs/hermes/HERMES_DATABASE_FIRST_INTEGRATION_ARCHITECTURE.md` | DB-first architecture — 6 hermes_* tables, roles, views |
| `docs/hermes/HERMES_PHASE_P0_FINAL_GATE.md` | P0 final gate — GO |
| `docs/hermes/HERMES_PHASE_P0_INSTALL_REPORT.md` | P0 install — v0.15.2 |
| `docs/hermes/HERMES_PHASE1_DB_STAGING_REPORT.md` | Phase 1 — 6 tables, 34 indexes |
| `docs/hermes/HERMES_PHASE1A_DB_ROLES_REPORT.md` | Phase 1A — roles, grants |
| `docs/hermes/HERMES_PHASE1B_RUNTIME_STAGING_WRITES_REPORT.md` | Phase 1B — staging ingestion |
| `docs/hermes/HERMES_PHASE1C_PRODUCTION_READ_ACCESS_MAP.md` | Phase 1C — 392 tables audited |
| `docs/hermes/HERMES_PHASE1C_SAFE_VIEW_DRAFTS.sql` | 8 safe view SQL ([Drive](https://drive.google.com/file/d/1BNdg-XOamE_reOkbrvURUfHTRF0DXTzy/view)) |
| `docs/hermes/HERMES_PHASE1C_READ_GRANT_DRAFTS.sql` | Read grant SQL ([Drive](https://drive.google.com/file/d/1AsFcrjgfBfIXYr-RlriRBWMYV_yl0QmJ/view)) |
| `docs/hermes/HERMES_PHASE1C_SECURITY_FINDINGS.md` | Security findings — 14 denied, 10 masked |
| `docs/hermes/HERMES_PHASE1D_VIEWS_AND_GRANTS_REPORT.md` | Phase 1D — 8 views, 40 grants APPLIED |
| `docs/hermes/HERMES_ROLLBACK_PLAN.md` | Rollback — `rm -rf hermes_sidecar/` |
| `docs/hermes/discovery/` | Gate 1 discovery artifacts |

### Hermes Phase 7 — Pipeline Quality Loop
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE7A_PIPELINE_QUALITY_DRY_RUN_REPORT.md` | Phase 7A dry-run — 3 findings |
| `docs/hermes/HERMES_PHASE7B_PIPELINE_QUALITY_STAGING_REPORT.md` | Phase 7B — 3 validation findings staged |
| `docs/hermes/HERMES_PHASE7C_PIPELINE_QUALITY_DASHBOARD_REPORT.md` | Phase 7C — dashboard section |
| `docs/hermes/HERMES_PHASE7D_PIPELINE_QUALITY_USEFULNESS_AUDIT.md` | Phase 7D — quality PASS |
| `docs/hermes/HERMES_PHASE7E_PIPELINE_QUALITY_LOOP_CLOSEOUT.md` | Phase 7E closeout |
| `docs/hermes/HERMES_PHASE7F_OLLAMA_MODEL_SAFETY_RECONCILIATION.md` | Phase 7F — model audit PASS |
| `docs/hermes/HERMES_PHASE7G_MODEL_RECONCILIATION_CLOSEOUT.md` | Phase 7G closeout |
| `docs/hermes/HERMES_PHASE8A_PORTFOLIO_REFLECTION_DRY_RUN_REPORT.md` | Phase 8A dry-run PASS |
| `docs/hermes/HERMES_PHASE8B_PORTFOLIO_REFLECTION_STAGING_REPORT.md` | Phase 8B — 3 reflections staged |
| `docs/hermes/HERMES_PHASE8C_PORTFOLIO_REFLECTION_DASHBOARD_REPORT.md` | Phase 8C — dashboard verified |
| `docs/hermes/HERMES_PHASE8D_PORTFOLIO_REFLECTION_USEFULNESS_AUDIT.md` | Phase 8D — quality PASS |
| `docs/hermes/HERMES_PHASE8E_PORTFOLIO_REFLECTION_LOOP_CLOSEOUT.md` | Phase 8E closeout |
| `docs/hermes/HERMES_PHASE9A_OBSERVATION_AND_STABILITY_AUDIT.md` | Phase 9A — stability PASS |
| `docs/hermes/HERMES_PHASE9D_OBSERVATION_AND_INFRA_PLANNING_CLOSEOUT.md` | **Phase 9D closeout** |
| `docs/infra/DOCKER_CONTAINERIZATION_ARCHITECTURE_AUDIT_2026_05_31.md` | Docker architecture — design only |
| `docs/infra/DOCKER_READINESS_CHECKLIST.md` | Docker readiness checklist |
| `docs/infra/DOCKER_ROLLBACK_RUNBOOK.md` | Docker rollback runbook |
| `docs/infra/DOCKER_PHASED_MIGRATION_PLAN.md` | 5-phase Docker migration plan |

### Session Closeout
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_FULL_SESSION_CLOSEOUT_2026_05_31.md` | **Full Hermes session closeout** — 101 commits, P0-P9, MASTER rewrite, Docker planning |
| `docs/project/SESSION_2026_05_31_HERMES_FULL_CLOSEOUT_SUMMARY.md` | Operator summary |
| `docs/hermes/HERMES_PHASE11A_OBSERVATION_HEALTH_CHECK.md` | Phase 11A — observation PASS |
| `docs/infra/DOCKER_PHASE11B_NONPROD_PREVIEW_PILOT_REPORT.md` | Phase 11B — Docker pilot PASS (static docs, cleaned up) |
| `docs/project/PHASE11_OBSERVATION_AND_DOCKER_PREVIEW_CLOSEOUT.md` | Phase 11 closeout |
| `docs/infra/DOCKER_PHASE12A_VERSION_CHECK_PILOT_DESIGN.md` | Phase 12A design |
| `docs/infra/DOCKER_PHASE12B_VERSION_CHECK_PILOT_RUN_REPORT.md` | Phase 12B — version-check PASS |
| `docs/infra/DOCKER_PHASE12C_VERSION_CHECK_SAFETY_AUDIT.md` | Phase 12C — safety PASS |
| `docs/project/PHASE12_DOCKER_VERSION_CHECK_CLOSEOUT.md` | Phase 12 closeout |
| `docs/hermes/HERMES_PHASE13B_PROMOTION_REVIEW_DRY_RUN_REPORT.md` | Phase 13B — review dry-run, 3 candidates |
| `docs/hermes/HERMES_PHASE13C_PROMOTION_REVIEW_USEFULNESS_AUDIT.md` | Phase 13C — quality PASS |
| `docs/project/PHASE13_PROMOTION_REVIEW_LOOP_CLOSEOUT.md` | Phase 13 closeout |
| `docs/hermes/HERMES_PHASE14B_PROMOTION_REVIEW_DASHBOARD_IMPLEMENTATION_REPORT.md` | Phase 14B — dashboard preview |
| `docs/hermes/HERMES_PHASE14C_PROMOTION_REVIEW_DASHBOARD_SAFETY_AUDIT.md` | Phase 14C — safety PASS |
| `docs/project/PHASE14_PROMOTION_REVIEW_DASHBOARD_CLOSEOUT.md` | **Phase 14 closeout** |
| `docs/hermes/HERMES_PHASE15_PROMOTION_EXECUTION_REPORT.md` | **Phase 15** — 3 candidates promoted (FJSCX, APAM, TRX) |

### SearXNG Shared Search Layer (Phase 16)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_SHARED_LAYER_ARCHITECTURE.md` | Architecture — internal-only, port plan, future gates |
| `docs/infra/SEARXNG_PHASE16_INSTALL_REPORT.md` | Phase 16B — Docker Compose standup, 127.0.0.1:18888 |
| `docs/infra/SEARXNG_PHASE16_SAFETY_AUDIT.md` | Phase 16C — safety PASS |
| `docs/infra/SEARXNG_PHASE16_COMMAND_CENTER_VISIBILITY_REPORT.md` | Phase 16D — read-only System Applications visibility |
| `docs/infra/SEARXNG_OPERATOR_RUNBOOK.md` | Operator runbook — status, logs, restart, rollback, privacy |
| `docs/project/PHASE16_SEARXNG_SHARED_LAYER_CLOSEOUT.md` | **Phase 16 closeout** |

### SearXNG Manual Query Wrapper (Phase 17)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_PHASE17A_MANUAL_WRAPPER_ARCHITECTURE.md` | Phase 17A — wrapper design |
| `docs/infra/SEARXNG_PHASE17B_MANUAL_WRAPPER_IMPLEMENTATION_REPORT.md` | Phase 17B — implementation + test |
| `docs/infra/SEARXNG_PHASE17C_MANUAL_WRAPPER_SAFETY_AUDIT.md` | Phase 17C — safety PASS |
| `docs/infra/SEARXNG_PHASE17D_COMMAND_CENTER_QUERY_VISIBILITY_DESIGN.md` | Phase 17D — CC visibility design (docs only) |
| `docs/project/PHASE17_SEARXNG_MANUAL_WRAPPER_CLOSEOUT.md` | **Phase 17 closeout** |

### SearXNG Source Discovery Dry-Run (Phase 18)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_PHASE18A_SOURCE_DISCOVERY_DRY_RUN_ARCHITECTURE.md` | Phase 18A — discovery architecture |
| `docs/infra/SEARXNG_PHASE18B_SOURCE_DISCOVERY_DRY_RUN_REPORT.md` | Phase 18B — 5 queries, 10 candidates |
| `docs/infra/SEARXNG_PHASE18C_SOURCE_DISCOVERY_QUALITY_AUDIT.md` | Phase 18C — quality PASS (4.5/5) |
| `docs/infra/SEARXNG_PHASE18D_FUTURE_INGESTION_MAPPING_DESIGN.md` | Phase 18D — ingestion mapping design |
| `docs/infra/searxng_phase18_source_discovery_dryrun/` | Dry-run output files |
| `docs/project/PHASE18_SEARXNG_SOURCE_DISCOVERY_DRY_RUN_CLOSEOUT.md` | **Phase 18 closeout** |

### SearXNG Staged Source Ingestion (Phase 19)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_PHASE19A_STAGED_INGESTION_REVALIDATION.md` | Phase 19A — 5 candidates validated |
| `docs/infra/SEARXNG_PHASE19B_STAGED_INGESTION_REPORT.md` | Phase 19B — 5 rows staged (ids 12–16) |
| `docs/infra/SEARXNG_PHASE19B_STAGED_INGESTION_ROLLBACK.sql` | Phase 19B rollback SQL |
| `docs/infra/SEARXNG_PHASE19C_STAGED_INGESTION_SAFETY_AUDIT.md` | Phase 19C — safety PASS |
| `docs/infra/SEARXNG_PHASE19D_STAGED_SOURCE_VISIBILITY_DESIGN.md` | Phase 19D — visibility design (docs only) |
| `docs/project/PHASE19_SEARXNG_STAGED_SOURCE_INGESTION_CLOSEOUT.md` | **Phase 19 closeout** |

### Hermes Agent Model and Actionability (Phase 20)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_AGENT_OPERATING_MODEL.md` | Agent operating model — 7 agents, source-of-truth hierarchy |
| `docs/hermes/HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md` | Agent contracts — mission, reads, writes, forbidden, caps |
| `docs/hermes/HERMES_ADVISORY_ACTIONABILITY_STANDARD.md` | Advisory actionability — 16 fields, 11 failure classes |
| `docs/hermes/HERMES_TELEGRAM_AND_COMMUNICATION_RETENTION_AUDIT.md` | Retention audit — payloads not stored |
| `docs/hermes/HERMES_TELEGRAM_REVIEW_ACTIONABILITY_GATE.md` | Actionability gate for weekly reviews |
| `docs/hermes/HERMES_TELEGRAM_REVIEW_ACTIONABILITY_DRY_RUN.md` | Dry-run: vague_rebalance_recommendation HIGH |
| `docs/project/PHASE20_HERMES_AGENT_MODEL_AND_ACTIONABILITY_CLOSEOUT.md` | **Phase 20 closeout** |

### Hermes Librarian Dry-Run (Phase 21)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE21A_LIBRARIAN_DRY_RUN_DESIGN.md` | Phase 21A — 17 check types |
| `docs/hermes/HERMES_PHASE21B_LIBRARIAN_STAGED_SOURCE_DRY_RUN_REPORT.md` | Phase 21B — 18 rows, 6 findings |
| `docs/hermes/HERMES_PHASE21C_COMMUNICATION_ACTIONABILITY_DRY_RUN_REPORT.md` | Phase 21C — Telegram FAIL |
| `docs/hermes/HERMES_PHASE21D_LIBRARIAN_USEFULNESS_AND_SAFETY_AUDIT.md` | Phase 21D — PASS (4.6/5) |
| `docs/hermes/phase21_librarian_dryrun/` | Librarian dry-run output files |
| `docs/hermes/phase21_communication_actionability_dryrun/` | Communication actionability output |
| `docs/project/PHASE21_HERMES_LIBRARIAN_DRY_RUN_CLOSEOUT.md` | **Phase 21 closeout** |

### Research Backlog Staged-Write Pilot (Phase 22)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE22A_RESEARCH_BACKLOG_TARGET_REVALIDATION.md` | Phase 22A — target validated |
| `docs/hermes/HERMES_PHASE22B_RESEARCH_BACKLOG_STAGED_WRITE_REPORT.md` | Phase 22B — 5 rows staged (ids 19–23) |
| `docs/hermes/HERMES_PHASE22B_RESEARCH_BACKLOG_STAGED_WRITE_ROLLBACK.sql` | Phase 22B rollback SQL |
| `docs/hermes/HERMES_PHASE22C_RESEARCH_BACKLOG_SAFETY_AUDIT.md` | Phase 22C — safety PASS |
| `docs/hermes/HERMES_PHASE22D_RESEARCH_BACKLOG_DASHBOARD_DESIGN.md` | Phase 22D — dashboard design (docs only) |
| `docs/project/PHASE22_RESEARCH_BACKLOG_STAGED_WRITE_CLOSEOUT.md` | **Phase 22 closeout** |

### Income-Rotation Research Discovery (Phase 23)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE23A_INCOME_ROTATION_RESEARCH_PLAN.md` | Phase 23A — 9 sleeves, evidence requirements |
| `docs/hermes/HERMES_PHASE23B_INCOME_ROTATION_DISCOVERY_REPORT.md` | Phase 23B — 8 queries, 55 candidates |
| `docs/hermes/HERMES_PHASE23C_INCOME_ROTATION_CANDIDATE_SCORING.md` | Phase 23C — 7 sleeves scored |
| `docs/hermes/HERMES_PHASE23D_INCOME_ROTATION_ACTIONABILITY_AUDIT.md` | Phase 23D — actionability 0.15→0.78 |
| `docs/hermes/phase23_income_rotation_discovery/` | Discovery output files |
| `docs/project/PHASE23_INCOME_ROTATION_RESEARCH_CLOSEOUT.md` | **Phase 23 closeout** |

### Research Backlog Dashboard (Phase 24)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE24A_RESEARCH_BACKLOG_DASHBOARD_IMPLEMENTATION_PLAN.md` | Phase 24A — plan |
| `docs/hermes/HERMES_PHASE24B_RESEARCH_BACKLOG_DASHBOARD_IMPLEMENTATION_REPORT.md` | Phase 24B — GET endpoint + UI |
| `docs/hermes/HERMES_PHASE24C_RESEARCH_BACKLOG_DASHBOARD_SAFETY_AUDIT.md` | Phase 24C — safety PASS |
| `docs/project/PHASE24_RESEARCH_BACKLOG_DASHBOARD_CLOSEOUT.md` | **Phase 24 closeout** |

### Embedding Curator Dry-Run (Phase 25)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE25A_EMBEDDING_CURATOR_DRY_RUN_DESIGN.md` | Phase 25A — 11 dimensions, rejection criteria |
| `docs/hermes/HERMES_PHASE25B_EMBEDDING_CURATOR_DRY_RUN_REPORT.md` | Phase 25B — 10 scored, 2 pilot recs |
| `docs/hermes/HERMES_PHASE25C_EMBEDDING_CURATOR_SAFETY_AUDIT.md` | Phase 25C — safety PASS |
| `docs/hermes/phase25_embedding_curator_dryrun/` | Curator output files |
| `docs/project/PHASE25_EMBEDDING_CURATOR_DRY_RUN_CLOSEOUT.md` | **Phase 25 closeout** |

### Hermes Trade AI Coverage Audit (Phase 28)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE28A_TRADEAI_DATA_SURFACE_INVENTORY.md` | Phase 28A — 10 surfaces mapped |
| `docs/hermes/HERMES_PHASE28B_HERMES_COVERAGE_GAP_AUDIT.md` | Phase 28B — 6 NOT COVERED, 4 views needed |
| `docs/hermes/HERMES_PHASE28C_MOMENTUM_SCOUT_AND_CATALYST_AUDIT.md` | Phase 28C — catalyst pipeline mapped |
| `docs/hermes/HERMES_PHASE28D_JOURNAL_BACKTESTING_LIBRARIAN_DESIGN.md` | Phase 28D — 16 Librarian checks |
| `docs/hermes/HERMES_PHASE28E_TRADEAI_TO_HERMES_BACKLOG_INTEGRATION_PLAN.md` | Phase 28E — 13 backlog item types |
| `docs/project/PHASE28_HERMES_TRADEAI_COVERAGE_AUDIT_CLOSEOUT.md` | **Phase 28 closeout** |

### Hermes Safe View Coverage (Phase 29)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE29A_SAFE_VIEW_SQL_DESIGN.md` | Phase 29A — 4 views designed |
| `docs/hermes/HERMES_PHASE29B_SAFE_VIEW_APPLY_REPORT.md` | Phase 29B — 4 views + grants applied |
| `docs/hermes/HERMES_PHASE29C_SAFE_VIEW_SECURITY_AUDIT.md` | Phase 29C — security PASS |
| `docs/hermes/HERMES_PHASE29D_COVERAGE_RECHECK.md` | Phase 29D — coverage 4/10 → 9/10 |
| `docs/hermes/HERMES_PHASE29E_MORNING_BRIEF_STORAGE_DESIGN.md` | Phase 29E — morning brief storage design |
| `sql/migrations/20260601_hermes_phase29_safe_views.sql` | Migration SQL |
| `sql/migrations/20260601_hermes_phase29_safe_views_rollback.sql` | Rollback SQL |
| `docs/project/PHASE29_HERMES_SAFE_VIEW_COVERAGE_CLOSEOUT.md` | **Phase 29 closeout** |

### Expanded Librarian Dry-Run (Phase 30)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE30A_EXPANDED_LIBRARIAN_DRY_RUN_DESIGN.md` | Phase 30A — 14 checks |
| `docs/hermes/HERMES_PHASE30B_EXPANDED_LIBRARIAN_DRY_RUN_REPORT.md` | Phase 30B — 21 findings |
| `docs/hermes/HERMES_PHASE30C_EXPANDED_LIBRARIAN_SAFETY_AUDIT.md` | Phase 30C — PASS (4.25/5) |
| `docs/hermes/HERMES_PHASE30D_EXPANDED_BACKLOG_STAGED_WRITE_MAPPING.md` | Phase 30D — staging mapping |
| `docs/hermes/phase30_expanded_librarian_dryrun/` | Dry-run output files |
| `docs/project/PHASE30_EXPANDED_LIBRARIAN_DRY_RUN_CLOSEOUT.md` | **Phase 30 closeout** |

### Expanded Backlog Staging (Phase 32)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE32A_EXPANDED_BACKLOG_REVALIDATION.md` | Phase 32A — 5 candidates validated |
| `docs/hermes/HERMES_PHASE32B_EXPANDED_BACKLOG_STAGING_REPORT.md` | Phase 32B — 5 rows staged (ids 24–28) |
| `docs/hermes/HERMES_PHASE32B_EXPANDED_BACKLOG_STAGING_ROLLBACK.sql` | Phase 32B rollback SQL |
| `docs/hermes/HERMES_PHASE32C_EXPANDED_BACKLOG_SAFETY_AUDIT.md` | Phase 32C — safety PASS |
| `docs/hermes/HERMES_PHASE32D_BACKLOG_DASHBOARD_REFRESH_VERIFICATION.md` | Phase 32D — dashboard 10 items verified |
| `docs/project/PHASE32_EXPANDED_BACKLOG_STAGING_CLOSEOUT.md` | **Phase 32 closeout** |

### Generated Output (not authoritative)
| Path | Content |
|------|---------|
| `docs/_generated/` | Governance reports, maturity snapshots, brief archive |
| `docs/playwright/` | Playwright screenshot archives |

---

## Archived (docs/_archive/)

1,276 files. Includes superseded versions, dated audits, executed prompts, session tarballs.
Archived this pass (2026-05-31):
- 4 top-level .tgz → `_archive/tarballs/`
- 2 session files (2026-05-27/28) → `_archive/reports/`
- 1 CC execution prompt → `_archive/prompts/`
- 1 ATM build prompt → `_archive/prompts/`
- 4 one-off dirs (drive_cleanup, cleanup, sessions) → `_archive/reports/`

## Trashed (docs/_trash/)

15 files. Morning briefs >7 days old + 2 empty files. Recoverable.

## Moved Outside docs/

- `~/backups/trade_ai_backup_20260524.zip` (2.9G) — was in docs/backups/

---

## Deferred — Next Session

- **MASTER architecture rewrite**: Replace all qwen3:14b references with gemma3:12b, update counts, refresh all 22 sections against live system
- **Architecture trio consolidation**: Merge MASTER + ARCHITECTURE_OVERVIEW + SYSTEM_ARCHITECTURE_COMPLETE into single authoritative source
- **Morning brief generator output path**: Change `aegis_morning_brief_delivery.py:403` to write to `docs/_generated/aegis_daily_briefs/` instead of `docs/` root

## Change Log

| Date | Change |
|------|--------|
| 2026-05-31 | A1A hygiene pass: archive 30 files, trash 15, fix SKILLS.md model refs, add MASTER stale warning, update counts (392 tables, ~190 crons, 24 strategies), thin index from 398→~120 lines |
| 2026-05-30 | Hermes P0-P1D docs, Phase 1C SQL drafts synced to Drive |
| 2026-05-29 | Classifier 100%, proposal P0/P1, backtesting UI, ATM audit, lifecycle inspector |
| 2026-05-28 | LLM safety, classifier enrichment, Ollama upgrade, model canaries |
