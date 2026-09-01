# PHASE 192I — Operator Approval Execution Endpoint Report

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**Endpoint:** `POST /api/v2/atm/protection-adjustment-proposals/:proposal_id/approve`
**Engine:** `scripts/apply_paper_protection_adjustment.py` · Alpaca **paper** only

---

## Behavior
- `confirm=false` (default) → **DRY_RUN_PREVIEW**: runs every guard, returns the full before/after,
  writes an audit record, **does not touch the broker**.
- `confirm=true` → executes a single allowed action (`MOVE_STOP_TO_PROFIT_LOCK` /
  `MOVE_STOP_TO_BREAKEVEN`) by **replacing** the paper stop order (`PATCH /v2/orders/<id>`), so the
  stop is never absent; persists new metadata; marks the proposal `APPLIED`.

## Hard guardrails (engine-enforced, in order)
1. `ALPACA_MODE == paper` (assertion) · paper-api base only (assertion)
2. proposal exists and `status='PROPOSED'`
3. action ∈ {MOVE_STOP_TO_PROFIT_LOCK, MOVE_STOP_TO_BREAKEVEN}
4. trade still `open` and has a tracked `stop_order_id`
5. quote fresh (≤ 30 min)
6. broker stop fetched and `status` active; `stop_price` equals expected `current_stop`
7. proposed stop **> broker stop** (raises stop) and **< price** (never increases risk)
8. audit before + after (always)
9. operator + reason required (HTTP 400 otherwise)

Any failed guard → `BLOCKED` with a `block_reason`, audited, no broker change.

## Verification (live, via API)
`POST …/20/approve {operator:"john", reason:"…", confirm:false}` →
```
ok: true, status: DRY_RUN_PREVIEW, stop 3.07 -> 3.555, profit_locked_after $201.18
```
Broker re-checked after: **ANY stop still 3.07 (UNCHANGED)**. No order placed or modified.

## Operator decision honored
Per operator authorization, the engine **can** apply `MOVE_STOP_TO_PROFIT_LOCK` for ANY (paper),
but **only on explicit `confirm=true`** ("on my click"). This phase performed **dry-run only** — no
real paper order was modified. To execute: `confirm:true` on the chosen proposal (or `--confirm`
via the CLI). Reversible by an operator-approved replace back to the prior stop.

## Guardrails
No GO/WAIT, no strategy, no live holdings, no live endpoint, Level 7 prohibited. Market orders not
used. Execution is replace-only (stop never absent).
