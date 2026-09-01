# Stop Management System Discovery — 2026-05-23

Status:      HISTORICAL
as_of:       2026-05-22T15:47:55-04:00
Measured at: efcc51365 / not measured

## TL;DR (3 sentences for John)

The system has two active monitors that manage stops using **identical R-multiple
thresholds** (1R→breakeven, 1.5R→lock 0.5R, 2R→lock 1R, 3R→lock 2R) applied
uniformly to all strategies — even though strategy YAML configs define per-strategy
methods (fixed_pct, level_based, fundamental, ema_21 trail) that are never read at
runtime. Every stop adjustment is logged to `paper_trade_risk_actions` and
`agent_curation_events`, and a post-trade analyzer (`trailing_stop_analyzer.py`)
uses qwen3:14b to generate lessons on closed trades — but the lessons don't feed
back into the live monitors. The biggest gaps are: (1) strategy configs are
decorative, not enforced; (2) no explicit state machine for stop lifecycle; (3) the
"Trail:" recommendation shown in the UI is advisory-only from historical analysis,
not a live decision.

---

## Code Map

| File | Role | Schedule | Inputs | Outputs |
|---|---|---|---|---|
| `scripts/paper_trade_monitor.py` | **Primary active stop manager** — adjusts stops on Alpaca, closes at target, tracks MFE/MAE | `*/5 9-16 * * 1-5` (every 5 min) | Alpaca positions API, `paper_trades` table | Stop orders to Alpaca API, `paper_trades` update, `agent_curation_events` log |
| `scripts/open_trade_monitor.py` | **Secondary monitor** — alerts, time stops, news auto-close, near-stop Telegram buttons | `*/2 9-16 * * 1-5` (every 2 min, but actually 15 min per crontab) | `paper_trades`, `trade_ai_scans` (prices), `news_articles` | `open_trade_alerts`, `paper_trade_risk_actions`, `agent_curation_events`, Telegram with buttons |
| `scripts/trailing_stop_analyzer.py` | **Post-trade learning** — simulates 5/8/10/15% trails on closed trades, generates LLM lessons | On-demand / API trigger | Alpaca OHLC bars, `paper_trades` (closed) | `trailing_stop_analysis` table |
| `scripts/stop_decision_brief.py` | **Alert narrative generator** — LLM-synthesized stop decision briefs | Triggered by `portfolio_alerts.py` | Holdings, news, technicals, sector context | Telegram brief + saved state |
| `scripts/stop_alert_assembler.py` | **Data assembly** — enriches stop alerts with tax lots, P&L scenarios, sector context | Called by alert pipeline | Internal APIs (risk, holdings) | Structured data dict (no side effects) |
| `scripts/portfolio_stops.py` | **Portfolio-level stops** — manages stops.json for live portfolio holdings (Schwab/etc.), not paper trades | Scheduled separately | `data/portfolios/state/` JSON files | stops.json updates, Telegram alerts |
| `scripts/open_trade_manager.py` | **Due diligence engine** — generates order modification proposals requiring admin approval | On-demand | Quote freshness, RSI, news, thesis | Proposals with confidence scores |

### Overlap and Responsibility Split

```
paper_trade_monitor.py          open_trade_monitor.py
├── Reads: Alpaca positions API  ├── Reads: paper_trades table
├── R-multiple trailing stops    ├── R-multiple trailing stops (SAME LOGIC)
├── Near-target tightening       ├── Near-stop/near-target ALERTS
├── Places/replaces Alpaca stops ├── Places/replaces Alpaca stops
├── Closes at target             ├── Closes at stop hit, time stop, critical news
├── MFE/MAE tracking             ├── Stale trade detection
└── Post-close analysis trigger  └── Telegram buttons (stopout/trail/hold)
```

**Key concern**: Both scripts can modify stops on Alpaca. They run on different
schedules (5 min vs 2/15 min) and could potentially race. In practice, both use
the same R-multiple thresholds and both only move stops UP, so a race would at
worst result in a redundant cancel+replace.

---

## Decision Logic

### R-Multiple Trailing Stop State Machine (both monitors)

