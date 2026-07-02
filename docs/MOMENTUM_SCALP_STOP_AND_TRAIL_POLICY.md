# Momentum Scalp — Stop & Trailing-Stop Policy

**Version:** 1.0  
**Effective Date:** 2026-06-29  
**Maturity Gate:** 4.4 → 4.5 (Paper-Trade Validation Required)  
**Owner:** Trade AI v12 – Momentum Scalp + Social Route  
**Last Updated:** 2026-06-30  
**Status:** Production Policy – Paper Trading Phase (advisory/logic only; no auto-broker writes until 4.5+)

> **Scope split:** This policy governs `momentum_scalp` and Social Route **paper trades**. Real-account **holdings** protective stops are governed separately by [`STOP_METHODOLOGY.md`](STOP_METHODOLOGY.md). Options spreads use the options desk policy.

> **Monitoring & alerting:** Once a stop is placed (paper or real), its lifecycle, Yellow/Amber/Red alerting, and readjustment workflow are governed by [`MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md`](MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md), surfaced in the Portfolio → **Stop Management** tab (`/api/v2/stops/management`).
>
> **Regime detection (Layer 4):** Per-symbol regime classification and dynamic stoplight R-thresholds are defined in [`MOMENTUM_SCALP_REGIME_DETECTION_ALGORITHM.md`](MOMENTUM_SCALP_REGIME_DETECTION_ALGORITHM.md) (`config/momentum_scalp_regime.yaml`, `scripts/lib/momentum_scalp_regime.py`).

> **Reconciliation note (2026-06-29):** Layer 3 (Chandelier/ATR trailing) remains **config-OFF for execution** pending paper validation. Our own backtests show trailing truncates the momentum fat tail (see §2). Layers 1–2 and 4 are **active**.

---

## 1. Purpose & Scope

This policy defines the standardized methodology for **initial stop placement**, **breakeven management**, **trailing stop activation**, and **real-time stop monitoring** for all Momentum Scalp and Social Route trades executed within the Trade AI v12 system.

**In Scope:**
- All `manual_scalp` and momentum continuation setups
- Social Route + Momentum hybrid signals
- Paper trading validation phase (target: 150+ closed trades)
- Integration with tagging, replay, AI Trade Critique, and portfolio risk modules

**Out of Scope:**
- Swing / position trading (separate policy — [`STOP_METHODOLOGY.md`](STOP_METHODOLOGY.md))
- Options spreads and multi-leg strategies (separate policy)
- Live broker execution (this policy governs logic only; no auto-broker writes until 4.5+)

---

## 2. Research & Industry Basis

This policy is grounded in empirical research and professional practice:

- **Chuck LeBeau** – Chandelier Exit (Highest High – 3× ATR, 22-period). Proven to let winners run while protecting profits.
- **Kaminski & Lo (2014)** and momentum crash literature – Volatility-adjusted stops significantly outperform fixed-percentage stops.
- **Lund University / Quant studies** – ATR-based trailing stops improve risk-adjusted returns (Sharpe) and reduce maximum drawdown vs static stops.
- **TradeZella / TradesViz** production systems – Context-aware stops (regime + setup + freshness) outperform one-size-fits-all rules.
- **Prop trading desk practice** – Breakeven move at +1.0R to +1.5R is near-universal for scalping books. Portfolio heat monitoring is mandatory above 3–4% open risk.

**Key Finding:** Stops must be **context-aware** (setup tag, regime, signal freshness, route type). Rigid stops destroy edge in momentum scalping.

### 2.1 System prior — backtest gate (material reconciliation)

**However — this system already tested trailing.** `scripts/backtest_hybrid_stops.py` (STOP-V2.4, 2026-06-13) backtested the MA-trend filter + **Chandelier** + dynamic-ATR overlay and returned **"HOLD — hybrid does not clearly beat the R-multiple; keep config OFF."**

**Phase 2 re-test (2026-06-29) — FAIL GATE.** `backtest_hybrid_stops.py --mode ctx` (130 baseline vs 159 ctx trades over V/RTX/LMT/NOC/GD/PLTR/NVDA/AMD, 3y) found the layered trailing — *with* L2 breakeven + delayed +1.5R activation + regime-aware multiplier — produced **Δ expectancy = −0.451R/trade vs the no-trail baseline** (ctx +0.645R vs baseline +1.096R). It raised win rate (40.9% vs 23.8%) but **truncated the fat right-tail** the momentum edge depends on.

