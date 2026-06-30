# Trade AI v12 — Documentation Index
**Updated:** 2026-06-24
**Protocol:** All doc changes follow `docs/A1A.md`. Do not add a doc without updating this index.
**Scope:** Project root = `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

> **Verified 2026-06-19:** every path below was checked against the filesystem. Paths corrected where
> the source draft had drifted, and docs that are actually in `docs/_archive/` are listed as archived
> rather than active (see **Index Corrections** at the bottom). This is an A1A requirement — the index
> must not point at phantom or mislocated files.

---

## TIER 1 — Canonical References (read these first, trust these most)

| Document | Purpose | Status |
|----------|---------|--------|
| `docs/A1A.md` | **Documentation due-diligence protocol** — what must stay current, drift detection, P0/P1/P2 meaning | Active |
| `docs/LIVE_SYSTEM_FACTS.md` | **Live scale counts** — tables/crons/scripts/strategies; regenerate via `generate_system_facts.py` | Active (2026-06-22) |
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | **Authoritative system reference** — architecture, pipeline, data, strategies, agents, LLM, API, frontend | Active |
| `docs/project/Trade_AI_v12_Reference_Architecture.docx` | **Canonical architecture DOCX** — updated append-only each session (latest: Session 2026-06-19) | Active |
| `docs/atm_audit_2026_05_26/SYSTEM_ARCHITECTURE_COMPLETE.md` | Complete architecture detail — tables, endpoints, cron map *(path corrected)* | Active |
| `docs/CHEAT_SHEET.md` | Operator quick reference — commands, models, cron, diagnostics | Active (counts → LIVE_SYSTEM_FACTS) |
| `docs/RESTORE_GUIDE.md` | Disaster recovery — holdings guard, deploy-zip rule, DB restore, rollback | Active |

---

## TIER 2 — Active Operational Docs

### Security & Safety
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/project/TRADE_SUPERVISION_METHODOLOGY.md` | Trade monitoring, stop/target rules, after-hours research, overnight pipeline | Active |
| `docs/GPU_OLLAMA_SETUP.md` | Intel Arc + Ollama setup, model list, GPU memory map | Active |
| `docs/MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` | **Momentum-scalp layered stop/trail policy** — initial/breakeven/risk active; Chandelier trailing gated on a fresh backtest (STOP-V2.4 prior); validation gate + monitoring | Active (2026-06-29, paper validation phase) |
| `docs/COST_MODEL.md` | Cloud LLM operating cost model, budget gates | Active |
| `docs/LLM_DATA_DICTIONARY.md` | Data flow to every model call, 6 context types, anti-hallucination spec | Active |

### LLM Fleet v4.1 (canonical set)
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` | Fleet architecture — process types, GPU lifecycle, phased rollout, overnight routing | Canonical |
| `docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md` | Operator runbook — phase gates, rollback triggers | Active |
| `docs/v4_1_deployment_log.md` | **Living deployment log** — fleet state, phase completions, 2026-08-11 gemma4 eval gate | Active — created 2026-06-19 (d09a653c) |
| `docs/_archive/prompts/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md` | CC execution prompt for fleet deploy | **Archived** *(was listed active; lives in _archive)* |

### Broker Integration *(paths corrected — these live under docs/architecture & docs/brokers)*
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md` | Schwab Phase 1 read-only — proven capabilities, fenced writes, Gate A | Active |
| `docs/architecture/SCHWAB_API_CAPABILITY_MAP.md` | Every Schwab endpoint → BUILT / READY / FENCED / NEVER | Active |
| `docs/brokers/stage2a-canary-protocol.md` | Stage 2a canary runbook — gap patches, risk caps, approval flow | Active — canary date set to **2026-06-22** in `canary_gate.py` |
| `docs/brokers/stop-management-architecture.md` | Canonical as-built stop/trailing architecture (Schwab live, Alpaca auto, Fidelity monitor) | Active (2026-06-22) |
| `docs/brokers/snaptrade-read-only-aggregation-spec.md` | SnapTrade holdings read path (Fidelity rollover IRA) | Active |
| `docs/brokers/snaptrade-fidelity-protective-stops-spec.md` | Fidelity monitor-only stops + one-share SnapTrade test (no sandbox) | Active (2026-06-22) |

