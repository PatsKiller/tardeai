# CIO Health Boundary — LAB Service (P-1.5)

Status:      ACTIVE
as_of:       2026-08-08T18:02:23-04:00
Measured at: efcc51365 / not measured

## Overview

The CIO Health Boundary is a **deterministic, domain-scoped advisory gate** that converts canonical Trade AI health and data-quality evidence into typed advisory availability states. It is a **read-only boundary** — it consumes health snapshots, produces decisions, and records durable CIO_DATA_QUALITY_BLOCK lifecycle events without performing remediation.

## Ownership Boundaries

| Component | Owner | Boundary Module Interacts With |
|---|---|---|
| Health Agent (`scripts/health_agent.py`) | Health Agent | Reads snapshot output only |
| Health Policy (`config/health_agent_policy.json`) | Health Agent | Reference only (read) |
| Escalation Handler (`scripts/claude_escalation_handler.py`) | Defense Desk | **NEVER called** |
| Coder Dispatch (`scripts/coder_dispatch.py`) | Defense Desk | **NEVER called** |
| CIO Action Ledger (`scripts/lib/cio_action_ledger.py`) | P-1.3 | Records block/unblock events |
| Agent Handoff Queue (`scripts/lib/cio_agent_handoff_queue.py`) | P-1.4 | Attaches health metadata |
| CIO Health Boundary (`scripts/lib/cio_health_boundary.py`) | **P-1.5 (this service)** | This module |

## Input Contract

The boundary consumes a `HealthSnapshot` dataclass instance containing:

```
health_snapshot_id: str        # Unique snapshot identifier
observed_at: str               # ISO-8601 timestamp
overall_score: float           # 0-100 aggregate score
overall_status: str            # healthy/degraded/critical/...
category_scores: dict          # {category_name: float 0-100}
findings: list[dict]           # Individual finding records with severity, category, status
data_freshness: dict           # {domain: {last_update, status}}
source_status: dict            # {source_name: status_string}
```

## Domain Scoping Policy Matrix

The boundary maps health categories to CIO domains with severity thresholds:

| Health Category | Affected CIO Domains | Block ≥ Severity | Degrade ≥ Severity |
|---|---|---|---|
| market_data | portfolio, holdings, performance, risk, watch, reentry, rotation, fundamentals, technicals | 4 | 2 |
| broker | portfolio, holdings, risk, broker_reconciliation | 3 | 1 |
| database | portfolio, holdings, performance, risk, watch, reentry, rotation, income, tax, retirement, fundamentals, technicals, catalysts, macro | 4 | 2 |
| backup | (none — advisory only) | 5 | 3 |
| agent_jobs | watch, reentry, rotation, catalysts | 4 | 2 |
| indicators | technicals, fundamentals | 4 | 2 |
| shadow_batch | performance, risk | 4 | 2 |
| llm | watch, catalysts, fundamentals | 4 | 3 |
| api | portfolio, holdings, performance, risk, broker_reconciliation | 4 | 2 |
| file_integrity | portfolio, holdings, performance, risk | 3 | 1 |
| watchlist | watch | 4 | 2 |

## Advisory State Model

| State | Meaning | Action |
|---|---|---|
| READY | All required domains healthy | Proceed with advisory |
| DEGRADED | Some domains have non-critical issues | Proceed with caution |
| BLOCKED | Critical domains unavailable | CIO_DATA_QUALITY_BLOCK created, advisory halted |
| UNKNOWN | No health evidence available | Fail closed, advisory halted |

**Rule**: Advisory is blocked for a domain only if severity ≥ block threshold on a finding in a category that maps to that domain. Overall score alone is insufficient — domain-level scoping is required.

## Reason Codes

The boundary emits typed reason codes including (non-exhaustive):

- `MARKET_DATA_DATA_UNAVAILABLE`, `BROKER_DATA_UNAVAILABLE`, `DATABASE_DATA_UNAVAILABLE` — severity ≥ 4 findings
- `MARKET_DATA_DEGRADED`, `BROKER_DEGRADED` — severity 2-3 findings
- `DATA_SOURCE_UNAVAILABLE` — data freshness status is "unavailable"
- `DATA_STALE` — data freshness status is "stale" or exceeds configured max age
- `HEALTH_EVIDENCE_UNAVAILABLE` — no health snapshot loaded
- `HEALTH_POLICY_UNKNOWN` — fallback when no other reason matches

## CIO_DATA_QUALITY_BLOCK Lifecycle

