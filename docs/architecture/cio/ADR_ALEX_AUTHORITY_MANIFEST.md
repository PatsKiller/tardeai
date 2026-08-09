# ADR: Alex Authority Manifest

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-AUTH-005
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Corrections 2, 4, 10

## Decision

Freeze Alex's initial authority manifest — what Alex is allowed to read and what Alex is denied — before any phase -1 implementation begins. Alex starts as read-only financial advisor. Authority expands only through explicit ADR amendment.

## READ Authority

Alex may READ the following through governed Trade AI APIs:

### Financial APIs (Read-Only)

- **Portfolio API** — current holdings, allocation, sector exposure
- **Performance API** — returns, benchmarks, attribution
- **Risk API** — concentration metrics, exposure, stop coverage
- **Health API** — platform health, data quality, freshness scores
- **Intelligence API** — Hermes research, catalysts, market context
- **Watchlist API** — current watchlist composition and status

### CIO APIs (Read-Only, After Implementation)

- **cio_action_read** — read prior CIO actions from action ledger (P-1.3+)
- **cio_health_check** — read current health boundary state (P-1.5+)
- **handoff_read** — read handoff queue state (P-1.4+)

### Operator Profile (Read-Only, Non-Authoritative)

- **OpenClaw USER.md** — non-authoritative preferences only:
  - Preferred name/addressing style
  - Communication preferences (format, verbosity, channels)
  - Timezone and scheduling preferences
  - Formatting preferences (charts vs tables)
  - Non-authoritative relationship notes (current concerns, upcoming events)

### Tool Allowlist (Allowed)

- `tradeai-readonly` — read: portfolio, health, holdings, risk (API-backed, safe)
- Narrowly scoped read-only health/status APIs
- Later: `cio_action_read` (P-1.3+)
- Later: handoff read/claim tools (P-1.4+)

## DENY Authority

Alex is EXPLICITLY DENIED authority for:

### Mutation Operations

- **tradeai-watchlist** — write-through skill (add, save-knowledge, add-topic commands). This is an API-backed WRITE-THROUGH skill per its SKILL.md. Removed from Alex's manifest per v3.3 Correction 2.
- Star/unstar/list mutations
- Write-through research mutations
- Any write capability that modifies Trade AI state

### Order and Position Changes

- Order submission
- Broker actions (buy, sell, modify, cancel)
- Position changes
- Risk changes
- Portfolio allocation changes
- Stop-loss modifications
- Trailing stop adjustments
- Any limit-price alterations

### Infrastructure and System

- systemctl commands
- crontab modifications
- systemd service management
- Infrastructure remediation (restarting services, modifying configurations)
- Config file mutations
- Database writes (direct DB access is denied)
- Deployment operations
- Secret or credential management

### Authentication and Security

- 2FA operations
- OAuth token manipulation
- API key management
- Session credential handling
- Any security-sensitive operation

### Paid-Model Access

- Direct paid-provider fallback (no direct OpenClaw DeepSeek)
- Bypassing Trade AI LLM gateway governance
- Using any ungoverned model path
- Accessing cost cap configuration

### Remediation Authority

Alex must NOT remediate infrastructure, health issues, or system failures. Per v3.3 Correction 7 and the ownership boundaries ADR:
- Health remediation → Health Agent
- Escalation handling → Escalation Handler
- Code fixes → Coder Dispatch
- These remain outside Alex authority

## Authority Matrix

| Operation | Alex | Maria | Guardian | Ledger | Health Agent |
|---|---|---|---|---|---|
| Read portfolio | READ | READ | READ | READ | READ |
| Read health state | READ | READ | - | - | READ |
| Write CIO action | READ (later) | - | - | - | - |
| Modify portfolio | DENY | DENY | DENY | DENY | DENY |
| Submit orders | DENY | DENY | DENY | DENY | DENY |
| Modify config | DENY | DENY | DENY | DENY | DENY |
| Remediate infra | DENY | DENY | DENY | DENY | REMEDIATE |
| Direct LLM call | DENY* | DENY* | DENY* | DENY* | - |
| Operator comms | VIA GATEWAY | OPERATOR | VIA HANDOFF | VIA HANDOFF | ALERTS |

*Must use governed Trade AI LLM gateway for all paid-model calls.

## Authority Escalation Path

Alex's authority is initially read-only. Any authority expansion requires:

1. P-1.10 canary passage (all 29 canaries)
2. Operator approval documented in ADR amendment
3. Explicit tool allowlist update
4. Governance gateway process registration
5. Budget allocation for new operation type

No autonomous enablement before P-1.10 acceptance is complete.

## No-Gos (Enforcement)

| Prohibited Action | Enforcement |
|---|---|
| tradeai-watchlist in Alex's tool manifest | Manifest audit in P-1.1 |
| Direct OpenClaw DeepSeek fallback | Gateway enforcement (G0-DS-08 canary) |
| Write-through mutations | Tool allowlist validation |
| Infrastructure remediation | Tool allowlist validation |
| Config mutation | Tool allowlist validation |
| Direct DB writes | API-layer enforcement |
| Autonomous actions before P-1.10 | Gate condition |

## Authority Reconstruction

Alex must be able to operate in a fresh OpenClaw conversation (no session context, empty MEMORY.md) by reconstructing authoritative state from Trade AI:

1. Query Trade AI action ledger for prior actions
2. Query Trade AI health API for current platform state
3. Query Hermes for current research context
4. Produce CIO response consistent with prior decisions
5. Write new action to CIO action ledger

OpenClaw conversational memory is a quality-of-life improvement, not a prerequisite for CIO function.

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires operator approval and ADR amendment.*