### Proposal & Execution Paths
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/PROPOSAL_EXECUTION_PATHS.md` | **Canonical two-path model** — Path A paper auto (Alpaca test) vs Path B live (Schwab 2FA / Fidelity FA manual) | Active (2026-06-23) |
| `docs/BROKER_PROPOSALS_UI.md` | **Broker Proposals live desk** — thesis validity bar, refresh/recalibrate, account picker, cloud oversight | Active (2026-06-24) |
| `docs/COMMAND_CENTER_RISK_VISUALIZATIONS.md` | **Risk visualization layer** — Recharts components, hub integration map, library roadmap | Active (2026-06-24) |
| `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md` | Options desk execution labels — same auto vs manual split as equity proposals | Active (2026-06-24) |

### Rotation Intelligence *(paths corrected — docs/project/)*
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/project/ROTATION_PRODUCTION_READINESS_2026-06-19.md` | Rotation advisory readiness — trust_verdict, dual-LLM, no-override rule | Active (2026-06-19) |
| `docs/project/V3_TRUST_HARDENING_AND_ROTATION_INTELLIGENCE.md` | v3 trust hardening + rotation intelligence baseline | Active (2026-06-16) |
| `docs/project/ROTATION_LLM_ADVISOR.md` | `rotation_llm_advisor.py` runbook — advisory only, safety contract | Active (2026-06-18) |

### Strategy & Agent Configuration
| Document | Purpose | Status |
|----------|---------|--------|
| `config/strategies/*.yaml` | **Live strategy definitions** (entry/exit, screeners, TTLs) — the authoritative source | Active (live) |
| `docs/project/SKILLS.md` | All agents, OpenClaw skills, system pipelines, LLM routing reference | Active |
| `docs/project/project_openclaw.md` | OpenClaw gateway config, bot settings, skill manifest | Active |
| `docs/_archive/2026-05-24_cleanup/old_versions/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md` | 23-strategy narrative playbook | **Archived** — superseded by live YAML config |
| `docs/_archive/2026-05-24_cleanup/old_versions/agents_bible.md` | Agent behavior rules, G1–G10, RACI | **Archived** — current rules live in agent configs |

