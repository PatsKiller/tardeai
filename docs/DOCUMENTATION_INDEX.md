# Trade AI v12 — Documentation Index
**Updated:** 2026-08-27 (audit finding M9 — backfilled 22 missing 2026-08-20/21/22 closeout doc entries; prior update 2026-08-24, R10.3 CIO persistent-cognition consumption source PR)
**Protocol:** All doc changes follow `docs/A1A.md`. Do not add a doc without updating this index.
**Scope:** Project root = `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

> **Verified 2026-06-19:** every path below was checked against the filesystem. Paths corrected where
> the source draft had drifted, and docs that are actually in `docs/_archive/` are listed as archived
> rather than active (see **Index Corrections** at the bottom). This is an A1A requirement — the index
> must not point at phantom or mislocated files.

---

## Autonomy & system state (2026-08-20) — read first for recovery

| Document | Purpose | Status |
|----------|---------|--------|
| `docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md` | **Material-change intelligence** — why a schedule-triggered sweep cannot notice one name behaving unlike itself, and the identity -> detect -> notify -> characterize -> interrogate -> route loop that can. Stages 0-2 SHIPPED 2026-09-06 (PRs #904-#907) and free; 3-5 designed and prototyped. Carries the guard rails: average-daily-move not ATR, unknown is the lowest rank, ACCEPTED is not DELIVERED, held is not dropped | Active |
| `docs/architecture/TRADEAI_SYSTEM_STATE_AND_AUTONOMY_2026-08-20.md` | **Master record** — LIVE architecture, timers, notify gates, freeform/desk loop, thesis SLA, autonomy directive gap matrix, roadmap | Active |
| `docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md` | **Phase 1 findings** — is CIO Desk actually the authoritative data/decision source? 11 evidence-based investigations, doc claim vs code vs live state | Active (closed out) |
| `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` | **Phase 2 plan + closeout status** — item→PR→merge-commit map for the 19 PRs merged 2026-08-27, and the ranked list of what remains | Active |
| `docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md` | **CI outage runbook** — repo-visibility flip exhausted the metered Actions quota; how to tell a quota block (0 steps, no runner, 0 billable ms) from a real test failure | Active |
| `docs/ops/HEALTH_AGENT_MATURITY_PLAN_2026-08-27.md` | **PLAN (not shipped)** — verify remediation *effect* not exit code; store-consistency invariants over the 29 canonical stores; root-cause capture. Built on the 24h/69-attempt silent sync failure | Plan |
| `docs/audits/CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md` | **Measured** answer to "is the pipeline diagram true?" — contracts and upper pipeline yes; loop never closes (0/94 workflows). Identity fork between the research and CIO arcs; two options open for operator decision | Active |
| `docs/architecture/cio/IDENTITY_AND_MEMORY_ADVISORY_2026-08-27.md` | **ADVISORY** — the GUID/memory layer is already designed (`security_identity` UUIDv5 spine, bitemporal `MemoryFact@v2`, `SecurityEvent@v1` catalysts, FROZEN event-sourcing ADR) and switched OFF: 0/315 envelopes carry a subject_guid. Promote, don't build | Active |
| `docs/_findings/ALEX_AUTONOMY_GROUND_TRUTH_2026-08-21.md` | Phase 0 closed snapshot (2414 wakes / 0 payloads at `b04f0016`) | Active (do not rewrite) |
| `docs/ops/MATURATION_G1_I0_A1_B1_2026-08-21.md` | G.1 quarantine + I.0 tree-pin audit + A.1 off-peak retarget + B.1 producer payload flags | Active |
| `docs/ops/CIO_UI_AUDIT_2026-08-22.md` | **Canonical per-tab UI audit** of `/v3/advisory` + CIO Office (A–E). Live `:7777` is pin `5e91225a`. Raw dump on Drive. | Active |
| `docs/ops/RESEARCH_LIFECYCLE_AS_OF_2026-08-22.md` | **Current-state lifecycle** — trigger → DeepSeek → parser/raw → mint → who consumes; holdings 17/22 CURRENT, SLA true; agents pull, not push | Active |
| `docs/ops/SESSION_CLOSEOUT_2026-08-22.md` | **Index of 2026-08-22 findings + fixes** (parser/join, mint, skip-gate, T3, ingest) | Active |
| `docs/ops/COST_CAP_EXCEEDED_2026-08-22.md` | 441 COST_CAP rows: bind 11:31 ET, tiers, 895 vs ~312, skip-gate not live on crontab tree | Active |
| `docs/ops/RESEARCH_LIFECYCLE_STANDARD.md` | Intended methodology (incremental / skip unchanged). Live measured state is the as-of file | Active |
| `docs/RESEARCH_PRIORITIZATION.md` | Hermes lane/tier SLA (who/when). Execute set = due ∩ lifecycle gate | Active |
| `docs/ops/RESEARCH_TIER_LLM_CADENCE.md` | **Canonical** five universe tiers, one watchlist research tier (T1-WATCH), S0–S3 vs hygiene 1–3, cron + confirm-run | Active |
| `docs/ops/TELEGRAM_FEED_REMEDIATION_2026-08-22.md` | Telegram audit 18,130 msgs — P0 T1/T2 shipped; T3–T7 after 8/27 | Active |
| `docs/ops/RESEARCH_QUALITY_AND_THESIS_GAP_2026-08-22.md` | Parser `[:500]` diagnosis, S1–S7, sandbox, mint; night numbers in the as-of file | Active |
| `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md` | Two LLM families (scheduler DeepSeek vs 2h OAuth); Telegram DATA_UNAVAILABLE is thesis-slot join | Active |
| `docs/ops/CIO_PHASE1_2_MEASURE_CLOSEOUT_2026-08-21.md` | Phase 1–2 measure closeout; evening note: 5-day window false start | Active |
| `docs/ops/AUTONOMOUS_ADVISOR_SESSION_CLOSEOUT_2026-08-20.md` | Session closeout — PR #414–#420 deploys, host proofs, commands, Drive sync notes | Active |
| `docs/ops/CIO_REENTRY_S3_WIRE_2026-08-20.md` | Reentry → S3 evidence wire (#414) | Active |
| `docs/ops/CIO_WATCH_S7_WIRE_2026-08-20.md` | Watch → S7 evidence wire (#415) | Active |
| `docs/ops/CIO_OPERATOR_DESK_LOOP_P0_2026-08-20.md` | Desk loop P0 meta_system (#418) | Active |
| `docs/ops/CIO_OPERATOR_FREEFORM_AGENT_2026-08-20.md` | Freeform Flash agent (#419) | Active |
| `docs/ops/CIO_HELD_THESIS_COVERAGE_2026-08-20.md` | Held-book thesis coverage SLA (#420) | Active |
| `docs/ops/CIO_ADVISORY_TRUTH_HARDENING_CLOSEOUT_2026-08-20.md` | Advisory-truth hardening closeout | Active |
| `docs/ops/CIO_CLOSED_LOOP_LINEAGE_CLOSEOUT_2026-08-20.md` | Closed-loop lineage closeout | Active |
| `docs/ops/CIO_LOOP_B1_B3_D1_CLOSEOUT_2026-08-20.md` | Loop B1/B3/D1 closeout | Active |
| `docs/ops/CIO_MATERIAL_NOTIFY_CANARY_2026-08-20.md` | Material-notify canary run | Active |
| `docs/ops/CIO_OUTCOME_LEARNING_CLOSEOUT_2026-08-20.md` | Outcome-learning closeout | Active |
| `docs/ops/CIO_PHASE_A_INTERDICT_NOTIFY_2026-08-20.md` | Phase A interdict-notify | Active |
| `docs/ops/CIO_DESK_MEMO_CONTINUOUS_2026-08-20.md` | Desk memo continuous-mode | Active |
| `docs/ops/FLASH_ACTIVATION_AND_THESIS_CANARY_2026-08-20.md` | Flash activation + thesis canary | Active |
| `docs/ops/RESEARCH_ENGINE_FLASH_FIRST_FAILURE_2026-08-20.md` | Research engine flash-first failure analysis | Active |
| `docs/ops/SYMBOL_THESIS_ACQUISITION_PIPELINE_LIVE_2026-08-20.md` | Symbol thesis acquisition pipeline live | Active |
| `docs/ops/SYMBOL_THESIS_CANARY_DRY_RUN_2026-08-20.md` | Symbol thesis canary dry-run | Active |
| `docs/ops/CIO_DECISION_PAYLOAD_PHASE1_2026-08-21.md` | CIO Decision Payload Phase 1 (`AGENT_DECISION_PAYLOAD` capture live) | Active |
| `docs/ops/DECISION_PAYLOAD_LANDING_2026-08-21.md` | Decision payload landing detail | Active |
| `docs/ops/CIO_MEMORY_SHADOW_MEASURE_PHASE2_2026-08-21.md` | Memory shadow-measure Phase 2 | Active |
| `docs/ops/CIO_INVESTMENT_INTELLIGENCE_CARD_2026-08-21.md` | Investment Intelligence Card (IIC) | Active |
| `docs/ops/CIO_IIC_FEEDBACK_CC_2026-08-21.md` | IIC feedback into Command Center | Active |
| `docs/ops/CIO_IIC_PHASE_D_SI_QUEUE_2026-08-21.md` | IIC Phase D symbol-intelligence queue | Active |
| `docs/ops/CIO_IIC_TELEGRAM_ACTIONABLE_VISUAL_2026-08-21.md` | IIC Telegram actionable-visual variant | Active |
| `docs/ops/CIO_IIC_SESSION_CLOSEOUT_2026-08-21.md` | IIC session closeout | Active |
| `docs/ops/LANE_QUALITY_BAKEOFF_2026-08-21.md` | Research lane quality bakeoff | Active |
| `docs/ops/LANE_QUALITY_BAKEOFF_OPERATOR_BLIND_2026-08-21.md` | Lane quality bakeoff, operator-blind variant | Active |
| `docs/ops/RESEARCH_COVERAGE_SNAPSHOT_2026-08-22.md` | 10:24 ET coverage snapshot (pre-confirm-run — not current counts, see lifecycle-as-of doc) | Active |
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` §24 "Session — 2026-08-20 to 2026-08-22" | Pointer-index summary of this whole window, folding the above into the master doc's session changelog (audit finding M9) | Active |
| `docs/architecture/TRADE_AI_INSTITUTIONAL_MEMORY_AND_AUTONOMOUS_AGENT_ARCHITECTURE_2026-08-24.md` | **Canonical R10** — taxonomy, BASELINE_PROJECTION vs material, PR sequence, constitution | Active |
| `docs/ops/TRADE_AI_R10_MEMORY_AUTONOMOUS_AGENT_CLOSEOUT_2026-08-24.md` | R10.2 closeout — M1 LIVE naturally proven on `5c0a993a` | Active |
| `docs/ops/YEDAS_EYE_INSTITUTIONAL_BRAIN_MATURITY_2026-08-24.md` | Yeda's Eye first audit after M1 natural PASS | Active |
| `docs/ops/CIO_PERSISTENT_COGNITION_CONSUMPTION_2026-08-24.md` | CIO read-only consumption of TickerResearchState + baseline | Active |
| `docs/ops/TRADE_AI_M2_MEMORY_SUBSTRATE_BENCHMARK_2026-08-24.md` | Isolated A/B/C substrate benchmark; POSTGRES_PGVECTOR decision | Active |
| `docs/architecture/GOOGLE_NOTES_BITEMPORAL_DDL_ARCHITECT_RECONCILIATION_2026-08-24.md` | Google Notes DDL: accepted / modified / rejected / benchmark-required | Active |
| `docs/ops/TRADE_AI_M3_MEMORY_CONSOLIDATION_2026-08-24.md` | M3 consolidator / episodes / preference candidates (source) | Active |
| `docs/ops/TRADE_AI_M4_CONTEXT_ENVELOPE_AND_CC_SPEC_2026-08-24.md` | M4 same-brain envelope + Command Center spec | Active |
| `docs/architecture/TRADE_AI_BITEMPORAL_MEMORY_DATA_MODEL_2026-08-24.md` | R10 MemoryFact@v2 + six architectural corrections (source/tested, not live) | Active |
| `docs/architecture/TRADE_AI_MEMORY_RETRIEVAL_AND_INDEX_STRATEGY_2026-08-24.md` | MemoryRetrievalUnit + index strategy; HNSW/Neo4j UNMEASURED | Active |
| `docs/ops/TRADE_AI_MEMORY_ARCHITECTURE_CORRECTION_CLOSEOUT_2026-08-24.md` | Six-defect closeout; reconciled onto post-#494 main | Active |
| `docs/architecture/HERMES_PERSISTENT_TICKER_INTELLIGENCE_ARCHITECTURE_2026-08-23.md` | **Canonical** identity v2 (issuer/security/listing), free-first, Librarian critique, LLM escalation | Active |
| `docs/ops/HERMES_FREE_FIRST_MEMORY_GRAPH_CONVERGENCE_2026-08-23.md` | R9.3 operational closeout — measured 120/0 artifacts, FREE_FIRST_ONLY | Active |
| `docs/ops/HERMES_FREE_FIRST_NATURAL_SCHEDULER_2026-08-23.md` | CURRENT-pinned FREE_FIRST_ONLY systemd timer (hourly :23 ET, zero paid) | Active |
| `docs/ops/HERMES_LIBRARIAN_CURATION_MATURITY_2026-08-23.md` | PR C Librarian epistemic + HermesCurationSummary — **live on `bc6ff5c6`**, first natural post-C tick 00:23 ET | Active |
| `docs/_evidence/hermes_r93/POST_C_NATURAL_TICK.json` | Two natural ticks + post-#492 00:23 ET receipt (117/2/1/0/120/0, SHA-unchanged graph/state) | Active |
| `docs/_evidence/memory_r10/` | R10 inventory, taxonomy, provider-convergence (M1) | Active |
| `docs/architecture/TICKER_KNOWLEDGE_GRAPH_GUID_LINEAGE.md` | v1 ticker GUID lineage (#487/#488). Ticker is alias, not security identity | Active (partially superseded) |

Drive mirror: **Trade_AI_Docs_v2** (`1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`) via `scripts/sync-docs-to-drive.sh`.

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

- **OPTIONS_LIFECYCLE_DESK.md** — Options Lifecycle Desk architecture & acceptance (2026-07-19, v1.1 same day): strategy-aware open-position management, journal bridge into trade_instances, ticker attribution, free-lane oversight. Supersedes the per-leg monitor sections of options-module.md for management decisions.
- **architecture/DECISION_PACKET_OPERATOR_CARD_AND_RTH_REFRESH.md** — Watchlist decision packet **operator card** + RTH **4h** plan refresh / `should_be_stale` (2026-07-21): compact READY/WAIT/REFRESH/BLOCKED/NO TRADE/MANAGE, timestamps, material technical hash, shadow-batch RTH freshness. Advisory only.
- **sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md** — Alpaca multi-account **R1–R5 build handoff** (registry, credentials, migration, live scaffolds, TV stub). Tip `4fa3ba33`.
- **brokers/trading-environments.md** · **alpaca-live-accounts.md** · **tradingview-lanes.md** · **_findings/alpaca_taxonomy_audit_2026-07-21.md** — D1 keys `tradeai_automated` / `alpaca_taxable_live` / `alpaca_ira_live`; audit + TV lanes.


### Security & Safety
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/project/TRADE_SUPERVISION_METHODOLOGY.md` | Trade monitoring, stop/target rules, after-hours research, overnight pipeline | Active |
| `docs/GPU_OLLAMA_SETUP.md` | Intel Arc + Ollama setup, model list, GPU memory map | Active |
| `docs/STOP_METHODOLOGY.md` | **Protective stop / trailing-stop methodology** — family % bands, swing-low anchor, floor/cap clamp, fixed-vs-trailing, **trailing-STOP-LIMIT (4th option, Schwab)**, **Holdings stop-kind pill + P/L-if-fired**, free-lane fallback, monthly Claude meta-review | Active (2026-07-21 v3.1) |
| `docs/MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` | **Momentum-scalp layered stop/trail policy** — 4-layer methodology (structure+ATR initial stop, breakeven @ +1.0–1.5R, Chandelier trailing **config-OFF** per backtest gate, portfolio heat); §6 validation gate (150 trades); Risk tab monitor + Stop Intelligence replay | Active (2026-06-30, paper validation phase) |
| `docs/COST_MODEL.md` | Cloud LLM operating cost model, budget gates | Active |
| `docs/LLM_DATA_DICTIONARY.md` | Data flow to every model call, 6 context types, anti-hallucination spec | Active |

### LLM Fleet v4.1 (canonical set)
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` | Fleet architecture — process types, GPU lifecycle, phased rollout, overnight routing | Canonical |
| `docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md` | Operator runbook — phase gates, rollback triggers | Active |
| `docs/runbooks/DB_HANG_PREVENTION.md` | **DB-induced dashboard hang** — root cause (ALTER queued behind idle-in-txn lock holder), per-connection + role-level `lock_timeout`/`statement_timeout`/idle guards, recovery steps | Active (2026-06-30) |
| `docs/runbooks/protective-stop-integration-2026-06-30.md` | **Protective stop integration** — Schwab evidence-bound STOP / STOP_LIMIT / TRAILING_STOP, per-account arming (rollover default), one-V-canary-only, after-hours override-required policy, lifecycle + read-back proof, Fidelity manual-ticket, OCO off until canary proven | Active (2026-07-04) |
| `docs/runbooks/post-sale-redeploy-sync-2026-07-14.md` | **Post-sale redeploy sync** — `deploy_detect` / `deploy_backfill` / `deploy_recompute`, intelligence engine, FCNTX example, Phase A–E infrastructure ops, PR-5 cron installer | Active (2026-07-13) — desk itself REOPENED, see design doc §0 |
| `docs/runbooks/PLAYWRIGHT_ARTIFACTS_POLICY.md` | **Ephemeral artifact policy** — Playwright/visual captures go to `artifacts/playwright/<run_id>/` (gitignored, Drive-excluded, 7-day retention via `scripts/artifacts_retention.sh`); never under `docs/`, never to canonical Drive | Active (2026-07-14) |
| `docs/v4_1_deployment_log.md` | **Living deployment log** — fleet state, phase completions, 2026-08-11 gemma4 eval gate | Active — created 2026-06-19 (d09a653c) |
| ~~CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL~~ | CC execution prompt for fleet deploy | **Purged** (2026-08-16 docs cleanup — recoverable via git history) |

### Portfolio truth & performance
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/features/share-reconciliation.md` | **Share drift / DRIP** — system vs broker shares, approval workflow, API | Active (2026-07-15) |
| `docs/features/transfer-aware-performance.md` | **Rollovers / Roth ladder / YTD** — transfer history, auto-normalize, residual ≈ market, Fidelity linked sleeve, daily YTD pin | Active (2026-07-15) |
| `docs/ui/stop-management-desk-redesign-2026-07-15.md` | **Stop Management desk UX** — card layout, semantic status, primary CTA, filters | Active (2026-07-15) |

### Broker Integration *(paths corrected — these live under docs/architecture & docs/brokers)*
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/brokers/trading-environments.md` | **Canonical env taxonomy** — D1: `tradeai_automated` / `alpaca_taxable_live` / `alpaca_ira_live` | Active (2026-07-21) |
| `docs/brokers/alpaca-live-accounts.md` | Live scaffolds roadmap (DISABLED) | Active (2026-07-21) |
| `docs/brokers/tradingview-lanes.md` | TV manual + dormant webhook | Active (2026-07-21) |
| `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md` | R1–R5 build handoff | Active (2026-07-21) |
| `docs/brokers/paper-trading.md` | **Path A as-is** — Alpaca paper equity + options procedures | Active (2026-07-21) |
| `docs/brokers/alpaca-live-accounts.md` | **Live scaffolds** `alpaca_taxable_live` / `alpaca_ira_live` (DISABLED) — gaps, phases (not implemented) | Active roadmap (2026-07-21) |
| `docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md` | Full inventory, risks, refactor backlog | Active (2026-07-21) |
| `docs/brokers/current-state-alpaca-integration.md` | 2026-06-11 equity paper code-trace (still valid) | Active |
| `docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md` | Schwab Phase 1 read-only — proven capabilities, fenced writes, Gate A | Active |
| `docs/architecture/SCHWAB_API_CAPABILITY_MAP.md` | Every Schwab endpoint → BUILT / READY / FENCED / NEVER | Active |
| `docs/SCHWAB_AUTO_REAUTH.md` | **Schwab OAuth 7-day reauth** — CC manual page (primary), token-health banner, APIs, notify-only agent; browser auto off | Active (2026-08-11) |
| `docs/audits/STORAGE_SAFEGUARDS_AUDIT_2026-08-11.md` | **Backup storm containment** — single local/Drive dump, enforcer, health anti-storm, docs/DB retention | Active (2026-08-11) |
| `config/backup_policy.yaml` | Local max_count=1, 20h interval, Drive db KEEP=1 | Active (2026-08-11) |
| `docs/brokers/stage2a-canary-protocol.md` | Stage 2a canary runbook — gap patches, risk caps, approval flow | Active — canary date set to **2026-06-22** in `canary_gate.py` |
| `docs/brokers/stop-management-architecture.md` | Canonical as-built stop/trailing architecture (Schwab live, Alpaca auto, Fidelity monitor) | Active (2026-06-22) |
| `docs/brokers/snaptrade-read-only-aggregation-spec.md` | SnapTrade holdings read path (Fidelity rollover IRA) | Active |
| `docs/brokers/snaptrade-fidelity-protective-stops-spec.md` | Fidelity monitor-only stops + one-share SnapTrade test (no sandbox) | Active (2026-06-22) |

### Proposal & Execution Paths
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/PROPOSAL_EXECUTION_PATHS.md` | **Canonical two-path model** — Path A paper auto (Alpaca test) vs Path B live (Schwab 2FA / Fidelity FA manual) | Active (2026-06-23) |
| `docs/BROKER_PROPOSALS_UI.md` | **Broker Proposals live desk** — thesis validity bar, refresh/recalibrate, account picker, cloud oversight | Active (2026-06-24) |
| `docs/PRIVATE_COMPANY_PROXY.md` | **Private-company → public-proxy GRAPH** — discover/score/rank public proxies for un-buyable private targets (Anthropic→ZM+graph); advisory, no live path | Active (2026-07-07) |
| `docs/COMMAND_CENTER_RISK_VISUALIZATIONS.md` | **Risk visualization layer** — Recharts components, hub integration map, library roadmap | Active (2026-06-24) |
| `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md` | Options desk execution labels — same auto vs manual split as equity proposals | Active (2026-06-24) |
| `docs/design/OCO_ATM_UNIFICATION_DESIGN.md` | **OCO brackets + ATM↔proposals unification** — Alpaca native OCO / Schwab API OCO (2FA) / Fidelity manual; auto-bracket at fill; §11 DD hardening (OCO_REPLACING + read-back + repair supervisor, reconciler `--fix` DB-only vs `--apply-oco-retrofit`, qty fail-closed) | **Partially implemented** — paper P1+P2 live + DD-hardened (2026-06-30); Schwab P3 staged inert (`OCO_BRACKETS_SCHWAB` off); P4/P5 pending |
| `docs/design/REDEPLOY_DESK_INSTITUTIONAL_DESIGN.md` | **Redeploy Desk v2** — institutional post-sale capital-allocation workbench: exposure decomposition, competing plans A–G, entry staging, scenarios, export trade plan, monitoring; operator policy + implementation-truth matrix (§0); FCNTX #144 fixture | **REOPENED** (2026-07-13) — Phase A–E infrastructure on main; analytics + full-page UI rebuild in progress; NOT complete |
| `docs/audits/REDEPLOY_FIXTURE_AUDIT_2026-07-13.md` | **P0 fixture-pollution audit** — Phase E test committed synthetic JEPQ fills to production event #144 (false 3% restoration); 8 contaminated locations; guards + quarantine shipped; gated cleanup transaction | **Open** — cleanup awaits operator approval |

### Rotation Intelligence *(paths corrected — docs/project/)*
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/project/ROTATION_PRODUCTION_READINESS_2026-06-19.md` | Rotation advisory readiness — trust_verdict, dual-LLM, no-override rule | Active (2026-06-19) |
| `docs/project/V3_TRUST_HARDENING_AND_ROTATION_INTELLIGENCE.md` | v3 trust hardening + rotation intelligence baseline | Active (2026-06-16) |
| `docs/project/ROTATION_LLM_ADVISOR.md` | `rotation_llm_advisor.py` runbook — advisory only, safety contract | Active (2026-06-18) |

### Research Intelligence (CC v3)
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/ENGINE_ROOM_V1.md` | **Engine Room v1** — server topology Path B (disconnect detect + 25s watchdog + CLOSE-WAIT reaper; gunicorn Path A infeasible), symbol-cards ETag, provenance-at-write (wire degrade), universe guard at generators, Hermes backlog collapse 2,510→30 + nightly drain | Active (2026-07-16) |
| `docs/architecture/DEFENSE_DESK_V1.md` | **Defense Desk v1** — sector momentum state machine (transitions-only, debounced, book-weighted), Trade→Defense page + posture strip, would-have-fired credibility fold, account capabilities matrix (taxable margin verified); B/C/D deferred pre-verified | Active (2026-07-17) |
| `docs/architecture/DEFENSE_DESK_V9.md` | **Defense Desk v9** — adjudication layer: pre-registered promote criteria + console, seat league (auditors audited), governance w/ living revoke criteria, governed tuning (proposes never adjusts), Saturday weekly loop; the honest Jul 30–31 can/cannot-prove statement | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V8.md` | **Defense Desk v8** — account-targeting inversion + quiet Telegram (5 live defects), oversight stack: config-generated constitution brief, both free seats critique every build (cached, schema-strict), verdict pills + memo panel; first memos verbatim | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V7.md` | **Defense Desk v7** — execution through the existing rails (intents → action_queue approvals → 2FA pill → paper auto / ARMED TICKET), canary caps + kill file + whitelist, chain validation gating the click, 10-min auto-fill poller, In-Play rail + Home hedge state machine | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V6.md` | **Defense Desk v6** — operator-owned ★CORE registry (engine-enforced: no full exits, patient windows, cleanup-exempt), funded rotation pairs (same-account, style-aware, both legs ticketed, supersede singles), LadderTrack stepper | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V5.md` | **Defense Desk v5** — dynamic trim composite (arithmetic on-card, guard-enforced), per-account sell tickets w/ tax fork + resulting exposure, exit ladders (T2/T3 armed at creation, fire AND disarm, price triggers on the 20-min evaluator), Rotation Plan panel + slice re-entry watches + brief/Home chips | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V4.md` | **Defense Desk v4** — fund lookthrough (effective exposure: tech 24.1% not 5.1%), materiality floor + cleanup card, full-book stances, round-trip ledger w/ wash-sale gate + one-tap confirm, actionable card faces (levels/dollars/CC strikes), honest radar/boards, queued refresh job | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V3.md` | **Defense Desk v3** — recommendations engine (4 groups, complete-or-absent cards, per-account tabs, paper twins), hedging radar (nightly chain snapshots), W/M/Q rotation boards w/ movement chips, dashboard redesign + machine design guard (check_design_tokens.sh in build) | Active (2026-07-18) |
| `docs/architecture/DEFENSE_DESK_V2.md` | **Defense Desk v2** — whole-market layer (indices/styles/internals + state line), 144-industry rotation layer (rel-SPY quadrants, book/starred alert gating, candidate pools), sector-alias coverage completion, RRG scatter + heat-spine page rebuild, debounced credibility fold; E2 (v1 engines) below cut line | Active (2026-07-18) |
| `docs/architecture/HOME_COMMAND_BRAIN_V2.md` | **Home v2 Command Brain** — Finviz signal board (throttled Elite export, 10 signals), book treemap (squarified, heat ramp, stop rings), guarded news modal, plain-English dictionary + complete click map | Active (2026-07-17) |
| `docs/runbooks/BARE_METAL_RECOVERY.md` | **Bare-metal recovery** — full rebuild sequence from offsite backups; P0 operator prerequisite (gpg passphrase off-box); nightly ops_backup manifests (dpkg/pip/ollama/pg/gog) | Active (2026-07-17) |
| `docs/architecture/REPORTS_DESK_V3.md` | **Reports Desk v3** — one corpus per panel (server-side quick views + qv_counts, corpus tags, config indexing-policy legend), System Rollup tab + nightly system_rollup_daily + Daily System Digest 20:40, preamble strip at write + backfill (preamble_leak lint), analyst scope labels + residual fold + dead-acked removal, producer registry chips | Active (2026-07-17) |
| `docs/architecture/REPORTS_DESK_V1.md` | **Reports Desk v1** — Report Library (9 families, in-page viewer), structured brief renderer + regenerate, analyst truth pass (CUSIP fold, held vocabulary), alert analytics + daily digest, Hermes→weekly wiring | Active (2026-07-16) |
| `docs/architecture/WATCH_DESK_V4.md` | **Watch Desk v4 — Terminal Grade**: watchTokens design system (zero-hex, chips, rails, keyboard), saved views/bulk, directive drawer+TTL+in-UI tier-3 approvals, converted-α + low-efficacy gate, sector RS history + book overlay, discovery-trace threading | Active (2026-07-16) |
| `docs/architecture/WATCH_DESK_V3.md` | **Watch Desk v3** — source scoreboard (α attribution), operator alerts, deterministic context, thin surfaces resolved | Active (2026-07-16) |
| `docs/architecture/WATCH_DESK_V2.md` | **Watch Desk v2 P0s** — header truth (SPAXX flip killed), directive family gate + Sunday hygiene + trend cap | Active (2026-07-16) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V3_1.md` | **RI v3.1 — Institutional Desk**: snapshots/ETag reliability, curation shelf+hide, provenance timestamps, deterministic QA lint, outbound links, ops restore | Active (2026-07-16) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V3.md` | **RI v3.0 — Decision Desk**: one-corpus counts, real lanes, stub demotion, brief-scoped tickers, Hermes joins, run-research queue, staged-idea lifecycle | Active (2026-07-16) |
| `docs/architecture/GAIN_GUARDIAN.md` | **Gain Guardian** — live-book exit intelligence: HWMs, parabolic/giveback states, tax gate, outcomes; SHADOW until `--promote` | Active (2026-07-16) |
| `docs/_findings/gain_guardian_diagnosis_2026-07-16.md` | Gain Guardian Phase 0 diagnosis — lots dateless, helper import map, cron slots | Active (2026-07-16) |
| `docs/_findings/ri_v3_diagnosis_2026-07-16.md` | RI v3 Phase 0 diagnosis — live mechanisms vs assumptions, flag-backs | Active (2026-07-16) |
| `docs/_findings/ops_morning_stability_2026-07-16.md` | **Morning ops stability** — reconnect/server_busy, trade_ai cache, Finviz SAVEPOINT, Telegram NEW GO, Health Agent limits, RI overnight-only | Active (2026-07-16) |
| `scripts/research_intelligence_queue.py` | Run-research queue (after-close drain of topic_ingestion, cron 16:45/02:40) | Active (2026-07-16) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2_6_MATURITY.md` | **RI v2.6** — transparent conviction, data gates, analyst/options, action bar | Superseded by v3 (2026-07-16) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2_5_SECURITY_MULTIFACTOR.md` | **RI v2.5** — RSI/RS/valuation conviction + multi-factor sizing | Active (2026-07-15) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2_4_CONCENTRATION_SIZING.md` | **RI v2.4** — concentration + heat sizing engine, theme capacity, funding trims | Active (2026-07-15) |
| `scripts/lib/research_intelligence_security.py` | Security snapshots + conviction scoring for RI tickers | Active (2026-07-15) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2_3_CONSISTENCY.md` | **RI v2.3** — consistent category-aware recs, quality tiers A/B/C, UI polish | Active (2026-07-15) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2_2_PORTFOLIO_ADVISORY.md` | **RI v2.2** — portfolio-aware tickers, sizing vs live weights, risk caveats | Active (2026-07-15) |
| `scripts/lib/research_intelligence_portfolio.py` | Holdings weight context + `build_advisory()` (v2.3 category gates) | Active (2026-07-15) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2_1_NARRATIVE_UI.md` | **RI v2.1** — article-style narrative fields + editorial dashboard redesign | Active (2026-07-15) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V2.md` | **Research Intelligence v2** — freshness/archive, retirement pillar, feedback, professional UI | Active (2026-07-15) |
| `scripts/lib/research_intelligence_narrative.py` | Narrative enrichment (lede, summary paras, takeaways, CTA) | Active (2026-07-15) |
| `scripts/research_intelligence_narrative_enrich.py` | Optional local-LLM batch writer for Hermes evidence_json.narrative | Active (2026-07-15) |
| `docs/architecture/RESEARCH_INTELLIGENCE_V1.md` | Research Intelligence v1 baseline — taxonomy, aggregator, first cockpit | Active (superseded by v2 for ops) |
| `config/research_intelligence_taxonomy.json` | Canonical category taxonomy v1.1 (pillars + subcategories) | Active (2026-07-15) |
| `config/research_intelligence_freshness.json` | Freshness tiers, refresh cadence, archive policy | Active (2026-07-15) |
| `config/research_intelligence_retirement_topics.json` | Retirement topic seed catalog (Roth ladder, Golden Window, IRMAA, …) | Active (2026-07-15) |
| `scripts/lib/research_intelligence.py` | Aggregator v2 — classify, freshness, feedback join, `build_feed` | Active (2026-07-15) |
| `scripts/research_intelligence_refresh.py` | Freshness SLO report + soft archive (never delete) | Active (2026-07-15) |
| `scripts/research_intelligence_retirement_seed.py` | Upsert retirement topics into topic_monitor | Active (2026-07-15) |
| `GET /api/v2/research-intelligence` | Unified feed (archive/freshness/star/sentiment filters) | Active (2026-07-15) |
| `GET /api/v2/research-intelligence/taxonomy` | Taxonomy + freshness policy | Active (2026-07-15) |
| `GET /api/v2/research-intelligence/freshness` | Category SLO + stale monitors | Active (2026-07-15) |
| `POST /api/v2/research-intelligence/feedback` | Star / vote / note | Active (2026-07-15) |

### Hermes Closed Loop & Self-Learning
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/hermes/HERMES_CLOSED_LOOP_TRACEABILITY.md` | Master roadmap — watchlist/holdings lifecycle, outcome bus traceability, symbol journey, learning scorecard | Active (2026-07-05) |
| `docs/hermes/HERMES_ADAPTIVE_THRESHOLD_LEARNING.md` | Threshold learner design — proposals, evaluation, evidence gates, do-no-harm | Active (2026-07-05) |
| `docs/hermes/HERMES_SCOPE_GOVERNOR.md` | Scope tiers, bus reactions, governor audit — advisory-only | Active |
| `scripts/hermes_learning_scorecard.py` | Daily learning scorecard CLI → `data/runtime/hermes_learning_scorecard.json` | Active (2026-07-05) |
| `GET /api/v2/hermes/learning-scorecard` | Scorecard API for Command Center Closed Loop panel | Active (2026-07-05) |

### Strategy & Agent Configuration
| Document | Purpose | Status |
|----------|---------|--------|
| `config/strategies/*.yaml` | **Live strategy definitions** (entry/exit, screeners, TTLs) — the authoritative source | Active (live) |
| `docs/project/SKILLS.md` | All agents, OpenClaw skills, system pipelines, LLM routing reference | Active |
| `docs/project/project_openclaw.md` | OpenClaw gateway config, bot settings, skill manifest | Active |
| ~~TRADE_AI_STRATEGY_PLAYBOOK_v1.0~~ | 23-strategy narrative playbook | **Purged** — superseded by live YAML config |
| ~~agents_bible~~ | Agent behavior rules, G1–G10, RACI | **Purged** — current rules live in agent configs |

### CIO & Wealth Advisory Agents (Alex & Steph)
| Document | Purpose | Status |
|----------|---------|--------|
| `docs/AGENT_ROSTER.md` | **Canonical agent roster** — all agents with identity, model, platform, schedule, authority (updated 2026-08-09) | Active |
| `docs/agent_runtime/FLEET_STATUS_2026-07-30.md` | Wave 1-2 agent_runtime fleet status — per-agent SHADOW/DESIGNED state, gap analysis, operator sequence | Active |
| `docs/agent_runtime/AGENT_HANDBOOK.md` | Agent runtime handbook — lifecycle, promotion contract, evidence gates | Active |
| `docs/agent_runtime/SHADOW_ACTIVATION_RUNBOOK.md` | Wave-1 SHADOW activation runbook — provider module, root timer, kill switch | Active |
| `docs/agent_runtime/AGENT_PERMISSION_MATRIX.md` | Per-agent tool deny-lists and authority boundaries | Active |
| `docs/agent_runtime/FLEET_LIFECYCLE_AND_PROMOTION.md` | Agent promotion contract — gates, evidence requirements, HUMAN_ONLY policy | Active |
| `docs/agent_runtime/LANE_D_SHADOW_AGENTS.md` | Lane D shadow agent architecture and governance | Active |
| `docs/agent_runtime/PERSISTENCE_RUNBOOK.md` | Agent runtime durable state persistence | Active |
| `docs/architecture/cio/CIO_PHASE_3_DELIVERY.md` | **CIO Phase 3 — DELIVERED 2026-08-09**: Alex autonomous CIOrity Officer — hybrid OpenClaw+Trade AI, 9 PRs, action ledger, 30-min heartbeat, wake worker, `/v3/cio` API, Hermes challenge bridge, DeepSeek V4 Pro primary | Active |
| `docs/advisory/desk-v1/` | **Advisory Desk v1** — phases 0–7 outcomes, autonomy/scheduling truth, situation catalog freeze, runtime truth | Active (2026-08-11) |
| `docs/cio/THESIS_STORE_P3.md` | **CIO P3 versioned thesis store** — `desk@vN` pins, plans/enrich/context wiring, `/cio thesis` | Active (2026-08-11) |
| `docs/cio/WAKE_TRACES_P5.md` | **CIO P5 wake traces** — append-only JSONL why-wake / llm path; fail-soft; CLI + `/cio traces` | Active (2026-08-11) |
| `docs/cio/P2B_PLAN_ENRICHMENT.md` | **CIO P2b plan enrichment** — evidence pack, governed Flash/Pro under cap, template fail-closed | Active (2026-08-11) |
| `docs/cio/CIO_TELEGRAM_CONVERSE_RUNBOOK.md` | **CIO P1 Telegram converse** — dedicated bot, allowlist, OPERATOR_MESSAGE wakes | Active (2026-08-11) |
| `docs/cio/CIO_WHATSAPP_CONVERSE_RUNBOOK.md` | **CIO P4 WhatsApp mirror** — Meta Cloud API webhook, shared converse core, flag default off | Active (2026-08-11) |
| `docs/cio/SITUATION_CATALOG_V1.md` | **Situation Catalog v1** — S1–S8 detector + plan store operator guide | Active (2026-08-11) |
| `docs/architecture/cio/` | **CIO architecture (38 files)** — ADRs (authority, state, containment, LLM governance, scheduler, specialist calc), lab docs (action ledger, wake detector, handoff queue, health boundary, notification outbox), Phase 2 delivery/authority/canary/cost/data/runtime/triggers, Phase -1 readiness/dependency, platform readiness report, quality metrics, run budgets, operator communication, financial schedule, governed model bridge, specialist maturity catalog, Hermes challenge policy, financial domain matrix, operator IPS template, legacy inventories | Active (2026-08-09) |
| `docs/architecture/cio/OPENCLAW_CIO_ARCHITECTURE_FEEDBACK_2026-08-08.md` | **OpenClaw CIO architecture audit** — runtime truth vs design: 3/9 specialist agents operational, memory/heartbeat disabled, Hermes bridge absent, no agent-to-agent delegation, DeepSeek auth unproven, $0.25/day cost cap concern | Active (2026-08-08) |
| `docs/CIO_PROMPT_INPUT_AUDIT_2026_07_01.md` | CIO prompt/input audit (Stages 1+2a merged, Stage 2b pending) — synthesis v3→v5, dual-consensus fixes, DQ notes, prompt-size budget | Active (2026-07-01) |
| `docs/wealth-advisor/STEPH_WEALTH_ADVISOR.md` | **Steph Wealth Advisor** — full documentation: architecture (OpenClaw + Wave-3), persona, command coverage, data discipline, cron jobs, skills, validation toolkit, model routing, deployment, gaps | Active (2026-08-09) |
| `scripts/lib/cio_event_bus.py` | **CIO Event Bus** — append-only, hash-chained event stream (15 event types). Agents subscribe instead of polling cron. Routes: alex (12 types), steph (4), hermes (4). Phase 0 foundation for event-driven autonomy. | Active (2026-08-09) |
| `scripts/agent_runtime_live_providers.py` | **Live provider module** — real DeepSeek/Ollama model + Data Broker retrieval + wake job/event bus job sources. Now ACTIVE (was shadow_fleet_provider no-op). | Active (2026-08-09) |

### Improvement Plans & Assessments *(both archived)*
| Document | Purpose | Status |
|----------|---------|--------|
| ~~VERIFIED_MATURITY_ASSESSMENT_2026-05-12~~ | Maturity scorecard 7.51/10 baseline | **Purged** — historical baseline (current ≈7.7) |
| ~~FOCUSED_IMPROVEMENT_PLAN~~ | 7 verified gaps | **Purged** — see Open Items below |

---

## TIER 3 — LLM Fleet Phase Test Reports (historical, do not modify)

`docs/v4_1_phase1_pilot_report.md` · `docs/v4_1_phase1c_controlled_expansion_report.md` ·
`docs/v4_1_phase1d_limit5_report.md` · `docs/v4_1_phase1_final_audit.md` ·
`docs/v4_1_phase1_final_closeout_report.md`  *(verify individually before relying on; some may be archived)*

---

## TIER 4 — Superseded / Purged

| Document | Disposition |
|----------|-------------|
| ~~ARCHITECTURE_OVERVIEW.md~~ | **Purged** (was archived; superseded by SYSTEM_ARCHITECTURE_COMPLETE) |
| `llm_fleet_strategy_v3_4_1.md` | **Purged** — no longer in tree; superseded by v4.1 FINAL |
| `IMPROVEMENT_PLAN_2026-05-11.md` | **Purged** — no longer in tree |
| `SYSTEM_AUDIT_2026-05-11.md` | **Purged** — no longer in tree |
| `candidate_freshness_3_bucket_design.md` | **Not found** — design captured in strategy YAML TTL buckets (B1/B2/B3) |

---

## Known Documentation Drift

**Policy (2026-06-22):** Active canonical docs use `docs/LIVE_SYSTEM_FACTS.md` — not hard-coded counts.
Run `.venv/bin/python3 scripts/generate_system_facts.py` to regenerate and check `data/system_fact_drift.json`.

Exempt from drift checks: `CHANGELOG.md` (historical), `PHASE*_CLOSEOUT.md` (evidence). *(Note: `docs/_archive/` was removed in the 2026-08-16 docs cleanup — superseded docs now live in git history / Google Drive, not in-repo.)*

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
| 2026-08-27 | **CIO platform audit closed out (19 PRs, `2ccee09a` → `b4b6ced7`):** indexed `docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md` (Phase 1 findings) + `CIO_PLATFORM_REMEDIATION_2026-08-27.md` (Phase 2 plan, now carrying the item→PR→commit closeout table and the ranked remainder). All P0 data-integrity items shipped; C3 Stage B (historical price scrub), M1/M10 (hub↔main divergence, needs operator sign-off), and H4 Phases 2–3 remain. New: `docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md` (68-min CI outage from a repo-visibility flip; detection signature + runbook), with the public-repo invariant added to `AGENTS.md` and `AI_WORK_POLICY.md` §13.1. Safety-gate bugfix `#540` (phantom `2FA` authority violation from opaque hex ids) recorded in `docs/CHANGELOG.md`. |
| 2026-08-11 | **Advisory desk CIO P1–P5 docs:** indexed `docs/cio/THESIS_STORE_P3.md`, `WAKE_TRACES_P5.md`, `P2B_PLAN_ENRICHMENT.md`, Telegram converse runbook, situation catalog; desk-v1 README + CHANGELOG updated on `feature/advisory-desk-v1`. |
| 2026-08-09 | **CIO & Wealth docs synced:** CIO Phase 3 delivery (Alex autonomous CIOrity Officer, hybrid OpenClaw+Trade AI, 9 PRs, action ledger, heartbeat, /v3/cio); 38-file `docs/architecture/cio/` indexed; OpenClaw CIO architecture feedback (2026-08-08) synced; Steph Wealth Advisor full docs created (`docs/wealth-advisor/STEPH_WEALTH_ADVISOR.md`); AGENT_ROSTER refreshed (model policy, Wave-3 states, OpenClaw heartbeats, authority boundaries, Morgan added, all qwen3:14b→gemma3:12b/DeepSeek); DOCS_ROSTER pending regeneration. |
| 2026-07-15 | Research Intelligence v2.5: security-level RSI/RS/valuation conviction + multi-factor sizing; `RESEARCH_INTELLIGENCE_V2_5_SECURITY_MULTIFACTOR.md`. |
| 2026-07-15 | Research Intelligence v2.4: concentration + heat actively size recs, theme capacity, funding trims; `RESEARCH_INTELLIGENCE_V2_4_CONCENTRATION_SIZING.md`. |
| 2026-07-15 | Research Intelligence v2.3: consistent portfolio-aware recs by primary, quality tiers, narrative polish; `RESEARCH_INTELLIGENCE_V2_3_CONSISTENCY.md`. |
| 2026-07-15 | Research Intelligence v2: freshness/archive, retirement seed, feedback API, professional dashboard; `RESEARCH_INTELLIGENCE_V2.md`. |
| 2026-07-15 | Research Intelligence v1: taxonomy + aggregator + `/api/v2/research-intelligence` + CC v3 Research Intel hub; `RESEARCH_INTELLIGENCE_V1.md`. |
| 2026-07-05 | Hermes maturity hardening: learning scorecard, evidence gates, counterfactuals, do-no-harm report, symbol journey extensions, advisory-only governance; `HERMES_CLOSED_LOOP_TRACEABILITY.md` + CHANGELOG updated. |
| 2026-07-04 | PR #33 canary hardening: reconciled after-hours policy (override-required), per-account arming, `protective_stop_canary.py` lifecycle/read-back; runbook + CHANGELOG updated; build marker `cc-v3 stop-evidence PR33 2026-07-04`. |
| 2026-06-30 | Expanded `MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` to full policy text; cross-linked from `STOP_METHODOLOGY.md`. |
| 2026-06-22 | A1A consolidation: LIVE_SYSTEM_FACTS.md, canonical docs → live pointers, drift detector hardened, DOCS_CONSOLIDATION closeout; runtime YAML/JSON/scripts committed. |
| 2026-06-22 | Added stabilization + maturity audit docs; open-items updated (overnight LLM cron, KTOS/KBR stops); SYSTEM_FACTS + STATE_OF_REPO regenerated. |
| 2026-06-19 | Index created + path/status verified against filesystem (14 corrections vs draft). Reflects commits d09a653c (deployment log) / 075bd602 (canary 2026-06-22) / 94e7275d (rotate-gap directives) / 65b3c751 (watchpool gap chip). |

### Watch Decision Desk V5 (2026-07-22)
- `docs/audits/WATCH_DECISION_DESK_V5_BASELINE_2026-07-22.md` — baseline audit + live CECO proofs
- `config/watch_decision_refresh_policy.yaml` — server-owned refresh policy (P0–P3)
- `scripts/watch_decision_refresh.py` / `watch_decision_scheduler.py` / `deterministic_thesis.py`
- API: POST /api/v2/watch/decision/refresh · GET …/refresh/status · …/latest · …/summary
