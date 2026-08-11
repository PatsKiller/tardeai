# Trade AI v12 — Documentation Index
**Updated:** 2026-08-09 (CIO Phase 3 delivery · CIO architecture docs indexed · Steph Wealth Advisor docs · AGENT_ROSTER refreshed · model policy updated)
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
| `docs/_archive/prompts/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md` | CC execution prompt for fleet deploy | **Archived** *(was listed active; lives in _archive)* |

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
| `docs/_archive/2026-05-24_cleanup/old_versions/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md` | 23-strategy narrative playbook | **Archived** — superseded by live YAML config |
| `docs/_archive/2026-05-24_cleanup/old_versions/agents_bible.md` | Agent behavior rules, G1–G10, RACI | **Archived** — current rules live in agent configs |

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
