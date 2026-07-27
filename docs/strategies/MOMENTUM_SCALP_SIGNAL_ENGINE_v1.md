# Momentum Scalp Signal Engine — Design Document v1 (DRAFT FOR REVIEW)

**Status:** v1 — **M3-S0 through M3-S5 BUILT, SHIPPED to main, and running in SHADOW** (2026-07-27).
No execution: engine flag OFF, no alerts, no proposals, no order path. See the §13 phase-plan status
column and the §16 Change Log for per-stage PRs/commits. M3-S6+ remain for operator authorization.
**Date:** 2026-07-27 (implementation) · **Author:** Claude (chat + code), operator direction
**Slot:** This is the **M3** document promised by `MOOMOO_INTEGRATION_DESIGN_v1_1.md` §8.
**Strategy key:** `momentum_scalp_intraday` (new key, per moomoo v1.1 Q6 recommendation)

> **VERIFICATION DEBT (read first).** This document was written without access to the live
> repository or live schema. Every table name, column name, script name, and threshold marked
> `[VERIFY]` is an assumption from project documentation, which lags the codebase by days to
> weeks. No implementation may proceed until the M3-S0 diagnostic pass (§13) confirms or
> corrects each one. Prior fabrication incidents in this system trace directly to skipping
> this step.
>
> **M3-S0 diagnostic status (2026-07-27):** the recon pass has run — see
> `docs/_findings/scalp_engine_recon_20260727.md` for the confirmed/corrected values. Highlights:
> `market_ohlcv_bars` exists but has **no usable 1m history** (yfinance caps 1m at ~7 days);
> data path decided = **Alpaca minute bars** (IEX for the RVOL_tod ratio; SIP confirmed entitled
> for later T1). `alert_dispatcher.py`, `opening_range_engine.py`, VWAP/ATR/EMA/MACD all exist
> and must be reused, not reimplemented. Live `momentum_scalp.yaml`: `max_float_m: 20`,
> `min_rvol: 5.0`, `STOP_OVER_15_PCT`. Findings supersede any `[VERIFY]` guess below.

---

## 0. Role definition (the governing sentence)

**This engine detects and times entries. It does not authorize them.**

It emits (a) notifications and (b) candidate proposals. Every proposal it emits passes through
the *existing, unmodified* gate chain: classifier real-criteria minimums → capability gate →
execution readiness gates → AUTO_PAPER approval. The engine never edits the deterministic core,
never bypasses a gate, never sizes a position, never submits an order.

Carried over unchanged: `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`,
`autonomous_live_submit=False`, ATM live-skip for momentum strategies, live adapter
`NotImplementedError`, null arm token.

---

## 1. Problem statement

The current `momentum_scalp` screen is a five-condition **AND-gate** on state variables:

```
price ∈ [1, 25]  AND  RVOL ≥ 5  AND  float ≤ 100M  AND  gap ≥ 5%  AND  score ≥ 40
```

Two structural failures follow.

**Failure 1 — the gate is used as an alert gate.** Trade authorization and discovery are
different jobs with opposite error costs. A false positive in authorization costs money; a
false positive in discovery costs one Telegram line. Running both off one AND-gate optimizes
for the wrong error.

**Failure 2 — level thresholds cannot detect a rate-of-change event.** A stock igniting on a
catalyst at 09:34 has not yet accumulated the volume that produces RVOL ≥ 5, and may not have
gapped at all if the news broke after the open. The pillars describe the *aftermath* of the
move. By the time all five read true, the first leg is spent. This is not a tuning problem —
no threshold on a lagging state variable detects an event in progress.

**Failure 3 — scan-time RVOL is arithmetically wrong intraday.** Finviz-style RVOL compares
partial-session cumulative volume against a *full-day* average. At 09:37 a stock trading at
8× its normal pace reports an RVOL near 0.6. This single defect suppresses nearly every early
leader. Fixing it is the highest-value change in this document.

---

## 2. Architecture — two lanes

```
                      ┌────────────── LANE A: IGNITION (OR-gate) ──────────────┐
  bars/quotes/L2 ───► │ time-of-day RVOL · volume burst · catalyst decay ·     │
                      │ VWAP displacement · dollar-volume rate · rel strength  │
                      │            → IGN score (0–100), continuous             │
                      └───────────────────────┬────────────────────────────────┘
                                              │ writes ONLY to scalp_ignition_events
                                              │ + alert_dispatcher (INFO/ALERT tiers)
                                              ▼
                      ┌────────────── LANE B: AUTHORIZATION (AND-gate) ────────┐
                      │ existing 5 pillars (UNCHANGED)                         │
                      │ + entry trigger fired (§6)                             │
                      │ + microstructure gate passed at the best available     │
                      │   data tier (§4–§5)                                    │
                      │ + slippage budget satisfied (§5.4)                     │
                      └───────────────────────┬────────────────────────────────┘
                                              ▼
                        EXISTING: classifier minimums → capability gate →
                        AUTO_PAPER → alpaca_paper_adapter → OCO → TCA
```

**The load-bearing rule:** Lane A is computable end-to-end from **Tier 0 data (bars only)**.
It never depends on Level 2, moomoo, or any premium feed. This is the direct answer to
"I don't want to miss the leader" — alerting degrades for *nothing*. Only Lane B, which risks
capital, degrades as data quality drops (§4.4).

---

## 3. Lane A — the Ignition Score

### 3.1 Time-of-day normalized relative volume

