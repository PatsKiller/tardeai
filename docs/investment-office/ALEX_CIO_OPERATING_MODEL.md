# Alex (CIO) Operating Model — Autonomous Orchestration Lifecycle

Status:      ACTIVE
as_of:       2026-08-13T20:51:47-04:00
Measured at: efcc51365 / not measured

> Canonical reference for the ONE authoritative CIO lifecycle that converges
> event → wake → run → handoff → synthesis → notify → disposition → follow-up.
>
> **Financial authority: `READ_ONLY_ADVISORY`.** No broker/order/stop/2FA writes.
> This document mirrors runtime truth; it is not a second source of it.

---

## 1. The single lifecycle

There is exactly **one** authoritative path from "something changed" to "Alex
decided and the operator was told":

```
canonical producer (heartbeat / reactive / DB outbox / operator message)
        │  deterministic, no model calls
        ▼
CIO Event Bus  (scripts/lib/cio_event_bus.py)
        │  semantic dedupe across publishers (cio_semantic_event_key.py)
        ▼
CIO Wake Dispatcher  (scripts/lib/cio_wake_dispatcher.py)  — SOLE wake claimant
        │  idempotency key + dispatch ledger + lease
        ▼
CIO Run / Case  (scripts/lib/cio_run.py)  — exactly one run per wake
        │  NEW_RUN (create) | RESUME_RUN (reopen existing parent)
        ▼
required specialist handoffs  (scripts/lib/cio_agent_handoff_queue.py)
        │  hash-chained; BLOCKED if target agent NOT_READY (fail-closed)
        ▼
optional Hermes challenge  (scripts/lib/cio_hermes_challenge_queue.py)
        │
        ▼
Alex synthesis → InvestmentDecision + action  (scripts/lib/cio_action_ledger.py)
        │
        ▼
notification outbox  (scripts/lib/cio_notification_outbox.py)  — fail-closed
        │
        ▼
operator disposition  (scripts/lib/cio_outcome_store.py)  — durable
        │
        ▼
follow-up / outcome  (ACTION_FOLLOWUP_DUE wake → new run; outcome ledger)
```

**Heartbeat is a deterministic detector/backstop only** (`scripts/cio_heartbeat.py`):
zero model calls, zero direct action writes, zero delegation, zero Telegram. The
live path is `scripts/cio_reactive_cycle.py` (systemd timer) → dispatcher →
`scripts/cio_wake_dispatch_entrypoint.py` → run worker.

---

## 2. Invariants (proven by Checkpoint 3 canaries)

| # | Invariant | Mechanism |
| --- | --- | --- |
| I1 | **One parent run per semantic event** | semantic event key → wake idempotency key → dispatch ledger → `PENDING→CLAIMED→DISPATCHED` (a dispatched wake is never re-polled) |
| I2 | **No duplicate notification** | outbox `dedupe_key` + `idempotency_key`; forbidden message classes rejected; no-credentials delivery blocked |
| I3 | **Heartbeat never reasons** | deterministic snapshot + change detection + situation detector only |
| I4 | **Crash recovery** | lease expiry → `recover_expired_leases()` → back to `PENDING`; hash chain verifies |
| I5 | **Parent run resumes** | `RESUME_RUN` validates the target run and reopens it; never spawns a sibling |
| I6 | **Deferred ≠ forgotten** | action `DEFERRED` + `followup_condition` + `next_check_at` → `ACTION_FOLLOWUP_DUE` wake |

All six are exercised by `tests/test_cio_checkpoint3_canaries.py` (17 tests,
zero provider calls, zero live side effects, temp-path stores).

---

## 3. Wake lifecycle state machine

`scripts/lib/cio_wake_jobs.py` (`CIOWakeJobStore`) — append-only, hash-chained:

```
PENDING → CLAIMED → DISPATCHED → IN_FLIGHT → COMPLETED
              │            │
              └── (lease)  └── ACKNOWLEDGED (optional ack)
```

- `claim()` sets a time-limited lease (default 300s).
- `recover_expired_leases()` releases stale `CLAIMED`/`DISPATCHED` wakes.
- `enqueue()` enforces idempotency via `idempotency_key`; a duplicate returns the
  existing event and does not create a second wake.
- Dispatch is **not** completion: `COMPLETED` only after the linked run reaches a
  terminal state (`COMPLETED/BLOCKED/FAILED/CANCELLED/EXPIRED`) via
  `on_run_completed()`.

Two wake intents:

- `NEW_RUN` — dispatcher creates exactly one run.
- `RESUME_RUN` — requires `target_run_id`; validates the run exists and is
  non-terminal; the worker resumes the **same** parent run.

Unknown/malformed intents **fail closed** — no run is created.

---

## 4. Run lifecycle state machine

`scripts/lib/cio_run.py` (`CIORunStore`) — append-only, hash-chained, with
budget enforcement:

```
QUEUED → HEALTH_CHECK → EVIDENCE_BUILD
                             ├─ SPECIALIST_REVIEW → WAITING_FOR_SPECIALISTS ─┐
                             ├─ HERMES_CHALLENGE → WAITING_FOR_HERMES ────────┤
                             └─ CIO_SYNTHESIS → ACTION_WRITE ─────────────────┤
                                                                             │
                                              (resume() → EVIDENCE_BUILD) ◄──┘
NOTIFICATION_ENQUEUE → COMPLETED
```

