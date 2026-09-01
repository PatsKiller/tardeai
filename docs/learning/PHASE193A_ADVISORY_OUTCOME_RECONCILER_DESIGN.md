# PHASE 193A — Profit-Protection Advisory Close-Loop Reconciler Design

Status:      HISTORICAL
as_of:       2026-06-02T12:45:21-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · learning telemetry · no execution / no stop or order mutation**

---

## Purpose
Close the loop opened by Phases 191 (advisory) and 192 (operator-approved adjustment): when a paper
trade closes, measure whether the advisory was right, whether the operator acted, and what it cost
or saved — feeding journaling/backtesting/threshold tuning.

## Inputs joined per trade
- `atm_profit_protection_advisories` — TradeAI action, Hermes opinion, operator_action_required.
- `paper_protection_adjustment_proposals` (status APPLIED) + audit JSONL — applied adjustment,
  stop before/after, profit locked, giveback avoided, operator decision.
- `paper_trades` — status, entry/exit/current, pnl, pnl_pct, r_multiple, MFE/MAE, take_profit.

## Output: table `protection_advisory_outcomes` (PK trade_id, upsert)
Records per trade: advisory linkage, adjustment linkage, operator_decision
(`accepted`/`ignored`/`none`), outcome (realized/unrealized pnl, r, MFE/MAE), `gave_back_profit`,
`profit_left_on_table_pct`, `take_profit_would_have_helped`, `trailing_would_have_helped`,
`advisory_accuracy` (`confirmed`/`contradicted`/`baseline_no_advisory`/`in_flight`),
`mfe_units_validated`, notes.

## Record kinds
- **final_closed** — trade closed; final accuracy + give-back computed.
- **interim_open** — open trade with an advisory and/or an applied adjustment; tracked until close
  (e.g. ANY after its profit-lock).
- **baseline_no_advisory** — closed trade that predates advisories (honest baseline).

## Operator decision logic
- `accepted` — an APPLIED adjustment (proposal or audit) exists for the trade.
- `ignored` — advisory required action, trade closed, no adjustment applied.
- `none` — no advisory action required / not applicable.

## Accuracy logic
For closed trades with an advisory that **urged protection**
(URGENT/LOCK/TAKE_PROFIT/BREAKEVEN): `confirmed` if the trade then **gave back profit**
(MFE excursion exceeded final result), else `contradicted`. Trades with no advisory →
`baseline_no_advisory`. Open → `in_flight`.

## ⚠️ MFE units integrity finding
Source `max_favorable_excursion` is **unit-inconsistent** across trades (some values read as %,
some are impossible as a max — e.g. a trade whose MFE < its final pnl_pct). The reconciler therefore
**does not fabricate a dollar "profit left on table"**: it captures MFE raw, computes the give-back
*signal* under a documented "MFE-as-%" assumption, and sets `mfe_units_validated=false` to flag the
field for pipeline validation. This is a real follow-up finding for the data pipeline, surfaced
honestly rather than papered over.

## Guardrails
Read-only on the broker; writes only the outcomes table. No execution, no GO/WAIT, no strategy, no
live. Idempotent (upsert by trade_id) — safe to schedule (recommended: after each close + nightly).
