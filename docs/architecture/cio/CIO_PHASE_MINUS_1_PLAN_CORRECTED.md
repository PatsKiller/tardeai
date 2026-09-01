# CIO Phase -1 Plan — Architecture Corrected v3.3

Status:      ACTIVE
as_of:       2026-08-08T18:02:23-04:00
Measured at: efcc51365 / not measured

**Reference:** Gate 0 Platform Readiness Report (`docs/architecture/cio/CIO_PLATFORM_READINESS_REPORT.md`)
**Audit Date:** 2026-08-08 04:00 UTC
**Correction Date:** 2026-08-08 08:59 UTC (v3.0 original 12 corrections)
**v3.3 Correction Date:** 2026-08-08 09:13 UTC (11 additional corrections)
**Mode:** Read-only planning. No implementation, no provider calls, no state mutation.

---

## P-1.0 EXECUTION COMPLETE — Architecture Frozen

**Completion Date:** 2026-08-08 09:25 UTC-4
**Branch:** `feat/defense-desk-remediation`
**HEAD SHA:** `2f9655f9b2fc9cd9d2f7b77e85724a81204dac3a`
**Committer:** CIO P-1.0 Architecture Freeze Agent
**Provider Calls:** 0
**Telegram Messages:** 0
**Runtime State Changed:** None
**Containment State Changed:** No

### ADRs Produced (Frozen)

All ADRs written to `docs/architecture/cio/`:

| ADR | File | Status |
|---|---|---|
| Ownership Boundaries | `ADR_OWNERSHIP_BOUNDARIES.md` | FROZEN |
| LLM Governance Boundary | `ADR_LLM_GOVERNANCE_BOUNDARY.md` | FROZEN |
| CIO State Architecture | `ADR_CIO_STATE_ARCHITECTURE.md` | FROZEN |
| Durable State Event Sourcing | `ADR_DURABLE_STATE_EVENT_SOURCING.md` | FROZEN |
| Alex Authority Manifest | `ADR_ALEX_AUTHORITY_MANIFEST.md` | FROZEN |
| Scheduler Ownership | `ADR_SCHEDULER_OWNERSHIP.md` | FROZEN |
| Containment Specification | `ADR_CONTAINMENT_SPECIFICATION.md` | FROZEN |
| Specialist Calculation Policy | `ADR_SPECIALIST_CALCULATION_POLICY.md` | FROZEN |
| Dependency Graph | `PHASE_MINUS_1_DEPENDENCY_GRAPH.md` | FROZEN |

### Canonical Paths Discovered

| Path Type | Discovered Location | Status |
|---|---|---|
| Model registry | `config/llm_model_registry.json` + `scripts/lib/llm_model_registry.py` | FOUND |
| Process registry | `config/llm_process_registry.json` (29 registered processes) | FOUND |
| LLM gateway | `scripts/lib/agent_flash_governance.py` (544 lines, fail-closed governance) | FOUND |
| Reservation module | Embedded in `scripts/lib/agent_flash_governance.py` (`_reserve_run_budget`) | FOUND (embedded) |
| Settlement module | `scripts/lib/llm_consumption.py` (`gate_and_generate` with return_provenance) | FOUND |
| Consumption module | `scripts/lib/llm_consumption.py` + `scripts/lib/consumption_run_manual.py` | FOUND |
| Circuit breaker | Embedded in `scripts/lib/agent_flash_governance.py` (`circuit_open`, `_trip_circuit`) | FOUND (embedded) |
| Dedupe module | Embedded in `scripts/lib/agent_flash_governance.py` (`evidence_hash`, `already_completed`) | FOUND (embedded) |
| Pro routing | `scripts/lib/rockville/model_policy.py` + `config/rockville/ROCKVILLE_WATCH_CIO_MODEL_POLICY.json` | FOUND |
| Containment module | `scripts/lib/agent_jobs_containment.py` | FOUND |
| CIO module root | No dedicated CIO module — code is in `scripts/` root | NOT_FOUND (no dedicated module) |
| OpenClaw skill root | `~/.openclaw/skills/` (13 skill directories) | FOUND |
| Data state root | `data/` (25 subdirectories, existing JSONL audit patterns) | FOUND |
| API router | `scripts/api_v2.py` (Flask-style, 35K+ lines), `scripts/inference_api.py` | FOUND |

### Legacy CIO Tables Verified

| Table | Status | Nature |
|---|---|---|
| `cio_decisions` | EXISTS (100+ references in api_v2.py) | Pipeline decision records, NOT the durable action ledger |
| `cio_decision_responses` | EXISTS (SQL migration, feedback loop) | Feedback loop closure, NOT the durable action ledger |
| `alex_hygiene_log` | EXISTS (INSERT/SELECT in alex_hygiene.py) | Hygiene run audit, NOT the durable action ledger |
| Durable CIO Action Ledger | DOES NOT EXIST | To be built in P-1.3 as separate event-sourced JSONL |

### Containment State Verified

| Check | Result |
|---|---|
| `AGENT_JOBS_P0_CONTAINED` env | NOT SET |
| `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED` flag file | NOT FOUND |
| Crontab per-process override | `AGENT_JOBS_P0_CONTAINED=0 AGENT_JOBS_P0_CONTAINMENT_FLAG=/tmp/tradeai_agent_jobs_p0_worker_absent` (explicit non-containment) |

### P-1.0 Gate Status

```yaml
p_1_0_completed: true
p_1_1_ready: false  # Awaiting P-1.1 execution
merge_recommended: true  # Docs-only, no runtime changes
remaining_p1_0_blockers: none
tests: none (doc-only)
ci: none (doc-only)
```

### Next Step

**P-1.1: Alex Workspace Identity + Read-Only Tool Manifest** — depends on P-1.0 (architecture boundaries frozen, canonical paths discovered). Scope: Alex OpenClaw workspace files only. No heartbeat activation, no provider calls. See `PHASE_MINUS_1_DEPENDENCY_GRAPH.md` for full dependency chain.

---

## v3.3 Correction Log

This document applies 11 additional architectural corrections (v3.3) on top of the original 12 corrections (v3.0). Total corrections: 23. The corrected 11-PR sequence (P-1.0 through P-1.10) is preserved and refined.

### v3.3 Correction 1: FIX CIO TABLE TRUTH (was Correction 1 original specification)

**Finding:** The corrected plan line 33 stated "CIO Action Ledger | NONEXISTENT (no `cio_decisions` table...)" — but legacy `cio_decisions`, `cio_decision_responses`, and `alex_hygiene_log` tables all EXIST in the PostgreSQL database and are actively used by the Trade AI pipeline.

**Evidence from codebase research:**
- `cio_decisions`: 100+ references in `scripts/api_v2.py` (SELECT, INSERT, aggregation queries), `health_agent.py` freshness checks, `system_freshness_monitor.py`, `cio_decision_engine.py` cron entry at 7 AM weekdays, Command Center visualization, multiple worktree syncs
- `cio_decision_responses`: SQL migration at `sql/migrations/20260511_feedback_loop_closure.sql` (CREATE TABLE with symbol index), API query in `api_v2.py`, documented in `MASTER_SYSTEM_DOCUMENTATION.md` as feedback loop
- `alex_hygiene_log`: SQL in `alex_hygiene.py` (INSERT/SELECT), API endpoint at `/api/v2/alex-hygiene/history`, documented in `LIFECYCLE_SCHEMA_AUDIT.md`

**Correction:** These legacy tables exist but are NOT the durable CIO action ledger. They serve pipeline decision recording (cio_decisions: daily rule-engine output; cio_decision_responses: feedback loop; alex_hygiene_log: hygiene run audit). The corrected codex position:

```yaml
legacy_cio_decisions_exists: true
cio_decision_responses_exists: true
alex_hygiene_log_exists: true
durable_cio_action_ledger_exists: false
```

**P-1.3 requirement:** Must explicitly define whether and how legacy `cio_decisions` can be referenced from the new action ledger without making it the action ledger itself. The legacy pipeline writes to `cio_decisions` daily; the new CIO action ledger is a separate append-only event store for Alex's autonomous CIO actions.

---

### v3.3 Correction 2: REMOVE WRITE-CAPABLE WATCHLIST SKILL FROM ALEX READ-ONLY MANIFEST

**Finding:** P-1.1's tool allowlist (line 382) listed `tradeai-watchlist (read: watchlist data)` as allowed. Codebase research confirms `tradeai-watchlist` is an API-backed WRITE-THROUGH skill: its SKILL.md declares "REAL read/write access to the live Trade AI watchlist" with commands `add`, `save-knowledge`, `add-topic` — all mutation operations. The Gate 0 Readiness Report Section 14 (line 583) also classifies it as "API-backed — safe, write-through API."

**Correction:** Remove `tradeai-watchlist` from Alex's read-only tool manifest entirely.

**Allowed initially:** `tradeai-readonly`, narrowly scoped read-only health/status APIs, later `cio_action_read`, later handoff read/claim tools where required.

**NOT allowed:** `tradeai-watchlist`, any star/unstar/list mutation, any write-through research mutation, scalp approval, order/proposal execution, system/ops tools.

---

### v3.3 Correction 3: DO NOT INVENT REPOSITORY PATHS OR PROCESS IDS

**Finding:** P-1.2 (lines 416-421) proposed paths like `src/llm/gateway/openclaw_agent_gateway.py` and process IDs like `alex_cio_advisory`. Codebase research confirms these are conceptual — they do not match actual repository conventions:

- **Actual Python code root:** `scripts/`, not `src/`
- **Actual LLM gateway module:** `scripts/lib/agent_flash_governance.py` (484+ lines, governs DeepSeek Flash path)
- **Actual process registry:** `config/llm_process_registry.json` (contains registered IDs like `watchlist_maria_flash_narrative`, `watchlist_cio_synthesis`, `deepseek_flash_operator_smoke` — NOT `alex_cio_advisory`)
- **Actual task-to-process mapping:** Defined in `agent_flash_governance.py` lines 31-41 (`TASK_TO_PROCESS` dict)
- **Actual API router:** `scripts/api_v2.py` (35K+ lines, Flask-style routing); `scripts/inference_api.py` (inference router)
- **Actual data/state root:** `data/` directory (not `src/data/`)
- **Actual CIO module root:** No `src/cio/` directory exists; CIO-related code is in `scripts/` root
- **Actual OpenClaw skill root:** `~/.openclaw/skills/`

**Correction:** Mark all existing path/ID references in the plan as CONCEPTUAL. Add requirement: P-1.0 must discover actual canonical paths from the repository before any P-1.2 through P-1.10 implementation begins.

**Canonical paths to discover:**
- `canonical_llm_gateway_module`: actual gateway module path (observed: `scripts/lib/agent_flash_governance.py`)
- `canonical_agent_flash_governance_module`: actual governance module
- `canonical_process_registry`: actual process registry file (observed: `config/llm_process_registry.json`)
- `canonical_api_router_pattern`: actual API routing pattern (observed: `scripts/api_v2.py` Flask-style, `scripts/inference_api.py`)
- `canonical_data_state_root`: actual data directory path
- `canonical_cio_module_root`: actual CIO code location (no dedicated module — code is in `scripts/` root)
- `canonical_openclaw_skill_root`: actual OpenClaw skill directory (observed: `~/.openclaw/skills/`)

---

### v3.3 Correction 4: TIGHTEN DIRECT OPENCLAW DEEPSEEK EXCEPTION

**Finding:** Correction 4 in the original plan already established that OpenClaw agents should route through Trade AI's governed gateway. However, the LAB exception was too broad — it allowed "direct OpenClaw DeepSeek for diagnostics" without explicit restrictions on financial agents.

**Correction:** Financial agents (Alex/Maria/Steph/Guardian/Ledger) must never have direct OpenClaw DeepSeek as fallback. If the governed Trade AI LLM route fails → typed failure → no direct OpenClaw DeepSeek fallback. Direct DeepSeek may remain only for:

1. Separate non-financial diagnostic/test agent
2. Explicit manual CLI diagnostic (`openclaw agent --agent diag`)
3. Isolated lab config (no financial tools, no portfolio access)
4. NO production CIO handoff route

OpenClaw's `secretref-managed` DeepSeek credential path must not be the production CIO path for any financial agent. The governed gateway is the ONLY paid-model route for financial agents.

---

### v3.3 Correction 5: FIX JSONL EVENT-STORE ATOMICITY

**Finding:** P-1.3 (lines 156-168) defined basic append-only properties but lacked event-sourcing primitives. The original spec had file lock + O_APPEND + hash but no stream ID, no event type, no chain hash chaining, no derived projection, and no crash test scenarios.

