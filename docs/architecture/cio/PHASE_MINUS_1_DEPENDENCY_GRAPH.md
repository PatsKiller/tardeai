# CIO Phase -1 Dependency Graph

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**Document ID:** CIO-P-1.0-DEPS
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Correction 10

## 11-PR Sequence with Dependencies, No-Go Scope, and Acceptance Criteria

### Dependency Graph (Visual)

```
P-1.0 (Architecture Freeze + Canonical Path Discovery)
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

### PR Details

---

#### P-1.0: Phase -1 Architecture Freeze

**Depends on:** Nothing (first PR — this document)
**Scope:** Documentation and ADR only. Freeze ownership boundaries, discover canonical paths. No code, no config, no system changes.
**No-go:** No code, no config, no system changes, no enablement, no provider calls, no containment state change.

**Acceptance:**
- 9 ADRs written covering: ownership, LLM boundary, CIO state, event sourcing, Alex authority, scheduler, containment, specialist policy, dependency graph
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
**Scope:** Alex OpenClaw workspace files only. No heartbeat activation, no provider call.

**Files:** `workspace-alex/SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `AGENTS.md`; delete `BOOTSTRAP.md`

**No-go:** No HEARTBEAT.md activation, no provider/API calls, no MEMORY.md with financial authority, no write tools, no `tradeai-watchlist` in tool manifest.

**Acceptance:** BOOTSTRAP.md deleted; SOUL.md/IDENTITY.md not template defaults; tool allowlist is read-only; `tradeai-watchlist` NOT in allowlist; USER.md non-authoritative only; no heartbeat running.

**Tests:** Workspace file audit, tool manifest allowlist validation, gateway log check (zero Alex provider calls after merge)
**Canaries:** None (no runtime changes)
**Rollback:** Revert workspace files from backup

---

#### P-1.2: Governed OpenClaw → Trade AI LLM Gateway

**Depends on:** P-1.1 (Alex identity and tool manifest ready)
**Scope:** Trade AI LLM gateway extension + OpenClaw tool integration. LAB only.

**No-go:** Do NOT remove OpenClaw DeepSeek plugin yet; do NOT change Trade AI's existing LLM routing; do NOT track two ledgers; do NOT allow financial agents direct OpenClaw DeepSeek fallback.

**Acceptance:** Alex can issue governed LLM call through Trade AI gateway; process registry validates; daily cap, dedupe, circuit breaker apply; failed calls fail-closed; consumption appears in Trade AI ledger.

**Tests:** Happy path, authorization denial, cap enforcement, deduplication, circuit breaker, fallback denial, direct-path denial canary (G0-DS-08)
**Canaries:** G0-DS-01 through G0-DS-08 (8 canaries)
**Rollback:** Remove `tradeai-llm` skill from OpenClaw; gateway endpoint is non-blocking

---

#### P-1.3: CIO Action Ledger LAB Service

**Depends on:** P-1.0 (boundaries frozen, legacy CIO tables documented)
**Scope:** Deterministic Python service for CIO action ledger. Event-sourced architecture. Alex calls tools, never writes files directly.

**No-go:** No Alex direct JSONL writes; no PostgreSQL yet (LAB = JSONL); do NOT conflate with legacy `cio_decisions` table.

**Acceptance:** 11 required properties verified; Alex can create/read actions via tools; crash-recovery passes; no direct file writes observed; legacy tables documented as separate.

**Tests:** Schema validation, authority check, lock, atomic append; integrity (hash verify → corrupt byte → detection); recovery (write 10 → kill → restart → all 10 readable); crash (SIGKILL mid-write → no partial event); disk-full; concurrent writer; integration (Alex → create → event in ledger → read returns it)
**Canaries:** G0-CIO-01, G0-CIO-02, G0-CIO-03 (3 canaries)
**Rollback:** Stop service; JSONL is append-only, safe to leave

---

#### P-1.4: Durable Handoff Queue

**Depends on:** P-1.2 (LLM gateway), P-1.3 (action ledger)
**Scope:** Agent Handoff Queue for Alex ↔ specialists. Event-sourced. Separate from Telegram notifications.

**No-go:** Do NOT combine with notification outbox; do NOT implement Hermes bridge yet; do NOT mutate prior JSONL rows.

**Acceptance:** Maria can enqueue CIO question; Alex can poll/claim/complete; retry with backoff; expired/deadline enforcement; budget enforcement; separate from notification outbox; operator inbound flows through queue.

**Tests:** Happy path (Maria → enqueue → Alex → claim → complete); retry (2 fails → retry → success on 3rd); expiry; budget exceeded; separation from Telegram; event sourcing replay; idempotency
**Canaries:** G0-HO-01, G0-HO-02, G0-HO-03 (3 canaries)
**Rollback:** Stop handoff service; queue file is append-only

---

#### P-1.5: Health Boundary + CIO_DATA_QUALITY_BLOCK

**Depends on:** P-1.2 (governed LLM), P-1.3 (action ledger for block events)
**Scope:** Alex cannot remediate infrastructure. Health state can block or degrade CIO advice.

**No-go:** Alex MUST NOT call health remediation scripts, modify health agent config, or trigger escalation handler.

**Acceptance:** data_quality=0 blocks Alex from financial advice; Alex writes block event to action ledger; Alex responds with correct block message; block clears on recovery; Alex cannot trigger remediation.

**Tests:** Block active → Alex receives block → writes event → responds correctly; block transition → recovery → unblock event; no remediation attempt accepted; handoff queue includes health context when blocked
**Canaries:** G0-HEALTH-01, G0-HEALTH-02 (2 canaries)
**Rollback:** Health boundary check is advisory; Alex degrades gracefully

---

#### P-1.6: Deterministic CIO Wake / Event Detector

