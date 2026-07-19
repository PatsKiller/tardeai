# Options Lifecycle Desk — Architecture & Acceptance (2026-07-19)

## Status (the three-level language, applied honestly)

- **STRUCTURALLY COMPLETE** — all 11 phases built: canonical strategy model,
  versioned policy engine, harvest/giveback, assignment/expiry engine,
  persistent alert lifecycle, hash-bound 2FA tickets, first-class UI, outcomes
  ledger, health checks, 23 passing tests.
- **OPERATIONALLY VERIFIED (partial)** — verified on an EMPTY live book (the
  truth: zero open option positions exist anywhere) plus seven demo strategies
  priced on REAL Schwab chains: covered call, protective put, long call,
  credit spread, DATA_BLOCKED, HARVEST_FULL, DEFEND, close+roll tickets,
  hash-tamper rejection, and one live Telegram 2FA preflight with **no order
  submitted**. Demo rows were deleted after evidence; the intake reconciler
  additionally proved its VANISHED transition by closing the demo legs the
  broker didn't hold. Full operational verification requires the first real
  (paper) position flowing through intake→policy→alert→ticket→broker-evidence.
- **OUTCOME VALIDATED: NO** — the outcome ledger has zero rows and received
  zero test fixtures. No outcome claims are possible until real closed
  positions accumulate (tuning gate: n≥20/strategy, ±20% bound, never
  automatic).

## Architecture

```
brokers (canonical truth)                    config/options_lifecycle_policy.json (v1.0.0)
  Schwab positions API ─┐                                     │
  Alpaca paper API ─────┤                                     ▼
  Fidelity: operator ───┘                        ┌── options_lifecycle_engine.py
        │                                        │   quotes (wide chain, per-leg,
        ▼                                        │   source+ts+spread persisted)
options_lifecycle_intake.py                      │   economics → snapshot (immutable)
  NEW/MATCHED/DRIFTED/VANISHED                   │   policy → decision (versioned,
  errored accounts never VANISH                  │   exact rationale sentences)
        │                                        │
        ▼                                        ▼
options_strategy_positions / _legs    options_position_snapshots / _lifecycle_decisions
  (strategies, never loose legs;               │
   roll ancestry; UNKNOWN stays NULL)          ▼
                                      options_lifecycle_alerts.py
                                        assignment/expiry review (DTE windows,
                                        ex-div vs extrinsic, cover verification)
                                        NEW→ACK/SNOOZE→ESCALATE→SUPERSEDE/RESOLVE
                                        Telegram red/amber via router gate
                                               │
                                               ▼
                                      options_lifecycle_tickets.py
                                        close/roll build (fresh chain, all legs
                                        or blocked) → approve (sha256 hash binds
                                        legs+prices+TIF) → Telegram 2FA → ARMED
                                        MANUAL TICKET → record_fill_evidence
                                        (broker/operator evidence ONLY closes)
                                               │
                                               ▼
                                      options_lifecycle_outcomes (Phase 8)
                                      options_lifecycle_health.py (Phase 9,
                                        8 fail-closed checks)

runner: options_lifecycle_run.py → data/runtime/options_lifecycle_latest.json
cron: */20 9-16 weekdays · */5 15:00-16:00 (expiry tightening) · digest 08:05
API: GET /api/v2/options/lifecycle · POST /api/v2/options/lifecycle/{refresh,
     alert-ack, ticket-build, ticket-approve, ticket-2fa, ticket-evidence,
     ticket-cancel}
UI:  /v3/trading?tab=Options&otab=Lifecycle (lead tab) + Defense compact strip
```

## Safety boundary (verified in code and demos)

- Advisory by default; **no autonomous live submission exists** — the Schwab
  options pilot lane stays DISARMED and untouched; lifecycle tickets render
  exact manual tickets after per-order 2FA. Fidelity is manual-only.
- Spreads decided and ticketed atomically; leg-out requires
  `operator_acknowledged_leg_out` and renders the incremental-risk warning.
- A UI click never closes a position — only `record_fill_evidence` (broker fill
  or operator-recorded manual evidence). Partial fills leave sized residuals.
- Fail closed everywhere: stale quotes reject approval/arming, unquotable legs
  block tickets, unknown basis → DATA_BLOCKED, unknown ex-div is a finding.
- The existing options proposal engine (options_engine.py + desk enterprise)
  is UNTOUCHED.

## Migration & rollback

Migration: additive only — five new tables (`options_strategy_positions`,
`options_strategy_legs`, `options_position_snapshots`,
`options_lifecycle_decisions`, `options_lifecycle_alerts`,
`options_lifecycle_tickets`, `options_lifecycle_outcomes`) created idempotently
by `ensure_tables` (DDL commits immediately). No existing table altered; the
empty `options_monitored_*` tables are frozen/superseded, their monitor cron
untouched.

Rollback: remove the three cron lines (`options_lifecycle`,
`options_lc_digest`), drop the seven new tables, delete the five
`options_lifecycle_*.py` scripts + UI Lifecycle tab/strip + API routes. Nothing
else depends on them.

## Acceptance evidence

- Diagnosis: `docs/_findings/OPTIONS_LIFECYCLE_DESK_DIAGNOSIS_2026-07-19.md`
- Demo transcript (sample strategy snapshots, decisions, tickets, tamper
  rejection, 2FA preflight): session evidence 2026-07-19; key results inline
  in the diagnosis and commit messages. Demo rows deleted; outcome ledger 0.
- Screenshots (no horizontal overflow at any width):
  `docs/_findings/options_lifecycle_screens/lifecycle_{1440,1680,1920,2560}.png`
- Tests: `tests/test_options_lifecycle_policy.py` — 23 passed (harvest gates,
  spread atomicity language, giveback escalation, DATA_BLOCKED, ITM-defend
  regression from the live-caught bug, hash/TIF invalidation, freshness).
- Live-caught defects fixed during acceptance (the process working):
  ITM-short-call-below-delta-threshold decided HOLD → now DEFEND;
  losing CC said "premium is being earned" → state-aware language;
  float/Decimal crash → coercion; NaN peak in strip → numeric guards;
  16-strike chain window too narrow for far legs → 48-strike lifecycle fetch.