**Correction:** The event log must be append-only event sourced. Each line must carry:

```
event_id | stream_id | event_type | occurred_at | prev_event_hash | payload_hash | event_hash | payload
```

**Write behavior:**
1. Acquire exclusive file lock (fcntl)
2. Verify chain head (last event_hash matches expected)
3. Append single event line using O_APPEND (atomic at POSIX line boundary)
4. fsync the file descriptor
5. Release lock
6. Update derived manifest/projection afterward (lazy, async)
7. If derived update fails → recover/rebuild from event log (event log is authoritative)

**The event log is authoritative; manifest/index/projection is derived and rebuildable.**

**Required crash test scenarios:**
- Write → kill process mid-write → recover → verify no partial event, chain intact
- Write 50 events → kill process → restart → verify all events readable, chain verified, projection rebuilds correctly
- Simulated disk-full → write fails → verify no corrupted event, lock released, previous chain intact
- Concurrent writer collision → second writer blocked by lock → retries or fails gracefully

---

### v3.3 Correction 6: MAKE HANDOFF/OUTBOX STATE EVENT-SOURCED

**Finding:** P-1.4 and P-1.7 proposed mutating status fields on handoff and notification records (status enum transitions). This is mutation of prior rows, not event sourcing.

**Correction:** Do not mutate prior JSONL rows. Represent state transitions as events.

**Handoff stream event types:**
- `HANDOFF_ENQUEUED` — initial creation
- `HANDOFF_CLAIMED` — agent claims the handoff
- `HANDOFF_STARTED` — processing begins
- `HANDOFF_RETRY_SCHEDULED` — retry after failure
- `HANDOFF_COMPLETED` — successful completion
- `HANDOFF_FAILED` — terminal failure
- `HANDOFF_EXPIRED` — deadline exceeded
- `HANDOFF_CANCELLED` — operator/source cancellation

**Notification stream event types:**
- `NOTIFICATION_ENQUEUED` — notification created
- `DELIVERY_ATTEMPTED` — delivery was attempted (record outcome)
- `DELIVERY_CONFIRMED` — delivery verified
- `DELIVERY_RETRY_SCHEDULED` — retry queued
- `NOTIFICATION_EXPIRED` — past expires_at
- `NOTIFICATION_DEAD_LETTERED` — terminal after max retries

**Read projections** derive current status by replaying the event stream. **Idempotency keys** (stream_id + event_type dedupe) prevent duplicate events.

---

### v3.3 Correction 7: FIX OPERATOR-MESSAGE DIRECTION IN P-1.6

**Finding:** P-1.6's trigger sources (lines 612-621) and the Notification Outbox (P-1.7) conflated inbound and outbound communication. The Notification Outbox is OUTBOUND only — CIO → operator delivery. Operator input requires a separate inbound path.

**Correction:** P-1.6 trigger sources corrected to:

1. Scheduled CIO job due (deterministic timer)
2. Material portfolio/market event (price threshold, stop trigger, regime change)
3. Health boundary state transition (data_quality crossing threshold, system state change)
4. **Inbound operator/CIO request** (separate ingress: Telegram/Maria → operator command/message ingress → classified request → Agent Handoff Queue → Alex)
5. Specialist handoff (Guardian/Ledger/Steph critique ready)
6. Hermes challenge resolution
7. Action-ledger follow-up condition due

The inbound operator path is: `Telegram/Maria → operator command/message ingress → request classification → Agent Handoff Queue enqueue → Alex polls → Alex picks up`. This is DISTINCT from the Notification Outbox (Alex → operator delivery).

---

### v3.3 Correction 8: CORRECT CANARY COUNT AND G0-DS-08

**Finding:** Line 838 states "All 28 canaries pass or documented as explicitly deferrable." Count of canaries in the P-1.10 table:

| Group | Canaries | Count |
|---|---|---|
| G0-DS-01 through G0-DS-08 | 8 |
| G0-CIO-01 through G0-CIO-03 | 3 |
| G0-HO-01 through G0-HO-03 | 3 |
| G0-HEALTH-01 through G0-HEALTH-02 | 2 |
| G0-WAKE-01 through G0-WAKE-03 | 3 |
| G0-NOTIFY-01 through G0-NOTIFY-03 | 3 |
| G0-SPEC-01 through G0-SPEC-04 | 4 |
| G0-HERMES-01 through G0-HERMES-03 | 3 |
| **TOTAL** | **29** |

**Correction:** The correct count is 29 named canaries, not 28.

**Replace G0-DS-08:** The original G0-DS-08 "OpenClaw independent API key" was a baseline measurement of the governance gap, not a target-state canary. Replace with target-state canary:

**G0-DS-08: Financial-agent direct-path denial** — proves Alex governed call uses Trade AI credential only, direct OpenClaw DeepSeek not available as fallback, failure returns typed no-fallback state, no ungoverned financial-model consumption recorded.

---

### v3.3 Correction 9: CORRECT CONTAINMENT VERIFICATION

**Finding:** Lines 846-847 reference "Containment flag (`P0_CONTAINED`)" and the Gate 0 Readiness Report (lines 71-73) checked env var `P0_CONTAINED`, `~/.config/`, and grepped for `P0_CONTAINED`. Codebase research proves the canonical containment implementation uses entirely different identifiers:

**Canonical containment (from `scripts/lib/agent_jobs_containment.py`):**
- **Env var:** `AGENT_JOBS_P0_CONTAINED` (NOT `P0_CONTAINED`)
- **Flag file:** `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED` (NOT `~/.config/`)
- **Optional override:** `AGENT_JOBS_P0_CONTAINMENT_FLAG` env var for alternate flag path
- **Behavior:** FAIL-CLOSED on any uncertainty (any I/O error, malformed content, unknown env value → block)
- **Scope:** Specifically guards `process_watchlist_agent_jobs.py` invocation
- **Callers:** `health_agent.py` (guard_remediation_command), `claude_escalation_handler.py` (guard_agent_jobs_execution), `process_watchlist_agent_jobs.py` (exit_if_contained_worker_entry, exit code 78), `agent_flash_governance.py`

**Verified state on this system (2026-08-08 09:13 UTC):**
- Canonical flag file `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`: **NOT FOUND** (does not exist on filesystem)
- The Gate 0 audit checked `P0_CONTAINED` which is NOT the canonical name — the audit tested the wrong identifier
- Crontab entries use process-scoped override: `AGENT_JOBS_P0_CONTAINED=0 AGENT_JOBS_P0_CONTAINMENT_FLAG=/tmp/tradeai_agent_jobs_p0_worker_absent`
- CECO Review Authorization Audit (2026-08-04) documented flag as "remained active" at that time — flag has since been cleared

**Correction:**
1. Replace all references to `P0_CONTAINED` with the canonical `AGENT_JOBS_P0_CONTAINED`
2. Replace `~/.config/` containment check with canonical path `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`
3. Document the canonical fail-closed behavior
4. Phase -1 must PRESERVE the canonical observed state (flag absent, env unset at host level, per-process overrides in cron)
5. Do NOT clear or assert inactive containment as prerequisite — the canonical implementation already handles this correctly

---

### v3.3 Correction 10: KEEP OPERATOR PROFILE NON-AUTHORITATIVE IN OPENCLAW

**Finding:** P-1.1 includes `workspace-alex/USER.md — operator profile` (line 379) without defining authority boundaries. The Gate 0 report noted "Trade AI financial memory...Survives everything. Accessible via HTTP API" and Correction 9 established "Financial memory → Trade AI authoritative."

**Correction:** OpenClaw USER/MEMORY may contain only:
- Preferred name/addressing style
- Communication preferences (format, verbosity, channels)
- Timezone and scheduling preferences
- Formatting preferences (charts vs tables)
- Non-authoritative relationship notes (current concerns, upcoming events, conversational tone)

Trade AI MUST own (authoritative, not stored in OpenClaw):
- Financial goals and investment policy statement (IPS)
- Account facts (account types, numbers, tax status)
- Tax constraints (tax brackets, state residency)
- Risk limits (concentration, VaR, max drawdown)
- Cash needs (income requirements, upcoming distributions)
- Portfolio models (target allocations, rebalancing bands)
- Action history (CIO action ledger, prior decisions, outcomes)

Alex reconstructs authoritative context from Trade AI on every material CIO run. OpenClaw USER.md is helpful for conversational quality but never authoritative for financial facts.

---

### v3.3 Correction 11: SPECIALISTS MUST BE DETERMINISTIC-FIRST

**Finding:** P-1.8 (lines 699-750) defines Guardian and Ledger as LLM-based specialist agents. But Guardian calculations (concentration, exposure, covariance/correlation, VaR/stress, stop/protection coverage, event risk) and Ledger calculations (tax lots, holding periods, wash-sale windows, account type, contribution/distribution constraints, estimated tax) are deterministic financial computations — they do not require LLM synthesis to produce accurate results.

**Correction:** Guardian and Ledger must be deterministic-first:

**Guardian deterministic service:**
- Portfolio concentration by symbol, sector, factor
- Exposure metrics (beta, delta, notional)
- Covariance/correlation matrices
- VaR / stress test calculations
- Stop-loss and protection coverage ratios
- Event risk scoring (earnings, FOMC, regulatory)

**Ledger deterministic service:**
- Tax lot identification (lot-level cost basis, acquisition date)
- Holding period tracking (short-term vs long-term classification)
- Wash-sale window detection (30-day window, across accounts)
- Account type constraints (IRA, Roth, taxable, HSA rules)
- Contribution/distribution constraints (RMD, 72(t), penalty risk)
- Estimated tax impact (STCG/LTCG, NIIT, state tax)

LLMs critique/explain deterministic evidence through governed gateway but must not invent the underlying financial calculation. The calculation comes from Trade AI's deterministic service layer (Python, SQL, existing trade/pricing/risk infrastructure). The LLM role is interpretation, narrative, and recommendation critique — not numeric production.

---

## Original Correction Log (v3.0, 12 corrections)

This document applies 12 architectural corrections from the original v3.0 plan to the Gate 0 Phase -1 plan. Each correction is documented with the original finding, the error, and the corrected position. The corrected 11-PR sequence (P-1.0 through P-1.10) replaces the original 8-PR sequence.

---

### Correction 1: Preserve Gate 0 Conclusions

**Original:** The Gate 0 report's specialist maturity classifications and runtime evidence were correct and must not be altered.

**Correction:** Accept all Gate 0 conclusions as-is:

| Conclusion | Verdict |
|---|---|
| Alex | SKELETON (template defaults, BOOTSTRAP not deleted, IDENTITY empty) |
| Maria | OPERATIONAL (rich SOUL.md, Command Center integration) |
| Steph | DESIGNED (basic wealth advisor persona, tax-aware) |
| Guardian (`risk_agent`) | SKELETON (agent SOUL exists but workspace empty — not production-ready) |
| Ledger | NONEXISTENT (no agent, no workspace, no config) |
| Hermes | ACTIVE but no bridge (16K rows, fresh, but Alex→Hermes query path undocumented) |
| OpenClaw + Trade AI DeepSeek paths | SEPARATE (two independent API keys, two cost ledgers) |
| Heartbeat | DISABLED (all HEARTBEAT.md files empty/comment-only) |
| Telegram | DEGRADED (127 timeout/error events in 24h, 3 delivery failures) |
| CIO Action Ledger | NONEXISTENT — no durable CIO action ledger exists. Legacy `cio_decisions`, `cio_decision_responses`, and `alex_hygiene_log` tables exist in PostgreSQL but are pipeline decision records, NOT Alex's CIO action ledger. See v3.3 Correction 1. |
| Health / Escalation / Coder Dispatch | SEPARATE systems that MUST remain outside Alex remediation authority |

**After:** No change — these classifications are the foundation for the corrected plan. CIO table truth corrected per v3.3 Correction 1.

---

### Correction 2: Fix Cost Feasibility Classification

**Original Gate 0 score:** `cost_feasibility = FAIL`. The report stated: "Even MINIMAL CIO workload...Fits under $0.25 cap with 100x headroom" and "NORMAL...Fits under $0.25 cap with 4x headroom" and "EVENT_HEAVY...Fits under $0.25 cap with 1.9x headroom," yet classified cost feasibility as FAIL and proposed P-1.8 to raise the cap to $1.50/day.