Replace scan-time RVOL everywhere in this engine:

```
RVOL_tod(t) = CumVol(t) / median_20d( CumVol at the same minute-of-session t )
```

Requires a per-symbol intraday volume profile: for each of the 390 regular-session minutes,
the trailing-20-session median of cumulative volume at that minute. Rebuilt nightly, stored
per symbol. Premarket uses a separate 07:00–09:30 profile.

Fallback when profile is missing (new listing, <10 sessions of history):

```
RVOL_tod_proxy(t) = CumVol(t) / ( ADV_20d × ExpectedFraction(t) )
```

where `ExpectedFraction(t)` is a **universe-level** U-shaped curve (median across the scalp
universe), not a per-symbol one. Flag `profile_source='universe_proxy'` on the event — proxy
values are noisier and §4.4 penalizes them.

### 3.2 Sub-scores (each normalized to [0, 1])

| Symbol | Definition | Formula |
|---|---|---|
| `v_rvol` | volume pace | `clamp( log(RVOL_tod / 2) / log(10), 0, 1 )` → 2× = 0, 20× = 1 |
| `v_burst` | ignition detector | `clamp( z_vol / 6, 0, 1 )`, `z_vol = (v_1m − μ_20bar) / σ_20bar` |
| `v_cat` | catalyst heat | `tier_weight × exp( −age_min / 90 )` |
| `v_disp` | displacement | `clamp( (P − VWAP) / (2 · ATR_1m · √n_bars), 0, 1 )` |
| `v_liq` | tradability | `clamp( log10( ($ × vol_5m) / 50_000 ) / 1.7, 0, 1 )` → $50K = 0, $2.5M = 1 |
| `v_rs` | leadership | intraday `ret_sym − ret_SPY` since open, percentile-ranked within the day's universe |

`tier_weight` reuses the **existing source-quality table** (SEC 8-K = 1.00 → unknown_social =
0.20) `[VERIFY: table/column name]`. τ = 90 min is the decay half-life analogue; a 4-hour-old
headline contributes ~7% of its tier weight.

`v_disp` is deliberately volatility-normalized rather than percentage-based. A 6% move in a
name whose 1-minute ATR is 0.4% is a real event; the same 6% in a name whose ATR is 3% is noise.

### 3.3 Composite

```
IGN = 100 × ( 0.28·v_rvol + 0.22·v_burst + 0.18·v_cat
            + 0.14·v_disp + 0.10·v_liq  + 0.08·v_rs )
```

Weights are **v1 priors, not findings.** §12 defines how shadow data replaces them. Do not
hand-tune them mid-shadow; that destroys the sample.

### 3.4 Notification tiers

| Condition | Action | Channel |
|---|---|---|
| `IGN ≥ 45` | add to watch set; subscribe L2 if available | dashboard only (`INFO`) |
| `IGN ≥ 60` | heads-up, tagged **`UNGATED — NOT A PROPOSAL`** | Telegram (`ALERT`), both chat IDs |
| `ΔIGN ≥ 15 within ≤10 min` | acceleration alert, fires at **any** absolute level | Telegram (`ALERT`) |
| `IGN ≥ 75` AND Lane B passes | proposal emitted | existing proposal path |

The acceleration trigger is the mechanism that catches the leader. It is a first derivative, so
it fires early by construction — typically before `v_rvol` has any magnitude at all.

All sends route through the **existing `alert_dispatcher.py`** `[VERIFY]` to inherit cross-script
dedupe, the 15/hour rate limit, and fatigue auto-downgrade. Additional engine-local controls:
per-symbol cooldown 20 min; hard cap 8 ignition alerts per session; on cap breach send one
summary line, not the ninth alert.

### 3.5 What is excluded from IGN, permanently

Social mention counts, StockTwits volume, Reddit velocity, YouTube sentiment, and every other
crowd-derived signal are **not inputs to IGN** and may never become inputs. `v_cat` is
news-tier weighted and is the only catalyst-adjacent term. This is the `409c055` rule
(sentiment must never count toward strategy match minimums) applied at the point where it
would most naturally be re-violated. Social data may *annotate* an alert for the operator's
reading; it may not move the number.

---

## 4. Data tier model — the fallback ladder

### 4.1 Correcting the premise on coverage

The concern was that moomoo L2 covers NASDAQ only. That is not the constraint.

Nasdaq TotalView covers every quote and order at every price level in Nasdaq-, NYSE-, NYSE
American- and regional-listed securities that trade on Nasdaq, with 60 levels of bid and ask,
and moomoo's platform offers six order books — NASDAQ TotalView, NYSE ArcaBook, NYSE OpenBook,
CBOE Bats BZX, CBOE Direct Edge, and National Quotation. Listing venue is therefore not the
limiting factor.

The real limitation is **venue fragmentation**: each book shows only the orders resting *on
that venue*. A US equity trades across ~16 exchanges plus dozens of ATSs. Even a full
TotalView feed is a partial view of consolidated liquidity, and it systematically understates
depth because reserve/iceberg orders are not displayed. Treat every L2 reading as a *sample*
of the book with a venue-coverage caveat, never as the book.

**Separate open question:** platform L2 entitlement ≠ **OpenAPI** L2 entitlement. moomoo M0
recon must confirm whether the API exposes depth at all, and for which books. Until M0
reports, this document assumes **Tier 2 may never arrive**, and Tier 1 is the design target.

### 4.2 The three tiers

