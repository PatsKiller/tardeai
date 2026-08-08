# ADR: Containment Specification

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-CONTAIN-007
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Correction 9

## Decision

Freeze the canonical containment specification with verified identifiers and fail-closed behavior. Containment state observed during P-1.0 is documented. MUST NOT alter containment state.

## Canonical Containment Identifiers

**Verified from `scripts/lib/agent_jobs_containment.py`:**

| Identifier | Canonical Value | Previous (Incorrect) |
|---|---|---|
| Environment variable | `AGENT_JOBS_P0_CONTAINED` | `P0_CONTAINED` (wrong) |
| Flag file | `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED` | `~/.config/` (wrong) |
| Flag override env | `AGENT_JOBS_P0_CONTAINMENT_FLAG` | (not previously documented) |

## Containment Module

**Canonical path:** `scripts/lib/agent_jobs_containment.py`

Key function: `guard_agent_jobs_execution(caller_script, source)` — called before any agent job execution. Returns dict with `blocked` key:
- `blocked: true` → agent job must not execute
- `blocked: false` → agent job may proceed

Callers:
- `scripts/lib/agent_flash_governance.py` — `governed_flash_call()` checks containment before any LLM call
- `scripts/health_agent.py` — `guard_remediation_command()`
- `scripts/claude_escalation_handler.py` — `guard_agent_jobs_execution()`
- `scripts/process_watchlist_agent_jobs.py` — `exit_if_contained_worker_entry()` with exit code 78

## Fail-Closed Behavior

On any uncertainty, the containment module blocks execution:

| Scenario | Behavior |
|---|---|
| Flag file exists and content is "1", "true", "/true/", "active" | Block |
| Flag file exists with empty or whitespace-only content | Block (fail-closed: empty means indeterminate) |
| Flag file does not exist | Allow (containment inactive) |
| Env `AGENT_JOBS_P0_CONTAINED` = "1", "true", "active" | Block |
| Env `AGENT_JOBS_P0_CONTAINED` = "0", "false", "inactive" | Allow (explicit inactive) |
| Env unset | Allow (default: not contained) |
| Any I/O error reading flag file | Block (fail-closed on uncertainty) |
| Malformed flag file content | Block (fail-closed on uncertainty) |
| Unknown env value (not in recognized set) | Block (fail-closed on uncertainty) |

## Observed Containment State (P-1.0 Run — 2026-08-08 09:25 UTC-4)

| Check | Result |
|---|---|
| `AGENT_JOBS_P0_CONTAINED` env variable | NOT SET (host level) |
| Flag file `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED` | NOT FOUND (does not exist on filesystem) |
| Crontab per-process override | Process-scoped overrides observed: `AGENT_JOBS_P0_CONTAINED=0 AGENT_JOBS_P0_CONTAINMENT_FLAG=/tmp/tradeai_agent_jobs_p0_worker_absent` |

**Verification note:** The Gate 0 readiness audit previously checked `P0_CONTAINED` and `~/.config/` — both were incorrect identifiers. This P-1.0 run verified the canonical identifiers.

**State:** Containment is currently INACTIVE at the host level. Crontab entries use per-process overrides to explicitly declare non-containment for specific processes.

## Phase -1 Containment Rules

1. **PRESERVE the canonical observed state.** Do NOT clear or assert inactive containment as a prerequisite. The canonical implementation already handles state correctly (fail-closed on uncertainty).
2. **MUST NOT alter containment state** during Phase -1. No setting `AGENT_JOBS_P0_CONTAINED=1` or creating flag files as part of architecture freeze.
3. **Containment references in documentation** must use canonical identifiers (`AGENT_JOBS_P0_CONTAINED`, `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`), not the incorrect `P0_CONTAINED` or `~/.config/`.
4. **Any future containment activation** must be a deliberate operator decision, documented with reason and approval, and must use canonical identifiers.

## CECO Review Authorization Audit (Historical Context)

- **Date:** 2026-08-04
- **Finding:** Flag documented as "remained active" at that time
- **Current state:** Flag has since been cleared (not present as of 2026-08-08)
- **Interpretation:** Containment was active on Aug 4 and was deliberately cleared between Aug 4 and Aug 8. This P-1.0 phase does NOT re-activate containment.

## Agent Jobs Scope

The containment mechanism specifically guards `process_watchlist_agent_jobs.py` invocation. In the future, CIO agent job paths may also be guarded:

```
Current scope: process_watchlist_agent_jobs.py
Future scope (CIO): CIO wake jobs, handoff processing, notification delivery
```

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires operator approval and ADR amendment. Containment state was observed and documented; must not be altered by P-1.0.*
