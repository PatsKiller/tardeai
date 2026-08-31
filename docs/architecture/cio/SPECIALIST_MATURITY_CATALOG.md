# Specialist Maturity Catalog

Status:      ACTIVE
as_of:       2026-08-13T15:38:32-04:00
Measured at: efcc51365 / not measured

## Phase 2.4 Post-Hardening State

| Field | Alex (CIO) | Maria (PA) | Steph (Wealth) | Guardian (Risk) | Ledger (Tax) |
|-------|-----------|------------|----------------|-----------------|--------------|
| **Identity** | Chief Investment Officer — synthesis, coordination, operator-facing advice | Personal Assistant & Concierge — front door, operator message classification, Telegram | Wealth Advisor — allocation, portfolio analysis, rebalancing | Risk Critic — deterministic-first risk data analysis | Tax & Account-Constraint Specialist — IRA limits, wash-sale checks |
| **Scope** | Platform-wide CIO reasoning, specialist coordination, priority communication | Operator message triage, Command Center queries, watchlist management | Portfolio snapshots, sector analysis, concentration flags, rebalancing signals — consumes Guardian/Ledger evidence | Risk exposure, stop-loss analysis, position sizing, volatility, regime | Account-type constraints, IRA contribution limits, wash-sale proximity, tax-lot validation |
| **Deterministic Dependencies** | Trade AI portfolio/risk/health data, CIO action ledger, handoff queue, CIO run store, operator profile, capability matrix | Trade AI readonly, Trade AI watchlist, Command Center | Trade AI portfolio_snapshot, risk_snapshot, income model, Guardian evidence, Ledger evidence | Trade AI risk_snapshot, risk data, stop-loss state, volatility metrics | Trade AI gain_guardian_tax, cost_basis, position_transfer data |
| **LLM Role** | Synthesis of deterministic data — never fabricates financial facts | Data query routing, conversational concierge — never invents portfolio numbers | Interpretation of allocation data — distinguishes fact from LLM synthesis; presents tradeoffs, not decrees | Risk explanation and challenge — deterministic calculations from Trade AI, not LLM estimates | Constraint flagging — applies fixed rules to Trade AI data, not LLM tax recall |
| **Tool Allowlist** | tradeai-readonly, CIO services (action ledger, handoff queue, run store, notification outbox, hermes queue) | tradeai-readonly, tradeai-watchlist | Portfolio JSON reads, Trade AI data reads | tradeai-risk-read (read-only) — no write tools | tradeai-account-read (read-only) — no execution tools |
| **Model/Process Policy** | deepseek-v4-pro (PRO), escalation: PRO_THINK, FAST for simple synthesis | deepseek-v4-pro primary, deepseek-v4-flash for FAST narratives | deepseek-v4-pro (PRO) primary, deepseek-v4-flash (FAST) allowed | deepseek-v4-flash (FAST) — deterministic-first | deepseek-v4-flash (FAST) — deterministic-first |
| **Current Maturity (P2.4)** | READY_AUTONOMOUS_MANAGER — workspace, SOUL, IDENTITY, TOOLS, process registry, CIO run orchestrator, all Phase -1 services integrated | OPERATIONAL — full workspace, process registry entries, actively used as operator front door | READY_AUTONOMOUS_ADVISORY — workspace hardened, artifact contract defined, specialist evidence consumption documented | READY_AUTONOMOUS_ADVISORY — SOUL hardened, artifact contract defined, governed routing target specified | READY_AUTONOMOUS_ADVISORY — SOUL hardened, artifact contract defined, governed routing target specified |
| **Known Gaps** | Fallback chain still has claude-cli + ollama; guardrail config pending Session 2 | Fallback chain includes chatgpt/gpt-5.4 + ollama; not yet governed-only | Fallback chain has claude-cli + ollama; needs governed route hardening | No runtime; no tool wiring; no model canary | No runtime; no tool wiring; no model canary |
| **Provider Route** | DeepSeek V4 (governed) | DeepSeek V4 (governed bridge planned) | DeepSeek V4 (governed bridge planned) | DeepSeek V4 FAST (governed) | DeepSeek V4 FAST (governed) |
| **Handoff Readiness** | Can receive from Maria; can create to all specialists; CIO run orchestrator manages lifecycle | Can classify and create handoffs to Alex | Ready for Alex-initiated handoffs; artifact contract defined | Ready for Alex-initiated handoffs; artifact contract defined | Ready for Alex-initiated handoffs; artifact contract defined |
| **Tests** | P-1.2B, P-1.3, P-1.4, P-1.5, P-1.6, P-1.7, P2.3 | Via CIO integration (P-1.3–P-1.4) | P-1.8 identity tests, P2.4 SOUL hardening | P-1.8 identity tests, P2.4 SOUL hardening | P-1.8 identity tests, P2.4 SOUL hardening |
| **Canary Required** | G0-CIO, G0-DS (governed tool-loop proved in P-1.2B) | G0-HO (handoff from Maria → Alex) | G0-SPEC (identity + no fallback) | G0-SPEC (identity + no fallback) | G0-SPEC (identity + no fallback) |
| **Production Schedule** | Deferred to Session 2 | Deferred — Maria remains operational as-is | Deferred to Session 2 | Deferred to Session 2 | Deferred to Session 2 |