**Param sweep (27 configs):** init-mult {1.0,1.5,2.0} × activation {1.0,1.5,2.5}R × regime-multiplier {tight,mid,wide} — **0 passed**; every config net-negative (best −0.13R).

**Consequently:**
- **Layers 1–2 + 4** (initial stop, breakeven, portfolio risk) — **ACTIVE**
- **Layer 3** (Chandelier/ATR trailing) — **config-OFF** for execution; computed + tagged + monitored in *advisory/paper* mode only. Re-enable only if the intraday micro-cap paper sample (§6) overturns this prior.

---

## 3. Layered Stop Methodology (Mandatory)

All momentum scalps must follow this **4-layer** structure.

### Layer 1: Initial Hard Stop (at Entry) — **ACTIVE**

**Primary Rule:** Structure + ATR Hybrid

- Place stop just beyond the most recent significant swing low (longs) or swing high (shorts) **OR** 1.0–1.5× ATR(14) from entry price, whichever is **tighter**.
- **Pure Momentum Scalp / Low Freshness (< 45s):** Use 0.8–1.0× ATR (tighter protection).
- **Social Route + Strong Momentum / High RVOL:** Allow up to 1.5–2.0× ATR.
- **Maximum Risk:** Never exceed **1.2R** on any single momentum scalp.

**Tagging Requirement:**
- Record in journal: `initial_stop_type` (structure | atr | hybrid) — stored as `initial_stop_method`
- Record: `initial_stop_distance_atr` — stored as `initial_stop_atr`
- Record: `initial_risk_r` (must be ≤ 1.2) — enforced via `dollar_risk` + `max_initial_risk_r` in YAML

**Config:** `config/strategies/momentum_scalp.yaml` → `exit_rules.layered_stop.layer1_initial`

### Layer 2: Breakeven / Profit Protection Trigger (Mandatory) — **ACTIVE**

- **Trigger:** Move stop to breakeven (or +0.3R) once unrealized P&L reaches **+1.0R to +1.5R**.
- This step is **non-negotiable** for all momentum scalps.
- **Social Route High-Conviction Exception:** May delay breakeven move until +2.0R (must be tagged).

**Tagging Requirement:**
- Record: `breakeven_trigger_r` (actual R at which BE was moved)

**Config:** `exit_rules.layered_stop.layer2_breakeven` (`trigger_r: 1.2`)

### Layer 3: Trailing Stop Activation & Rules — **GATED (advisory only)**

> **Execution OFF** until §6 validation passes. Advisory/replay computes what trailing *would* have done.

**Activation Condition:**
- Trailing stop logic activates only **after** breakeven is secured **and** price has reached at least **+1.5R to +2.0R** profit.
- Do **not** trail too early — this is the most common cause of premature stop-outs on momentum scalps.

**Primary Trailing Method: Modified Chandelier Exit (Context-Aware)**

**Longs:**
```
Trail Price = Highest High since trail activation – (ATR(14) × Multiplier)
```

**Shorts:**
```
Trail Price = Lowest Low since trail activation + (ATR(14) × Multiplier)
```

**Multiplier Table (Tag-Driven)**

| Setup / Regime                    | Recommended Multiplier | Notes |
|-----------------------------------|------------------------|-------|
| Pure Momentum Scalp               | 1.5x – 2.0x           | Tighter trail to protect quick gains |
| Social Route Confirmed            | 2.5x – 3.5x           | Higher edge expected — let it run |
| Ranging / Low Freshness           | 1.0x – 1.5x           | Aggressive protection |
| Strong Trending (RVOL > 1.8)      | 3.0x – 4.0x           | Classic Chandelier – capture runners |
| High Portfolio Heat (> 3.5%)      | Reduce by 0.5x        | Global tighten rule |

**Alternative Method (when simpler is preferred):**
- Pure ATR Trailing Stop (no Chandelier highest-high logic) — use when price action is choppy.

**Tagging Requirement:**
- Record: `trail_multiplier_used`, `trail_activation_r`

**Config:** `exit_rules.layered_stop.layer3_trailing.enabled: false` (params retained for advisory/replay)

### Layer 4: Dynamic / Portfolio-Level Adjustments — **ACTIVE (advisory)**

**Mandatory Adjustments:**

1. **Regime Shift Rule**
   - If regime detection changes from **Trending → Ranging** while in a trade → immediately tighten active trail by **0.5× ATR**.

2. **Portfolio Heat Rule**
   - If aggregate open risk across all momentum scalps exceeds **3.5–4.0%** of account equity → automatically tighten **all** active trails by 0.5× ATR and pause new entries.

