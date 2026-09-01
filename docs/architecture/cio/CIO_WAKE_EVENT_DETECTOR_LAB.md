# CIO Wake/Event Detector Lab (P-1.6)

Status:      ACTIVE
as_of:       2026-08-08T18:02:23-04:00
Measured at: efcc51365 / not measured

## Overview

The CIO Wake/Event Detector is a **deterministic, restart-safe** engine that creates durable, idempotent wake jobs for material CIO work. It reads action ledger (P-1.3), handoff queue (P-1.4), and schedule definitions to determine when the CIO agent (Alex) needs to wake and perform work.

**Zero model calls. Zero Telegram. Zero production activation.** This is a LAB deliverable.

## Trigger Sources

### 1. Schedule-Based (SCHEDULE_DUE)
Five canonical Alex schedules discovered from actual crontab:

| Schedule ID | Type | Time (ET) | Days | Legacy Cron |
|---|---|---|---|---|
| `alex_daily` | daily | 05:00 | Mon-Fri | `0 5 * * 1-5` |
| `alex_weekly` | weekly | 08:00 | Sunday | `0 8 * * 0` |
| `alex_monthly` | monthly | 09:00 | 1st of month | `0 9 1 * *` |
| `alex_hygiene` | daily | 07:15 | Mon-Fri | `15 7 * * 1-5` |
| `alex_gov_research` | weekly | 06:00 | Monday | `0 6 * * 1` |

### 2. Action Follow-Up (ACTION_FOLLOWUP_DUE)
Reads P-1.3 action ledger. Actions with `next_check_at` in the past (and not in terminal state) trigger a wake. Deadline proximity boosts priority to `high`.

### 3. Handoff Completion (HANDOFF_COMPLETED)
Reads P-1.4 handoff queue. Recently completed handoffs (within LOOKBACK_HOURS) trigger a wake for CIO attention.

### 4. Health Block Transitions (FUTURE)
HEALTH_BLOCK_STARTED and HEALTH_BLOCK_CLEARED trigger types are defined and modeled in the wake store. Integration with P-1.5 health boundary transition events is pending the health boundary exporting transition events.

## Materiality Policy

The detector is **purely deterministic** — no LLM decisions about what constitutes "material" work. Materiality is defined by:

1. **Schedule**: If a configured schedule slot is due and not yet woken, it's material.
2. **Action follow-up**: If an action has an expired `next_check_at` and is not terminal, it's material.
3. **Handoff completion**: If a handoff recently completed, CIO review is material.
4. **Health transition**: Future — block/unblock transitions are material.

**No-work fast path**: If no schedules are due, no actions need follow-up, and no handoffs recently completed, `run_once()` returns 0 wakes and 0 cost.

## Idempotency

All wake jobs are idempotent via content-addressed keys:

| Trigger Source | Idempotency Key Components |
|---|---|
| Schedule | `schedule_id + slot + policy_version` |
| Action Follow-Up | `action_id + next_check_at + last_event_hash + policy_version` |
| Handoff Completion | `handoff_id + completed_event_id + artifact_hash + policy_version` |
| Health Transition | `decision_id + transition + policy_version` (future) |

Re-running the detector after wake creation produces **zero new wakes** — existing wakes are detected via idempotency key scan.

## Timezone Handling

All schedules use **America/New_York** (Eastern Time), matching the legacy crontab. DST transitions are handled by `zoneinfo.ZoneInfo`.

The detector clock is injectable (`set_clock()`) for deterministic testing. All internal comparisons use UTC.

## Restart Recovery

**Bounded lookback**: The detector looks back up to `LOOKBACK_HOURS=24` hours to catch missed schedule slots and recently completed handoffs. This prevents creating duplicate wakes for very old events while ensuring brief downtime doesn't cause missed work.

**CATCHUP_MAX_SLOTS=7**: Maximum 7 missed schedule slots to catch up, preventing cascade on long downtime.

## Wake Job Lifecycle

```
PENDING → CLAIMED → DISPATCHED → ACKNOWLEDGED → COMPLETED
  ↓          ↓           ↓
CANCELLED  RELEASED   EXPIRED
  ↓                    (terminal)
EXPIRED              CANCELLED
(terminal)           RETRY_PENDING → CLAIMED...
```

Terminal states: `COMPLETED`, `EXPIRED`, `CANCELLED`

## Wake Job Store

Event-sourced JSONL store at `data/cio/cio_wake_jobs.jsonl`. Replicates P-1.3/P-1.4 primitives:
- `canonicalize_payload` — deterministic JSON
- `compute_payload_hash` — SHA-256
- `compute_event_hash` — full envelope hash
- `build_event` — complete event envelope
- `fcntl` exclusive lock + `fsync` on every write
- Hash-chained for integrity verification
- Projection rebuildable from event log via replay

## Separation from Other Modules

- **Action Ledger (P-1.3)**: Detector reads actions (list_actions), never writes them.
- **Handoff Queue (P-1.4)**: Detector reads handoffs (list_handoffs), never writes them.
- **Health Boundary (P-1.5)**: Detector references health decision IDs but does not invoke the boundary.

## Dispatch Activation (NOT in P-1.6)

Wake jobs are **created** by the detector but **not dispatched** in this phase. P-1.7 will wire the dispatch to:
- Actual CIO agent invocation
- OpenClaw integration
- Production scheduler activation

## Rollback

If needed: preserve wake evidence in `data/cio/cio_wake_jobs.jsonl`, disable the detector by not running `run_cio_event_detector_once()`. No crontab, systemd, or OpenClaw changes were made.

## Test Coverage

47 tests in `tests/test_cio_wake_detector.py`:
- Schema & policy validation (2)
- Scheduled wake scenarios (6)
- Action follow-up logic (5)
- Health transition fixtures (2)
- Handoff completion logic (4)
- Wake store state machine (6)
- Reason codes & priority (2)
- Recovery & lookback (3)
- Integrity & hash chain (3)
- Concurrent safety (1)
- Structural containment (8)
- G0 acceptance (3)
- Primitive determinism (3)

All tests use temporary stores. Zero canonical runtime pollution.