```
                              ┌──────────────┐
                              │  FIXED STOP  │
                              │ (initial)    │
                              └──────┬───────┘
                                     │ R ≥ 1.0
                              ┌──────▼───────┐
                              │  BREAKEVEN   │
                              │ stop = entry │
                              └──────┬───────┘
                                     │ R ≥ 1.5
                              ┌──────▼───────┐
                              │  LOCK 0.5R   │
                              │ stop = entry │
                              │   + 0.5×risk │
                              └──────┬───────┘
                                     │ R ≥ 2.0
                              ┌──────▼───────┐
                              │  LOCK 1.0R   │
                              │ stop = entry │
                              │   + 1.0×risk │
                              └──────┬───────┘
                                     │ R ≥ 3.0
                              ┌──────▼───────┐
                              │  LOCK 2.0R   │
                              │ stop = entry │
                              │   + 2.0×risk │
                              └──────────────┘

    At any point: if price ≥ 80% of target move → NEAR_TARGET tightening
                  (stop moves to lock 65% of the entry→target move)
                  [paper_trade_monitor.py only, lines 255-265]

    Stops NEVER move down. Each tier supersedes the previous.
```

### Time Stop Logic (open_trade_monitor.py only)

| Strategy Type | Time Stop Rule |
|---|---|
| `momentum_scalp`, `gap_and_go` | Auto-close at 3:45 PM ET |
| `swing_breakout`, `swing_trade` | Auto-close after 21 days |
| `earnings_catalyst` | Auto-close after 7 days |
| `speculative_growth` | Auto-close after 21 days |
| `sector_rotation`, `defense_thesis` | Auto-close after 56 days |
| `core_growth_compounder`, `dividend_growth_compounder`, `reit_income`, etc. | No time stop (None) |

### Critical News Auto-Close (open_trade_monitor.py only)

Keywords: `SEC halt`, `trading halt`, `bankruptcy`, `delisting`, `going concern`,
`fraud investigation`, `Chapter 11`, `Chapter 7`. Triggers immediate position
liquidation via Alpaca `DELETE /v2/positions/{symbol}`.

---

## LLM Involvement

| Component | LLM Used | When Called | Model | Purpose |
|---|---|---|---|---|
| `trailing_stop_analyzer.py` | Yes | Post-trade (closed trades only) | `qwen3:14b` via Ollama | Generate 2-3 sentence lesson on stop placement |
| `stop_decision_brief.py` | Yes | When portfolio stop alert triggers | Local LLM via `local_llm_config` | Generate narrative decision brief (HOLD/HONOR_STOP/PARTIAL_TRIM) |
| `paper_trade_monitor.py` | **No** | N/A | N/A | Pure math R-multiple logic |
| `open_trade_monitor.py` | **No** | N/A | N/A | Pure math R-multiple logic |

**Key insight**: The two scripts that actually move stops are pure math. LLMs are
only involved in advisory/narrative roles (post-trade lessons, stop alert briefs).
No LLM is in the live stop adjustment loop.

---

## Audit Trail

| Table | Per-decision row? | Fields captured | Retention |
|---|---|---|---|
| `paper_trade_risk_actions` | Yes — one row per stop change, close, time stop | `paper_trade_id, symbol, action_type, old_value, new_value, trigger_price, trigger_reason, broker_order_updated, action_result` | Permanent |
| `agent_curation_events` | Yes — one row per non-hold action | `event_type` (e.g. MONITOR_ADJUST_STOP), `event_summary`, `payload` (JSON with action, price, stop, new_stop, r_multiple, pnl, mfe, mae) | Permanent |
| `open_trade_alerts` | Yes — one per alert (deduplicated) | `trade_id, symbol, strategy_id, alert_type, severity, title, message` | Permanent |
| `trailing_stop_analysis` | One per closed trade | `trade_id, symbol, strategy_id, entry/stop/exit, trail simulation results at 4 pct levels, recommendation, lesson_text` | Permanent |
| `stop_decisions` | Per human override only | `symbol, decision, decided_by, notes` | Permanent (7 rows exist) |
| `paper_trades` columns | Inline — current state only | `stop_loss, stop_loss_price, max_favorable_excursion, max_adverse_excursion, r_multiple` | Overwritten each cycle |