3. **Freshness Decay Rule**
   - If signal freshness > 90 seconds at entry and price has not moved favorably by +0.8R within 60 seconds → move to breakeven immediately and tighten trail.

4. **Social Route Override**
   - High-conviction Social signals (tagged) may use the wider multiplier band (2.5x–3.5x) even in moderate heat.

---

## 4. Monitoring & Real-Time Stop Management

### Required Dashboard Metrics (per open trade)

- Current stop distance in **R** and in **ATR**
- Distance to breakeven trigger (R and time remaining)
- Distance to trail activation (R)
- Current MAE vs planned initial stop
- "Trail Tightness Score" (% distance from current price to trail line)
- Regime + Freshness status at entry vs current
- Portfolio heat contribution of this trade

**Implementation:** Risk tab → `ScalpStopMonitorCard` (`/api/v2/scalp/stop-monitor`, `scripts/scalp_stop_monitor.py`). Partial — core R metrics + alerts live; ATR distance, trail-tightness, and tighten-all action pending.

### Alerting Rules (Build into Risk / Monitoring Agent)

| Condition                              | Alert Level | Action |
|----------------------------------------|-------------|--------|
| Price within 0.3R of stop              | Yellow      | Notify operator |
| Trail should be active but is not (> +2R) | Amber    | Auto-suggest activation |
| Regime shift detected in trade         | Amber       | Auto-tighten trail 0.5× ATR |
| Portfolio heat > 3.5%                  | Red         | Global tighten + pause new entries |
| Freshness > 90s + no favorable move    | Red         | Force breakeven + tighten |

---

## 5. Journaling, Tagging & AI Critique Integration

Every closed momentum scalp **must** record:

- `initial_stop_type`, `initial_stop_distance_atr`, `initial_risk_r` — via `initial_stop_method`, `initial_stop_atr`, `dollar_risk`
- `breakeven_trigger_r` (actual)
- `trail_multiplier_used`, `trail_activation_r`
- `final_r_vs_planned_stop` (was final exit better/worse than planned stop?)
- `stop_quality_score` (operator or AI rated 1–5)

**Already on `paper_trades` (reuse, do NOT duplicate):** `max_adverse_excursion` (MAE), `max_favorable_excursion` (MFE), `market_regime`, `vix_at_entry`, `rvol_at_entry`, `planned_stop`, `current_stop`, `stop_type`, `trailing_active`, `trailing_policy_version`, `dollar_risk`, `signal_grade`, `bracket_state`, `oco_group_id`.

**Migration:** `scripts/migrate_momentum_scalp_stop_tagging.py` adds the policy-specific columns.

**AI Trade Critique Integration:**
The AI Critique must explicitly answer:
- Was the initial stop optimal relative to MAE?
- Did the trail activate at the correct profit level?
- What R-multiple was left on the table due to trail being too tight or too loose? (use actual post-exit replay data)
- Recommended stop/trail parameters for this exact setup + regime combination going forward

---

## 6. Validation Requirements (4.4 → 4.5 Gate)

To pass from Maturity 4.4 → 4.5, the following must be demonstrated via paper trading:

| Metric                              | Minimum Target          | Notes |
|-------------------------------------|-------------------------|-------|
| Closed paper trades                 | ≥ 150                   | Across ≥ 3 regimes |
| Social Route trades                 | ≥ 40                    | Minimum sample |
| Win Rate                            | ≥ 58%                   | — |
| Expectancy (net R)                  | ≥ +0.35R                | After slippage |
| Profit Factor                       | ≥ 1.65                  | — |
| Max Drawdown (paper account)        | ≤ 4.5%                  | — |
| Freshness Compliance                | ≥ 92%                   | Acted within SLA |
| Trail Activation Rate               | ≥ 85% of +2R winners    | Not left on table |
| Average R Improvement from Trailing | ≥ +0.25R on winners     | vs no-trail baseline |

**Statistical Requirement:**
- 95% confidence interval lower bound on expectancy must be **positive**.

**Tracker:** `scripts/scalp_stop_validation_tracker.py` — reports `INSUFFICIENT SAMPLE` until ≥150 closed trades. Current sample: ~3 closed (as of 2026-06-30).

---

## 7. Risk Limits & Kill Switches (Mandatory)

- Single trade max risk: **1.2R**
- Max concurrent momentum scalps: **3**
- Daily loss limit (momentum book): **3R** or **2.5%** of account (whichever is lower)
- Portfolio heat kill switch: Pause new entries at **4.5%** aggregate open risk
- Any trade hitting **–2.0R** without regime justification must be reviewed in next AI Critique

