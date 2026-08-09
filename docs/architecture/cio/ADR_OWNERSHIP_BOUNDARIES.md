# ADR: Platform Ownership Boundaries

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-OWNERSHIP-001
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3 (23 corrections)

## Decision

Freeze platform ownership boundaries across five domains. No domain shall cross boundaries without explicit ADR amendment.

## Ownership Domains

### 1. OpenClaw Platform

**Location:** `~/.openclaw/`
**Canonical skill root:** `~/.openclaw/skills/`
**Canonical workspaces:** `~/.openclaw/workspace-alex/`, `~/.openclaw/workspace-maria/`, `~/.openclaw/workspace-steph/`, `~/.openclaw/workspace-risk_agent/`

**Owns:**
- Autonomous agent identity (SOUL.md, IDENTITY.md, AGENTS.md)
- Conversational relationship with the operator (session continuity, addressing style, presentation)
- Operator interaction surface (Telegram ingress via Maria, conversational orchestration)
- Non-authoritative conversational memory (MEMORY.md, session context, preferences)
- OpenClaw-native scheduling concerns (conversational heartbeat, session housekeeping)

**Does NOT own:**
- Canonical financial truth (owned by Trade AI)
- Durable CIO jobs or financial cadence scheduling
- Paid-model governance or authorization
- Financial action memory or ledger
- Infrastructure remediation authority

**Boundary rule:** OpenClaw USER/MEMORY may contain non-authoritative preferences only (name, formatting, timezone, communication preferences). Financial facts (IPS, goals, accounts, tax, risk, cash needs, portfolio models, action history) belong to Trade AI.

---

### 2. Trade AI Platform

**Location:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`
**Canonical module root:** `scripts/` (no dedicated `src/` or `cio/` module; code lives in `scripts/` root)
**Canonical data root:** `data/` (extensive runtime state, jsonl audit logs, state, portfolios, runtime)

**Owns:**
- Canonical financial truth (portfolio, holdings, performance, risk, health, intelligence)
- Data Broker (read-only financial APIs, HTTP API access to financial state)
- Durable CIO jobs and financial cadence scheduling
- Financial action memory (CIO action ledger, event-sourced, append-only)
- Model governance boundary (single governed paid-model gateway)
- Authorization, reservation, and settlement (pre-flight, post-flight cost governance)
- Scheduler ownership for financial jobs (deterministic event detection, durable wake jobs)
- Deterministic financial calculations (risk metrics, tax calculations, concentration analysis)
- Health boundary enforcement (CIO_DATA_QUALITY_BLOCK)
- Agent Handoff Queue (Alex ↔ specialists, event-sourced, separate from notifications)
- Notification Outbox (outbound CIO → operator delivery, event-sourced)

**Does NOT own:**
- Agent identity or conversational persona
- Operator interaction surface
- Hermes research autonomy
- Infrastructure remediation (owned by Health/Escalation/Coder)

---

### 3. Hermes Platform

**Location:** Hermes DB (16K+ rows, actively fresh)
**Relevant modules:** `scripts/hermes_autonomous_loop.py`, `scripts/lib/hermes_discovery/`, `scripts/hermes_discovery.py`

**Owns:**
- Autonomous independent research challenger
- Research memory (intelligence, catalyst classification, market context)
- Research scheduling (independent of Alex/CIO cadence)
- Hermes coordinator (picks up challenge jobs on independent schedule)
- Hermes DB (16K+ rows, canonical research state)

**Does NOT own:**
- Alex's CIO decision-making
- Financial truth (Trade AI is canonical)
- Triggering by Alex (challenge bridge is a two-way handoff, not Alex commanding Hermes)
- Self-promotion (challenge results are evidence, not self-praise)

**Boundary rule:** Hermes is an independent challenger, not Alex's research assistant. Alex may create Hermes challenge jobs, but Hermes processes them on its own schedule. Alex does not control Hermes scheduling or research priorities.

---

### 4. Health / Escalation / Coder Dispatch

**Location:**
- Health: `scripts/health_agent.py`
- Escalation: `scripts/claude_escalation_handler.py`
- Coder: `scripts/coder_dispatch.py`

**Owns:**
- Operational monitoring and health detection
- Infrastructure remediation and recovery
- Escalation handling and error classification
- Coder dispatch for automated fixes
- Health/operational audit trails (JSONL logs)

**Does NOT own:**
- Financial decision-making
- CIO advisory authority
- Portfolio management

**Critical boundary:** Alex must NOT have remediation authority. Health/Escalation/Coder remain outside Alex's tool allowlist. Alex may READ health state (to decide whether to block financial advice), but must NOT remediate, fix, restart services, or modify infrastructure configuration.

---

### 5. Specialist Agents (Guardian, Ledger)

**Location:** `~/.openclaw/workspace-risk_agent/`, `~/.openclaw/workspace-ledger/` (to be created)
**Deterministic services:** Trade AI (Python/SQL calculations)

**Owns:**
- Financial critique and explanation (interpretation of deterministic evidence)
- Advisory recommendations within their domain
- Handoff-based interaction with Alex via Agent Handoff Queue

**Does NOT own:**
- Numeric financial calculation production (Guardian: VaR, concentration, stress tests; Ledger: tax lots, wash-sale detection, estimated tax)
- Autonomous execution or portfolio modification
- Direct paid-model access (must route through governed Trade AI gateway)

**Boundary rule:** Guardian and Ledger are deterministic-first. Their LLM role is critique and explanation — numeric calculations come from Trade AI's deterministic service layer.

---

## Ownership Matrix

| Concern | Owner | Shared With | Notes |
|---|---|---|---|
| Financial truth | Trade AI | None | Canonical, authoritative, survives all restarts |
| CIO action ledger | Trade AI | Alex (read via API) | Event-sourced, append-only, deterministic write service |
| Agent identity | OpenClaw | None | SOUL.md, IDENTITY.md |
| Conversational memory | OpenClaw | None | Non-authoritative preferences only |
| Financial scheduling | Trade AI | None | Deterministic wake, durable jobs |
| Conversation heartbeat | OpenClaw | None | Session housekeeping, no paid model calls |
| Paid-model governance | Trade AI | None | Single governed gateway boundary |
| Research autonomy | Hermes | None | Independent schedule, independent priorities |
| Infrastructure remediation | Health/Escalation/Coder | None | Alex must not remediate |
| Operator notification delivery | Trade AI (outbox) | OpenClaw/Telegram (delivery) | Outbox writes = Trade AI; delivery = OpenClaw/Telegram |
| Operator ingress | OpenClaw/Telegram/Maria | Trade AI (handoff queue) | Inbound path separate from outbound outbox |
| Deterministic financial calculations | Trade AI | Guardian/Ledger (critique) | LLMs critique only, never invent numbers |

## Immutable Rules

1. **Trade AI is the canonical financial truth.** OpenClaw is the conversational surface.
2. **One governed paid-model boundary** — Trade AI LLM gateway. No direct OpenClaw DeepSeek for financial agents.
3. **Financial jobs → Trade AI scheduler.** Conversational heartbeat → OpenClaw.
4. **Alex reconstructs CIO state from Trade AI on every material run.** OpenClaw MEMORY.md is conversational hygiene, not authoritative.
5. **Health/Escalation/Coder remediation remains outside Alex authority.**
6. **Hermes is an independent challenger, not Alex's subordinate.**
7. **Guardian and Ledger are deterministic-first.** LLMs critique; Trade AI computes.
8. **Operator inbound path (Telegram/Maria → handoff queue) is separate from outbound notification outbox.**

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires ADR amendment with operator approval.*