### Creation (create_data_quality_block)
1. Evaluate health snapshot → BLOCKED decision
2. Create action in CIO Action Ledger (status: OPEN)
3. Transition action to BLOCKED via CIO_ACTION_BLOCKED
4. Action ID: `data-quality-block-{idempotency_key[:8]}`
5. Idempotent: duplicate calls with same decision return None

### Auto-Unblock (unblock_if_healthy)
1. Evaluate health snapshot → READY or DEGRADED
2. If action exists and is BLOCKED, transition via CIO_ACTION_UNBLOCKED
3. Action status returns to OPEN
4. Block history preserved in event stream

### Block History
- All events are append-only in the CIO Action Ledger
- Block → Unblock sequence preserves full history
- `CIO_ACTION_CREATED` + `CIO_ACTION_BLOCKED` + `CIO_ACTION_UNBLOCKED` events are all retained

## Handoff Integration

- `attach_health_metadata_to_handoff(handoff_id, decision, queue)`: Attaches advisory decision metadata to a handoff without changing its status
- `is_handoff_eligible(handoff, boundary, required_domains)`: Returns (eligible: bool, decision) — blocks handoff claim/start if health is BLOCKED

## Idempotency

Both block creation and unblock operations are idempotent:
- Block creation uses a SHA-256 hash of (policy_version, blocked_domains, reason_codes, snapshot_id) as the idempotency key
- Duplicate block calls return None (no duplicate events)
- Unblock only operates on actions currently in BLOCKED status

## Determinism

- Same health snapshot + same domains → same decision every time
- Decision hash (SHA-256) is deterministic over sorted inputs
- No external state, no randomness, no provider calls

## No-Remediation Authority

The CIO Health Boundary module:
- **NEVER** imports or calls claude_escalation_handler
- **NEVER** imports or calls coder_dispatch
- **NEVER** executes shell commands or subprocess
- **NEVER** restarts services or modifies system state
- **NEVER** calls any LLM/provider (openai, anthropic, deepseek)
- **NEVER** sends Telegram messages
- **NEVER** modifies scheduler, heartbeat, or cost-cap configuration

## Test Coverage

### G0-HEALTH-01: Data quality zero, required source unavailable
- All data sources down (scores 0)
- Expected: BLOCKED, typed reason codes, CIO_DATA_QUALITY_BLOCK created
- Verified: no provider call, no remediation, no Telegram

### G0-HEALTH-02: Block → healthy snapshot → UNBLOCK
- Phase 1: Block action created and transitioned to BLOCKED
- Phase 2: Health restored → action unblocked (status: OPEN)
- Verified: block history preserved (CREATE + BLOCK + UNBLOCK events intact), no provider call

### Additional Tests (26 total)
- Schema validation (healthy/blocked/degraded snapshots)
- State transitions (READY/DEGRADED/BLOCKED/UNKNOWN)
- Domain scoping (blocked domains don't leak to unrelated domains)
- Determinism (same input → same output)
- Idempotency (duplicate block → None)
- Fail-closed (no snapshot → UNKNOWN)
- No remediation (structural check)
- Zero provider (structural check)
- Invalid domain → ValueError
- Recheck time computation
- Handoff eligibility

## Later Activation Steps

P-1.5 is currently a **LAB service** (not production-activated). To activate:

1. Wire the boundary into the CIO advisory pipeline (e.g., before processing CIO questions)
2. Configure health snapshot consumption from the Health Agent's output
3. Integrate `is_handoff_eligible` into the handoff claim/start flow
4. Set `PRODUCTION_HEALTH_BOUNDARY_ENABLED=true`
5. Do **NOT** enable Alex live advisory blocking until P-1.6+ readiness review

## Rollback

To rollback P-1.5:
1. Set `PRODUCTION_HEALTH_BOUNDARY_ENABLED=false`
2. Preserve event files (blocks remain in ledger as historical records)
3. Disable boundary reads in the advisory pipeline
4. No data loss — the boundary is read-only and append-only

## File Listing

| File | Purpose |
|---|---|
| `scripts/lib/cio_health_boundary.py` | Core boundary module |
| `tests/test_cio_health_boundary.py` | Test suite (26 tests) |
| `docs/architecture/cio/CIO_HEALTH_BOUNDARY_LAB.md` | This document |

## Dependencies

- P-1.3: `scripts/lib/cio_action_ledger.py` (CIOActionLedger for block/unblock events)
- P-1.4: `scripts/lib/cio_agent_handoff_queue.py` (AgentHandoffQueue for metadata attachment)
- Health Agent: `scripts/health_agent.py` (consumes snapshot output)
- Health Policy: `config/health_agent_policy.json` (reference only)