**Error:** The report's own arithmetic proves ALL three workload models fit under the current $0.25/day cap. The FAIL classification was based on an unsupported projection that the cap "would need $0.50-1.50/day." Since even EVENT_HEAVY fits at $0.133/day with 1.9x headroom, cost feasibility is PARTIAL, not FAIL.

**Corrected classification:** `cost_feasibility = PARTIAL`

**Corrected reasoning:**
- MINIMAL: ~$0.0024/day (100x headroom under $0.25 cap)
- NORMAL: ~$0.06/day (4x headroom)
- EVENT_HEAVY: ~$0.133/day (1.9x headroom)
- All measured scenarios fit under cap.
- BUT: cap is shared across all Trade AI LLM use, OpenClaw direct DeepSeek calls are outside the ledger (governance gap), and actual token distributions are unmeasured.
- Target: unify governance through Trade AI, run measured canaries, observe 7-14 days of real consumption, then propose cap change only if evidence requires.
- **REMOVED: Proposed P-1.8 "increase cap to $1.50."** There is no P-1.8 in the corrected sequence.

**Corrected position:** Do NOT propose raising the cap in Phase -1. Unify the governance boundary first, then measure.

---

### Correction 3: Fix Heartbeat Plan

**Original Gate 0 proposal:** Sections 5 and 15 proposed a layered heartbeat with escalating model calls — deterministic Layer 1 checking Trade AI health API, then Layer 2 escalation triggering a DeepSeek Flash call every 4 hours, then Layer 3 alert with another model call. This proposed model-triggering tasks in HEARTBEAT.md.

**Error:** Financial monitoring must NOT depend on periodic model calls. Even at $0.00027/call, the pattern of "check health → if unhealthy, call LLM → if blocked, call LLM again" introduces per-tick LLM consumption for a function that should be deterministic. The heartbeat is a wake/detect function, not a synthesis function.

**Corrected heartbeat architecture:**

```
Layer 1 — Deterministic Event Detector (Trade AI, $0 cost, no model):
  - Trade AI cron/service checks material conditions (health, data quality, market hours, events)
  - IF material change detected (health degradation, new operator message, scheduled CIO job)
  - THEN: create durable CIO wake job in Trade AI job queue
  - IF no material change → silence, no model call ever

Layer 2 — Durable CIO Wake (Trade AI → OpenClaw handoff):
  - Trade AI pushes wake job to Agent Handoff Queue (see Correction 6)
  - OpenClaw Alex receives durable wake/handoff on next poll
  - Alex evaluates job context (read-only: health score, action ledger, Hermes)

Layer 3 — Governed LLM Call (only if synthesis required):
  - IF job requires CIO synthesis (advisory, recommendation, challenge)
  - THEN: Alex issues governed LLM call through Trade AI LLM Gateway (see Correction 4)
  - IF job is status-only or informational → Alex acknowledges, no model call
```

**Conversational heartbeat (OpenClaw, separate):** OpenClaw may retain a conversational heartbeat mechanism for session housekeeping (e.g., "is this conversation still alive?"), but this is unrelated to financial monitoring and must NOT consume paid model calls.

**OpenClaw native no-model heartbeat:** Determine whether OpenClaw has a native no-model heartbeat mechanism. If it does not, do NOT emulate one with LLM calls. The financial wake path is fully handled by the deterministic Trade AI event detector above.

---

### Correction 4: Fix DeepSeek Governance Architecture

**Original Gate 0 finding:** `governed_llm_gateway_integration = FAIL`. OpenClaw and Trade AI use separate DeepSeek API keys with independent cost ledgers. The report proposed P-1.3 "Unified DeepSeek Consumption Tracking" — instrumenting both systems into a single daily cost ledger, effectively tracking both ledgers.

**Error:** "Tracking both ledgers" does not solve the governance problem. It creates a dual-key architecture where OpenClaw agents can still bypass Trade AI's authorization, reservation, daily cap, circuit breaker, dedupe, and artifact provenance. The correct architecture requires ONE governed paid-model boundary.

**Corrected architecture:**

```
OpenClaw Alex / Specialists
  │
  ▼
Allowlisted Trade AI LLM Tool/API (single gateway, single API key)
  │
  ├─ Trade AI Process Registry
  │   ├─ Process ID authorization (registered financial-agent process IDs)
  │   ├─ Reservation (pre-flight cost reservation against daily cap)
  │   ├─ Daily cap enforcement (LLM_GLOBAL_DAILY_USD_CAP = $0.25)
  │   ├─ Deduplication (6h TTL cache)
  │   ├─ Circuit breaker (8 consecutive errors → 900s cooldown, fail-closed)
  │   ├─ Settlement (post-flight cost settlement, consumption record)
  │   └─ Artifact provenance (model, tokens, process ID, run ID, hash)
  │
  ▼
deepseek-v4-flash / deepseek-v4-pro / explicit secondary
```

**Phase -1 target:** Plan migration of ALL financial-agent LLM calls away from independent OpenClaw paid DeepSeek execution. The OpenClaw `secretref-managed` DeepSeek credential path must not be the production CIO path.

**LAB exception (tightened per v3.3 Correction 4):** Direct OpenClaw DeepSeek may remain ONLY for:
1. Separate non-financial diagnostic/test agent
2. Explicit manual CLI diagnostic
3. Isolated lab config with NO financial tools
4. NO production CIO handoff route

Financial agents (Alex/Maria/Steph/Guardian/Ledger) must never have direct OpenClaw DeepSeek as fallback.

**What changes in the PR sequence:** The original P-1.3 "Unified DeepSeek Consumption Tracking" is replaced by P-1.2 "Governed OpenClaw → Trade AI LLM Gateway" — building the single gateway, not tracking two ledgers.

---

### Correction 5: Fix CIO Action-Ledger Implementation

**Original Gate 0 proposal:** P-1.2 proposed "Implement ledger write from Alex SOUL instructions" — meaning Alex would append directly to `cio_action_ledger.jsonl` by following instructions in SOUL.md. The report stated "Option B (JSONL + SHA-256 manifest)...Fast to implement, reuses existing `file_integrity.py`."

**Error:** Alex MUST NOT append directly to JSONL via SOUL.md instructions. A model agent writing filesystem records directly is architecturally unsafe: no schema enforcement, no atomicity, no authority validation, and model hallucinations produce corrupted or malformed entries that poison the ledger.

**Corrected architecture:**

```
Alex / Operator
  │
  ▼
cio_action_create / cio_action_update (Trade AI API tools)
  │
  ├─ JSON Schema validation (reject on schema violation)
  ├─ Authority validation (is this agent authorized for this action type?)
  ├─ Event sourcing (per v3.3 Correction 5 and v3.3 Correction 6)
  ├─ File lock / fsync / O_APPEND
  ├─ Immutable event append (append-only, never overwrite)
  ├─ Content hash (SHA-256 of each event, chained via prev_event_hash)
  ├─ Manifest update (file_integrity_manifest.json extended with ledger entries)
  └─ Read projection (for Agent Handoff Queue, notification outbox, dashboard)
```

**LAB storage (acceptable for Phase -1):** Append-only event-sourced JSONL.
- Path: `data/cio/cio_action_ledger.jsonl`
- Manifest: extend `data/runtime/file_integrity_manifest.json` to include ledger entries
- Writes by deterministic Python/service code (`cio_action_service.py`), never raw model-authored filesystem writes

**Required LAB properties (updated per v3.3 Corrections 5,6):**

| Property | Implementation |
|---|---|
| JSON Schema validation | Validate event against `cio_action_event.schema.v1.json` before any write |
| Event-sourced format | Each line: `event_id|stream_id|event_type|occurred_at|prev_event_hash|payload_hash|event_hash|payload` |
| Atomic append / lock / fsync | `fcntl.flock()` → verify chain head → O_APPEND write → fsync → release lock |
| Monotonic event IDs | UUIDv7 (time-ordered) |
| Chained content hash | SHA-256 of each event body; prev_event_hash links to prior event; event_hash covers full line |
| Chain/manifest integrity | Each event references previous event hash; manifest stores cumulative chain head |
| Append-only audit | File opened with O_APPEND; no truncation, no overwrite, no delete |
| Read projection | In-memory or SQLite read cache rebuilt on restart from JSONL event log |
| Corruption detection | On each write, verify previous event hash; on read, verify chain |
| Rebuildable projection | Manifest/index/projection is derived from event log; recoverable on corruption |
| Crash test scenarios | Write-kill-recover, disk-full, concurrent writer collision (per v3.3 Correction 5) |
| Recovery test | Automated canary: write → crash → recover → verify chain intact |
| No secrets | Event bodies must contain zero credentials, API keys, or tokens |

**Existing infrastructure reuse:** `scripts/lib/file_integrity.py` — YES, reusable.
- `FileIntegrity.compute_sha256()` → hash ledger event bodies
- `FileIntegrity.verify_file()` pattern → verify individual ledger entries
- `file_integrity_manifest.json` structure → extend to include `cio_action_ledger` file key with its own `sha256`, `size`, `max_age_minutes`
- New file key entry: `"cio_action_ledger": {"canonical_path": "data/cio/cio_action_ledger.jsonl", "sha256": "<chain-head-hash>", ...}`

**Relation to legacy CIO tables (v3.3 Correction 1):** P-1.3 must define whether and how legacy `cio_decisions` can be referenced from the new action ledger without making it the action ledger itself. The legacy pipeline writes to `cio_decisions` daily; the new CIO action ledger is an independent append-only event store.

**What this replaces:** Original P-1.2 "CIO Action Ledger (SOUL.md instructions)" → corrected P-1.3 "CIO Action Ledger LAB Service."

---

### Correction 6: Separate Handoffs from Telegram

**Original Gate 0 scope:** P-1.5 proposed "Durable Agent Handoff + Maria→Alex Bridge" and referenced `~/.openclaw/delivery-queue/` as a single durable outbox for both agent-to-agent messages AND Telegram delivery.

**Error:** Agent handoffs and operator notifications are different domains with different schemas, retry policies, and failure modes. Conflating them means Telegram delivery failure (common — 51 failures in 24h) could block agent handoff processing, and vice versa. They must be separate durable domains.

**Corrected separation:**

#### Domain 1: Agent Handoff Queue (Alex ↔ specialists)

Event-sourced stream (per v3.3 Correction 6). Event types: HANDOFF_ENQUEUED, HANDOFF_CLAIMED, HANDOFF_STARTED, HANDOFF_RETRY_SCHEDULED, HANDOFF_COMPLETED, HANDOFF_FAILED, HANDOFF_EXPIRED, HANDOFF_CANCELLED.

Core fields per handoff stream:
| Field | Type | Purpose |
|---|---|---|
| `handoff_id` | UUIDv7 | Stream ID (immutable) |
| `from_agent` | string | `alex`, `maria`, `steph`, `guardian`, `ledger` |
| `to_agent` | string | Target agent |
| `task_type` | enum | `cio_question`, `risk_review`, `tax_check`, `challenge`, `research_request`, `wake`, `operator_request` |
| `priority` | P1/P2/P3 | Processing priority |
| `deadline` | ISO8601 | Must-complete-by timestamp |
| `budget` | float | Max USD allowed for LLM calls on this handoff task |

Storage: `data/cio/agent_handoff_queue.jsonl` (event-sourced, same integrity pattern as action ledger)

#### Domain 2: Operator Notification Outbox (Telegram / Command Center) — OUTBOUND ONLY

Event-sourced stream (per v3.3 Correction 6). Event types: NOTIFICATION_ENQUEUED, DELIVERY_ATTEMPTED, DELIVERY_CONFIRMED, DELIVERY_RETRY_SCHEDULED, NOTIFICATION_EXPIRED, NOTIFICATION_DEAD_LETTERED.

Core fields per notification stream:
| Field | Type | Purpose |
|---|---|---|
| `notification_id` | UUIDv7 | Stream ID (immutable) |
| `cio_action_id` | UUID | Links to CIO action ledger event |
| `message_class` | enum | `advisory`, `alert`, `escalation`, `status`, `checkin`, `confirmation` |
| `severity` | enum | `P0`, `P1`, `P2`, `INFO` |
| `expires_at` | ISO8601 | After this, notification is stale and should not be delivered |
| `dedupe_key` | string | Deterministic key to prevent duplicate delivery |

**Critical rule:** Telegram delivery failure must NEVER lose the CIO action. The CIO action is written to the action ledger (Correction 5) BEFORE the notification is enqueued. Notification delivery is a separate, retryable, expirable concern.

**Operator inbound (separate, per v3.3 Correction 7):** Telegram/Maria → operator command/message ingress → classified request → Agent Handoff Queue → Alex. This is the INBOUND path and is separate from the OUTBOUND notification outbox.