## Fallback Chain Audit

All financial agents currently have fallback chains that include non-DeepSeek providers. Target state for ALL: NONE.

| Agent | Current Fallback Chain | Target | Status |
|-------|----------------------|--------|--------|
| Alex | [flash, chat, claude-sonnet, ollama] | NONE | Pending Session 2 |
| Maria | [flash, chat, gpt-5.4, ollama] | NONE | Pending Session 2 |
| Steph | [flash, chat, claude-sonnet, ollama] | NONE | Pending Session 2 |
| Guardian | N/A (not in openclaw.json) | NONE | Pre-registered only |
| Ledger | N/A (not in openclaw.json) | NONE | Pre-registered only |

## Process Registry Mapping

| Specialist | Process ID | Policy | Lane | Registered |
|------------|-----------|--------|------|------------|
| Alex | alex_cio_synthesis | PRO | deepseek-v4-pro | P-1.2A |
| Alex | alex_cio_escalation | PRO_THINK | pro_think | P-1.2A |
| Maria | watchlist_maria_flash_narrative | FAST | deepseek-v4-flash | Pre-existing |
| Maria | watchlist_maria_priority | (OAuth) | OAuth | Pre-existing |
| Steph | watchlist_steph_flash_narrative | FAST | deepseek-v4-flash | Pre-existing |
| Steph | steph_allocation_planning | PRO/FAST | deepseek-v4-pro/flash | P-1.8 |
| Guardian | guardian_risk_critique | FAST | deepseek-v4-flash | P-1.8 |
| Ledger | ledger_tax_critique | FAST | deepseek-v4-flash | P-1.8 |

## Specialist Artifact Contract (P2.4)

Every specialist must produce handoff artifacts with these fields:

| Field | Required | Description |
|-------|----------|-------------|
| artifact_id | YES | Unique artifact identifier |
| artifact_type | YES | Type classification (risk_critique, tax_constraint_check, allocation_analysis, etc.) |
| specialist | YES | Specialist name (guardian, ledger, steph) |
| run_id | YES | Parent CIO run ID |
| handoff_id | YES | Parent handoff queue ID |
| input_snapshot_id | YES | Evidence snapshot reference |
| input_hash | YES | SHA-256 of input evidence |
| deterministic_evidence_refs | YES | List of Trade AI data sources used |
| conclusion | YES | Analysis summary or constraint verdict |
| confidence | YES | LOW / MEDIUM / HIGH |
| limitations | YES | Known data quality issues or gaps |
| contradictions | YES | Conflicting evidence (empty list if none) |
| model_provenance | YES | process_id, model, lane used |
| artifact_hash | YES | SHA-256 of artifact content |

## Handoff Lifecycle (P2.4)

1. Alex creates handoff via AgentHandoffQueue with artifact requirements
2. Specialist claims handoff
3. Specialist reads canonical Trade AI evidence via governed model bridge
4. Specialist writes artifact with full provenance
5. Handoff marked COMPLETED in AgentHandoffQueue
6. CIOEventDetector creates wake job for Alex
7. Alex receives completion wake and processes artifact

No autonomous specialist polling or scheduling. Manual governed routes only.

## Maria Handoff Contract

Maria's contract for CIO-level handoff to Alex:

1. Maria classifies operator messages on reception
2. Standard queries: Maria answers directly (Command Center, watchlist, concierge)
3. CIO-level synthesis triggers: Maria creates a handoff task to Alex via AgentHandoffQueue (P-1.4)
4. Maria remains FAST/deterministic: primary route deepseek-v4-flash for watchlist narratives
5. Maria NEVER performs CIO synthesis — she delegates to Alex
6. Maria NEVER invents portfolio numbers — she reads from Trade AI skills
7. Handoff task types: cio_synthesis, portfolio_review, specialist_coordination, risk_assessment
