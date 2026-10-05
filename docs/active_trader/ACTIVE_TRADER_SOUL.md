# Active Trader — Soul and Foundation

Operator, 2026-10-05, after reviewing the XNDU scalp minute by minute:

> "This is the exact type of methodology I need you to build into this as a soul and its foundation.
> If this was an automated trade — build up to having both the option for manual and automated — it
> would have got in and got out safely according to the volume and what was happening in the Level 2,
> and would have made this a profitable automated momentum scalp trade."

This document is that methodology. Every principle names the check that proves it, the code that
measures it and the config that tunes it. Thresholds live in `config/scalp_signal_engine.yaml`; changes
are proposed by `signal_calibration.py` from graded evidence and **ratified by the operator** — nothing
here tunes itself.

## 1. The canonical case: XNDU, 2026-10-05

| Time (ET) | Price | Engine | Should have been |
|---|---|---|---|
| 09:50:13 | 4.33 | 🟡 Heads-up | ✅ Correct, right before the move |
| 09:51 | 4.35 | Breakout happened; alert held until the next 5-min check | 🟢 Time to buy (best entry #1) |
| 09:55:11 | 4.43 | 🟢 Time to buy, 4m12s late, +1.8% already | "Extended, don't chase; buy zone 4.38–4.40" |
| 09:59–10:00 | 4.38–4.40 | Seen at 10:00:22, blocked by the 15-min cooldown | 🟢 Back in buy zone (best entry #2) |
| 10:05:16 | 4.46 | 🟡 Heads-up | Second breakout already underway |
| 10:06 | 4.50 | — | Top of the move |
| 10:07:09 | 4.48 | Your buy, 1m53s after the 10:05 heads-up | After the top |
| 10:08:15 | 4.49 | Your sell, +$0.99 | — |

`scripts/active_trader/session_review.py` reproduces this table from the minute bars, the alert
journal and your fills (`tests/test_at_soul_review_sim_20261005.py`, fixture
`tests/fixtures/active_trader/xndu_session_20261005.json`). At 500 shares, the simulator puts the
engine's actual decision at −$17.64 (it bought the chase), the improved timing at +$69.57 after
book slippage and fees, and "should have been" at +$85 before costs.

## 2. Principles and their checks

| # | Principle | Measurable check | Where |
|---|---|---|---|
| P1 | **Be early, never late.** A buy alert arrives within seconds of the break print, and a heads-up before it. | Alert latency from the ideal entry bar: target p50 ≤ 30 s, p90 ≤ 60 s (`late_s`). Heads-up ≤ `heads_up_lead_s` before the entry counts as correct. | `session_review.grade` → `metrics.latency_s`; Alerts page latency KPI (fast trigger loop) |
| P2 | **Never chase.** Above the entry by `chase_pct`% or `chase_r` R, the message is "EXTENDED — buy zone X–Y", never "time to buy". | `metrics.chases` (ext %, ext R) must trend to 0. | `session_review.grade`; EXTENDED kind (fast loop) |
| P3 | **Enter at a defined zone, with confirmation.** Either the break of a base (≥ `base_min_bars`, range ≤ `base_max_range_pct`%, break volume ≥ `break_vol_mult`×) or a pullback into the 38.2–61.8% zone of the prior leg that holds. Confirm with spread, book balance, supply at the ask and tape buys. | Every ideal entry names its base or zone; every engine entry carries its L2/tape/supply evidence in the journal. | `session_review.ideal_trades`; `momentum_alerts.l2_evidence` / `supply_evidence`; `microstructure_signals.entry_signals` |
| P4 | **Size to the supply.** Never take more than `max_take_pct`% of the shares near the inside ask. | Simulator fill feasibility rate; refusals name the supply. | `auto_trader_sim.simulate_symbol` |
| P5 | **Exit by evidence, or the stop — never hope.** Stop hit; close below the prior bar's low; volume climax with a long upper wick; VWAP lost; time stop. | Every ideal and simulated exit names its reason. One function (`session_review.exit_evidence`) serves review and simulation. | `session_review.exit_evidence`; `exit_watch` for live positions |
| P6 | **No silent misses.** A cooldown or veto that blocks an ideal entry is a graded miss with its reason. | `metrics.missed[].reasons`; repeated identical suppressions are calibration evidence. | `session_review.grade` |
| P7 | **Every decision is timestamped, replayed and graded against "should have been".** | A review exists for every session (`data/active_trader/reviews/YYYY-MM-DD.json`) and for every operator fill. | `session_review.run_day`; lane `active-trader-session-review` |
| P8 | **Learn only from graded evidence; the operator ratifies.** | Review records (`type=review`) and decision/trip records feed `signal_calibration.py`, which writes proposals only. | `trade_learning.append_new`; `signal_calibration.py` |
| P9 | **One brain for manual and automated.** Same signals, same entries, same exits, same thresholds. | The simulator imports the review's entry definitions and exit rule; there is no second strategy. | `auto_trader_sim` ← `session_review` |
| P10 | **Automation earns trust in simulation first.** | `active_trader_mode: auto_sim` writes a ledger; metrics: win rate, profit factor, average R, max drawdown, fill feasibility. | `auto_trader_sim.metrics`; `data/active_trader/auto_sim/ledger.jsonl` |
| P11 | **One source of truth.** All data comes from the Command Center (data broker, recorder store, alert journal); no process fetches its own. | Static test: review and simulator import no provider or broker client. | `tests/test_at_soul_review_sim_20261005.py` |

## 3. "Should have been", precisely

Defined in `session_review.py` (thresholds in `active_trader_review:`):

- **Breakout entry:** the first bar that closes and trades above the high of a base of
  `base_min_bars`–`base_max_bars` bars whose range is ≤ `base_max_range_pct`% of price, on volume ≥
  `break_vol_mult`× the base's mean. Price = max(base high, break-bar open). Stop = base low, floored
  at `min_stop_pct`%.
- **Pullback entry:** after an exited leg of ≥ `min_leg_pct`%, the first bar within
  `pullback_max_bars` of the leg high whose low reaches the zone
  [high − 0.618 × leg, high − 0.382 × leg] and closes ≥ zone low − `zone_tolerance`. Stop = the leg's
  entry price.
- **Exit:** the first evidence after the entry bar (P5).
- **Top:** the highest high within `horizon_bars` of the first entry.

One position at a time; a base break while holding is recorded as "second breakout underway".

## 4. Manual and automated

`active_trader_mode` in `config/scalp_signal_engine.yaml`:

| Mode | What happens |
|---|---|
| `manual` (default) | You trade from the alerts. Each session the simulator runs as a comparison only: Manual vs Auto-sim vs Should-have-been on the Session review tab. |
| `auto_sim` | The same, and the simulator's trades are appended to `auto_sim/ledger.jsonl` — the track record automation must earn. |

Simulated fills: the ask at the decision plus slippage from walking the recorded book for
`size_shares`; refused when the size exceeds `max_take_pct`% of the near-ask supply; exits at the bid
less book slippage; SEC fee and FINRA TAF on sells. Two entry sources run side by side: the engine's
own buy decisions as they fired, and the review's ideal entries ("improved timing") — what the fast
trigger loop is built to deliver.

## 5. What is deliberately absent

There is **no `auto_live` mode** and no code path from this doctrine to an order. `MBI_BEHAVIOR = 0`
(AGENTS.md §0): the agent never sizes, orders, stops or writes to a broker.

## 6. Daily rhythm

| ET | Job |
|---|---|
| 06:00–09:29 | Premarket watch + recorder (premarket) |
| 09:28–12:00 | Recorder; 09:30–11:55 alert engine (+ fast trigger loop when live) |
| 12:05 | Session review (dry run → persist; Telegram summary only in `send` mode) |
| 12:10 | Signal calibration (proposals only) |
| 16:10 | Session review again with the full day |

## 7. Gates before any live automation (design note — not built)

Live automated trading would be a new capability. None of these exist today; all are required:

1. **Operator decision** recorded as an operator-only decision (AGENTS.md §17), naming account, max
   size, max daily loss and symbols.
2. **Execution-engineering grant** naming the files and expiry (AGENTS.md §0 rule 2); built against
   the simulated broker first (`sim_execution.py`).
3. **Per-order authorization:** the live execution gates (per-order 2FA via web or Telegram, armed
   session, broker token health) stay in force for every order; automation never holds a standing
   approval.
4. **Track record in `auto_sim`:** ≥ 30 sessions and ≥ 100 simulated trades, profit factor ≥ 1.3,
   max drawdown ≤ the operator's daily loss limit, fill feasibility ≥ 90%, and simulated vs actual
   fill price within 1 tick on the operator's own fills over the same period.
5. **Kill switches:** a file kill and a Telegram command that stop new entries immediately, plus an
   automatic halt on a daily-loss breach or stale data (recorder snapshot older than its contract).
6. **Exits automated before entries:** protective exits on the operator's own positions run first,
   and must prove themselves before any automated entry.

## Related

- `docs/strategies/MOMENTUM_SCALP_SIGNAL_ENGINE_v1.md` — the ignition engine
- `scripts/active_trader/momentum_alerts.py` — alert decisions (L2/tape/supply evidence)
- `scripts/active_trader/microstructure_recorder.py`, `microstructure_signals.py` — the book and tape
- `scripts/active_trader/trade_replay.py`, `trade_learning.py`, `signal_calibration.py` — replay and learning