Storage: `data/cio/notification_outbox.jsonl` (event-sourced, same integrity pattern)

**What this replaces:** Original P-1.5 "Durable Agent Handoff + Maria→Alex Bridge" → corrected P-1.4 "Durable Handoff Queue" and P-1.7 "Telegram Durable Notification Outbox."

---

### Correction 7: Fix Scheduler Migration

**Original Gate 0 proposal:** P-1.6 proposed "Move Alex cron entries from system crontab to OpenClaw cron" (the scheduler ownership table listed the migration as "Alex cron → OpenClaw cron").

**Error:** Moving financial cron jobs to OpenClaw cron duplicates schedules across two systems (Trade AI crontab + OpenClaw cron), creates ownership confusion, and violates the core architecture rule established in Section 7 of the Gate 0 report.

**Corrected scheduler ownership rules:**

| Function | Owner | Rationale |
|---|---|---|
| Deterministic financial / event detection | Trade AI | Cost-free, reliable, timezone-aware, existing infrastructure |
| Durable financial jobs (CIO wake, scheduled scans, periodic synthesis) | Trade AI | Jobs must survive OpenClaw restart, must have deduplication, must have restart recovery |
| Conversational heartbeat (session housekeeping) | OpenClaw | OpenClaw-native concern, no financial impact |
| Hermes research loops | Hermes (Trade AI crontab trigger) | Hermes coordinator owns research schedule |
| Ops remediation | Health / Escalation (Trade AI crontab) | Must remain outside Alex authority |
| Operator delivery | Durable outbox → OpenClaw / Telegram | Outbox writes are Trade AI; delivery is OpenClaw/Telegram |
| Operator ingress | Telegram/Maria → Agent Handoff Queue | Inbound path, separate from outbox per v3.3 Correction 7 |

**Existing `run_alex_daily.py` cron jobs — LEGACY path:**

The following crontab entries exist today but must NOT be duplicated in OpenClaw:

| Cron Entry | Current Schedule | Legacy Path | Replacement |
|---|---|---|---|
| `run_alex_daily.py` | Daily 5 AM | Trade AI crontab → script → direct model call | Replace with durable Trade AI CIO wake job → Agent Handoff Queue → Alex governed LLM call |
| `run_alex_daily.py` | Weekly Sun 8 AM | Trade AI crontab → script → direct model call | Replace with durable Trade AI CIO weekly job |
| `run_alex_daily.py` | Monthly 1st 9 AM | Trade AI crontab → script → direct model call | Replace with durable Trade AI CIO monthly job |
| `alex_hygiene.py` | Mon-Fri 7:15 AM | Trade AI crontab → script | Evaluate: is this financial or conversational? Route accordingly |
| `alex_gov_research.py` | Mon 6 AM | Trade AI crontab → script | Evaluate: route to Hermes challenge or CIO wake job |

**Migration plan (no implementation in Phase -1 — documentation only):**
1. Document all legacy cron entries in `docs/operations/LEGACY_CRON_INVENTORY.md`
2. For each entry, specify the target replacement mechanism (durable Trade AI job, handoff queue, or retirement)
3. No new OpenClaw cron schedules for financial cadence
4. After P-1.6 "Deterministic CIO Wake/Event Detector" is operational, retire legacy cron entries one at a time with operator approval

**What this replaces:** Original P-1.6 "Scheduler Ownership Documentation + Migration Prep (Alex cron → OpenClaw cron)" → corrected P-1.6 "Deterministic CIO Wake/Event Detector."

---

### Correction 8: Clarify Ledger Agent Scope

**Original Gate 0 proposal:** P-1.7 was titled "Ledger Agent Creation" and described: "Implement CIO action ledger read-only view. Wire into Health Agent for audit coverage monitoring. Connect to existing file_integrity infrastructure." This conflated a financial tax specialist with a CIO action ledger auditor.

**Error:** The name "Ledger" was overloaded to mean both (a) a tax/account-constraint domain specialist and (b) a CIO action-ledger/integrity auditor. These are completely different concerns.

**Corrected Ledger agent scope:**

| "Ledger" = tax/account-constraint specialist ONLY |
|---|
| Tax lots (lot identification, holding period tracking) |
| Wash-sale risk detection (30-day window, across accounts) |
| Account type constraints (IRA, Roth, taxable, HSA) |
| Asset location optimization (tax-efficient placement) |
| Estimated tax impact (STCG/LTCG, NIIT, state tax) |
| Distribution and withdrawal constraints (RMD, 72(t), penalty risk) |
| Retirement-account constraints (contribution limits, prohibited transactions) |
| Evidence-based tax/account critique of CIO recommendations |

**"Ledger" is advisory only. It does not execute, does not modify holdings, and does not audit the CIO action ledger.**

**Deterministic-first per v3.3 Correction 11:** Ledger calculations (tax lots, holding periods, wash-sale windows, account type, contribution/distribution constraints, estimated tax) come from deterministic Python/SQL services in Trade AI. The Ledger agent's LLM role is critique, explanation, and recommendation — not numeric tax calculation.

**If a separate audit/integrity component is needed:** Name it separately — e.g., `Auditor` or `IntegrityMonitor`. This component would:
- Read the CIO action ledger (read-only)
- Verify hash chains
- Detect corruption
- Report anomalies to Health Agent
- It would NOT be the same agent as the tax specialist "Ledger"

**What this replaces:** Original P-1.7 "Ledger Agent Creation" conflating tax + audit → corrected Ledger scope defined in P-1.8 "Minimum Specialist Foundation."

---

### Correction 9: Reclassify Workspace Memory

**Original Gate 0 score:** `workspace_memory = FAIL` — "Alex workspace is entirely template defaults. No MEMORY.md." Listed as one of four critical blockers.

**Error:** Alex lacking a MEMORY.md file is a real gap, but it is NOT the durable financial-memory blocker. The report acknowledged that "Trade AI financial memory...Survives everything. Accessible via HTTP API" — meaning the actual financial state of record lives in Trade AI, not in an OpenClaw workspace file.

**Corrected memory classification:**

| Memory Domain | Storage Location | Authority | Survives |
|---|---|---|---|
| **Financial memory** (CIO actions, operator decisions, IPS/goals, cases, outcomes, follow-up dates, evidence, model provenance) | Trade AI (CIO action ledger + PostgreSQL) | **Trade AI is authoritative** | Survives all OpenClaw restarts, new conversations, agent deletion |
| **Conversational memory** (preferences, relationship context, presentation style, non-authoritative continuity) | OpenClaw (MEMORY.md + session DB) | OpenClaw is helpful but non-authoritative | Survives session restart; lost on new Telegram conversation if no MEMORY.md |
| **Research memory** (Hermes intelligence, catalyst classification, market context) | Hermes DB (16K rows) | Hermes is authoritative | Survives everything |

**Operator profile authority per v3.3 Correction 10:** OpenClaw USER.md may contain non-authoritative preferences only (name, style, timezone, formatting). Trade AI owns authoritative financial facts (IPS, goals, accounts, tax, risk, cash needs, portfolio models, action history).

**Corrected position:** Alex lacking MEMORY.md is a workspace hygiene gap, not a financial readiness blocker. Alex must function after an empty or new OpenClaw conversation by reconstructing CIO state from Trade AI (action ledger API, health API, portfolio API, Hermes API).

**Required acceptance test — Restart / New Session Recovery:**

```
GIVEN: Alex starts in a fresh OpenClaw conversation (no session context, empty/new MEMORY.md)
WHEN: Alex receives a CIO query via Agent Handoff Queue
THEN: Alex queries Trade AI action ledger for prior actions
AND: Alex queries Trade AI health API for current platform state
AND: Alex queries Hermes for current research context
AND: Alex produces a CIO response consistent with prior decisions
AND: Alex writes the new action to the CIO action ledger
VERIFY: Alex's response references at least one prior CIO action from the ledger
VERIFY: Alex does not claim ignorance of past decisions
```

**MEMORY.md is still valuable** for: conversational continuity (how does the operator prefer to be addressed?), presentation preferences (charts vs. tables?), relationship context (current concerns, upcoming events). But it is a quality-of-life improvement, not a gate condition.

**What this changes:** `workspace_memory` is reclassified from a FAIL/critical-blocker to a PARTIAL/hygiene-gap. The corrected Gate 0 final acceptance (Correction 11) explicitly states: "workspace MEMORY.md is NOT a hard financial blocker when Trade AI state can reconstruct CIO context."

---

### Correction 10: Revised Phase -1 PR Sequence

**Original:** 8 PRs (P-1.1 through P-1.8) with incorrect dependency order, missing governance PR, conflated domains.

**Corrected:** 11 PRs (P-1.0 through P-1.10) with corrected ownership, correct dependency order, and frozen architecture boundaries. Refined by v3.3 corrections.

---

#### P-1.0: Phase -1 Architecture Corrections + Canonical Path Discovery

**Depends on:** Nothing (first PR)
**Scope:** docs/ADR only — this document + canonical path discovery. Freeze ownership boundaries before any code changes. Discover actual repository paths and process IDs.
**No-go scope:** No code, no config, no system changes, no enablement.

**Contents:**
- `docs/architecture/cio/CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` (this document, v3.3)
- `docs/architecture/cio/adr/ADR-G0-PHASE_MINUS_1_ARCHITECTURE.md` (ADRs extracted from corrections)
- `docs/architecture/cio/adr/ADR-DOMAIN_OWNERSHIP_BOUNDARIES.md` (corrected ownership rules)
- `docs/architecture/cio/CANONICAL_PATH_DISCOVERY.md` — map of discovered canonical paths from repository:
  - `canonical_llm_gateway_module` (observed: `scripts/lib/agent_flash_governance.py`)
  - `canonical_process_registry` (observed: `config/llm_process_registry.json`)
  - `canonical_api_router_pattern` (observed: `scripts/api_v2.py`)
  - `canonical_data_state_root` (to discover)
  - `canonical_cio_module_root` (to discover — currently in `scripts/` root)
  - `canonical_openclaw_skill_root` (observed: `~/.openclaw/skills/`)
  - `canonical_containment_module` (observed: `scripts/lib/agent_jobs_containment.py`)
  - `canonical_containment_flag_path` (observed: `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`)
- Document legacy CIO table inventory: `cio_decisions`, `cio_decision_responses`, `alex_hygiene_log` — what they are, what they're not

**Acceptance:**
- All 23 corrections documented with before/after (12 original + 11 v3.3)
- Ownership boundaries frozen: OpenClaw vs. Trade AI vs. Hermes vs. Health/Escalation
- All canonical paths discovered from repository (not invented)
- Legacy CIO tables documented: exist, active, but NOT the durable action ledger
- Containment state verified with canonical identifiers
- No code in this PR

**Tests:** Document review by operator
**Canaries:** None (doc-only)
**Rollback:** Revert the docs directory

---

#### P-1.1: Alex Workspace Identity + Read-Only Tool Manifest

**Depends on:** P-1.0 (architecture boundaries frozen, canonical paths discovered)
**Scope:** Alex OpenClaw workspace files. No heartbeat activation, no provider call, no financial MEMORY.md authority.

**Files to create/modify:**
- `workspace-alex/SOUL.md` — CIO persona, boundaries, correction-aware (not template)
- `workspace-alex/IDENTITY.md` — CIO role, not retirement-only
- `workspace-alex/USER.md` — operator profile: NON-AUTHORITATIVE preferences only (per v3.3 Correction 10):
  - Preferred name/addressing style
  - Communication preferences (format, verbosity, channels)
  - Timezone and scheduling preferences
  - Formatting preferences (charts vs tables)
  - Non-authoritative relationship notes
  - MUST NOT contain: financial goals, IPS, account facts, tax constraints, risk limits, cash needs, portfolio models, action history — these belong to Trade AI
- `workspace-alex/TOOLS.md` — financial read-only tool allowlist ONLY (per v3.3 Correction 2):
  - `tradeai-readonly` (read: portfolio, health, holdings, risk)
  - Narrowly scoped read-only health/status APIs
  - later `cio_action_read` (read: action ledger — from P-1.3 once implemented)
  - later handoff read/claim tools where required
  - **REMOVED: `tradeai-watchlist`** — it is a write-through skill (add, save-knowledge, add-topic). Per v3.3 Correction 2.
  - NO: execution tools, write tools, order tools, system tools, crontab, systemctl
  - NO: star/unstar/list mutation
  - NO: write-through research mutation
  - NO: scalp approval
  - NO: order/proposal execution
  - NO: system/ops tools
