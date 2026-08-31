# PHASE 189E — Hermes Missing-Stop Failure Analysis

Status:      HISTORICAL
as_of:       2026-06-02T09:13:00-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:08 ET · Alpaca **paper** only · Evidence-backed (file:line / view defs)

---

## The question
Why did Hermes (the advisory/librarian/health layer) not flag ANY (48), SNOW (43), TMHC (47) as
protection defects?

## The answer
Three compounding structural reasons — Hermes has **no visibility** into open-position protection
state, **no rule** to evaluate it, and its only position-touching loop reads **closed trades
only**.

## Findings

1. **Hermes safe views enumerated:** 12 `hermes_v_*` views + 7 base tables. Only three touch
   trades/positions: `hermes_v_trade_reflection_context`, `hermes_v_portfolio_context`,
   `hermes_v_proposal_context`.

2. **No safe view exposes broker-protection state.**
   `hermes_v_trade_reflection_context` (from `paper_trades`) exposes only `stop_loss, target_1,
   target_2, dollar_risk` among protection-adjacent fields. It does **NOT** expose
   `stop_order_id`, `stop_verified_at`, `take_profit_price`, `unrealized_pnl`, `proposal_id`,
   `bracket_order`, or `status`. Consequence: a position with no broker stop is **indistinguishable
   from a protected one**, and TMHC's planned `stop_loss=68.02` even *looks* protected.
   `hermes_v_portfolio_context` reads `stopped_out_watch` (post-stop history), irrelevant to live
   naked detection.

3. **JOIN-exclusion is NOT the cause.** `hermes_v_trade_reflection_context` is
   `paper_trades UNION ALL trade_closed` with no proposal JOIN — so ANY/SNOW (proposal_id NULL)
   *are* present in it. They're missed because of (2)/(4)/(5), not a filter. (They are absent from
   the proposal-only `hermes_v_proposal_context`, but that was never the protection surface.)

4. **The only Hermes loop touching these views queries CLOSED trades only.**
   `scripts/hermes_autonomous_loop.py:64-65` → `FROM hermes_v_trade_reflection_context t WHERE
   t.lifecycle_state = 'closed'`. It is a **thesis challenger** (research), not a risk monitor —
   it never selects open positions or reads stop/broker fields. All other `hermes_*.py` are
   librarian/embedding/research workers.

5. **No Hermes rule for naked/unverified/unprotected positions — ABSENT.** Searched all
   `scripts/hermes_*.py`, `siem_to_hermes_backlog.py`, and `hermes_sidecar/` for
   `naked|unprotected|stop_order_id|stop_verified|protection|take_profit_price`. No match (only
   irrelevant `node_modules` docs). `hermes_validation_findings.finding_type` values are only
   `stale_data, broken_pipeline, missing_data`; `hermes_advisory_events.event_type` only
   `source_discovery_followup_staged, librarian_backlog_created, research_staged`;
   `hermes_alerts` has 0 rows.

6. **Hermes ran recently — on the wrong surface.** `hermes_advisory_events`/`hermes_research_
   intelligence` latest `created_at = 2026-06-02 03:45`; the 5 most-recent events are all
   `librarian_backlog_created`. Hermes is alive and doing research/librarian work only. The
   sidecar SQLite DBs are effectively empty (0 kanban tasks, 0 responses).

## Conclusion
Hermes did not flag these because **(a)** no safe view exposes `stop_order_id` /
`stop_verified_at` / `take_profit_price` / `unrealized_pnl` / `status`; **(c)** no rule for
"open position with no stop", "large unrealized gain with no profit protection", or "note claims
stop placed but no broker stop_order_id" exists anywhere; and **(d)** the only loop touching the
view is closed-trade research. **(b)** (JOIN exclusion) is not the cause.

## What must be ADDED (designed in 189G; built in Phase 190 — not here)
1. **New safe view** `hermes_v_open_position_protection_context` over `paper_trades WHERE
   status='open'`, exposing `id, symbol, status, proposal_id, opened_via, entry_price,
   current_price, unrealized_pnl, stop_loss, stop_loss_price, planned_stop, stop_order_id,
   stop_verified_at, take_profit_price, bracket_order, notes` + derived `protection_status`
   (`naked` | `claimed_unverified` | `protected`). Do **not** repurpose the closed-trade
   reflection view.
2. **New Hermes check** (e.g. `scripts/hermes_open_position_protection_check.py`) that reads that
   view each session and writes `hermes_validation_findings` rows with new finding types
   (`naked_position`, `unverified_stop`, `unprotected_gain`) promoted to `hermes_alerts` — running
   regardless of `proposal_id` so `alpaca_sync` positions are covered.
