# PHASE 189G — Durable Protection Remediation Plan

Status:      HISTORICAL
as_of:       2026-06-02T09:13:00-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:10 ET · Alpaca **paper** only · **Design only — no code changed here.**
Implementation is **Phase 190**. This plan prevents recurrence; it does not patch blindly.

---

## Problem restated (from 189B–189E, evidence-grounded)
The book is currently hedged (all 6 paper positions have live broker stops), but the system
**cannot prove it, cannot self-heal, and does not alert** because: (1) `alpaca_sync` onboards
positions with no strategy/stop/proposal metadata; (2) the post-fill stop path **discards** the
broker `stop_order_id`; (3) the only broker-stop verifier is report-only, unscheduled, and its
CRITICAL findings are log-swallowed with no alert; (4) the alert-capable health agents read
brokerage JSON, not `paper_trades`; (5) Hermes has no view or rule for open-position protection;
(6) there is no deferred-to-open lifecycle state for premarket scalps.

## Controls

### 1. Submission-time stop enforcement
- No paper ATM **entry** may be submitted without a resolved `planned_stop` unless the strategy is
  on a documented exemption list with a written risk rule. Enforce in
  `proposal_paper_submitter.submit_paper` before `adapter.submit_entry`.
- Persist `planned_stop` on the trade row at insert (currently never set —
  `alpaca_paper_adapter.py:596-606`).

### 2. Broker stop verification (the highest-leverage fix)
- After fill, **capture** the `_api_post('/v2/orders', stop_order)` response and write
  `stop_order_id` + `stop_verified_at` to `paper_trades` (today the return is discarded at
  `alpaca_paper_adapter.py:534`).
- A scheduled verifier (promote `reconcile_stop_v21_broker_stops.py` to its own cron, not just
  embedded in the supervisor) confirms each open position has a matching broker stop; on miss →
  **P1 SIEM event**; if high notional or large unrealized gain → **P0/P1 actionable Telegram**.
- Stop "placed" note must be written **only** on confirmed broker acceptance, never from the
  `use_market` boolean (`alpaca_paper_adapter.py:626-627`).

### 3. Alpaca-sync onboarding
- Any `alpaca_sync` position lacking strategy/stop metadata must enter a **protection-review**
  queue rather than landing silently as `unknown_sync`.
- Assign a provisional strategy or explicit `UNKNOWN_STRATEGY`, and **require a protection
  decision** (assign stop / adopt existing broker stop into the record / operator review).
- Adopt the *existing* broker stop into the DB (`stop_order_id`, derived `stop_loss`) so synced
  positions become trackable — `backfill_stop_v20_tracking.py:99-133` already has this logic;
  make it run automatically post-sync.

### 4. Health-agent coverage
A health check must evaluate **every** open paper position for: stop exists (broker-verified),
`stop_order_id` recorded, take-profit present if required, trailing eligibility, **large
unrealized gain without verified protection**, stale quote, and missing strategy metadata. Point
it at `paper_trades` + Alpaca orders — **not** brokerage `risk_management.json`. Wire
`unified_stop_supervisor` CRITICAL findings to SIEM + Telegram (today: log-only,
`unified_stop_supervisor.py:126-128`).

### 5. Hermes coverage
- Add safe view `hermes_v_open_position_protection_context` (fields + derived `protection_status`
  per 189E).
- Add a Hermes check that writes `hermes_validation_findings` (`naked_position`,
  `unverified_stop`, `unprotected_gain`) → `hermes_alerts`, independent of `proposal_id`.

### 6. SIEM / Telegram routing
- Naked position (no broker stop) → **actionable** alert.
- Stale quote → digest only (unless it is blocking an otherwise-eligible approval).
- Large unrealized gain without verified profit protection → **actionable** alert.

### 7. Dashboard protection coverage panel
ATM dashboard surfaces: protected (tracked) / protected-but-unrecorded / naked / unverified stops
/ take-profit missing / trailing eligible / action required — sourced from the broker-verified
view, refreshed each cycle.

### 8. (From 189B) Premarket lifecycle
Add a `PENDING_TRADING_WINDOW` lifecycle state; park premarket scalps there until the open instead
of looping delayed-revalidation every 15 min; dedup repeated stale proposals into the parked row.

## Acceptance criteria for Phase 190
- Every open paper position has `stop_order_id` + `stop_verified_at` populated and reconciled.
- A simulated broker-stop cancellation raises a SIEM event **and** a Telegram alert within one
  monitor cycle.
- An `alpaca_sync` import with no stop is blocked from sitting unreviewed (enters protection-review).
- Hermes emits a `naked_position` finding for any unprotected open position.
- Dashboard shows a protection-coverage panel with a non-zero "action required" count when applicable.

## Sequencing
Phase 190 = **Durable Protection Guardrails Implementation.** Do **not** "place stops" as the next
action — the stops exist; the next action is to make protection **provable, verified, and
alertable**, then enforce it at submission and sync time.