Budget caps (calls, cost, wall-time, specialists, Hermes challenges) are clamped
to hard server-side ceilings. `record_model_call()` fails closed once the cap is
hit — there is **no silent fallback** to an ungoverned provider.

---

## 5. Materiality, dedupe, cooldown

Alex must not notify on every tick. Three deterministic gates:

1. **Source materiality** — `cio_plan_enrichment.is_material_source()`:
   `system.heartbeat_ok` is non-material; `situation.raised` / `OPERATOR_MESSAGE`
   are material. Unknown sources fail closed to non-material.
2. **Plan materiality** — `cio_plan_enrichment.is_material_plan()`:
   - `S5_CASH_DEPLOYMENT`, `S6_CONCENTRATION_OR_DISPOSITION`,
     `S8_DEFENSIVE_REGIME` → material (operator-facing).
   - `S4_SECTOR_ROTATION`, `S7_WATCH_PROMOTION`, `S2_STOP_GAP` → forward-loop
     signals (feed Watch / opportunity queue), not operator notifications.
3. **Dedup + cooldown** — `CIOPlanStore.find_recent_dedup()` (within-hours window),
   goal-wake dedup (30 min per agent+goal), and the semantic event key.

The CIO run may still be triggered for a non-material event; only the operator
**notification** is suppressed unless material.

---

## 6. Notification outbox — fail-closed

`scripts/lib/cio_notification_outbox.py` (`NotificationOutbox`):

- `FORBIDDEN_MESSAGE_CLASSES` (`execute_trade`, `order_submission`,
  `risk_override`, `2fa_code`, `credential_request`, `secret_delivery`) are
  rejected at enqueue.
- Body hash is validated; channel and deep-link schemes are allow-listed.
- Delivery is lease-claimed, retried with backoff (30s/2m/10m, max 3), then
  **dead-lettered** — never silently dropped, never silently delivered.
- `RealTelegramAdapter` returns `DELIVERY_BLOCKED_CREDENTIALS` when credentials
  are missing — no silent fallback to fake delivery.

---

## 7. Disposition and follow-up

- `CIOOutcomeStore.record_outcome()` persists `ACKNOWLEDGED / ACCEPTED /
  DEFERRED / REJECTED / DONE / CANCELLED` dispositions with a hash chain.
- `CIOActionLedger` carries `followup_condition` + `next_check_at` on every
  action. Deferring an action records `CIO_ACTION_DEFERRED`; the future condition
  is durable on the action, and `CIOEventDetector` emits an
  `ACTION_FOLLOWUP_DUE` wake (mapped to an `ACTION_FOLLOWUP` run) when the
  condition comes due. Deferred work is re-opened, not forgotten.

---

## 8. Checkpoint 3 — controlled canaries (17/17 pass)

| Canary | Result | Proof |
| --- | --- | --- |
| material holding change | PASS | `detect_changes` → `portfolio.material_change`; semantic key deduped |
| cash above policy band | PASS | `S5_CASH_DEPLOYMENT` material |
| concentration breach | PASS | `S6_CONCENTRATION_OR_DISPOSITION` material |
| watch promotion candidate | PASS | `S7_WATCH_PROMOTION` plan + durable `find_recent_dedup` |
| defensive/rotation change | PASS | `S8_DEFENSIVE_REGIME` material; `S4` forward-loop |
| specialist handoff required | PASS | run `SPECIALIST_REVIEW → WAITING → resume` (one run) |
| provider blocked | PASS | budget `provider_calls` cap fails closed |
| restart/replay recovery | PASS | stale lease released; run state reconstructed from disk |
| operator defer + future trigger | PASS | `DEFERRED` + `followup_condition` + `ACTION_FOLLOWUP` mapping |
| no-change event suppressed | PASS | `system.heartbeat_ok` non-material |

Invariants: **exactly one run per semantic event** (dispatcher idempotency) and
**no duplicate notification** (outbox dedupe + forbidden-class + credential block).

---

## 9. Known gaps (honest, not hidden)

1. **`test_outbox_process_crash.py` requires live Postgres** — 4 integration
   tests error in this environment (password auth) because they target
   `localhost:5432`. They are DB-gated, not unit tests.

Resolved (no longer gaps):

- **Handoff readiness drift** — handoff tests that assumed
  `enqueue → PENDING → claim` were updated to pin the target specialist `maria`
  as `AVAILABLE` (monkeypatching the maturity-catalog registry and the
  `can_claim` readiness gate, mirroring the canary pattern in
  `tests/test_cio_checkpoint4_resume.py`). `steph` stays `NOT_READY` so the
  explicit `BLOCKED` fail-closed tests keep exercising that path. The queue's
  fail-closed `BLOCK`-to-`NOT_READY` behavior is unchanged; only the tests were
  corrected. Fixed in `tests/test_cio_wake_detector.py` (Section E, 3 tests) and
  `tests/test_cio_agent_handoff_queue.py` (22 tests).
- **Outbox dedupe was per-stream** — `NotificationOutbox._check_dedupe` and
  `_check_idempotency` now search globally across all streams (via
  `_iter_all_events`), so two producers enqueueing different `notification_id`s
  for the same semantic event collapse to a single notification. Covered by
  `test_cross_stream_dedupe` and `test_cross_stream_idempotency`.
