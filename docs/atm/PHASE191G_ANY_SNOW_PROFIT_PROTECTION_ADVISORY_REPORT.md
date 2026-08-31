# PHASE 191G — ANY & SNOW Profit-Protection Advisory Report

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~11:00 ET · Alpaca **paper** only · **Advisory only — no stops modified.**
Marks are live-quote-dependent and move intraday.

---

## ANY (trade 48) — ⚠️ URGENT PROTECTION REVIEW

- **Fresh quote:** yes · **Live P&L:** ~**+$402 (+20.1%)** on 619 shares (entry 3.23, px ~4.02)
- **Broker stop:** 3.07 (live, tracked) — **below entry**, so it locks **$0** of profit
- **Giveback if stopped now:** ~the entire unrealized gain (stop is below entry, not below current price by a protective margin relative to the gain)
- **Take-profit:** missing · **Trailing:** not active, tier not met
- **TradeAI:** `URGENT_PROTECTION_REVIEW` — "Large gain with stop not protecting it."
- **Hermes:** `caution` — concurs there's a real protection gap; notes strategy/risk metadata is
  missing (`unknown_sync`, no `planned_stop`), so advice is based on stop-vs-entry only.
- **Operator action needed:** **YES.**
- **What would be considered if approved (Phase 192):** move stop up to lock a portion of the gain
  (breakeven 3.23 → or a profit-lock level), and/or set a take-profit / convert to trailing, and/or
  take partial profit. **First step: classify the position to a real strategy + set a stop that
  locks profit.**
- **Why no automatic action was taken:** this phase is advisory-only; ANY also lacks strategy/risk
  metadata, so any stop move must be operator-reviewed, not auto-applied.

## SNOW (trade 43) — TAKE-PROFIT ADVISORY (not urgent)

- **Fresh quote:** yes · **Live P&L:** ~**+$158 (+8.3%)** on 8 shares (entry 236.50, px ~256)
- **Broker stop:** 254.38 (live, tracked) — **above entry**, already **locks ~$143** of profit
- **Giveback if stopped now:** small (~$13) — the stop already protects most of the gain
- **Take-profit:** missing · **Trailing:** not active
- **TradeAI:** `TAKE_PROFIT_ADVISORY` — "Meaningful gain with no take-profit set."
- **Hermes:** `caution` — agrees TP is missing; confirm against strategy timeframe (`unknown_sync`).
- **Operator action needed:** **YES (lower urgency than ANY).**
- **What would be considered if approved (Phase 192):** set a take-profit, or convert the
  profit-locking stop to a trailing stop to capture further upside. No urgent stop move — the stop
  is already protective.
- **Why no automatic action was taken:** advisory-only phase; SNOW is already protected, so this is
  optimization, not risk mitigation.

## Side-by-side summary
| | ANY | SNOW |
|---|---|---|
| Live gain | +$402 / +20.1% | +$158 / +8.3% |
| Stop protects profit? | **No** (below entry) | **Yes** (locks ~$143) |
| Take-profit | missing | missing |
| TradeAI | URGENT_PROTECTION_REVIEW | TAKE_PROFIT_ADVISORY |
| Hermes | caution (metadata missing) | caution (confirm timeframe) |
| Urgency | **High** | Medium |
| Operator action | YES | YES |

The system now states **what to do and why**, and correctly ranks ANY (loose stop on a big winner)
above SNOW (already protected, only missing TP).
