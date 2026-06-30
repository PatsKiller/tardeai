# Momentum Scalp — Stop & Trailing-Stop Policy

**Version:** 1.0 (reconciled to Trade AI v12 as-built) · **Effective:** 2026-06-29
**Maturity gate:** 4.4 → 4.5 (paper-trade validation required) · **Status:** Paper validation phase — **advisory/logic only, no auto-broker writes**
**Scope:** `momentum_scalp` + Social Route paper trades. Swing/position holdings are governed by [`STOP_METHODOLOGY.md`](STOP_METHODOLOGY.md); options by the options desk policy.

> Adapted from the research-backed policy draft (Grok, 2026-06-29) and **reconciled to what already exists** in the system, with one material change: the trailing-stop methodology is **gated on a fresh backtest** (see §2).

---

## 2. Empirical basis AND the prior that gates it

The draft cites LeBeau (Chandelier 22×3 ATR), Kaminski & Lo, momentum-crash literature, and prop practice — volatility-adjusted/trailing stops generally beat fixed stops.

**However — this system already tested it.** `scripts/backtest_hybrid_stops.py` (STOP-V2.4, 2026-06-13) backtested the MA-trend filter + **Chandelier** + dynamic-ATR overlay and returned **"HOLD — hybrid does not clearly beat the R-multiple; keep config OFF."** So the policy's Chandelier/ATR-multiplier core is exactly what our own data did *not* confirm.

**Decision (operator, 2026-06-29):** re-backtest the *layered, context-aware* version (tag/regime/freshness-driven multipliers — which STOP-V2.4 did **not** test) before any rollout.

**Phase 2 re-test result (2026-06-29) — FAIL GATE.** `backtest_hybrid_stops.py --mode ctx` (130 baseline vs 159 ctx trades over V/RTX/LMT/NOC/GD/PLTR/NVDA/AMD, 3y) found the layered trailing — *with* L2 breakeven + delayed +1.5R activation + regime-aware multiplier — produced **Δ expectancy = −0.451R/trade vs the no-trail baseline** (ctx +0.645R vs baseline +1.096R), with worse drawdown and profit factor. It *raised* win rate (40.9% vs 23.8%) but **truncated the fat right-tail** the momentum edge depends on. This **confirms STOP-V2.4** even with the policy's refinements. The §6 gate (≥ +0.25R from trailing) is **not met** (it's −0.45R).

