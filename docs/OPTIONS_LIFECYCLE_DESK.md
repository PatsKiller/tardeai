# Options Lifecycle Desk — Architecture & Acceptance (2026-07-19)

## Status (the three-level language, applied honestly)

- **STRUCTURALLY COMPLETE** — all 11 phases built: canonical strategy model,
  versioned policy engine, harvest/giveback, assignment/expiry engine,
  persistent alert lifecycle, hash-bound 2FA tickets, first-class UI, outcomes
  ledger, health checks, 38 passing tests.
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

- Advisory by default; **no autonomous live submission exists**. The Schwab
  options pilot's DB arm switch (gate #1) is **INTENTIONALLY ARMED by operator
  decision (2026-07-19, recorded in system_controls)** — the operative controls
  are per-order 2FA (OPTIONS_EXECUTION_1 marker) and per-strategy
  `live_allowed` flags (all false today). Lifecycle tickets render exact
  manual tickets after per-order 2FA. Fidelity is manual-only.
- Spreads decided and ticketed atomically; leg-out requires
  `operator_acknowledged_leg_out` and renders the incremental-risk warning.
- A UI click never closes a position — only `record_fill_evidence` (broker fill
  or operator-recorded manual evidence). Partial fills leave sized residuals.
- Fail closed everywhere: stale quotes reject approval/arming, unquotable legs
  block tickets, unknown basis → DATA_BLOCKED, unknown ex-div is a finding.
- The existing options proposal engine (options_engine.py + desk enterprise)
  is UNTOUCHED.

## Migration & rollback (v1.1-corrected counts)

Migration: additive only — **ten** lifecycle tables, created idempotently (DDL
commits immediately): `options_strategy_positions`, `options_strategy_legs`,
`options_position_snapshots`, `options_lifecycle_decisions`,
`options_lifecycle_alerts`, `options_lifecycle_tickets`,
`options_lifecycle_outcomes`, plus v1.1 `options_basis_evidence`,
`options_journal_events`, `options_oversight_runs`; one view
`v_options_journal`; additive columns on `options_strategy_legs`
(`basis_source`) and rows in `trade_instances`
(source_table='options_strategy_positions' — its own UNIQUE constraint).
The empty `options_monitored_*` tables AND orphan `journal_options_groups` are
frozen/superseded; existing monitor cron untouched; `trade_closed` never
written.

Modules (**twelve**): `options_lifecycle_{model,intake,engine,alerts,tickets,
health,run,digest,basis,oversight}.py` + `options_journal_bridge.py` +
`ticker_attribution.py`.

Exact cron lines (installed 2026-07-19):
```
*/20 9-16 * * 1-5 cd <repo> && flock -n /tmp/options_lifecycle.lock bash -c "set -a; . ./.env; set +a; .venv/bin/python scripts/options_lifecycle_run.py" >> logs/options_lifecycle.log 2>&1
*/5 15 * * 1-5   cd <repo> && flock -n /tmp/options_lifecycle.lock bash -c "set -a; . ./.env; set +a; .venv/bin/python scripts/options_lifecycle_run.py" >> logs/options_lifecycle.log 2>&1
5 8 * * 1-5      cd <repo> && flock -n /tmp/options_lc_digest.lock bash -c "set -a; . ./.env; set +a; .venv/bin/python scripts/options_lifecycle_digest.py" >> logs/options_lifecycle.log 2>&1
```

Rollback dependencies: remove the three cron lines; drop the ten tables + view;
delete the twelve scripts, the UI Lifecycle tab/strip, and the
`/api/v2/options/lifecycle*` routes; `DELETE FROM trade_instances WHERE
source_table='options_strategy_positions'`. Nothing else depends on them —
the proposal engine, Defense oversight, journal builders, and Drive sync are
all untouched by rollback.

## v1.1 additions (2026-07-19, same day)

- **Single-primary reducer** — precedence DATA_BLOCKED > EXPIRATION_CRITICAL >
  ASSIGNMENT_CRITICAL > DEFEND > ROLL > ACCEPT_ASSIGNMENT > EXERCISE_REVIEW >
  HARVEST_FULL > HARVEST_PARTIAL > LET_MATURE > HOLD; losers persist as
  subordinate context in the same decision/alert.
- **Ticket/2FA idempotency** — one active ticket per idempotency key
  (position+action+legs+prices+TIF+policy); repeat approve revokes the prior
  challenge (generation tracked); 2FA text names the exact order.
- **Contract-exact quotes** — escalating strike windows (48/120/250) +
  expiration verification; provenance persisted; neighbors never price tickets.
- **Basis workflow** — priority chain broker_fill → broker_orders →
  intent_evidence → txn_history → roll_parent → operator_evidence (document ref
  REQUIRED, visibly labeled); cumulative roll economics across roll_root_id.
- **Journal bridge** — one strategy = one trade_instances row
  (trade_uid `options_strategy_positions:<id>`), journal events from fill
  evidence only, `v_options_journal` canonical read, deep links both ways.
  Identity: strategy_position_id + roll_root_id + account_key + underlying —
  never underlying+date.
- **Ticker attribution** — separate stock / options / dividends / fees
  components with the machine-checked invariant
  `stock + options + dividends − fees = combined`; protective-put premium is a
  labeled hedge cost; covered-call premium never inflates stock return.
- **Free-lane oversight** — llm_lane chatgpt/grok on configured exception
  triggers only; verdicts CONCUR/QUALIFY/OBJECT/UNAVAILABLE; advisory-only (no
  write path into decisions/tickets/2FA/outcomes); **paid disabled by default**.
- **Alert identity + delivery evidence** — every alert names account/position/
  contracts/strikes/expirations/decision; attempted/delivered/message_id/
  failure/retry persisted.

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
