# ADR: CIO State Architecture

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-STATE-003
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Correction 1

## Decision

Freeze the state of CIO database tables and the relationship between legacy pipeline records and the new durable CIO action ledger.

## CIO Table Truth

Researched on 2026-08-08 from codebase evidence:

```yaml
legacy_cio_decisions_exists: true
legacy_cio_decision_responses_exists: true
alex_hygiene_log_exists: true
durable_cio_action_ledger_exists: false
```

### Evidence for Legacy Tables

#### `cio_decisions` — Pipeline Decision Records

**Evidence:** 100+ references in `scripts/api_v2.py` (SELECT, INSERT, aggregation queries), referenced in `health_agent.py` freshness checks, `system_freshness_monitor.py`, `cio_decision_engine.py` cron entry at 7 AM weekdays, Command Center visualization, multiple worktree syncs.

**Nature:** Pipeline decision recording — daily rule-engine output from the existing `cio_decision_engine.py`. Records what the deterministic pipeline decided each day. NOT the same as Alex's autonomous CIO action records.

**Status:** EXISTS, ACTIVE, PIPELINE RECORD — not the durable CIO action ledger.

#### `cio_decision_responses` — Feedback Loop

**Evidence:** SQL migration at `sql/migrations/20260511_feedback_loop_closure.sql` (CREATE TABLE with symbol index), API query in `api_v2.py`, documented in `MASTER_SYSTEM_DOCUMENTATION.md`.

**Nature:** Feedback loop closure — records operator responses and feedback on CIO decisions. Part of the existing pipeline feedback mechanism.

**Status:** EXISTS, ACTIVE, FEEDBACK LOOP — not the durable CIO action ledger.

#### `alex_hygiene_log` — Hygiene Run Audit

**Evidence:** SQL in `alex_hygiene.py` (INSERT/SELECT), API endpoint at `/api/v2/alex-hygiene/history`, documented in `LIFECYCLE_SCHEMA_AUDIT.md`.

**Nature:** Audit log for Alex hygiene runs — records when hygiene jobs ran and their outcomes. NOT Alex's autonomous CIO action records.

**Status:** EXISTS, ACTIVE, HYGIENE AUDIT — not the durable CIO action ledger.

### Durable CIO Action Ledger — NOT YET EXISTS

The new CIO action ledger (to be built in P-1.3) is a separate append-only event-sourced store. It records Alex's autonomous CIO actions with event-sourcing integrity. It is NOT the legacy `cio_decisions` table.

## Relationship Between Legacy Tables and New Action Ledger

### Clear Separation

| Aspect | Legacy `cio_decisions` | New CIO Action Ledger |
|---|---|---|
| **Writer** | Pipeline rule engine (`cio_decision_engine.py`) | Alex via deterministic `cio_action_service.py` |
| **Storage** | PostgreSQL table | Append-only event-sourced JSONL (`data/cio/cio_action_ledger.jsonl`) |
| **Format** | SQL rows (mutable) | Event-sourced events (immutable, chained hashes) |
| **Content** | Daily pipeline output | Alex's autonomous CIO actions, handoffs, notifications |
| **Authority** | Pipeline decision record | CIO action of record |
| **Query** | SQL SELECT | Event stream replay + read projection |

### Permitted Reference (Explicit)

The new CIO action ledger may REFERENCE legacy `cio_decisions` records as context/evidence for Alex's actions, but must NOT:
- Treat `cio_decisions` as the action ledger itself
- Write CIO actions INTO the `cio_decisions` table
- Mutate existing `cio_decisions` rows
- Depend on `cio_decisions` schema for its own event schema

### Permitted Reference Pattern

```yaml
# In CIO action ledger event:
cio_action_event:
  event_type: CIO_ADVISORY_PRODUCED
  payload:
    advisory: "..."
    contextual_decision_refs:
      - legacy_cio_decision_id: 12345  # READ-ONLY REFERENCE
        decision_date: "2026-08-07"
```

## Data State Root

**Canonical path:** `data/` (verified: exists, extensive subdirectory structure)

Existing data directories and their CIO relevance:
- `data/runtime/` — runtime state, file integrity manifests
- `data/state/` — application state
- `data/health/` — health agent data
- `data/hermes/` — Hermes research data
- `data/logs/` — existing JSONL audit logs (`health_agent.jsonl`, `claude_escalation_retry_cmd.jsonl`, `coder_dispatch.jsonl`, `llm_routing_audit.jsonl`, `safe_flock_events.jsonl`)
- `data/state_guard_audit.jsonl` — state guard audit trail (existing event-sourced pattern)

**Target CIO state paths (for P-1.3+):**
- `data/cio/cio_action_ledger.jsonl` — CIO action ledger (event-sourced)
- `data/cio/agent_handoff_queue.jsonl` — Agent Handoff Queue (event-sourced)
- `data/cio/notification_outbox.jsonl` — Notification Outbox (event-sourced)
- `data/cio/hermes_challenge_queue.jsonl` — Hermes Challenge Queue (event-sourced)

## Existing JSONL Patterns in Codebase

The codebase already uses append-only JSONL for multiple audit trails:
- `logs/health_agent.jsonl`
- `logs/claude_escalation_retry_cmd.jsonl`
- `logs/coder_dispatch.jsonl`
- `logs/llm_routing_audit.jsonl`
- `logs/safe_flock_events.jsonl`
- `data/state_guard_audit.jsonl`

The CIO action ledger follows the same append-only JSONL pattern but adds event-sourcing primitives (chained hashes, stream IDs, event types, read projections).

## PostgreSQL State

The Trade AI PostgreSQL database contains the legacy CIO tables. The database connection is configured through existing infrastructure. The new CIO action ledger is LAB-phase JSONL and will migrate to PostgreSQL in a future SHADOW phase.

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires ADR amendment.*