- Delete: `workspace-alex/BOOTSTRAP.md`
- `workspace-alex/AGENTS.md` — updated for corrected architecture

**No-go scope:**
- Do NOT enable HEARTBEAT.md (no heartbeat activation)
- Do NOT make any provider/API call
- Do NOT create MEMORY.md with financial authority
- Do NOT add any write tool to Alex's tool manifest
- Do NOT include tradeai-watchlist or any write-through skill

**Acceptance:**
- BOOTSTRAP.md deleted
- SOUL.md / IDENTITY.md not template defaults
- Tool allowlist is read-only, no execution or system tools
- tradeai-watchlist NOT in allowlist
- USER.md contains non-authoritative preferences only
- No heartbeat running, no provider calls observed in gateway logs

**Tests:**
- Workspace file presence and content audit
- Tool manifest allowlist validation (tradeai-watchlist absent)
- Gateway log check: zero Alex provider calls after PR merge

**Canaries:** None (no runtime changes)
**Rollback:** Revert workspace files from backup

---

#### P-1.2: Governed OpenClaw → Trade AI LLM Gateway

**Depends on:** P-1.1 (Alex identity and tool manifest ready)
**Scope:** Trade AI LLM gateway extension + OpenClaw tool integration. LAB only — direct OpenClaw DeepSeek remains for non-financial diagnostics until governed route proves parity.

**Files to create/modify (CONCEPTUAL — actual paths to be discovered by P-1.0):**
- `[canonical_llm_gateway_module]/openclaw_agent_gateway.py` — new gateway endpoint for OpenClaw agent LLM calls (CONCEPTUAL: actual module path TBD by P-1.0)
- `[canonical_process_registry]` — add registered financial-agent process IDs (CONCEPTUAL: actual process IDs TBD by P-1.0 based on canonical registry conventions. Currently observed IDs: `watchlist_maria_flash_narrative`, `watchlist_cio_synthesis`, etc. NOT yet observed: OpenClaw agent process IDs.)
- `[canonical_agent_flash_governance_module]` — extend to accept external agent process IDs with authorization check
- `~/.openclaw/skills/tradeai-llm/skill.yaml` — new OpenClaw skill: governed LLM call tool (CONCEPTUAL: actual skill location per P-1.0)
- `~/.openclaw/skills/tradeai-llm/tradeai_llm.py` — Python script that routes LLM call through Trade AI gateway

**Design:**
- OpenClaw Alex calls `tradeai-llm` tool (not direct DeepSeek plugin)
- Trade AI gateway validates process ID, checks authorization
- Trade AI process registry enforces: reservation, daily cap, dedupe, circuit breaker
- Trade AI routes to `deepseek-v4-flash` or `deepseek-v4-pro` based on process policy
- Settlement recorded in Trade AI consumption ledger
- Artifact provenance recorded (process ID, run ID, model, tokens, hash)
- Failure returns typed no-fallback state — NO direct OpenClaw DeepSeek fallback for financial agents (per v3.3 Correction 4)

**LAB exception (tightened per v3.3 Correction 4):** Direct OpenClaw DeepSeek available ONLY for:
1. Separate non-financial diagnostic/test agent
2. Explicit manual CLI diagnostic
3. Isolated lab config with NO financial tools
4. NO production CIO handoff route
Financial agents (Alex/Maria/Steph/Guardian/Ledger) must NEVER have direct OpenClaw DeepSeek as fallback.