Consequently:
- **Layers 1–2 + 4 (initial stop, breakeven, portfolio risk)** — adopt (they don't contradict the prior).
- **Layer 3 (Chandelier/ATR trailing)** — **stays config-OFF** for execution; computed + tagged + monitored in *advisory/paper* mode only. Re-enable consideration only if the **intraday micro-cap paper sample (§6)** — the definitive test, which the daily backtest cannot stand in for — shows a positive trailing edge. Prior evidence is now **doubly negative** (STOP-V2.4 + this layered re-test).

---

## 3. Layered methodology (4 layers)

### Layer 1 — Initial hard stop (at entry) — **ACTIVE**
- Structure + ATR hybrid: just beyond the recent swing low (long) / high (short) **or** 1.0–1.5× ATR(14), whichever is **tighter**.
- Pure momentum / low freshness (<45s): 0.8–1.0× ATR. Social Route + strong momentum/high RVOL: up to 1.5–2.0× ATR.
- **Max risk ≤ 1.2R** per scalp. Tag `initial_stop_method`, `initial_stop_atr`, `dollar_risk` (existing).

### Layer 2 — Breakeven / profit protection — **ACTIVE**
- Move stop to breakeven (or +0.3R) at **+1.0R–1.5R** unrealized (mandatory). Social high-conviction may delay to +2.0R (tagged). Tag `breakeven_trigger_r`.

### Layer 3 — Trailing activation — **GATED (advisory until re-backtest)**
- Activate only after breakeven AND **+1.5R–2.0R**. Modified Chandelier: `HighestHigh_since_activation − ATR×mult` (long).
- Context-aware multiplier (tag-driven): momentum scalp 1.5–2.0× · Social confirmed 2.5–3.5× · ranging/low-freshness 1.0–1.5× · strong trend (RVOL>1.8) 3.0–4.0× · high heat (>3.5%) reduce 0.5×. Tag `trail_multiplier_used`, `trail_activation_r`.
- **Execution stays OFF** until §6 validation passes; runs in advisory/replay so we measure what it *would* have done.

### Layer 4 — Dynamic / portfolio adjustments — **ACTIVE (advisory)**
- Regime Trending→Ranging (`market_regime`, existing): tighten trail 0.5× ATR. Portfolio heat > 3.5% aggregate open risk: tighten all trails 0.5× + pause new entries. Freshness >90s + no +0.8R in 60s: force breakeven. Social override: wider band.

---

## 4. Journal / tagging (reconciled — reuse what exists)
**Already on `paper_trades` (reuse, do NOT duplicate):** `max_adverse_excursion` (MAE), `max_favorable_excursion` (MFE), `market_regime`, `vix_at_entry`, `rvol_at_entry`, `planned_stop`, `current_stop`, `stop_type`, `trailing_active`, `trailing_policy_version`, `dollar_risk`, `signal_grade`, `bracket_state`, `oco_group_id`.
**Added by `migrate_momentum_scalp_stop_tagging.py`:** `initial_stop_atr`, `initial_stop_method`, `trail_multiplier_used`, `trail_activation_r`, `breakeven_trigger_r`, `final_r_vs_planned_stop`, `stop_quality_score`.

## 5. Monitoring & alerts (Risk tab — to build)
Per open scalp: stop distance in R & ATR · distance to breakeven/trail-activation · MAE vs planned stop · trail-tightness score · regime+freshness (entry vs now) · portfolio-heat contribution. Alerts: within 0.3R of stop (yellow) · trail-should-be-active >+2R (amber) · regime shift in-trade (amber, suggest tighten) · heat >3.5% (red, tighten-all + pause) · freshness>90s no-move (red, force BE).

## 6. Validation gate (4.4 → 4.5)
Paper trades ≥150 (≥3 regimes) · Social Route ≥40 · win ≥58% · expectancy ≥ +0.35R (post-slippage, 95% CI lower bound > 0) · profit factor ≥1.65 · max DD ≤4.5% · freshness compliance ≥92% · trail activation ≥85% of +2R winners · **avg R improvement from trailing ≥ +0.25R vs the no-trail baseline** (this is the metric that must overturn the STOP-V2.4 prior). Tracked by the Validation Tracker (§8) and the re-backtest harness.

## 7. Risk limits & kill switches
Single-trade max **1.2R** · max concurrent scalps **3** · daily momentum-book loss limit **3R or 2.5%** (lower) · portfolio-heat kill at **4.5%** aggregate open risk (pause new entries) · any −2.0R without regime justification → next AI Critique review. (Aligns with `prop_desk_discipline` + `momentum_scalp.yaml`.)

## 8. Implementation plan (phased — trailing gated per §2)
1. **[done]** Journal tag fields (`migrate_momentum_scalp_stop_tagging.py`) + this policy doc.
2. **Re-backtest harness** — extend `backtest_hybrid_stops.py` with the context-aware (tag/regime/freshness) multipliers vs the R-multiple baseline; verdict gates Layer-3 execution.
3. **Validation Tracker** — the §6 metrics over tagged paper trades (trail activation rate, R-improvement vs no-trail, false stop-outs, expectancy CI).
4. **Stop Intelligence panel** (Trade Detail/Replay) — what a 2× ATR / Chandelier(22,3) trail *would* have done vs actual, + optimal trail point from replay bars.
5. **Monitoring metrics + alerts** (§5) in the Risk tab.
6. **`momentum_scalp.yaml` exit_rules** — replace with the layered methodology; Layer-3 trailing carried behind a config flag that stays OFF until §6 passes.
7. **AI Trade Critique** — per closed scalp: was the initial stop optimal vs MAE? did the trail activate at the right R? what R was left on the table (replay)? recommended params for this setup+regime.

## 9. Cross-references
`backtest_hybrid_stops.py`, `strategy_trailing_policy.py`, `protection_trail_calculator.py`, `config/strategies/momentum_scalp.yaml`, `migrate_momentum_scalp_stop_tagging.py`; related policy: `STOP_METHODOLOGY.md`, `PROP_DESK_DISCIPLINE` (memory), `project_scalp_lifecycle_hardening` (memory).

## 10. Version history
| Ver | Date | Change |
|---|---|---|
| 1.0 | 2026-06-29 | Initial — layered stops + context-aware trailing (gated on re-backtest) + monitoring + validation, reconciled to as-built |