### Audit Trail Assessment

**Strengths**: Every stop adjustment is logged in `paper_trade_risk_actions` with
old/new values and trigger reason. `agent_curation_events` provides a secondary
log with richer payload (R-multiple, P&L, MFE/MAE at decision time).

**Weakness**: `paper_trades.stop_loss` is overwritten in place — there's no
historical column showing the stop trajectory. The full history requires joining
`paper_trade_risk_actions` by `paper_trade_id` and ordering by `created_at`.

---

## Gap Analysis

| Capability | Status | Evidence | Recommended Fix |
|---|---|---|---|
| **Rule-based stop transitions** | **EXISTS** | R-multiple tiers in both monitors (1R→BE, 1.5R→0.5R lock, 2R→1R lock, 3R→2R lock) + near-target tightening | Working as designed |
| **Per-decision audit log** | **EXISTS** | `paper_trade_risk_actions` + `agent_curation_events` log every adjustment | Add `stop_state` column to paper_trades for current-state queries without joining |
| **LLM-augmented decisions** | **PARTIAL** | Post-trade lessons (trailing_stop_analyzer) and alert briefs (stop_decision_brief) exist, but neither feeds into the live monitors | Consider: LLM "trend intact?" check before tightening at +2R |
| **Position-side state machine** | **MISSING** | No `stop_state` enum (FIXED/BREAKEVEN/TRAILING_0.5R/etc.). State is implicit from comparing stop_loss vs entry_price. Both monitors recompute from scratch each cycle. | Add `stop_state` column to `paper_trades` to eliminate recomputation and enable state-transition logging |
| **Strategy-specific stop rules** | **MISSING at runtime** | YAML configs define `stop_method` (fixed_pct, level_based, fundamental), `trail_method` (ema_21), `stop_max_pct` — but monitors hardcode identical R-multiple tiers for all strategies | Read strategy YAML at runtime; apply per-strategy thresholds |
| **End-of-day behavior** | **PARTIAL** | Intraday strategies (momentum_scalp, gap_and_go) force-close at 3:45 PM. Swing strategies have max-hold-day time stops. No EOD tightening for non-intraday. | Consider: tighten stops to breakeven for swing trades at 3:50 PM if R > 0.5 |
| **Backtest replay capability** | **PARTIAL** | `trailing_stop_analysis` simulates 4 fixed-pct trails on closed trades. Cannot replay the actual R-multiple logic against historical bars. | Build R-multiple replay simulator using OHLC bars, analogous to trailing_stop_analyzer |
| **Broker-side stop sync** | **EXISTS with gaps** | Both monitors submit stop orders to Alpaca via cancel+replace. But 3 of 9 closed trades show `exit_reason='position_closed_in_alpaca'` — Alpaca hit the stop but the system didn't see it in real-time, only discovered it later via phantom check / alpaca_sync. | Add webhook listener for Alpaca order fills, or poll more frequently for stop-hit events |

### The "broker close" Hole — Detailed Finding

Three closed trades exited with reasons indicating the system learned about the
close after the fact:

| Trade | Exit Reason | Closed Via | What Happened |
|---|---|---|---|
| #1 SMX | `cancelled_never_submitted_to_broker` | (none) | Orphan — never reached Alpaca |
| #2 MNKD | `cancelled_never_submitted_to_broker` | (none) | Orphan — never reached Alpaca |
| (various) | `position_closed_in_alpaca` | `alpaca_sync` / `monitor_phantom_check` / `manual_audit` | Alpaca stop triggered, system discovered position gone on next sync cycle |

The `position_closed_in_alpaca` cases mean: Alpaca's stop order fired between
monitor cycles, position was liquidated, and the next monitor run found the position
missing from Alpaca and reconciled. This creates a gap where the system doesn't know
the exact exit price or time from Alpaca — it discovers the absence and infers.

**Impact**: Exit price logging may be inaccurate for these trades (system uses
last-known price rather than actual fill price). P&L and R-multiple calculations
could be off.

---

## Strategy Config vs Runtime Reality

The strategy YAML configs define rich stop/trail configuration that the runtime
completely ignores:

