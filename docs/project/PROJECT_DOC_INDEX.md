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
| `docs/project/PHASE12_DOCKER_VERSION_CHECK_CLOSEOUT.md` | **Phase 12 closeout** |

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