| Tier | Source | Contents | Availability |
|---|---|---|---|
| **T2** | moomoo OpenD (post-M1) | order book depth, per-level size, book updates | uncertain; venue-partial |
| **T1** | Alpaca / Polygon consolidated SIP `[VERIFY entitlement]` | trades + NBBO quotes, all US equities | broad |
| **T0** | yfinance / Polygon / `market_ohlcv_bars` `[VERIFY]` | 1m/5m OHLCV bars | always |

### 4.3 Metric substitution ladder — the core deliverable

Every Tier-2 microstructure metric has a defined substitute at T1 and T0. Nothing in the
pipeline is allowed to hard-depend on T2.

| Concept | **T2 (book)** | **T1 (trades + NBBO)** | **T0 (bars only)** |
|---|---|---|---|
| Directional pressure | Book imbalance `BI` (§5.1) | **Trade Flow Imbalance** via Lee-Ready | **Volume-weighted close location** |
| Transaction cost | Quoted spread from book | **Effective spread** from prints vs mid | **Corwin–Schultz** / **Abdi–Ranaldo** |
| Depth for my size | Top-3 level size | Participation cap vs trailing 1m volume | Participation cap vs trailing 1m volume |
| Impact per unit size | Depth decay across levels | **Kyle's λ** regression | **Amihud ILLIQ** |
| Aggression / sweeps | Print vs displayed size | Block prints, sub-second print clusters | Volume z-score + range expansion |
| Absorption | Size refills at a level | Volume up, price flat, TFI positive | **Wyckoff effort-vs-result** |
| Book stability | Quote update rate | NBBO flicker rate | Bar-range dispersion |

**T1 formulas**

*Lee–Ready trade classification (1991)* — print above mid = buy-initiated, below = sell-initiated,
at mid = tick test against last differing trade price. Use contemporaneous quotes; the original
5-second lag was an artifact of 1990s tape latency and is wrong on modern data.

```
TFI_w = ( V_buy − V_sell ) / ( V_buy + V_sell )        over rolling window w (60s, 300s)
```

`TFI` is the direct substitute for book imbalance and, in a fragmented market, is arguably the
*better* signal — it reflects what actually executed across all venues rather than what was
displayed on one.

*Effective spread*, volume-weighted over the window:

```
ES_bps = 10⁴ × 2 × | P_trade − Mid_at_trade | / Mid_at_trade
```

*Kyle's λ (1985)*, fit per symbol per session on 1-minute bars:

```
ΔP_t = λ · SignedDollarVolume_t + ε        →  expected_impact_bps ≈ 10⁴ · λ · (shares × price)
```