**No-go scope:**
- Do NOT remove OpenClaw DeepSeek plugin yet (LAB exception for non-financial diagnostics)
- Do NOT change Trade AI's existing LLM routing (agent tasks still use Flash directly)
- Do NOT track two ledgers — OpenClaw consumption through gateway is in ONE ledger (Trade AI's)
- Do NOT allow financial agents direct OpenClaw DeepSeek fallback

**Acceptance:**
- OpenClaw Alex can issue a governed LLM call through Trade AI gateway
- Process registry validates and authorizes
- Daily cap, dedupe, and circuit breaker apply to governed calls
- Failed governed calls fail-closed (no silent fallback to direct OpenClaw DeepSeek)
- Consumption appears in Trade AI consumption ledger

**Tests:**
- Happy path: Alex → tradeai-llm → gateway → deepseek-v4-flash → response
- Authorization: unregistered process ID → rejected
- Cap enforcement: post-cap call → rejected
- Deduplication: duplicate call → cache hit
- Circuit breaker: 8 consecutive errors → 900s cooldown
- Fallback denial: governed route fails → NO silent fallback to direct OpenClaw path → typed failure state
- Direct-path denial canary (G0-DS-08 per v3.3 Correction 8): agent tries direct DeepSeek → blocked

**Canaries:** G0-DS-01, G0-DS-02, G0-DS-03, G0-DS-04, G0-DS-05, G0-DS-06, G0-DS-07, G0-DS-08 (executed only with explicit operator authorization)
**Rollback:** Remove `tradeai-llm` skill from OpenClaw; gateway endpoint is non-blocking

---

#### P-1.3: CIO Action Ledger LAB Service

**Depends on:** P-1.0 (architecture boundaries frozen, legacy CIO tables documented)
**Scope:** Deterministic Python service for CIO action ledger writes. Alex calls `cio_action_create` / `cio_action_update` tools — never writes files directly. Event-sourced architecture.

**Files to create/modify:**
- `[canonical_cio_module_root]/cio_action_service.py` — deterministic service: create, update-by-event, read, verify (CONCEPTUAL: actual path per P-1.0)
- `[canonical_cio_module_root]/schemas/cio_action_event.schema.v1.json` — JSON Schema for CIO action events (CONCEPTUAL)
- `[canonical_data_state_root]/cio/cio_action_ledger.jsonl` — append-only event-sourced store (CONCEPTUAL: actual data root per P-1.0)
- `[canonical_data_state_root]/runtime/file_integrity_manifest.json` — extend with event-sourced `cio_action_ledger` file key (CONCEPTUAL)
- `~/.openclaw/skills/cio-action-ledger/skill.yaml` — OpenClaw skill: `cio_action_create`, `cio_action_read` (CONCEPTUAL: actual skill location per P-1.0)
- `~/.openclaw/skills/cio-action-ledger/cio_action_ledger.py` — thin client calling the service

**Design (per v3.3 Corrections 5, 6):**
- Event-sourced JSONL format: `event_id|stream_id|event_type|occurred_at|prev_event_hash|payload_hash|event_hash|payload`
- Alex → `cio_action_create` tool → service validates → schema check → authority check → file lock → verify chain head → O_APPEND write → fsync → release lock → update derived projection
- All writes by deterministic Python code; Alex NEVER writes to JSONL directly
- Monotonic event IDs (UUIDv7)
- SHA-256 chain integrity (prev_event_hash links events)
- Append-only, no overwrite, no delete
- Manifest/projection is derived and rebuildable from event log
- Corruption detection on every write and read

**Properties (must pass all, updated per v3.3 Corrections 5, 6):**
1. JSON Schema validation
2. Event-sourced format with stream_id, event_type, prev_event_hash
3. Atomic append / lock / fsync / chain-head verify
4. Monotonic event IDs (UUIDv7)
5. Content hash (per event, chained via prev_event_hash)
6. Chain/manifest integrity (manifest stores chain head; rebuildable from event log)
7. Append-only audit (no truncation, no delete)
8. Read projection (queryable without JSONL parse; derived and rebuildable)
9. Corruption detection (on write: verify chain; on read: verify chain)
10. Crash test scenarios: write-kill-recover, disk-full, concurrent writer collision
11. No secrets in event bodies

**Legacy CIO table relationship (per v3.3 Correction 1):** Must document whether and how legacy `cio_decisions`, `cio_decision_responses`, and `alex_hygiene_log` can be referenced from the new action ledger without making them the action ledger itself.

**Reuse:** `scripts/lib/file_integrity.py` `FileIntegrity.compute_sha256()` for event hashing. `file_integrity_manifest.json` extended for ledger entries.

**No-go scope:**
- Do NOT let Alex append to JSONL directly (no SOUL.md file-write instructions)
- Do NOT use PostgreSQL yet (LAB = JSONL only; PostgreSQL in SHADOW phase)
- Do NOT conflate with legacy `cio_decisions` table

**Acceptance:**
- All 11 required properties verified by automated test
- Alex can create and read CIO actions via tool calls
- Write crash-recovery test passes (write-kill-recover, disk-full, concurrent collision)
- No direct file writes from Alex observed
- Legacy CIO tables documented: they exist but are not the action ledger

**Tests:**
- Service unit tests: schema validation, authority check, lock, atomic append
- Integrity test: write → hash verify → corrupt byte → detection
- Recovery test: write 10 events → kill process → restart → all 10 events readable, chain verified
- Crash test: write → SIGKILL mid-write → recover → verify no partial event
- Disk-full test: simulate ENOSPC → verify no corruption, lock released
- Concurrent test: two writers → one blocked by lock → graceful behavior
- Integration test: Alex → `cio_action_create` → event appears in ledger → `cio_action_read` returns it

**Canaries:** G0-CIO-01 (action ledger write), G0-CIO-02 (action ledger read), G0-CIO-03 (action ledger recovery)
**Rollback:** Stop service; JSONL file is append-only and safe to leave in place

---

#### P-1.4: Durable Handoff Queue

**Depends on:** P-1.2 (LLM gateway), P-1.3 (action ledger — handoffs reference actions)
**Scope:** Agent Handoff Queue for Alex ↔ specialists. Separate from Telegram notifications. Event-sourced.

**Files to create/modify:**
- `[canonical_cio_module_root]/agent_handoff_service.py` — deterministic event-sourced service (CONCEPTUAL)
- `[canonical_cio_module_root]/schemas/agent_handoff.schema.v1.json` — JSON Schema for handoff events (CONCEPTUAL)
- `[canonical_data_state_root]/cio/agent_handoff_queue.jsonl` — append-only event-sourced handoff store (CONCEPTUAL)
- `~/.openclaw/skills/agent-handoff/skill.yaml` — OpenClaw skill (CONCEPTUAL)
- `~/.openclaw/skills/agent-handoff/agent_handoff.py` — thin client

**Design (per v3.3 Corrections 6, 7):**
- Event-sourced stream types: HANDOFF_ENQUEUED, HANDOFF_CLAIMED, HANDOFF_STARTED, HANDOFF_RETRY_SCHEDULED, HANDOFF_COMPLETED, HANDOFF_FAILED, HANDOFF_EXPIRED, HANDOFF_CANCELLED
- Stream ID = handoff_id (UUIDv7, immutable)
- Current status derived from replaying event stream (read projection)
- Idempotency keys prevent duplicate events
- Retry policy: 3 attempts with exponential backoff (1m, 5m, 15m)
- Deadline enforcement: expired handoffs → HANDOFF_EXPIRED event
- Budget enforcement: if handoff task would exceed budget, fail with reason
- Maria → Alex handoff: Maria enqueues CIO question as `task_type=cio_question` → HANDOFF_ENQUEUED
- Operator inbound: Telegram/Maria → operator command ingress → classified request → HANDOFF_ENQUEUED into Agent Handoff Queue (per v3.3 Correction 7)
- Alex polls Agent Handoff Queue on wake

**No-go scope:**
- Do NOT combine with Telegram notification outbox (separate event-sourced domain — see P-1.7)
- Do NOT implement Hermes challenge bridge yet (see P-1.9)
- Do NOT mutate prior JSONL rows (event-sourced transitions only)

**Acceptance:**
- Maria can enqueue a CIO question for Alex → HANDOFF_ENQUEUED event
- Alex can poll, claim → HANDOFF_CLAIMED, and complete → HANDOFF_COMPLETED
- Failed handoffs retry with backoff → HANDOFF_RETRY_SCHEDULED events
- Expired handoffs → HANDOFF_EXPIRED events
- Budget exceeded handoffs fail with reason
- Handoff queue is separate from notification outbox
- Operator inbound requests flow through Agent Handoff Queue

**Tests:**
- Happy path: Maria enqueue → Alex poll → Alex claim → Alex complete → artifact linked
- Retry: fail twice → HANDOFF_RETRY_SCHEDULED twice → succeed on third → HANDOFF_COMPLETED
- Expiry: deadline passed → HANDOFF_EXPIRED
- Budget: handoff with $0 budget for LLM → HANDOFF_FAILED with budget reason
- Separation: Telegram failure does not affect handoff queue processing
- Event sourcing: replay handoff stream → projection shows correct current state
- Idempotency: duplicate enqueue → single HANDOFF_ENQUEUED event

**Canaries:** G0-HO-01 (Maria → Alex handoff), G0-HO-02 (handoff retry), G0-HO-03 (handoff expiry)
**Rollback:** Stop handoff service; queue file is append-only

---

#### P-1.5: Health Boundary + CIO_DATA_QUALITY_BLOCK

**Depends on:** P-1.2 (Alex can call governed LLM), P-1.3 (action ledger for block events)
**Scope:** Implement G0-HEALTH-01 canary from Gate 0 report. Alex cannot remediate infrastructure. Health state can block or degrade CIO advice.

**Files to create/modify:**
- `[canonical_cio_module_root]/cio_health_boundary.py` — reads health API, writes block/unblock events (CONCEPTUAL)
- `[canonical_cio_module_root]/schemas/cio_health_boundary.schema.v1.json` (CONCEPTUAL)
- `~/.openclaw/skills/cio-health/skill.yaml` — OpenClaw skill: `cio_health_check` (read-only) (CONCEPTUAL)
- No modifications to health_agent.py, claude_escalation_handler.py, or coder_dispatch.py

**Design:**
- Alex calls `cio_health_check` before any financial advisory
- If `data_quality = 0` AND `finnhub` is stale → CIO_DATA_QUALITY_BLOCK active
- If block active: Alex writes `cio_health_block` event to action ledger, responds to operator with block message, does NOT provide financial advice
- Alex MUST NOT say "based on stale data..." or attempt to work around the block
- Block clears automatically on next health check showing `data_quality > 0`
- Alex has NO authority to remediate health issues — that remains with health/escalation

**No-go scope:**
- Alex MUST NOT call health remediation scripts
- Alex MUST NOT modify health agent configuration
- Alex MUST NOT trigger escalation handler
- Health boundary is advisory-only: blocks advice, does not block operations

**Acceptance:**
- `data_quality = 0` blocks Alex from providing financial advice
- Alex writes `cio_health_block` event to action ledger
- Alex responds with correct block message (not "based on stale data...")
- Block clears when data quality recovers
- Alex cannot trigger remediation

**Tests:**
- Block active: Alex queries → receives block → writes block event → responds with block message
- Block transition: data quality recovers → next health check → Alex receives unblock → writes unblock event
- No remediation: Alex attempts remediation → rejected (not in tool allowlist)
- Agent Handoff Queue health integration: if health is blocked, handoffs from Maria → Alex include health context

**Canaries:** G0-HEALTH-01 (data quality block), G0-HEALTH-02 (auto-unblock on recovery)
**Rollback:** Health boundary check is advisory; Alex degrades gracefully if check unavailable

---

#### P-1.6: Deterministic CIO Wake / Event Detector

**Depends on:** P-1.2 (LLM gateway), P-1.4 (Agent Handoff Queue)
**Scope:** Trade AI deterministic event detector creates durable CIO jobs. No model calls for wake detection. No OpenClaw financial cron duplication. Separates inbound operator path from outbound notifications.

**Files to create/modify:**
- `[canonical_cio_module_root]/cio_event_detector.py` — deterministic checks, creates wake jobs (CONCEPTUAL)
- `[canonical_cio_module_root]/cio_scheduler.py` — durable CIO job scheduler (replaces legacy cron) (CONCEPTUAL)
- `[canonical_data_state_root]/docs/operations/LEGACY_CRON_INVENTORY.md` — document all legacy cron entries and their planned replacements (CONCEPTUAL)
- No new OpenClaw cron entries for financial cadence

**Design (per Correction 7, refined by v3.3 Correction 7):**
- Deterministic checks (no model, $0 cost):
  1. Is it time for a scheduled CIO job? (daily 5 AM, weekly Sun 8 AM, monthly 1st)
  2. Has health state changed materially? (score crossing threshold)
  3. Is there a pending operator/CIO request? (from inbound operator path: Telegram/Maria → operator command/message ingress → classified request → Agent Handoff Queue)
  4. Has a handoff deadline expired?
  5. Has Hermes flagged a material research finding?
  6. Has a specialist (Guardian/Ledger/Steph) handoff completed?
  7. Has an action-ledger follow-up condition become due?
- IF any check triggers → create durable CIO wake job in Trade AI job queue
- Wake job → Agent Handoff Queue → Alex picks up on next poll
- Deduplication: same wake condition → single job (dedupe key = condition hash)
- Restart recovery: if Trade AI restarts, re-scan conditions from last known state
- **Operator inbound is separate from notification outbox** (per v3.3 Correction 7)

**Trigger sources (corrected per v3.3 Correction 7):**
1. Scheduled CIO job due
2. Material portfolio/market event
3. Health boundary state transition
4. Inbound operator/CIO request (separate ingress path)
5. Specialist handoff ready
6. Hermes challenge resolution
7. Action-ledger follow-up condition due

**Legacy cron retirement path (documentation, not implementation):**
| Legacy Cron | Planned Replacement | Retirement Trigger |
|---|---|---|
| `run_alex_daily.py` (5 AM daily) | CIO daily wake job → Agent Handoff Queue → Alex governed synthesis | After P-1.6 wake job proves reliable for 7 days |
| `run_alex_daily.py` (Sun 8 AM) | CIO weekly wake job | Same |
| `run_alex_daily.py` (monthly 1st) | CIO monthly wake job | Same |
| `alex_hygiene.py` | Evaluate: conversational or financial? Route to OpenClaw or retire | After evaluation |
| `alex_gov_research.py` | Hermes challenge job or CIO wake job | After Hermes bridge (P-1.9) |

**No-go scope:**
- Do NOT create OpenClaw cron schedules for financial cadence
- Do NOT delete legacy cron entries yet (document only)
- Do NOT make model calls during wake detection
- Do NOT conflate inbound operator path with outbound notification delivery

**Acceptance:**
- Scheduled CIO jobs trigger without model calls
- Wake jobs are deduplicated (same condition → one job)
- Wake jobs survive Trade AI restart
- No OpenClaw cron entries created for financial schedules
- Legacy cron inventory documented
- Operator inbound and notification outbox are architecturally separate

**Tests:**
- Deterministic trigger: set scheduled time → wake job created in queue → Alex polls and receives
- Deduplication: trigger same condition twice → single wake job
- Restart: kill Trade AI process → restart → wake detector re-scans → creates missed wake jobs
- Cost: wake detection produces zero LLM cost
- Operator ingress: Telegram → Maria → handoff enqueue → Alex picks up (separate from outbox)

**Canaries:** G0-WAKE-01 (scheduled wake), G0-WAKE-02 (event wake), G0-WAKE-03 (restart recovery)
**Rollback:** Wake detector is new service; legacy cron continues until retirement approved

---

#### P-1.7: Telegram Durable Notification Outbox

**Depends on:** P-1.3 (action ledger — notifications reference CIO actions)
**Scope:** Durable notification outbox for OUTBOUND CIO→operator delivery. Event-sourced. Separate from Agent Handoff Queue and operator ingress. Delivery failure does not lose the CIO action.

**Files to create/modify:**
- `[canonical_cio_module_root]/notification_outbox_service.py` — deterministic event-sourced service (CONCEPTUAL)
- `[canonical_cio_module_root]/schemas/notification_outbox.schema.v1.json` (CONCEPTUAL)
- `[canonical_data_state_root]/cio/notification_outbox.jsonl` — append-only event-sourced outbox store (CONCEPTUAL)
- `~/.openclaw/skills/cio-notify/skill.yaml` — OpenClaw skill: deliver notifications via Telegram (CONCEPTUAL)

**Design (per v3.3 Corrections 6, 7):**
- Event-sourced stream types: NOTIFICATION_ENQUEUED, DELIVERY_ATTEMPTED, DELIVERY_CONFIRMED, DELIVERY_RETRY_SCHEDULED, NOTIFICATION_EXPIRED, NOTIFICATION_DEAD_LETTERED
- CIO action is written to action ledger FIRST (P-1.3), THEN NOTIFICATION_ENQUEUED
- This is OUTBOUND only: CIO → operator delivery
- Operator input uses separate inbound path (Telegram/Maria → operator ingress → Agent Handoff Queue) per v3.3 Correction 7
- Delivery retries: 3 attempts with backoff (30s, 2m, 10m) → DELIVERY_ATTEMPTED events → DELIVERY_RETRY_SCHEDULED if failed
- After 3 failures → NOTIFICATION_DEAD_LETTERED
- Expired notifications → NOTIFICATION_EXPIRED
- Idempotency: same dedupe_key → not re-enqueued

**No-go scope:**
- Do NOT combine with Agent Handoff Queue (separate event-sourced domain)
- Do NOT retry indefinitely (dead-letter after 3 attempts)
- Do NOT block CIO action creation on notification delivery
- Do NOT use this for operator inbound (that's a separate ingress path)

**Acceptance:**
- CIO action creation → NOTIFICATION_ENQUEUED → delivered via Telegram → DELIVERY_CONFIRMED
- Failed delivery → DELIVERY_ATTEMPTED → DELIVERY_RETRY_SCHEDULED → dead-letter on 3rd failure
- Expired notification → NOTIFICATION_EXPIRED
- Deduplication: same key → single NOTIFICATION_ENQUEUED event
- CIO action survives even if all deliveries fail
- Event stream replay produces correct current delivery status

**Tests:**
- Happy path: action → NOTIFICATION_ENQUEUED → delivery → DELIVERY_CONFIRMED
- Retry: Telegram down → 2 DELIVERY_ATTEMPTED failures → DELIVERY_RETRY_SCHEDULED → 3rd succeeds → DELIVERY_CONFIRMED
- Dead-letter: 3 failures → NOTIFICATION_DEAD_LETTERED
- Expiry: notification past expiry → NOTIFICATION_EXPIRED
- Deduplication: same action ID enqueued twice → one NOTIFICATION_ENQUEUED event
- Separation: Agent Handoff Queue continues working independently of notification state
- Scale: 500 notifications → replay → projection shows correct delivery states

**Canaries:** G0-NOTIFY-01 (notification delivery), G0-NOTIFY-02 (retry + dead-letter), G0-NOTIFY-03 (expiry)
**Rollback:** Outbox is independent; notifications queue, existing Telegram infrastructure continues

---

#### P-1.8: Minimum Specialist Foundation

**Depends on:** P-1.2 (LLM gateway), P-1.4 (Agent Handoff Queue)
**Scope:** Harden Guardian (deterministic-first), create Ledger (deterministic-first), harden Steph, integrate Maria. Maturity catalog. No broad schedules yet.

**Guardian — Deterministic-first (per v3.3 Correction 11):**

Guardian calculations MUST come from deterministic Python/SQL services:
- Portfolio concentration by symbol, sector, factor
- Exposure metrics (beta, delta, notional)
- Covariance/correlation matrices
- VaR / stress test calculations
- Stop-loss and protection coverage ratios
- Event risk scoring

LLM role: critique and explain deterministic evidence through governed gateway. Must NOT invent numeric risk calculations.

Workspace files (`workspace-risk_agent/`):
- `workspace-risk_agent/SOUL.md` — risk evidence critic persona, deterministic-first
- `workspace-risk_agent/IDENTITY.md`
- `workspace-risk_agent/TOOLS.md` — risk read-only tools (portfolio risk API, position concentration, VaR)
- Agent SOUL already exists (FLEET critic) — expand with deterministic boundary

**Ledger — NEW, Deterministic-first (per v3.3 Corrections 8, 11):**

Ledger calculations MUST come from deterministic Python/SQL services:
- Tax lot identification (lot-level cost basis, acquisition date)
- Holding period tracking (short-term vs long-term)
- Wash-sale window detection (30-day, across accounts)
- Account type constraints (IRA, Roth, taxable, HSA)
- Contribution/distribution constraints (RMD, 72(t), penalty risk)
- Estimated tax impact (STCG/LTCG, NIIT, state tax)

LLM role: critique and explain deterministic evidence through governed gateway. Must NOT invent numeric tax calculations.

Workspace files:
- `workspace-ledger/SOUL.md` — tax/account-constraint specialist, deterministic-first
- `workspace-ledger/IDENTITY.md`
- `workspace-ledger/TOOLS.md` — tax read-only tools (lot data, account types, tax estimates)
- Agent SOUL: tax-aware, lot-tracking, wash-sale-aware, account-constraint-aware, advisory only
- `~/.openclaw/agents/ledger/models.json` — use governed gateway only

**Steph (`workspace-steph/`):**
- Harden retirement planning depth
- Integrate with Ledger for tax-aware recommendations

**Maria (`workspace-maria/`):**
- Integrate with Agent Handoff Queue (enqueue CIO questions for Alex, handle operator ingress)
- Update SOUL.md for corrected agent handoff path and inbound operator routing

**Maturity catalog:**
- `docs/architecture/cio/SPECIALIST_MATURITY_CATALOG.md` — per-agent: scope, maturity, gaps, test coverage, canaries, deterministic boundary

**No-go scope:**
- Do NOT create broad specialist schedules (no cron, no heartbeat activation)
- Do NOT overload Ledger with audit/integrity scope
- Do NOT enable autonomous Guardian risk actions
- Do NOT let Guardian or Ledger LLMs produce numeric financial calculations (LLMs critique deterministic output only)

**Acceptance:**
- Guardian workspace operational with deterministic risk calculation service
- Ledger workspace created with tax scope only, deterministic tax calculation service
- Steph hardened with retirement planning depth
- Maria integrated with handoff queue and operator ingress
- Maturity catalog published with deterministic boundaries documented
- All specialists use governed LLM gateway (P-1.2), not direct DeepSeek

**Tests:**
- Guardian: deterministic service produces risk metrics → LLM critiques → CIO handoff
- Ledger: deterministic service produces tax data → LLM critiques → CIO handoff
- Guardian deterministic-only: disable LLM → risk metrics still computed → structured output available
- Ledger deterministic-only: disable LLM → tax data still computed → structured output available
- Steph: read portfolio + tax context → provide retirement distribution recommendation
- Maria: receive operator question → classify → enqueue CIO handoff if appropriate
- All specialists use governed LLM gateway (P-1.2), not direct DeepSeek

**Canaries:** G0-SPEC-01 (Guardian critique), G0-SPEC-02 (Ledger tax check), G0-SPEC-03 (Steph retirement), G0-SPEC-04 (Maria→Alex handoff)
**Rollback:** Specialists are advisory; system degrades gracefully without them

---

#### P-1.9: Hermes Challenge Bridge

**Depends on:** P-1.4 (Agent Handoff Queue), P-1.3 (action ledger — challenges reference actions)
**Scope:** Durable challenge jobs and artifacts. Hermes remains independent. No self-promotion.

**Files to create/modify:**
- `[canonical_cio_module_root]/hermes_challenge_service.py` — deterministic service: create challenge job, query results (CONCEPTUAL)
- `[canonical_cio_module_root]/schemas/hermes_challenge.schema.v1.json` (CONCEPTUAL)
- `[canonical_data_state_root]/cio/hermes_challenge_queue.jsonl` (CONCEPTUAL)
- `~/.openclaw/skills/hermes-challenge/skill.yaml` — OpenClaw skill (CONCEPTUAL)

**Design (per Gate 0 Section 9 contract):**
- Challenge types: `research_gap`, `contradiction`, `freshness_decay`, `source_quality`
- Challenge includes: symbols, sectors, themes, trigger reason, source evidence, priority
- Hermes coordinator picks up challenge job (independent schedule, not triggered by Alex)
- Resolution includes findings, new intelligence IDs
- Artifact stored and referenced in action ledger

**No-go scope:**
- Hermes is INDEPENDENT — Alex does not control Hermes schedule
- Alex does not self-promote — challenge results are evidence, not self-praise
- Do NOT integrate Hermes into OpenClaw agent workspace (Hermes is a Trade AI system)

**Acceptance:**
- Alex can create a Hermes challenge job
- Hermes picks up challenge and processes (within Hermes's own schedule)
- Alex can query challenge results
- Results linked to CIO actions in ledger

**Tests:**
- Challenge create: Alex → `hermes_challenge_create` → job appears in queue → Hermes picks up
- Challenge query: Alex → `hermes_challenge_query` → returns findings or pending status
- Independence: Hermes fails → challenge remains pending → Alex handles gracefully (does not block)
- Evidence integration: challenge results → Alex writes CIO action referencing challenge artifact

**Canaries:** G0-HERMES-01 (challenge create), G0-HERMES-02 (challenge resolve), G0-HERMES-03 (Hermes independent failure)
**Rollback:** Challenge bridge is independent; system degrades gracefully

---

#### P-1.10: Gate 0 Provider / Restart Canaries

**Depends on:** P-1.2 through P-1.9 (all infrastructure in place)
**Scope:** Execute Gate 0 canaries from the report. Agent handoff canary, action ledger recovery, notification outbox, host/gateway restart. Only after explicit operator authorization. 29 canaries (corrected per v3.3 Correction 8).

**Canaries to execute (all from Gate 0 report, defined not executed):**
| ID | Name | PR Dependency |
|---|---|---|
| G0-DS-01 | Non-interactive credential resolution | P-1.2 |
| G0-DS-02 | Exact model ID routing | P-1.2 |
| G0-DS-03 | Flash FAST policy works | P-1.2 |
| G0-DS-04 | Cap enforcement | P-1.2 |
| G0-DS-05 | Deduplication | P-1.2 |
| G0-DS-06 | Circuit breaker | P-1.2 |
| G0-DS-07 | Pro escalation path | P-1.2 |
| G0-DS-08 | Financial-agent direct-path denial | P-1.2 |
| G0-CIO-01 | Action ledger write + integrity | P-1.3 |
| G0-CIO-02 | Action ledger read + chain verify | P-1.3 |
| G0-CIO-03 | Action ledger crash recovery | P-1.3 |
| G0-HO-01 | Maria → Alex handoff | P-1.4 |
| G0-HO-02 | Handoff retry | P-1.4 |
| G0-HO-03 | Handoff expiry | P-1.4 |
| G0-HEALTH-01 | Data quality block | P-1.5 |
| G0-HEALTH-02 | Auto-unblock on recovery | P-1.5 |
| G0-WAKE-01 | Scheduled wake | P-1.6 |
| G0-WAKE-02 | Event wake | P-1.6 |
| G0-WAKE-03 | Restart recovery | P-1.6 |
| G0-NOTIFY-01 | Notification delivery | P-1.7 |
| G0-NOTIFY-02 | Retry + dead-letter | P-1.7 |
| G0-NOTIFY-03 | Expiry | P-1.7 |
| G0-SPEC-01 | Guardian critique | P-1.8 |
| G0-SPEC-02 | Ledger tax check | P-1.8 |
| G0-SPEC-03 | Steph retirement | P-1.8 |
| G0-SPEC-04 | Maria→Alex handoff | P-1.8 |
| G0-HERMES-01 | Hermes challenge create | P-1.9 |
| G0-HERMES-02 | Hermes challenge resolve | P-1.9 |
| G0-HERMES-03 | Hermes independent failure | P-1.9 |

**G0-DS-08 updated per v3.3 Correction 8:** Target-state canary — Financial-agent direct-path denial. Proves Alex governed call uses Trade AI credential only, direct OpenClaw DeepSeek not available as fallback, failure returns typed no-fallback state, no ungoverned financial-model consumption recorded.

**Restart canaries (host and gateway):**
- Host restart: all services recover, wake detector re-scans, handoffs not lost, notifications retry
- Gateway restart: sessions persist, governed LLM path works, action ledger readable
- Must execute only with explicit operator authorization

**Acceptance:**
- All 29 canaries pass or documented as explicitly deferrable
- Host restart: all services within P-1.0 through P-1.9 recover
- Gateway restart: all services recover
- No data loss across restarts

**No-go scope:**
- Do NOT execute any canary without explicit operator authorization
- Do NOT modify production configuration during canary execution
- Containment flag (`AGENT_JOBS_P0_CONTAINED`) must remain in its observed state. Do NOT clear or assert inactive as prerequisite. The canonical implementation at `scripts/lib/agent_jobs_containment.py` handles state correctly (fail-closed on uncertainty).

---

### Correction 11: Gate 0 Final Acceptance

**Original Gate 0:** 5 PASS / 8 PARTIAL / 4 FAIL / 3 NOT_PROVEN. Session 2 blocked until all PRs merged.

**Corrected acceptance criteria:** Session 2 may begin only when these score PASS. `workspace_memory` is reclassified — workspace MEMORY.md is NOT a hard financial blocker when Trade AI state can reconstruct CIO context.

| Acceptance Item | Required Score | Verification |
|---|---|---|
| `runtime_version_coherence` | PASS or documented divergence with plan | OpenClaw CLI vs. gateway divergence; Trade AI deployed vs. dev divergence — must be documented with reconciliation plan |
| `deepseek_noninteractive_auth` | PASS | G0-DS-01 canary passed (both Trade AI and governed gateway resolve creds non-interactively) |
| `governed_llm_gateway_integration` | PASS | OpenClaw Alex calls Trade AI governed gateway; direct OpenClaw DeepSeek is non-financial-only exception |
| `heartbeat/wake_architecture` | PASS | Deterministic wake detector operational; no model calls for financial monitoring |
| `session_persistence` | PASS | Already passes (SQLite-backed sessions survive restarts) |
| `financial_action_memory` | PASS | CIO action ledger operational; Alex reconstructs state from Trade AI after new session (restart acceptance test per Correction 9) |
| `durable_agent_handoff` | PASS | Agent Handoff Queue operational; Maria → Alex handoff proven (G0-HO-01); event-sourced |
| `financial_tool_allowlist` | PASS | Already passes (comprehensive allowlist in place); Alex tool manifest is read-only financial tools only; tradeai-watchlist REMOVED |
| `telegram_durable_outbox` | PASS | Notification outbox operational; Telegram failure does not lose CIO action; event-sourced |
| `trade_ai_data_broker_access` | PASS | Already passes (API-backed, read-only, safe) |
| `hermes_bridge` | PASS or explicitly deferrable | If deferrable: must document what is deferred and why; Hermes independent operation verified |
| `cost_feasibility` | PASS | Reclassified to PARTIAL at Gate 0; after P-1.2 gateway unification and 7-14 days of measured canaries, cost must remain within $0.25/day cap. If it does not fit, a documented cap-change proposal with evidence is required before PASS. |
| `audit_tracing` | PASS | Already passes (health_agent JSONL, escalation JSONL, coder dispatch JSONL, file integrity manifest) |
| `minimum_specialist_roster` | PASS | Alex (identity+manifest), Maria (operational), Steph (hardened), Guardian (risk workspace operational, deterministic-first), Ledger (tax specialist created, deterministic-first), Hermes (operational) |
| `platform_health_boundary` | PASS | CIO_DATA_QUALITY_BLOCK operational; Alex cannot remediate infrastructure |
| `containment_canonical` | VERIFIED | Canonical containment uses `AGENT_JOBS_P0_CONTAINED` (env) + `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED` (flag); fail-closed on uncertainty; observed state documented per v3.3 Correction 9 |
| `financial_agent_deepseek_fallback` | DENIED | G0-DS-08 target-state: financial agents have NO direct OpenClaw DeepSeek fallback (per v3.3 Corrections 4, 8) |
| `guardian_deterministic_first` | PASS | Guardian calculations (concentration, VaR, stress, coverage) from deterministic services; LLM critiques only (per v3.3 Correction 11) |
| `ledger_deterministic_first` | PASS | Ledger calculations (tax lots, wash-sale, account constraints) from deterministic services; LLM critiques only (per v3.3 Correction 11) |
| `operator_profile_authority` | ENFORCED | OpenClaw USER.md = non-authoritative preferences only; Trade AI owns financial facts (per v3.3 Correction 10) |
| `operator_ingress_separated` | ENFORCED | Inbound operator path (Telegram/Maria → handoff queue) is separate from outbound notification outbox (per v3.3 Correction 7) |

**Explicitly NOT a hard blocker:**
- `workspace_memory / MEMORY.md` — not a financial readiness blocker when Trade AI state can reconstruct CIO context. MEMORY.md is a quality-of-life improvement for conversational continuity, not a gate condition.

**No Session 2 until P-1.10 acceptance complete.** Session 2 = target CIO architecture design and autonomous enablement.

---

### Correction 12: Required Return — Key-Value Summary

```yaml
CIO_PHASE_MINUS_1_CORRECTED:
  reference: docs/architecture/cio/CIO_PLATFORM_READINESS_REPORT.md
  audit_date: 2026-08-08T04:00:00Z
  correction_date: 2026-08-08T08:59:00-04:00
  v3_3_correction_date: 2026-08-08T09:13:00-04:00
  corrections_applied: 23
  v3_0_corrections: 12
  v3_3_corrections: 11
  corrected_pr_count: 11
  pr_sequence:
    - P-1.0: Architecture Corrections + Canonical Path Discovery
    - P-1.1: Alex Workspace Identity + Read-Only Tool Manifest (tradeai-watchlist REMOVED)
    - P-1.2: Governed OpenClaw → Trade AI LLM Gateway (financial agents: no direct DeepSeek fallback)
    - P-1.3: CIO Action Ledger LAB Service (event-sourced)
    - P-1.4: Durable Handoff Queue (event-sourced)
    - P-1.5: Health Boundary + CIO_DATA_QUALITY_BLOCK
    - P-1.6: Deterministic CIO Wake / Event Detector (operator ingress separated)
    - P-1.7: Telegram Durable Notification Outbox (event-sourced, outbound only)
    - P-1.8: Minimum Specialist Foundation (Guardian + Ledger deterministic-first)
    - P-1.9: Hermes Challenge Bridge
    - P-1.10: Gate 0 Provider / Restart Canaries (29 canaries)
  gate_0_classifications_preserved:
    alex: SKELETON
    maria: OPERATIONAL
    steph: DESIGNED
    guardian: SKELETON (not-production-ready)
    ledger: NONEXISTENT
    hermes: ACTIVE (no bridge)
    openclaw_tradeai_deepseek: SEPARATE (dual-key)
    heartbeat: DISABLED
    telegram: DEGRADED
    cio_action_ledger: NONEXISTENT (durable ledger); legacy cio_decisions EXISTS (pipeline records, not CIO action ledger)
    health_escalation_coder: SEPARATE (must remain outside Alex authority)
  corrected_classifications:
    cost_feasibility: PARTIAL (was: FAIL)
    workspace_memory: PARTIAL/hygiene-gap (was: FAIL/critical-blocker)
  v3_3_corrected_facts:
    legacy_cio_decisions_exists: true
    cio_decision_responses_exists: true
    alex_hygiene_log_exists: true
    durable_cio_action_ledger_exists: false
    tradeai_watchlist_removed_from_readonly_manifest: true
    canonical_paths_discovery_required: true
    canonical_process_ids_discovery_required: true
    direct_openclaw_deepseek_financial_fallback: denied
    jsonl_event_atomicity_corrected: true
    handoff_event_sourcing: true
    notification_event_sourcing: true
    operator_ingress_separated_from_outbox: true
    p1_10_canary_count: 29
    g0_ds_08_target: financial-agent-direct-path-denial
    canonical_containment_env: AGENT_JOBS_P0_CONTAINED
    canonical_containment_flag: ~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED
    canonical_containment_flag_override: AGENT_JOBS_P0_CONTAINMENT_FLAG
    canonical_containment_state_verified: FLAG_NOT_FOUND__ENV_NOT_SET_AT_HOST_LEVEL__PER_PROCESS_OVERRIDE_IN_CRON
    openclaw_user_profile_authority: non_authoritative_preferences_only
    guardian_deterministic_first: true
    ledger_deterministic_first: true
    p_1_0_ready: true
    p_1_1_ready: false
    p_1_2_authorized: false
    session_2_allowed: false
    remaining_blockers:
      - governed_llm_gateway_integration (FAIL: OpenClaw + Trade AI use separate DeepSeek API keys)
      - workspace_memory (gaps: Alex SKELETON, BOOTSTRAP not deleted, IDENTITY empty)
      - minimum_specialist_roster (FAIL: Guardian SKELETON, Ledger NONEXISTENT)
      - durable_agent_handoff (NOT_PROVEN: Maria→Alex handoff never tested)
      - telegram_durable_outbox (NOT_PROVEN: no durable outbox observed)
      - cost_feasibility (PARTIAL: needs governance unification + measured evidence)
      - canonical_path_discovery_incomplete (P-1.0 must discover actual paths)
      - containment_state_needs_verification_with_canonical_identifiers
      - tradeai_watchlist_must_be_removed_from_alex_tool_manifest
      - jsonl_event_sourcing_must_be_implemented
      - handoff_notification_must_be_event_sourced
      - operator_ingress_must_be_separated_from_outbox
      - guardian_ledger_must_be_deterministic_first
      - openclaw_user_profile_must_be_non_authoritative
  removed:
    - P-1.8 "increase cap to $1.50" (in original plan)
    - P-1.3 "Unified DeepSeek Consumption Tracking / track both ledgers" (replaced by governed gateway)
    - P-1.5 "single durable outbox for handoffs + Telegram" (split into P-1.4 + P-1.7)
    - P-1.6 "Alex cron → OpenClaw cron migration" (replaced by deterministic wake detector)
    - P-1.7 "Ledger Agent = audit/integrity" (re-scoped to tax specialist only)
    - tradeai-watchlist from Alex read-only tool manifest (write-through skill)
    - P0_CONTAINED references (replaced with canonical AGENT_JOBS_P0_CONTAINED)
    - G0-DS-08 "OpenClaw independent API key baseline" (replaced with direct-path-denial target-state)
  key_architectural_rules:
    - ONE governed paid-model boundary (Trade AI)
    - NO model calls for financial wake detection
    - CIO action writes by deterministic Python, never raw model-authored files
    - Agent Handoff Queue and Notification Outbox are separate event-sourced domains
    - Operator ingress (inbound) is separate from notification outbox (outbound)
    - Financial jobs → Trade AI; conversational → OpenClaw
    - Ledger = tax specialist only; audit = separate component if needed
    - Financial memory → Trade AI; conversational memory → OpenClaw
    - Alex must reconstruct CIO state from Trade AI after fresh conversation
    - Health/escalation/coder remediation remains outside Alex authority
    - Telegram failure must never lose the CIO action
    - Financial agents must NEVER have direct OpenClaw DeepSeek as fallback
    - Guardian and Ledger calculations → deterministic services; LLMs critique only
    - OpenClaw USER.md → non-authoritative preferences only; Trade AI owns financial facts
    - Event log is authoritative; manifest/projection is derived and rebuildable
    - Containment uses canonical AGENT_JOBS_P0_CONTAINED; fail-closed on uncertainty
    - Legacy cio_decisions exist but are pipeline records, not the CIO action ledger
  session_2_blocked_until: P-1.10 acceptance complete
  summary_block: >
    CIO PHASE -1 CORRECTION GATE v3.3: Do not begin target CIO architecture or autonomous
    enablement until paid-model governance is unified through Trade AI, no financial agent
    has direct OpenClaw DeepSeek fallback, financial wakeups are deterministic and durable,
    action and handoff state are event-sourced by deterministic services, Telegram delivery
    is outboxed and inbound operator requests are separately ingress, platform remediation
    remains outside Alex authority, specialist calculations are deterministic with LLM
    critique only, authoritative financial facts are inside Trade AI not OpenClaw profiles,
    canonical containment is verified, legacy CIO tables are distinguished from the new
    action ledger, and measured usage proves the existing cost policy is sufficient or
    justifies an explicit change.
```

---

## Phase -1 Dependency Graph

```
P-1.0 (Architecture Corrections + Canonical Path Discovery)
 │
 ├─► P-1.1 (Alex Workspace Identity) ──► P-1.2 (Governed LLM Gateway)
 │                                            │
 ├─► P-1.3 (Action Ledger LAB) ◄──────────────┤
 │     │                                      │
 │     ├─► P-1.4 (Handoff Queue) ◄────────────┤
 │     │     │                                │
 │     │     ├─► P-1.6 (CIO Wake/Event) ◄─────┤
 │     │     │                                │
 │     │     ├─► P-1.8 (Specialist Foundation) ◄┤
 │     │     │     │                          │
 │     │     │     └─► P-1.9 (Hermes Bridge) ◄┤
 │     │     │                                │
 │     ├─► P-1.5 (Health Boundary) ◄──────────┤
 │     │                                      │
 │     └─► P-1.7 (Notification Outbox) ◄──────┤
 │                                            │
 └────────────────────────────────────────────┘
                                              │
                                              ▼
                                    P-1.10 (Provider/Restart Canaries — 29 canaries)
                                              │
                                              ▼
                                    SESSION 2 (only after acceptance)
```

---

## No-Go Summary for Phase -1

| Prohibited Action | Reason |
|---|---|
| Raise LLM cap before evidence | All workloads fit under $0.25; unify governance first, measure, then propose |
| Enable HEARTBEAT.md with model triggers | Financial monitoring must use deterministic $0 wake, not periodic LLM calls |
| Track both DeepSeek ledgers | Must unify to ONE governed boundary, not instrument dual keys |
| Let Alex append directly to JSONL | All ledger writes by deterministic Python service with schema + event sourcing |
| Combine handoff queue and notification outbox | Separate event-sourced domains with different schemas, retry policies, and failure modes |
| Conflate operator ingress with notification outbox | Inbound operator path separate from outbound CIO→operator delivery |
| Move Alex financial cron to OpenClaw | Financial jobs stay with Trade AI; only conversational heartbeat in OpenClaw |
| Overload Ledger with audit/integrity scope | Ledger = tax specialist; separate audit component if needed |
| Block Session 2 on MEMORY.md | Trade AI reconstructs CIO state; MEMORY.md is conversational hygiene |
| Create duplicate OpenClaw schedules | No OpenClaw cron for financial cadence |
| Let Alex remediate infrastructure | Health/escalation/coder dispatch remain outside Alex authority |
| Enable autonomous actions before P-1.10 | All 29 canaries must pass before any autonomous enablement |
| Include tradeai-watchlist in Alex's tool manifest | Write-through skill; Alex must be read-only for financial tools |
| Use invented paths instead of discovered canonical paths | P-1.0 must discover actual paths from repository |
| Give financial agents direct OpenClaw DeepSeek fallback | Denied: only non-financial diagnostic agents, no production CIO route |
| Mutate prior JSONL rows for handoff/notification state | Event-sourced transitions only; read projections derive current state |
| Let Guardian or Ledger LLMs invent financial calculations | Deterministic services produce numbers; LLMs critique only |
| Store authoritative financial facts in OpenClaw USER.md | Trade AI owns financial facts; OpenClaw has non-authoritative preferences only |
| Reference containment as P0_CONTAINED | Canonical name is AGENT_JOBS_P0_CONTAINED |
| Confuse legacy cio_decisions table with CIO action ledger | Legacy tables exist (pipeline records); new ledger is separate event store |

---

## v3.3 Required Return — Key-Value Summary Block

```yaml
cio_table_truth_corrected: true
tradeai_watchlist_removed_from_readonly_manifest: true
canonical_paths_discovery_required: true
canonical_process_ids_discovery_required: true
direct_openclaw_deepseek_financial_fallback: denied
jsonl_event_atomicity_corrected: true
handoff_event_sourcing: true
notification_event_sourcing: true
operator_ingress_separated_from_outbox: true
p1_10_canary_count: 29
g0_ds_08_target: financial-agent-direct-path-denial
canonical_containment_env: AGENT_JOBS_P0_CONTAINED
canonical_containment_flag: ~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED
canonical_containment_flag_override: AGENT_JOBS_P0_CONTAINMENT_FLAG
canonical_containment_state_verified: FLAG_NOT_FOUND__ENV_NOT_SET_HOST_LEVEL__PER_PROCESS_OVERRIDE_IN_CRON
openclaw_user_profile_authority: non_authoritative_preferences_only
guardian_deterministic_first: true
ledger_deterministic_first: true
p_1_0_ready: true
p_1_1_ready: false
p_1_2_authorized: false
session_2_allowed: false
remaining_blockers:
  - governed_llm_gateway_integration
  - workspace_memory_gaps
  - minimum_specialist_roster
  - durable_agent_handoff
  - telegram_durable_outbox
  - cost_feasibility_needs_evidence
  - canonical_path_discovery_incomplete
  - containment_state_verified_with_canonical_identifiers
  - tradeai_watchlist_must_be_removed_from_alex_tool_manifest
  - jsonl_event_sourcing_not_implemented
  - handoff_notification_not_event_sourced
  - operator_ingress_not_separated_from_outbox
  - guardian_ledger_not_deterministic_first
  - openclaw_user_profile_not_non_authoritative
```

---

CIO PRE-IMPLEMENTATION GATE: P-1.0 may begin only after the corrected plan distinguishes legacy CIO decisions from the new action ledger, removes write-capable tools from Alex's read-only manifest, uses canonical repository paths and process IDs, event-sources durable state safely, separates inbound operator requests from outbound notifications, denies direct paid-model fallback for financial agents, preserves canonical AGENT_JOBS_P0 containment state, and keeps authoritative financial facts and calculations inside Trade AI.