**Config:** `config/strategies/momentum_scalp.yaml` → `risk` block

---

## 8. Implementation Notes for Trade AI v12

### Immediate Actions (Paper Phase)

| # | Action | Status |
|---|--------|--------|
| 1 | Add journal fields listed in §5 | **Done** — `migrate_momentum_scalp_stop_tagging.py` |
| 2 | Build **Stop Intelligence** panel (Trade Detail / Replay) | **Done** — `scalp_stop_intelligence.py`, `StopIntelligencePanel.tsx`, `/api/v2/scalp/stop-intelligence` |
| 3 | Wire regime detection + freshness into trail adjustment logic | **Done (advisory)** — 2026-07-01: `scalp_stop_monitor.py` reads `market_regime_snapshots.regime_label`; entry-Trending→now-Ranging emits a regime-shift **amber** alert + a 0.5× ATR tighten SUGGESTION (`layer4_dynamic.regime_shift_tighten_atr`) |
| 4 | Add "Tighten All Trails" one-click action in Risk dashboard when heat is high | **Done (paper)** — 2026-07-01: `POST /api/v2/scalp/tighten-all` (`scalp_stop_monitor.tighten_all`) + button in `ScalpStopMonitorCard`; dry-run→confirm→apply; PAPER momentum_scalp only, advisory for non-paper, no broker order. Heat tier at `portfolio_heat_tighten_pct: 3.5` (§4 Red) distinct from the 4.5% kill |
| 5 | Monitoring metrics + alerts (§4) in Risk tab | **Done** — 2026-07-01: added stop-distance-ATR + Trail-Tightness Score (% price→stop) + regime-shift flag + pause-new-entries to `scalp_stop_monitor.py` / `ScalpStopMonitorCard.tsx` |
| 6 | `momentum_scalp.yaml` exit_rules → layered methodology | **Done** — L3 behind `enabled: false` gate |
| 7 | Re-backtest harness (context-aware multipliers) | **Done** — FAIL gate; see §2.1 |
| 8 | Validation Tracker (§6 metrics) | **Done** — `scalp_stop_validation_tracker.py` |
| 9 | AI Trade Critique stop-discipline questions | **Done** — journal critique prompt extended |

### Future (Post 4.5)

- Optional automated trail adjustment (operator approval required initially)
- Stop quality scoring model trained on tagged outcomes

---

## 9. Cross-References

| Resource | Path |
|----------|------|
| Strategy config | `config/strategies/momentum_scalp.yaml` |
| Backtest harness | `scripts/backtest_hybrid_stops.py` |
| Open-scalp monitor | `scripts/scalp_stop_monitor.py` |
| Stop Intelligence replay | `scripts/scalp_stop_intelligence.py` |
| Validation tracker | `scripts/scalp_stop_validation_tracker.py` |
| Journal migration | `scripts/migrate_momentum_scalp_stop_tagging.py` |
| Trailing policy (holdings) | `scripts/strategy_trailing_policy.py` |
| Trail calculator | `scripts/protection_trail_calculator.py` |
| Risk tab UI | `apps/command-center-v3/src/components/ScalpStopMonitorCard.tsx` |
| Trade detail UI | `apps/command-center-v3/src/components/StopIntelligencePanel.tsx` |
| Holdings stop policy | [`STOP_METHODOLOGY.md`](STOP_METHODOLOGY.md) |
| Scalp lifecycle | [`diligence/current/MOMENTUM_SCALP_LIFECYCLE.md`](diligence/current/MOMENTUM_SCALP_LIFECYCLE.md) |
| Validation ops | [`diligence/current/MOMENTUM_SCALP_VALIDATION_OPS.md`](diligence/current/MOMENTUM_SCALP_VALIDATION_OPS.md) |

---

## 10. Version History

| Version | Date       | Changes                                      | Author |
|---------|------------|----------------------------------------------|--------|
| 1.0     | 2026-06-29 | Initial policy — layered stops + context-aware trailing + monitoring framework; reconciled to as-built with L3 gated OFF | Grok (Trade AI v12) |
| 1.0.1   | 2026-06-30 | Full policy text added to `docs/`; implementation status table; cross-references | Operator docs sync |

---

**Approval Status:**  
Pending operator review and paper-trade validation completion.

**Next Review Date:** After 150 closed paper trades or 2026-07-31, whichever comes first.

---

*This policy replaces all previous ad-hoc stop rules for momentum scalps and Social Route paper trades.*