*VPIN (Easley, López de Prado & O'Hara)* — bucket trades into equal-**volume** buckets, split
each bucket by bulk classification, then

```
VPIN = (1/n) · Σ | V_buy − V_sell | / V_bucket
```

High VPIN means informed/toxic flow. Nuance for this strategy: elevated VPIN *aligned* with the
position is the fuel; elevated VPIN *against* it is an exit signal, and either way it raises
adverse-selection risk on the way out. Treat VPIN as an exit-urgency modifier, not an entry filter.

**T0 formulas**

*Volume-weighted close location* — the bars-only pressure proxy (Chaikin lineage):

```
CLV_i = (C_i − L_i) / (H_i − L_i)            ∈ [0,1], undefined if H=L → skip bar
BarPressure_w = Σ (2·CLV_i − 1) · V_i / Σ V_i      ∈ [−1, +1]
```

Same range and sign convention as `TFI` and `BI`, so downstream gate code takes one input
regardless of tier.

*Corwin–Schultz high-low spread estimator (2012)*, from two consecutive bars:

```
β = Σ_{j=0}^{1} [ ln( H_{t+j} / L_{t+j} ) ]²
γ = [ ln( H_max(t,t+1) / L_min(t,t+1) ) ]²
α = ( √(2β) − √β ) / (3 − 2√2)  −  √( γ / (3 − 2√2) )
S = 2 · ( e^α − 1 ) / ( 1 + e^α )               negative → clamp to 0
```

Designed for daily bars; applies to consecutive intraday bars with more noise. Average over
several bar pairs. Cross-check against **Abdi–Ranaldo (2017)**, which is generally more accurate
on high-volatility names; use `max()` of the two as the conservative estimate.

*Amihud illiquidity (2002)*:

```
ILLIQ = mean_over_bars( | r_bar | / DollarVolume_bar )
```

**Do not use the Roll (1984) estimator here.** Roll requires negative serial covariance of
returns, and momentum ignition produces *positively* autocorrelated returns — exactly the
regime where Roll returns an undefined or nonsense value. It fails precisely when this engine
needs it.

*Wyckoff effort vs. result* — absorption detection with no order data at all:

```
EvR = ( |ΔP_bar| / ATR_1m ) / ( V_bar / μ_V_20bar )
```

Low `EvR` on high volume = large effort, no result = supply absorbing demand = the leg is
being sold into. This is the deterministic form of what a tape reader is doing by eye, and it
works on any symbol with bars.

### 4.4 Data Confidence Factor — how degradation is priced

The tier does not gate the alert. It gates **size and strictness** on the trade.

| Tier | `DCF` | IGN required for proposal | Slippage budget (§5.4) | Participation cap |
|---|---|---|---|---|
| T2 | 1.00 | 75 | ≤ 15% of stop | 1.0% of trailing 1m volume |
| T1 | 0.70 | 80 | ≤ 12% of stop | 0.7% |
| T0 | 0.40 | 85 | ≤ 8% of stop | 0.5% |
| any tier, data stale > 120s | 0.00 | **NO TRADE** | — | — |

```
shares = floor( ( risk_budget_$ × DCF ) / ( entry − stop ) )
```

subject to the participation cap and the existing $2,000 max position / $200 max risk rules.
The staleness rule is a hard fail-closed. A 3-minute-old quote on a stock moving 8% per hour
is not data.

---

## 5. Microstructure gate (Lane B)

**Boundary: the microstructure layer is a VETO, never a scorer.** It can reject a setup or
reduce its size. It can never raise a score, upgrade a grade, or promote a candidate. Without
this rule the book starts voting weak setups up, which is the failure mode that destroys
tape-based systems.

### 5.1 Checks (expressed at T2; substitute per §4.3 at lower tiers)

| Check | Metric | Gate |
|---|---|---|
| Spread | `spread_bps` | ≤ 40 bps for $2–10 names; hard block > 100 bps |
| Directional pressure | `BI` / `TFI` / `BarPressure` | ≥ +0.15 for longs |
| Depth vs. size | ask size within 0.5% of mid | ≥ 3× intended shares, else size down |
| Tape direction | `TS = V_at_ask / (V_at_ask + V_at_bid)`, 60s | ≥ 0.60 |
| Book stability | `σ(spread_bps)` over 60s | reject if > 0.5 × mean spread |
| Absorption | `EvR` | reject if bottom-quartile on the last 3 bars of the impulse |
| Halt risk | LULD band proximity | reject if within 2% of a band edge |

`BI` at T2:

```
BI = ( Σ bid_size_top5 − Σ ask_size_top5 ) / ( Σ bid_size_top5 + Σ ask_size_top5 )
```

### 5.2 Hidden liquidity caveat

Displayed size is not true size — reserve and iceberg orders mean the book understates depth,
and layered orders that vanish on approach mean it sometimes overstates it. Consequence:
**depth may only ever be used to size down, never to justify sizing up.** A thick-looking book
is not permission.

### 5.3 Halt handling

Low-float momentum names halt. Required behavior: on halt detection, cancel all working entry
orders immediately, hold existing position with stop intact, suppress all new entries in that
symbol for the remainder of the session, and alert. Never place a resting entry order into a
halted book — the reopening auction print is unforecastable and stops do not protect through it.

### 5.4 The slippage budget — the single most important gate

```
expected_slip_bps = spread_bps / 2  +  k × ( intended_shares / available_depth )
GATE:  expected_slip_bps  ≤  DCF_budget × stop_distance_bps
```

If expected round-trip friction consumes more than the tier's budget of the stop distance, the
edge is already gone regardless of how good the chart looks. Start `k = 20`; recalibrate from
live canary TCA (predicted vs. realized slippage), never from estimation.

This is the concrete form of the `R4` book-quality rule sketched in the moomoo design. It exists
because **paper fills are polite** — Alpaca paper fills at NBBO with no impact, so the paper
scoreboard will systematically overstate this strategy's edge. R4 is what stops the engine from
learning a habit that only works against a simulator.

---

## 6. Entry trigger — formalizing the operator pattern

The screen-watching pattern — "first candle that reverses the downtrend" — made deterministic
on 1-minute bars. All seven conditions required.

| # | Condition | Test |
|---|---|---|
| 1 | Impulse leg exists | advance ≥ `2.0 × ATR_1m(14)` from leg origin |
| 2 | Pullback structure | ≥ 2 consecutive lower highs |
| 3 | Retrace depth valid | `retrace ∈ [0.236, 0.618]` of leg; `> 0.786` → leg void, reset state |
| 4 | Volume dry-up | `mean(vol_pullback) ≤ 0.60 × mean(vol_impulse)` |
| 5 | Structure held | pullback low ≥ VWAP, **or** VWAP reclaimed within the trigger bar |
| 6 | Trigger bar | closes above prior bar high **AND** close in top ⅓ of its range **AND** `vol ≥ 1.5 × mean(vol_pullback)` |
| 7 | Absorption absent | `EvR` not bottom-quartile over the last 3 impulse bars |

**Condition 4 is the highest-value filter in the set** and is the one most systems omit. A
pullback on expanding volume is distribution, not rest. Skipping it is the main source of
false triggers on this pattern.

**Levels:**

```
entry = trigger_bar_high + $0.02
stop  = min( trigger_bar_low, pullback_low ) − $0.02,
        floored at  entry − 1.0 × ATR_1m       (noise-stop protection)
R     = entry − stop
```

**Rejections:** `stop_distance > 8%` of entry (existing rule) · `R:R to target_1 < 2.0` ·
`entry > leg_high × 1.02` (no-chase) · session outside the permitted window.

### 6.1 On MACD — honest pushback

MACD on 1-minute bars whipsaws badly in exactly the volatility regime this strategy trades. It
will veto good entries and confirm late ones. **Recommendation: use it as a 5-minute regime
filter only** — `hist > 0` or `hist` rising permits longs — and never as a trigger. VWAP,
condition 4, and `EvR` are doing the real work. If shadow data later shows the 5m MACD filter
has no discriminating power, drop it entirely rather than keeping it for familiarity.

### 6.2 Sampling — a known v1 limitation

Time bars oversample quiet periods and undersample bursts, which is precisely backwards for
ignition detection: the most informative 90 seconds of the day gets one-and-a-half bars.
**Volume bars or dollar bars** (a new bar every N shares or N dollars traded) are the correct
sampling unit and should be evaluated in v2. v1 stays on 1-minute time bars to reuse the
existing `market_ohlcv_bars` infrastructure `[VERIFY]` and to keep the shadow comparison clean.
Logging the dollar-bar equivalent alongside costs nothing and makes the v2 case empirically.

---

## 7. Exit math

| Rule | Definition |
|---|---|
| Target 1 | `entry + 2R` → scale 50% |
| Target 2 | `entry + 3R` or trailing stop on remainder |
| Hard stop | as defined §6 — placed with the bracket, never mental |
| VWAP rule | second close below VWAP after entry → full exit |
| Absorption exit | `EvR` bottom-quartile for 2 consecutive bars while in profit → scale out |
| Toxicity exit | `VPIN` elevated and `TFI` flips negative → tighten to breakeven |
| Time stop | flat by 15:45 ET, no exceptions, no overnight |
| Daily circuit breaker | 2 consecutive full-stop losses → engine halts for the session |

The daily circuit breaker is new and non-negotiable. Two clean stop-outs in a row means the
regime is not the one the engine was calibrated on, and the correct response is to stop, not
to look for the third setup.

---

## 8. Practitioner grounding

Paraphrased principles with their operational translation — the point is what each one becomes
in code, not the phrasing.

| Principle | Source | Translation in this engine |
|---|---|---|
| Effort vs. result: volume is effort, price change is result; large effort with no result means supply is absorbing demand | Richard Wyckoff | `EvR` (§4.3) — gates entry (§6 cond. 7) and drives an exit (§7) |
| Trade with the line of least resistance; wait for the market to confirm direction rather than anticipating it | Jesse Livermore, via Lefèvre's *Reminiscences of a Stock Operator* (1923) | Trigger requires a **close** above the prior bar high (§6 cond. 6), not a touch. No anticipatory entries |
| Quoted, effective, and realized spreads are three different numbers; displayed size is not true size | Larry Harris, *Trading and Exchanges* (2003) | §5.2 hidden-liquidity rule; §5.4 uses **effective** spread, not quoted |
| Information arrives in volume time, not clock time | López de Prado, *Advances in Financial Machine Learning* (2018) | §6.2 — volume/dollar bars flagged as the v2 sampling correction |
| Order flow toxicity is measurable and precedes volatility | Easley, López de Prado & O'Hara (VPIN) | Exit-urgency modifier (§7), not an entry filter |
| Price impact is approximately linear in signed order flow | Albert Kyle (1985) | Kyle's λ as the T1 impact estimator (§4.3) |
| Execution cost rises with participation rate | Almgren & Chriss (2000) | Participation caps in the DCF table (§4.4) |
| Define each setup precisely, review every trade, and size up only on the setups you have actually documented | Mike Bellafiore, SMB Capital | The entire §6 spec exists as one playbook entry; §11 is the review loop |
| The edge is in the review loop — track your own execution data | Brett Steenbarger | §11 shadow schema + §12 promotion gates |
| Trades can be classified as buyer- or seller-initiated from prints and quotes alone | Lee & Ready (1991) | `TFI`, the T1 substitute for book imbalance |
| Spread and illiquidity are estimable from low-frequency price data | Corwin & Schultz (2012); Abdi & Ranaldo (2017); Amihud (2002) | The entire T0 fallback tier |

The through-line worth stating plainly: the T0/T1 fallback tiers are not a consolation prize.
Wyckoff read absorption for decades from a paper tape with no depth data at all, and the
academic estimators exist specifically because researchers needed liquidity measures where no
book was recorded. A well-built T1 engine, working on consolidated prints across all venues,
may outperform a T2 engine reading one venue's partial book. Build T0/T1 first on the merits,
not as a fallback.

---

## 9. Configuration discrepancy requiring a decision

Operator states float ≤ **30M** for this strategy. Live config states:

```yaml
max_float_m: 100
preferred_max_float_m: 20
```

Three numbers, three sources. This needs a single decided value before shadow starts, because
changing the universe mid-evaluation invalidates the sample.

> **M3-S0 correction (2026-07-27):** the live `config/strategies/momentum_scalp.yaml` now reads
> `max_float_m: 20` / `preferred_max_float_m: 10` (operator preference applied 2026-06-26), NOT
> 100. So the live discrepancy is operator-30M vs live-20M. The `[VERIFY]` guess of 100 was stale.
> Still requires a single decided value on the **new** `momentum_scalp_intraday` key.

Additional consequence: `momentum_scalp` currently carries a **not-suspended review gate**
(gate = ≥ 5 trades, WR trend under monitoring). Tightening its float band mid-evaluation
corrupts that gate. Recommended resolution — set float ≤ 30M on the **new**
`momentum_scalp_intraday` key only, leave `momentum_scalp` untouched until its own review
concludes.

---

## 10. Guardrails — what this engine must never do

1. Never write directly to `paper_trade_proposals`. Lane A writes to `scalp_ignition_events`;
   Lane B emits candidates through the existing proposal path only.
2. Never bypass the classifier real-criteria minimum. IGN is not a criterion. `409c055` stands.
3. Never let social/sentiment data enter IGN (§3.5).
4. Never let the microstructure layer raise a score (§5).
5. Never let depth justify sizing up (§5.2).
6. Never trade on data older than 120 seconds (§4.4).
7. Never place a resting order into a halted book (§5.3).
8. Never modify `momentum_scalp` config, thresholds, or scoreboard.
9. Never touch broker order state from this engine — proposals only.
10. Live execution stays structurally locked. This document does not discuss unlocking it.
11. Kill file `~/.tradeai/SCALP_ENGINE_DISABLED` halts everything, checked every cycle.

---

## 11. Shadow-mode logging

Shadow means: compute everything, log everything, **emit nothing** — no proposals, no Telegram
beyond a daily summary. `[VERIFY: table does not exist; names are proposed]`

```sql
CREATE TABLE scalp_ignition_events (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT        NOT NULL,
    fired_at        TIMESTAMPTZ NOT NULL,
    session_date    DATE        NOT NULL,
    lane            TEXT        NOT NULL,   -- 'IGN_45'|'IGN_60'|'IGN_ACCEL'|'IGN_75'|'TRIGGER'
    ign_score       NUMERIC(5,2) NOT NULL,
    subscores       JSONB       NOT NULL,   -- v_rvol, v_burst, v_cat, v_disp, v_liq, v_rs
    rvol_tod        NUMERIC(8,2),
    profile_source  TEXT,                   -- 'per_symbol' | 'universe_proxy'
    data_tier       TEXT        NOT NULL,   -- 'T0'|'T1'|'T2'
    dcf             NUMERIC(3,2) NOT NULL,
    data_age_sec    INT,
    -- microstructure, whichever tier supplied them
    spread_bps      NUMERIC(8,2),
    spread_source   TEXT,                   -- 'book'|'effective'|'corwin_schultz'|'abdi_ranaldo'
    pressure        NUMERIC(5,3),           -- BI | TFI | BarPressure, same sign convention
    pressure_source TEXT,
    evr             NUMERIC(8,4),
    kyle_lambda     NUMERIC(14,8),
    amihud_illiq    NUMERIC(14,8),
    vpin            NUMERIC(5,3),
    -- hypothetical trade
    entry_ref       NUMERIC(12,4),
    stop_ref        NUMERIC(12,4),
    r_dollars       NUMERIC(12,4),
    stop_dist_bps   NUMERIC(8,2),
    intended_shares INT,
    participation_pct NUMERIC(6,3),
    expected_slip_bps NUMERIC(8,2),
    slip_budget_ratio NUMERIC(6,3),         -- expected_slip / (DCF_budget × stop_dist)
    -- gate outcome
    gate_result     TEXT        NOT NULL,   -- 'PASS'|'VETO'
    gate_reasons    JSONB       NOT NULL,
    -- outcomes, backfilled T+1 by a separate job
    mfe_5m   NUMERIC(8,4),  mae_5m   NUMERIC(8,4),
    mfe_15m  NUMERIC(8,4),  mae_15m  NUMERIC(8,4),
    mfe_30m  NUMERIC(8,4),  mae_30m  NUMERIC(8,4),
    r_multiple_30m   NUMERIC(8,4),
    hit_1r_first     BOOLEAN,               -- reached +1R before −1R
    time_to_1r_sec   INT,
    outcome_filled_at TIMESTAMPTZ
);
CREATE INDEX idx_sie_session  ON scalp_ignition_events (session_date, lane);
CREATE INDEX idx_sie_symbol   ON scalp_ignition_events (symbol, fired_at DESC);
CREATE INDEX idx_sie_pending  ON scalp_ignition_events (fired_at)    WHERE outcome_filled_at IS NULL;
```

**Log vetoed setups too.** The counterfactual is the whole point — if VETO'd setups outperform
PASS'd ones, the gate is inverted, and that is only discoverable if both are recorded.

---

## 12. Promotion gates

**Primary metric — P@1R:** the fraction of fires that reach `+1R` before `−1R`.

```
P@1R(lane) = count( hit_1r_first ) / count( fires in lane )
```

| Gate | Requirement |
|---|---|
| G1 · Sample | ≥ 100 `TRIGGER` fires across ≥ 15 trading sessions |
| G2 · Precision | `P@1R ≥ 0.40` on `TRIGGER` fires |
| G3 · **Monotonicity** | `P@1R` rises monotonically across IGN deciles |
| G4 · Alert utility | ≥ 30% of `IGN_60` and `IGN_ACCEL` fires reach `+1R` within 30 min |
| G5 · Gate validity | PASS cohort `P@1R` exceeds VETO cohort by ≥ 10 points |
| G6 · Noise | ≤ 8 Telegram alerts per session, median ≤ 4 |
| G7 · Tier parity | T1-only cohort `P@1R` within 8 points of T2 cohort |

**G3 is the real test.** If a composite score does not order outcomes, it is decoration —
individual sub-scores may still work, but the weighting is wrong and must be refit before
anything is promoted. G7 is what proves the fallback ladder actually works and that T2 is
worth paying for.

Weight refitting happens **once**, after G1 is satisfied, on the shadow sample. Then the
weights lock and the sample restarts. No continuous tuning against outcomes — that is
overfitting with extra steps.

**Ladder:** shadow (log-only, ≥ 15 sessions) → G1–G7 → AUTO_PAPER → 30 trades · 55% WR ·
PF ≥ 1.3 earned from zero on the `momentum_scalp_intraday` scoreboard → live discussion only
after, behind every existing lock.

**PDT note:** sustained live intraday automation requires taxable equity > $25K. A funding
prerequisite, independent of everything in this document.

---

## 13. Phase plan

| Phase | Scope | Exit criteria | Status (2026-07-27) |
|---|---|---|---|
| **M3-S0** | **Diagnostic only, zero code.** Confirm every `[VERIFY]`: bar table schema/coverage, data entitlement, source-quality table, `alert_dispatcher`, live `momentum_scalp.yaml`, whether the profile is buildable | Findings doc; every assumption confirmed/corrected | ✅ **SHIPPED** PR #225 `0aa7fc4e` (recon: `docs/_findings/scalp_engine_recon_20260727.md`) |
| **M3-S1** | Volume profile builder + `RVOL_tod`. Nightly job, 20-session profile per universe symbol | Profile for ≥ 90% of universe; spot-check ignition days | ✅ **SHIPPED** PR #225 `0aa7fc4e`. Coverage 39/72 per-symbol; rest = §3.1 proxy cohort. Nightly cron 20:30 ET |
| **M3-S2** | T0 metric library — Corwin–Schultz, Abdi–Ranaldo, Amihud, `BarPressure`, `EvR`. Pure, hand-computed fixtures | Suite green; values sane on 10 symbols | ✅ **SHIPPED** PR #226 `6a687f8c`. 26 tests; Amihud separates liquid/micro-float by ~4 orders |
| **M3-S2.5** | Gate clearance — freshness accessor, tier-ladder invariant, spread gate/score split, provenance | Verdict GATES CLEAR | ✅ **SHIPPED** PR #228 `07c855d0` (`docs/_findings/M3_S2_5_GATE_CLEARANCE_2026-07-27.md`) |
| **M3-S3** | IGN scorer + `scalp_ignition_events` + shadow logging. **No alerts, no proposals** | 5 clean sessions; zero pipeline impact | ✅ **SHIPPED** PR #227 `7043d5da`. Shadow logger cron 6am–noon ET |
| **M3-S4** | Outcome backfill (MFE/MAE, `hit_1r_first`) + rollup + dashboard panel | Panel shows fires, deciles, `P@1R` | ✅ **SHIPPED** PR #229 `7021cbf0`. Dashboard `/v3-next/scalp-shadow.html`; P@1R per-cohort never pooled; AST isolation test |
| **M3-S5** | Entry-trigger state machine, logged as `TRIGGER` lane. Still shadow | ≥ 15 sessions, G1 satisfied | ✅ **SHIPPED** PR #230 `fa0ec680`. Fires on real data; finding: thin-name triggers get tiny stops → whipsaw |
| **M3-S6** | T1 upgrade — Lee-Ready `TFI`, effective spread, Kyle's λ, VPIN | Tier parity measurable (G7) | ⏳ pending auth (SIP-delayed entitled) |
| **M3-S7** | Enable Telegram tiers. Alerts only, still no proposals | G4 + G6 satisfied | ⏳ pending |
| **M3-S8** | Weight refit, lock, restart sample | Locked weights committed with hash | ⏳ pending (do NOT refit before the sample gate) |
| **M3-S9** | Proposal emission → AUTO_PAPER | G1–G7 all satisfied; operator sign-off | ⏳ pending |
| **M3-S10** | T2 layer, contingent on moomoo M0/M1 delivering API depth | Bolts onto §5 without touching S1–S9 | ⏳ pending |

**Shadow accrual clock:** the 10/≥15-session shadow sample starts when S3/S5 go live (2026-07-27) and
accrues via the 6am–noon logger cron. Do not promote or refit weights before the §12 sample gate.

S1–S7 require **no moomoo, no L2, and no new vendor**. If moomoo M0 reports no API depth
entitlement, this plan is unaffected through S9.

---

## 14. Open questions for architect review

1. **Volume profile storage** — new table, or extend the existing bar cache? 390 minutes × ~600
   symbols × 20 sessions is small, but the nightly rebuild cost needs measuring against the
   existing overnight window.
2. **T1 data source** — does the current Alpaca entitlement include consolidated SIP trades and
   quotes, or IEX-only? IEX-only would make `TFI` a ~2% volume sample and materially weaker
   than the T0 `BarPressure` fallback. **This is the single highest-impact unknown in the
   document** and M3-S0 must answer it first.
   > **M3-S0 answer (2026-07-27):** SIP **is entitled** — a direct `/v2/stocks/{sym}/bars?feed=sip`
   > call returns full consolidated bars (incl. extended hours) with the existing keys. IEX also
   > works. So `TFI`/effective-spread at T1 are viable on consolidated data, not a 2% sample.
3. **Circuit breaker scope** — session-halt after 2 consecutive stops: per-symbol or engine-wide?
   Author lean: engine-wide, since consecutive stops indicate a regime read failure, not a
   symbol failure.
4. **Universe definition** — does `momentum_scalp_intraday` inherit the existing scalp universe,
   or get its own screener at float ≤ 30M? Affects §9.
5. **Premarket window** — include 07:00–09:30 in v1? Gap structure is genuine rule material, but
   it doubles profile-building work and premarket VWAP is unreliable on thin names.
   Author lean: log premarket in shadow, exclude from triggers until S5 data justifies it.
6. **Volume bars in v1** — build §6.2 dollar-bar sampling as a parallel logged track from S3, or
   defer entirely to v2? Author lean: log the dollar-bar equivalent from S3 at near-zero cost so
   the v2 decision is empirical rather than argued.

---

## 15. Out of scope

Live execution and any unlocking thereof · IRA eligibility (this strategy is taxable-only,
unchanged) · changes to `momentum_scalp` · changes to any existing gate, classifier, or ATM
config · broker order management · options · short side (long-only in v1; the short variant is
a separate design cycle because borrow availability and locate mechanics are a different problem)

---

## 16. Change Log & Provenance (M3-S2.5 gate clearance, 2026-07-27)

Recorded so the doc is an accurate record of what shipped, not a reconstruction. See
`docs/_findings/M3_S2_5_GATE_CLEARANCE_2026-07-27.md`.

- **Roll (1984) → Abdi–Ranaldo (2017) spread substitution.** §4.3 uses Corwin–Schultz cross-checked
  with Abdi–Ranaldo (conservative `max` for the gate consumer), and **excludes Roll**. Rationale:
  Roll's `2√(−cov)` degenerates when the serial covariance of returns goes non-negative, which on
  thin low-float momentum names (positively autocorrelated during ignition) is frequent — it fails
  exactly where this engine needs it. **Provenance (G5.1): `CITATION_RETROFITTED`** — this doc
  entered the repo at commit `0aa7fc4e` (PR #225) with Abdi–Ranaldo already present in §4.3; there
  is no prior in-repo revision citing Roll to diff against. The substitution is endorsed on the
  merits; this note exists so the record is honest.
- **Tier numbering is fixed to the design-doc convention** (operator ruling 2026-07-27):
  **T2 = full book (best data) → T1 = SIP/quotes → T0 = bars-only (weakest, ships today).** This is
  the *opposite* label direction to some external "ascending-capability" ladders — deliberately
  **not** renumbered. The load-bearing property is the invariant, not the label: ordered by
  descending data quality (`data_tiers.quality_order = [T2,T1,T0]`), the size multiplier (`dcf`) is
  non-increasing and `assumed_slippage_bps` is non-decreasing. This is enforced by
  `tests/test_scalp_data_tier_invariant.py` (G4.3) and cannot be violated silently. In the live
  config bar-only (T0) already carries the **lowest** multiplier (0.40), so the "weakest data inherits
  the biggest size" failure mode does not exist.
- **EvR (Wyckoff effort-vs-result) is a DIAGNOSTIC, not a sub-score.** The IGN score has exactly the
  **six** §3.2 sub-scores (`v_rvol, v_burst, v_cat, v_disp, v_liq, v_rs`), whose priors are re-fit
  once on shadow data (§12). `effort_vs_result` in `scalp_t0_metrics.py` is logged alongside events
  for review and is **never weighted** (grep-verified: no EvR key in `config/scalp_signal_engine.yaml`).
- **Spread aggregation split by consumer (G6):** `spread_estimate_gate` (max — risk-safe upward bias)
  for sizing/risk; `spread_estimate_score` (median — unbiased) for the future scorer consumer. Neither
  is wired into a sub-score yet.

### Implementation log (M3-S3 → S5, 2026-07-27)

- **M3-S3 (PR #227 `7043d5da`):** IGN scorer `scripts/scalp_ignition_scorer.py` (pure §3.2 six
  sub-scores incl. the σ-floor guard on `v_burst`), `scalp_ignition_events` table (no FK to
  `paper_trade_proposals`), `scripts/scalp_shadow_logger.py` (assembles inputs from Alpaca bars +
  the M3-S1 profile + catalyst rows + M3-S2 T0 metrics; cross-sectional `v_rs`). `notifications.emit`
  hard-false. Verified on the 2026-07-13 QTTB ignition (AGEN RVOL_tod 140× → IGN 59 → IGN_45).
- **M3-S4 (PR #229 `7021cbf0`):** `scripts/scalp_shadow_outcome_backfill.py` (isolated T+1 job —
  MFE/MAE, `hit_1r_first`, `r_multiple_30m`), `scripts/scalp_shadow_rollup.py` (P@1R by IGN band
  **per cohort, never pooled**) + static read-only HTML dashboard. AST Step-7 isolation test (import
  nodes + string literals, docstrings structurally excluded). The logger now stores a hypothetical
  `entry_ref`/`stop_ref` (entry = fire price, stop = entry − 1·ATR) so outcomes are computable.
- **M3-S5 (PR #230 `fa0ec680`):** `scripts/scalp_trigger_engine.py` — pure state machine
  IDLE→IMPULSE→PULLBACK→ARMED→TRIGGERED|VOID, all seven §6 conditions, noise-stop floor (R ≤ ATR),
  reject guards, MACD(5m) logged-not-gating, post-halt 30-bar re-warm. Logged under the `TRIGGER`
  lane. **Interpretation:** §6 "R:R to target_1" implemented as measured-move feasibility
  `leg_height/R ≥ 2` (§7's exit target_1 = entry+2R is separate) — operator may revise.
- **Open (owed to a later stage):** the §3.1 proxy path's ADV_20d is currently circular (needs a
  real Alpaca daily-bar ADV source); `v_cat` catalyst age is approximate (uses `scanned_at`); a
  minimum-R trigger filter is a candidate (thin-name triggers get sub-cent stops that whipsaw); the
  outcome-backfill/rollup runner exists but is not yet scheduled.

---

*Review process: architects annotate v1 → v2 final → M3-S0 authorized on v2 sign-off.*
*Implementation status is tracked in the §13 phase-plan Status column and the log above.*
