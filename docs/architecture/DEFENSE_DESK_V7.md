# Defense Desk v7 — Execute Through the Rail · Validate the Chain · Watch Every Play (2026-07-18)

Status:      ACTIVE
as_of:       2026-07-18T15:02:40-04:00
Measured at: efcc51365 / not measured

Session 7. The desk stages and arms; the EXISTING approvals + per-order-2FA pipeline
owns execution. `autonomous_live_submit_allowed` stays False.

## The EXEC branch (Phase 0 decision — docs/_findings/defense_desk_v7_diagnosis)
`schwab_transport.place_order` EXISTS (Stage 2b) but is pilot-fenced: taxable-only
assert, canary/protective kinds, hard caps, full guard stack. **Not widened.** Live
legs render **ARMED ORDER TICKETS** post-approval/post-2FA (redeploy-desk precedent);
paper legs auto-execute through the existing Alpaca lanes. When the operator later
grants defense-kind live submits, the intents already carry everything place_order
needs — that wiring is a fence decision, not a build.

## WS-EXEC — proven end-to-end on day one
- `defense_order_intents` (ONE table) + mirror rows in `action_queue` → the SAME
  approvals chip/UI/decision endpoint. `/approvals/decision` hook issues the 2FA
  pill (Telegram OPERATIONAL, 6-digit, 15-min) for `dint-` rows.
- Staging gates (config `defense_execution_caps.json`): kill file (`disabled`),
  whitelist (held-only trims/CCs, SH/PSQ/DOG/RWM inverse list, vetted short pool,
  rendered pair legs), $25K/order, 6 intents/day. **All three refusal classes
  demonstrated live** (kill, whitelist TSLA, $60K cap) — rendered on-page + audited.
- 2FA consume → paper: pre-approved proposal → ATM lane (**PROVEN: BUY 75 PSQ
  submitted**) · live: ARMED ORDER TICKET (exact instrument/side/qty/limit-band/
  account — **PROVEN: full ticket returned**). Pair sequencing: buy legs BLOCKED
  until the sell leg FILLS (tested both directions).
- `defense_execution_audit`: every hop, never deleted; the on-page Execution log
  fold shows the last 20 (the E2E chain including debug refusals is in it).

## WS-CHAIN — validation gates the click
`/defense/chain/validate`: fresh throttled pull → per-rail pass/fail (OI, vol,
spread%, Δ) + live book + as-of; drift (Δ walk >0.05 or spread >6%) proposes the
corrected strike with a diff line, **re-stage required, never silent substitution**.
The CC queue-trade button is LOCKED ("re-validate first") unless a passing
validation is ≤15 minutes old.

## WS-FILL v2 — 10-min RTH poller (cron, with cd — 7th catch)
Accounts with open intents: `get_transactions` delta (paper: trade_transactions)
matched by symbol/side/qty±10% → unique match = FILLED → ladder/pair/round-trip
advance automatically → OPERATIONAL Telegram; multiple matches → one-tap
disambiguation, never a guess.

## WS-PLAY / WS-HOME — shipped vs deferred (honest cut)
SHIPPED: the In-Play execution rail (every intent's live state); hedge playbook
STATE MACHINE server-side (entry_window_open / in_play ±% / stand_down / armed)
rendered on the Home posture strip with click-through; ladder steppers live-firing
(ARKX T2 fired on factor-count rise the same evening; BND shows the patient
90-session ★CORE window). Telegram classes labeled (OPERATIONAL fire now;
ADVISORY suppressed pre-promote).
**DEFERRED to v7.1 (stated, not silent): shorts squeeze-watch cycle (short-float Δ
recheck + RVOL flag), CC assignment-risk chips + roll-up-and-out suggestion
tickets, the in-play line in the daily Telegram digest.** All have their data
sources already flowing (enrichment short_float, radar cc picks, digest pipeline).

## Gotchas (new)
- `action_queue.action` is varchar(30); `dedupe_key` has NO unique constraint
  (no ON CONFLICT — existence-check).
- api_v2 hot-reload does NOT reload imported modules — `_dex()` importlib.reload
  helper for operator-cadence handlers.
- DDL-commit-before-fail-soft hit a 4th time → now reflexive in every new module.

## Re-score (two axes)
**Structural 9.5** — the full loop exists: recommend → pair → stage → approve →
2FA → execute/ticket → auto-fill → monitor → re-enter, all inside the existing
rails, all audited, all capped. **Proven ~5 and climbing measurably**: one paper
intent E2E today; the Jul 30–31 review now ALSO reads the first week of the
execution audit chain. The remaining proven-points are calendar + operator items
(rotation runbook 15 min, options_level, Cost Basis ×4, factsheet eyeball).
