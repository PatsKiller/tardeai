# PHASE 192C — Operator-Approved Protection Action Policy

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only.** Defines allowed paper-only adjustment actions, their guards, and Alpaca
support. **Nothing executes without explicit operator approval (`confirm=true`).**

---

## Allowed actions
| Action | When allowed | When blocked | Alpaca paper | API | Cancel/replace? |
|---|---|---|---|---|---|
| `MOVE_STOP_TO_BREAKEVEN` | in profit, BE raises the stop | stop already ≥ BE; quote stale | yes | `PATCH /v2/orders/<stop_id>` (replace) | replace (stop never absent) |
| `MOVE_STOP_TO_PROFIT_LOCK` | gain, lock level raises the stop | level ≤ current stop; stale | yes | `PATCH /v2/orders/<stop_id>` | replace |
| `CONVERT_TO_TRAILING_STOP` | in profit | n/a until supported-path validated | yes (`trailing_stop`) | cancel + `POST /v2/orders` | cancel+create (review-only this phase) |
| `ADD_FIXED_TAKE_PROFIT` | TP missing | OCO support unverified | yes (limit) | `POST /v2/orders` sell limit | new order |
| `ADD_BRACKET_OR_OCO_IF_SUPPORTED` | entry context | not for existing naked stop | conditional | OCO | review-only |
| `TAKE_PARTIAL_PROFIT_REVIEW_ONLY` | always | — | n/a | review-only | — |
| `KEEP_CURRENT_STOP` | always | — | n/a | none | — |
| `REJECT_ADVISORY` / `NEEDS_MORE_EVIDENCE` | always | — | n/a | none | — |

**Executable this phase (real paper order modify, on operator confirm):**
`MOVE_STOP_TO_PROFIT_LOCK`, `MOVE_STOP_TO_BREAKEVEN` only — via order **replace** (stop never
absent). Others are review/preview only until separately approved.

## Per-action requirements
- **Quote freshness:** ≤ 30 min, else blocked (`quote_stale`).
- **Spread/liquidity:** flagged; extreme spread → operator caution (advisory).
- **Current stop verification:** broker `stop_price` must equal the proposal's `current_stop`
  (`broker_stop_state_mismatch` otherwise).
- **Risk direction:** proposed stop must be **strictly above** the current broker stop (stop-up
  only) and **below** current price. Never increases risk.
- **Audit:** before + after record written for every call (even blocks/dry-runs).

## Hard blocks (engine-enforced)
- not paper account → assertion failure (`ALPACA_MODE must be paper`)
- non-paper endpoint → assertion failure
- no market order in this workflow
- quote stale → blocked
- broker stop verification fails / mismatch → blocked
- proposed move would not raise the stop → blocked
- proposal expired / not `PROPOSED` / trade not open → blocked
- strategy metadata missing → advisory notes it; operator must acknowledge (Hermes `caution`)
- no GO/WAIT, strategy, or live-holdings mutation anywhere

## Rollback
Order **replace** is reversible by a subsequent operator-approved replace back to the prior
`stop_price` (the prior value is recorded in `broker_order_before`). The audit log retains the full
before/after for restore.