| Strategy | YAML Config | Runtime Reality |
|---|---|---|
| `momentum_scalp` | `stop_method: fixed_pct`, `stop_max_pct: 0.15` | Same R-multiple tiers as everything else |
| `dividend_growth_compounder` | `stop_method: fundamental` | Same R-multiple tiers |
| `swing_breakout` | `stop_method: level_based`, `stop_at: base_low`, `trail_method: ema_21` | Same R-multiple tiers |
| `reit_income` | (not checked, likely has config) | Same R-multiple tiers |
| `core_growth_compounder` | (not checked, likely has config) | Same R-multiple tiers, no time stop |

**Gap**: The YAML configs represent John's intended design. The monitors implement
a simpler one-size-fits-all approach. Bridging this gap is a major v2 opportunity.

---

## "Trail:" Label in the UI — How It Works

The "Trail: Keep fixed stop — Keep fixed stop (avg max potential +2.0%)" label
shown in the Trade Journal UI is generated by a chain:

1. `trailing_stop_analyzer.py` → runs post-trade on closed trades for each strategy
2. `get_strategy_trail_recommendations()` → aggregates recommendations by strategy_id
3. `api_v2.py` line 14710-14715 → reads the strategy-level recommendation
4. If recommendation is `keep_fixed` → displays "Keep fixed stop (avg max potential +X%)"
5. If recommendation is `use_trail_Xpct` → displays "Consider X% trailing stop (+Y% vs fixed)"
6. `OpenTradesCard.tsx` line 102 → renders the label

**This is advisory only** — based on historical analysis of closed trades for
that strategy. It does NOT drive the live stop monitor. The live monitors always
use R-multiple tiers regardless of this recommendation.

---

## Specific Questions for John to Answer Before Building

1. **Should strategy YAML stop configs drive runtime behavior?**
   The configs already define `stop_method` (fixed_pct, level_based, fundamental)
   and `trail_method` (ema_21) per strategy. Should the monitors read and enforce
   these, or continue using universal R-multiple tiers?

2. **Should momentum_scalp move to breakeven at +0.5R or +1.0R?**
   Current: +1.0R for all strategies. Scalps have shorter life and tighter risk —
   earlier breakeven may be appropriate.

3. **Should an LLM evaluate "is the trend still intact?" before tightening?**
   Current: pure math. Adding an LLM check (e.g. "RSI still above 50, MACD still
   bullish") before locking profit could prevent premature tightening on pullbacks.
   Trade-off: adds latency and complexity to the 5-min cycle.

4. **Should EOD tighten stops for swing trades?**
   Current: no EOD behavior for non-intraday strategies. Could tighten to breakeven
   at 3:50 PM for swing trades with R > 0.5 to reduce overnight risk.

5. **Should the system use Alpaca websockets for real-time stop-hit detection?**
   Current: poll-based (every 2-5 min). 3 trades were discovered closed after the
   fact. Websockets would provide immediate notification of stop fills.

6. **Should the trailing_stop_analyzer recommendations feed back into live monitors?**
   Current: advisory only, shown in UI. Could automatically switch from R-multiple
   to percentage-based trailing when the analyzer has enough data for a strategy.

7. **For the 3 "position closed in Alpaca" exits — should the system attempt to
   fetch the actual Alpaca fill price and timestamp retroactively?**
   Current: uses last-known price. Alpaca's order history API could provide the
   actual fill data for more accurate P&L.

---

## Verification Checklist

- [x] IRON RULE state check passed at start (ATM mode: active)
- [x] All stop-management files identified and mapped (7 files)
- [x] Audit trail confirmed: `paper_trade_risk_actions` + `agent_curation_events`
- [x] Per-strategy logic: EXISTS in YAML configs, MISSING at runtime
- [x] LLM involvement: post-trade only (qwen3:14b in trailing_stop_analyzer, local LLM in stop_decision_brief)
- [x] Broker-close hole investigated: 3 trades discovered closed after the fact via phantom check/sync
- [x] Discovery doc written

---

*Investigation performed: 2026-05-23*
*ATM mode: active (not modified during investigation)*
*Read-only session — no code changes made*
