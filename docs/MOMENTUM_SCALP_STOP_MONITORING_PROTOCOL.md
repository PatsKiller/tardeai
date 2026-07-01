# Stop Monitoring & Adjustment Protocol

**Status:** Active (2026-06-30) · **Owner:** operator (advisory system; nothing here auto-submits a broker order)
**Related:** [`MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md`](MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md) ·
[`STOP_METHODOLOGY.md`](STOP_METHODOLOGY.md) · [`runbooks/protective-stop-integration-2026-06-30.md`](runbooks/protective-stop-integration-2026-06-30.md)

This protocol governs how the system **monitors** every protective stop from placement to trade close, **alerts**
the operator when a stop needs attention (Yellow / Amber / Red), and how stops are **readjusted**. It powers the
Portfolio → **Stop Management** tab and the `/api/v2/stops/management` aggregation.

Scope is **all open positions with a stop** across the four accounts (Fidelity 401k, Schwab Rollover IRA, Schwab
Roth IRA, Schwab Taxable) plus the Alpaca paper account. Momentum-Scalp / Social-Route trades are a first-class
subset that carries extra route + freshness columns.

---

## 1. Scope — stop types monitored

| Stop type | Description | Where it lives |
|---|---|---|
| **Hard stop** | Fixed price; does not move. Advisor default for core holds. | broker STOP order / advisory |
| **Trailing stop** | Ratchets up with price by a % width; never lowers. | broker TRAILING_STOP / monitored |
| **Breakeven stop** | Hard stop moved to entry once a position is in profit. | broker STOP at entry |
| **Limit-based exit** | Take-profit limit (or the limit leg of a stop-limit / OCO). | broker LIMIT / OCO leg |

Two truths are tracked per position and shown side-by-side when they diverge:
- **Broker actual** — what is actually resting at the broker (Schwab / Alpaca), read back and verified. Source of truth.
- **Journal / advisor planned** — what the operator intended or the advisor recommends (family-band % + swing-low anchor).

A divergence (planned stop exists but no broker stop, or broker stop ≠ planned) is itself an alert condition (§3).

---

## 2. Monitoring lifecycle

```
PLACED → ACTIVE → [TRAIL-ELIGIBLE] → TRAILING → NEAR-STOP → TRIGGERED/CLOSED
                         │                                        │
                    (should trail,                          (broker read-back
                     not yet active)                         confirms exit)
```

- **PLACED** — a broker stop is confirmed via read-back (never assumed from the POST response).
- **ACTIVE** — resting; proximity and coverage tracked every scan.
- **TRAIL-ELIGIBLE** — the trailing policy says the stop *should* be trailing (profit ≥ family threshold, price > 50d SMA)
  but the resting order is still a fixed stop → surfaced as "trailing not active."
- **TRAILING** — the stop ratchets with price.
- **NEAR-STOP** — price within the Amber/Red proximity band (§3); the trade is close to stopping out.
- **TRIGGERED / CLOSED** — broker shows the stop filled; the position moves to the stopped-out review + re-entry watch.

Backend: `stop_lifecycle_monitor.scan()` produces per-position `{proximity_pct, coverage, is_trailing, lifecycle,
health, flags}`; `/api/v2/stops/management` joins it with holdings, advisories, and portfolio heat.

---

## 3. Alerting framework (Yellow / Amber / Red)

Alert level is the **highest** severity any trigger fires. Rules are advisory — they never move a stop by themselves.

> **Distance metric — what actually drives severity.** The primary distance signal is **percent to stop**
> (`distance_% = (price − stop) / price × 100`), which is reliable for every position. **ATR** (`(price − stop) / ATR`)
> adds a volatility-aware Amber signal when an advisor ATR is available. **R** (`(price − stop) / (basis − planned_stop)`)
> is **displayed for context but not used to set severity** — the advisor `basis_ps` is not a dependable per-lot cost
> basis, so an R band would misfire. The `%` thresholds below are calibrated so a typical stop (~1R ≈ 3–5% for these
> families) lands in the intended bucket. "Naked" (advised stop, no active broker/monitored stop) is Amber for active
> momentum/social trades but only Yellow for long-term core holds (monitored-by-advisory is normal there).

### 🟡 Yellow — watch
Any one of:
- **Distance to stop ≤ 6%** of price (comfortable, but worth watching).
- **Trailing not active**: the advisor recommends trailing (P&L ≥ family threshold **and** price > 50d SMA per
  `STOP_METHODOLOGY.md`) but the resting stop is still fixed — surfaced as the 🔒 Trail action.
- **Core hold naked**: a long-term core hold has an advised stop but no active broker/monitored stop.
- *(scalps)* last quote/technical older than the scalp freshness SLA but < 2× SLA.

### 🟠 Amber — needs attention
Any one of:
- **Distance to stop ≤ 3%** of price, **OR** price within **1.0×ATR** of the stop.
- **Active-trade naked**: a momentum/social trade has an advised stop but **no active stop placed**.
- **Broker looser than advised**: the resting broker stop sits below the advised family floor.
- **Portfolio-heat contribution ≥ 1.5%** of portfolio heat.
- *(scalps)* quote/technical older than **2× the scalp SLA**.

### 🔴 Red — act now
Any one of:
- **Distance to stop ≤ 1.5%** of price — imminent stop-out.
- **Active-trade naked in a downgraded regime**: no active stop AND regime is risk-off.
- **Portfolio-heat breach**: total portfolio heat > the heat cap (default 5%) AND this position contributes ≥ 1.5%.
- **Kill-switch / data gaps**: broker unreadable, quote stale + unparseable, or evidence store unavailable (fail-closed).