### Improvement Plans & Assessments *(both archived)*
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/_archive/2026-05-24_cleanup/old_versions/VERIFIED_MATURITY_ASSESSMENT_2026-05-12.md` | Maturity scorecard 7.51/10 baseline | **Archived** — historical baseline (current ≈7.7) |
| `docs/_archive/2026-05-24_cleanup/old_versions/FOCUSED_IMPROVEMENT_PLAN.md` | 7 verified gaps | **Archived** — see Open Items below |

---

## TIER 3 — LLM Fleet Phase Test Reports (historical, do not modify)

`docs/v4_1_phase1_pilot_report.md` · `docs/v4_1_phase1c_controlled_expansion_report.md` ·
`docs/v4_1_phase1d_limit5_report.md` · `docs/v4_1_phase1_final_audit.md` ·
`docs/v4_1_phase1_final_closeout_report.md`  *(verify individually before relying on; some may be archived)*

---

## TIER 4 — Superseded / Purged

| Document | Disposition |
|----------|-------------|
| `docs/_archive/2026-05-31_master_rewrite/ARCHITECTURE_OVERVIEW.md` | Already archived (superseded by SYSTEM_ARCHITECTURE_COMPLETE) |
| `llm_fleet_strategy_v3_4_1.md` | **Purged** — no longer in tree; superseded by v4.1 FINAL |
| `IMPROVEMENT_PLAN_2026-05-11.md` | **Purged** — no longer in tree |
| `SYSTEM_AUDIT_2026-05-11.md` | **Purged** — no longer in tree |
| `candidate_freshness_3_bucket_design.md` | **Not found** — design captured in strategy YAML TTL buckets (B1/B2/B3) |

---

## Known Documentation Drift

**Policy (2026-06-22):** Active canonical docs use `docs/LIVE_SYSTEM_FACTS.md` — not hard-coded counts.
Run `.venv/bin/python3 scripts/generate_system_facts.py` to regenerate and check `data/system_fact_drift.json`.

Exempt from drift checks: `CHANGELOG.md` (historical), `_archive/` (snapshots), `PHASE*_CLOSEOUT.md` (evidence).

---

## Open Items Tracking (as of 2026-06-22)

| Item | Priority | Status | Next action |
|------|----------|--------|-------------|
| OpenAI API key rotation | **P0** | OPEN | Dedicated session — blocks Stage 2a canary |
| OpenClaw API key rotation | **P0** | OPEN | Same session |
| Overnight LLM cron re-enable | **P1** | OPEN | `run_deep_overnight_llm_window.sh` PHASE102-RETIRED; 1,941 pending |
| KTOS/KBR stop-out review | P1 | OPEN | Schwab taxable stops filled 2026-06-22 — operator confirm flat |
| Pre-deploy state guard (zip wipe vector) | P1 | OPEN | Standalone session |
| `basis_unknown` resolution (~12 symbols) | P1 | OPEN | CSV import workflow |
| momentum_scalp suspension | P2 | MONITORING | Revisit at ≥5 trades |
| Stage 2a canary session | GATE | BLOCKED | Requires P0 key rotation first |
| gemma4:26b-a4b re-evaluation | CALENDAR | GATED | **2026-08-11** — see `v4_1_deployment_log.md` |

---

## Index Corrections (2026-06-19, applied vs the source draft)

The source draft index drifted from the filesystem; corrected here per A1A:
- **Paths fixed (doc exists, wrong path):** SYSTEM_ARCHITECTURE_COMPLETE (→ atm_audit_2026_05_26), both Schwab docs (→ architecture/), stage2a-canary-protocol (→ brokers/), all 3 rotation docs (→ project/).
- **Re-classified active → archived** (they live in `docs/_archive/`): CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL, TRADE_AI_STRATEGY_PLAYBOOK_v1.0, agents_bible, VERIFIED_MATURITY_ASSESSMENT, FOCUSED_IMPROVEMENT_PLAN.
- **Marked purged** (not in tree): llm_fleet_strategy_v3_4_1, IMPROVEMENT_PLAN_2026-05-11, SYSTEM_AUDIT_2026-05-11, candidate_freshness_3_bucket_design.
- **Added** the canonical Reference Architecture DOCX and the live `config/strategies/*.yaml` as the authoritative strategy source.

## Session Docs (2026-06-22)

| Document | Purpose |
|----------|---------|
| `docs/LIVE_SYSTEM_FACTS.md` | **Canonical live scale counts** — regenerate, do not hard-code elsewhere |
| `docs/project/DOCS_CONSOLIDATION_2026_06_22.md` | A1A consolidation closeout — drift fix, pointer policy, 32-file commit |
| `docs/project/STABILIZATION_SESSION_2026_06_22.md` | Track-1 stabilize: agent backlog, screener upsert, SIEM triage, LLM queue root cause |
| `docs/project/MATURITY_AUDIT_2026_06_22.md` | Area maturity scores (≈7.1/10) from live probe + Jun-11 baseline |

## Change Log

| Date | Change |
|------|--------|
| 2026-06-22 | A1A consolidation: LIVE_SYSTEM_FACTS.md, canonical docs → live pointers, drift detector hardened, DOCS_CONSOLIDATION closeout; runtime YAML/JSON/scripts committed. |
| 2026-06-22 | Added stabilization + maturity audit docs; open-items updated (overnight LLM cron, KTOS/KBR stops); SYSTEM_FACTS + STATE_OF_REPO regenerated. |
| 2026-06-19 | Index created + path/status verified against filesystem (14 corrections vs draft). Reflects commits d09a653c (deployment log) / 075bd602 (canary 2026-06-22) / 94e7275d (rotate-gap directives) / 65b3c751 (watchpool gap chip). |