**Depends on:** P-1.2 (LLM gateway), P-1.4 (Agent Handoff Queue)
**Scope:** Trade AI deterministic event detector creates durable CIO jobs. No model calls for wake detection. No OpenClaw financial cron duplication.

**No-go:** No OpenClaw cron for financial cadence; no legacy cron deletion yet; no model calls during wake detection; do NOT conflate inbound operator path with outbound outbox.

**Acceptance:** Scheduled jobs trigger without model calls; wake jobs deduplicated; wake jobs survive restart; no OpenClaw cron for financial schedules; legacy cron inventory documented; operator inbound separated from outbox.

**Tests:** Deterministic trigger → wake job → Alex polls; deduplication; restart recovery; zero LLM cost; operator ingress separate from outbox
**Canaries:** G0-WAKE-01, G0-WAKE-02, G0-WAKE-03 (3 canaries)
**Rollback:** Wake detector is new service; legacy cron continues until retirement approved

---

#### P-1.7: Telegram Durable Notification Outbox

**Depends on:** P-1.3 (action ledger — notifications reference actions)
**Scope:** Durable notification outbox for OUTBOUND CIO→operator delivery. Event-sourced. Separate from Agent Handoff Queue.

**No-go:** Do NOT combine with Agent Handoff Queue; do NOT retry indefinitely; do NOT block CIO action creation on notification delivery; do NOT use for operator inbound.

**Acceptance:** CIO action → NOTIFICATION_ENQUEUED → delivered → DELIVERY_CONFIRMED; failed delivery → retry → dead-letter on 3rd; expired → NOTIFICATION_EXPIRED; deduplication; CIO action survives all delivery failures; event stream replay correct.

**Tests:** Happy path; retry (2 fails → retry → success); dead-letter; expiry; deduplication; separation from handoff queue; scale (500 notifications → replay → correct projection)
**Canaries:** G0-NOTIFY-01, G0-NOTIFY-02, G0-NOTIFY-03 (3 canaries)
**Rollback:** Outbox is independent; existing Telegram continues

---

#### P-1.8: Minimum Specialist Foundation

**Depends on:** P-1.2 (LLM gateway), P-1.4 (Agent Handoff Queue)
**Scope:** Harden Guardian (deterministic-first), create Ledger (deterministic-first), harden Steph, integrate Maria. Maturity catalog.

**No-go:** No broad specialist schedules; no Ledger audit/integrity scope; no autonomous Guardian risk actions; no LLM numeric calculations.

**Acceptance:** Guardian workspace operational with deterministic risk service; Ledger workspace created with tax scope only; Steph hardened; Maria integrated with handoff queue; maturity catalog published; all specialists use governed gateway.

**Tests:** Guardian deterministic → LLM critique → handoff; Ledger deterministic → LLM critique → handoff; deterministic-only mode (LLM disabled → metrics still computed); Steph portfolio + tax → retirement recommendation; Maria → classify → enqueue; gateway governance for all specialists
**Canaries:** G0-SPEC-01, G0-SPEC-02, G0-SPEC-03, G0-SPEC-04 (4 canaries)
**Rollback:** Specialists are advisory; system degrades gracefully

---

#### P-1.9: Hermes Challenge Bridge

**Depends on:** P-1.4 (Agent Handoff Queue), P-1.3 (action ledger)
**Scope:** Durable challenge jobs and artifacts. Hermes remains independent.

**No-go:** Hermes is INDEPENDENT; Alex does not control Hermes schedule; Alex does not self-promote; do NOT integrate Hermes into OpenClaw workspace.

**Acceptance:** Alex can create challenge; Hermes picks up independently; Alex can query results; results linked to CIO actions.

**Tests:** Challenge create → job appears → Hermes picks up; challenge query → findings or pending; Hermes failure → challenge pending → Alex handles gracefully; evidence integration → action references challenge artifact
**Canaries:** G0-HERMES-01, G0-HERMES-02, G0-HERMES-03 (3 canaries)
**Rollback:** Challenge bridge is independent; system degrades gracefully

---

#### P-1.10: Gate 0 Provider / Restart Canaries

**Depends on:** P-1.2 through P-1.9 (all infrastructure in place)
**Scope:** Execute 29 Gate 0 canaries. Only after explicit operator authorization.

**Canary Groups:**
- G0-DS-01 through G0-DS-08: DeepSeek governance (8)
- G0-CIO-01 through G0-CIO-03: CIO Action Ledger (3)
- G0-HO-01 through G0-HO-03: Handoff Queue (3)
- G0-HEALTH-01 through G0-HEALTH-02: Health Boundary (2)
- G0-WAKE-01 through G0-WAKE-03: CIO Wake (3)
- G0-NOTIFY-01 through G0-NOTIFY-03: Notification Outbox (3)
- G0-SPEC-01 through G0-SPEC-04: Specialists (4)
- G0-HERMES-01 through G0-HERMES-03: Hermes Bridge (3)
- **Total: 29 canaries** (corrected from 28 — v3.3 Correction 8)

**Acceptance:** All 29 canaries pass or documented as explicitly deferrable; host restart: all services recover; gateway restart: all services recover; no data loss.

**No-go:** No canary execution without explicit operator authorization; no production config modification; containment flag must remain in observed state.

---

## Session 2 Gate

Session 2 (target CIO architecture design and autonomous enablement) is BLOCKED until:

```
P-1.10 acceptance complete AND all P-1.10 canaries pass
```

### Explicitly NOT a hard blocker:
- `workspace_memory / MEMORY.md` — not a financial readiness blocker when Trade AI state can reconstruct CIO context

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Dependencies, no-go scope, and acceptance criteria are immutable until P-1.10 passes and Session 2 begins.*