Distance to stop is sourced from active stops in priority order: **live broker read → last broker snapshot →
operator-confirmed → Fidelity monitored → advisor-planned** (so after-hours coverage is complete). Alert reasons
(what fired) are shown inline per row.

---

## 4. Readjustment rules & workflow

Adjustments are **operator-driven**: the rules engine *suggests*, the operator *applies*. There is no autonomous
stop movement on real accounts (Alpaca paper is auto-managed separately by `alpaca_stop_manager`). Every real-account
change routes through the existing evidence-bound + per-order 2FA protective-stop path and is read-back verified.

| Situation | Suggested action | One-click |
|---|---|---|
| Position ≥ +1R and stop still below entry | **Move to breakeven** (stop → entry) | ✅ |
| TRAIL-ELIGIBLE but fixed stop resting | **Switch to trailing** at the advised family width | ✅ |
| Volatility contracted, giving back too much room | **Tighten by 0.5× ATR** | ✅ |
| Social-Route conviction / wider structure | **Widen for Social Route** (within family cap) | ✅ |
| Advised stop above the resting stop (ratchet) | **Raise stop** to the advised level | ✅ (via drift alert) |

The Adjust modal shows the current stop, the **suggested** new stop with its reasoning (family band, swing-low anchor,
ATR, R-multiple), and lets the operator apply the suggestion or enter a custom price. Custom prices are still bounded
by the family floor/cap and the "never above current price for a long" invariant.

**Adjustment history is append-only:** every change records `{previous_value, new_value, changed_by, changed_at,
reason}` so the tab can show "Last adjusted … because …".

---

## 5. Integration with existing components

- **Journal tags** — route (Pure Momentum / Social+Momentum), setup tag, and planned stop come from the journal /
  strategy classification; shown as columns and filters.
- **AI Trade Critique** — stop-discipline findings (e.g. "stop too tight for the setup", "gave back > 1R") surface as
  row annotations and feed the closed-loop lessons.
- **Regime detection** — the current risk regime vs the regime at entry drives the Amber "regime shift" trigger.
- **Portfolio heat / open risk** — `portfolio_heat_pct` + `total_risk_dollars` drive the heat cards and the heat-breach
  Red trigger; each row's `$ at risk = (current_price − stop) × qty` rolls up to Total Open Risk.
- **Freshness SLA** — the momentum-scalp quote/technical freshness SLA drives the scalp freshness triggers; the
  session-aware quote freshness (regular 15m / extended 60m) drives the "refresh before acting" state.

---

## 6. Data model — fields per active stop

Aggregated read-only by `/api/v2/stops/management` (no new table required for v1; sourced from `stop_lifecycle`,
holdings, `hermes_research_intelligence` protection advisories, and risk metrics):

| Field | Meaning |
|---|---|
| `symbol`, `account`, `broker` | position identity |
| `route` | Pure Momentum / Social+Momentum / core-hold |
| `stop_type` | HARD / TRAILING / BREAKEVEN / LIMIT |
| `broker_stop`, `planned_stop`, `divergence` | actual vs planned + flag |
| `current_price`, `qty`, `held_qty`, `coverage` | position + how much the stop covers |
| `distance_r`, `distance_atr`, `distance_dollars` | distance to stop in three units |
| `unrealized_r`, `unrealized_dollars` | open P&L |
| `dollars_at_risk` | `(current_price − stop) × qty` |
| `time_in_trade`, `last_adjusted_at`, `last_adjusted_reason` | lifecycle timing |
| `alert_level`, `alert_reasons[]` | 🟡/🟠/🔴 + which triggers fired |
| `trailing_should_be_active` | TRAIL-ELIGIBLE but fixed |
| `regime_at_entry`, `regime_now` | regime shift detection |
| `heat_contribution_pct` | share of portfolio heat |
| `freshness_sec`, `quote_session` | scalp freshness / session |

Adjustment history rows: `{symbol, account, previous_stop, new_stop, changed_by, changed_at, reason}`.

---

## 7. Escalation & kill-switch

- **Escalation:** any 🔴 that persists across two consecutive scans, or a naked position in a risk-off regime, escalates
  to the operator via the existing SIEM + Telegram path (`stop_drift_alert` / `protection_alerts`). Amber/Red counts
  surface on the Stop Management summary cards and the Home briefing.
- **Kill-switch (fail-closed):** if the broker is unreadable, the evidence store is down, or execution_state blocks the
  operator-2FA path, the tab marks affected rows **Red / BLOCKED** and disables their live-adjust buttons with the exact
  reason. Nothing is auto-submitted. Real-account adjustments always require operator click + per-order 2FA + read-back;
  `OCO_BRACKETS_SCHWAB` stays OFF; Fidelity remains manual-ticket only.

---

## 8. Operator quick reference

1. Open **Portfolio → Stop Management**. Scan the summary cards (Total Open Risk, 🟡/🟠/🔴 counts, heat, trailing-not-active).
2. Use the **Needs Attention** quick view (Amber + Red). Work top-down by severity.
3. For each flagged row, open **Adjust Stop** → review the suggested stop + reasoning → apply or set custom.
4. Real-account changes: confirm whole-share, (after-hours) acknowledge, click once, complete per-order 2FA, wait for read-back.
5. Naked positions (planned stop, no broker stop) are Amber/Red — place the protective stop first.
