# Options v1.2/v1.2.1 + Costs — Phase 0 Read-Only Truth Audit (2026-07-19)

Status:      HISTORICAL
as_of:       2026-07-19T15:38:06-04:00
Measured at: efcc51365 / not measured

## 1. Schema truth (live DB vs committed builders)

Audited all 10 lifecycle tables + trade_instances/trade_closed/trade_transactions.
**Workstation-only columns found (v1.2.1 P0 finding, now FIXED in committed
builders + proven by the clean-schema install test):**
- options_lifecycle_decisions: subordinate, precedence_rule, prior_recommendation, transition_reason
- options_lifecycle_alerts: attempted_at, delivered_at, message_id, failure_reason, retry_count
- options_lifecycle_tickets: idempotency_key + 6 challenge-lineage columns

`verify_schema()` (EXPECTED_SCHEMA) now guards this permanently; the ephemeral-
schema test installs everything from the repository alone.

## 2. Hypothetical traces (drove the P0 fixes)

- Full close: v1.2 projected the journal BEFORE status/outcome — fixed (P0 order:
  legs → status → cumulative outcome → outbox → commit).
- Two-batch partial: v1.2 compared cumulative fills to the mutated residual —
  fixed (immutable ticket targets + evidence-ledger projection); proven by the
  three-batch VWAP test asserting DB rows.
- Spread close in separate updates: cumulative-per-ticket-leg handles it.
- Roll: v1.2 created the child but no parent outcome — fixed; one-sided fills
  now persist as options_package_incidents (4 states) with red health.
- Assignment/exercise: premium double-count risk — fixed via MODEL A
  (option retains premium; stock transfer strike-only; fields persisted).

## 3. P&L field semantics (verified)

- trade_closed.pnl: NET of fees (schwab_round_trips net_pnl = gross − fees).
- options_lifecycle_outcomes.realized_pnl: NET (realized − cumulative fees;
  fees retained in meta.fees).
- trade_instances.pnl (bridge): mirrors outcome (net).
- eConfirm "Charge and/or Interest": COMBINED, never subtyped.

## 4. Schwab payload fee inventory

trade_transactions carries one combined `fees` column (150 non-zero rows,
$47.92, sells only — SEC/TAF-like but the source does NOT itemize). Normalized
as `broker_charge_unclassified` with raw label/amount/rule/confidence retained.
No raw per-charge API payloads are persisted by the ingest today (P1 follow-up:
persist raw payloads at ingest).

## 5. Gmail availability (P1-2 answer)

The repository host HAS an authorized Gmail READ integration: the gog CLI
(same account as Drive sync). Live probe found real Schwab eConfirms;
the adapter parsed 25 trades from 11 emails and reconciled 22 MATCHED,
2 price mismatches (BJDX), 1 missing ledger row (FCNTX) — the reconciler's
first run produced genuine findings. Email remains SECONDARY evidence.
