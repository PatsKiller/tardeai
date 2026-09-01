# Inverse-ETF Hedge Stoplights — Research Memorandum & Results (2026-07-19)

Status:      HISTORICAL
as_of:       2026-07-19T18:22:46-04:00
Measured at: efcc51365 / not measured

Pre-registration: `INVERSE_HEDGE_TWODAY_PREREGISTRATION_2026-07-19.md` @ commit
`f2988645` (committed BEFORE results). Backtest code:
`scripts/research/inverse_hedge_backtest.py` (reproducible: Schwab daily
history, split-adjusted, cached with source noted).

## 1. Primary sources

- **FINRA Regulatory Notice 09-31** — inverse/leveraged ETFs "typically are
  unsuitable for retail investors who plan to hold them for longer than one
  trading session"; the products reset daily and require active monitoring.
  (finra.org/rules-guidance/notices/09-31)
- **SEC/FINRA joint investor alert on leveraged and inverse ETFs** — multi-day
  returns can differ significantly from the stated multiple of the index
  return over the same period, especially in volatile markets.
- **Avellaneda & Zhang (2009), "Path-Dependence of Leveraged ETF Returns"
  (SSRN 1404708)** — formalizes the volatility-drag/path-dependence of
  daily-reset products; holding-period return depends on realized variance,
  not just the index's net move. This motivates the governed maximum holding
  period and the MANAGE-light path-dependence check.
- **Daniel & Moskowitz (2014/2016), "Momentum Crashes" (NBER w20439)** —
  bearish/short-side momentum is vulnerable to violent rebounds after market
  declines; positions betting on continued decline suffer their worst outcomes
  precisely in panic-rebound states. This motivates the anti-chase veto and
  the recovery vetoes rather than any belief that strength reliably continues
  or reverses.
- **Sponsor pages (ProShares)** — SH (-1x S&P 500, net expense ~0.88%), PSQ
  (-1x Nasdaq-100, ~0.95%), DOG (-1x Dow 30, ~0.95%), RWM (-1x Russell 2000,
  ~0.95%); each prospectus states the DAILY investment objective and the
  compounding risk for periods longer than one day.

**What the literature can and cannot establish about two consecutive positive
sessions:** it CANNOT establish a universal edge. Short-horizon studies find
both continuation and reversal depending on volatility, liquidity, and market
state; momentum-crash evidence specifically warns that post-decline rebounds
are violent and hard to time. Two green days is therefore, at best, an
execution-price filter inside an already-valid bearish regime — never a signal
that the market should be shorted. Our own pre-registered test (below) found
it FAILED even as a price filter, out-of-sample.

## 2. Current methodology (audited from code/config)

`config/defense_recommendations.json → hedge_playbook`: bearish eligibility
from the desk's sector-deterioration triggers + book exposure (the field-
guarded HEDGE card); instrument SH or PSQ by tech-led flag; entry after one
underlying bounce day ≥ +0.75%; three equal tranches; take-profit +8% (half)
and +15% (rest) on the INVERSE price; hard exit when the deterioration trigger
exits for two closes. Preserved as the backtest baseline.

## 3. Pre-registered backtest — results

Data: inception→2026-07-17 daily (SH/PSQ/DOG 2006-06, RWM 2007-01; 4,900–5,167
sessions each). Thesis proxy, grid, walk-forward, metrics, and promotion gates
were all fixed at `f2988645` before results.

**Train (SPY/SH 2006-2015):** baseline n=42; best two-day config
(min_daily 0.50%, cum 0.75%, ATR≥1.0, chase≤1.5 ATR, trend veto, 20-session
max hold) n=13 — `INSUFFICIENT N` already at selection time (noted, not hidden).

**Out-of-sample (frozen params, 4 pairs × 2016-2020 + 2021-2026) —
SIGNAL-WEIGHTED (v2 correction: cells weighted by trade count, not averaged
equally; the earlier unweighted table overstated magnitudes slightly without
changing the verdict):**

**DECISIVE ACCEPTED EVIDENCE (entry timing — unaffected by overlay corrections):**

| arm | total n | avg net ret | whipsaw | bench +5d after entry (AAE) | eff/day |
|---|---|---|---|---|---|
| baseline (+0.75% day) | 138 | −0.49% | 15.2% | **−0.54%** | −0.041 |
| two-day (frozen) | 56 | −0.58% | 16.1% | **+0.73%** | −0.115 |
| untimed (thesis-open) | 90 | −0.61% | 13.3% | −0.04% | −0.049 |

**CORRECTED OVERLAY EVIDENCE (v3: entry-day look-ahead REMOVED — hedge return
attribution runs t+1 through exit close; missing inverse observations excluded
+ counted, never fabricated as −benchmark; result JSON byte-deterministic with
full provenance):**

| arm | portfolio MDD reduction | downside β (hedged) | missing inverse obs |
|---|---|---|---|
| baseline | **+0.60 pp** | 0.980 | 0 |
| two-day (frozen) | **+0.07 pp** | 0.994 | 0 |
| untimed | +0.46 pp | 0.989 | 0 |

The earlier v2 overlay table carried entry-day look-ahead (it credited the
inverse ETF's signal-session return to a hedge entered at that session's
close); corrected, the two-day arm is no longer negative on MDD but remains
~8× weaker than baseline. The rejection NEVER rested on the overlay — the
decisive entry-timing gate stands on the corrected AAE/whipsaw/efficiency
numbers above.

**Verdict:** the two-day rule FAILS the DECISIVE ENTRY-TIMING gate (a) —
instead of improving avoided-adverse-entry by ≥25%, it inverted the sign: the
benchmark ROSE +0.73% (signal-weighted) in the five sessions after two-day
entries — the rule systematically buys the hedge into relief rallies that
continue — versus −0.54% after baseline bounce-day entries. Whipsaw worsened
slightly (16.1% vs 15.2%); per-dollar-day efficiency ~3× worse; and the
portfolio-MDD gate now also fails (−0.04 pp vs baseline +0.26 pp — a two-day-
timed hedge protects LESS than no hedge at all). Per-cell samples are mostly below
n=30 (`INSUFFICIENT N` marked in the results JSON), but the aggregate
direction is consistent across benchmarks and windows.

**Recommendation (from the pre-registered menu): REJECT TWO-DAY RULE** as the
actionable entry gate. The baseline +0.75% bounce-day filter is retained. The
two-day sequence is kept as SHADOW telemetry on the ENTRY light ("DAY 1 OF 2 —
WAIT" / "DAY 2 COMPLETE") so paper evidence continues accruing at zero risk;
a future governed amendment can re-test with more OOS data.

The hedge arms are net-negative in aggregate — expected and correct framing:
these are INSURANCE costs during bearish regimes, evaluated on drawdown
protection and timing quality, never promoted because the inverse ETF made money.

## 4. What was implemented

`scripts/defense_inverse_stoplights.py` — four independent LABELED lights
(THESIS/ENTRY/MANAGE/EXIT) per -1× candidate; THESIS derives from the desk's
own field-guarded HEDGE card (never a competing thesis); ENTRY computes from
the UNDERLYING benchmark only (bounce gate, 50DMA recovery veto, 1.5-ATR
anti-chase veto, exact arithmetic incl. day1/day2/two-day/ATR-normalized
values and contributing close dates); MANAGE covers objectives/drift/max-hold/
thesis-weakening; EXIT enforces thesis-exit-regardless-of-P&L, trend recovery,
max-hold (daily-reset products never outlive their reason), and
exposure-reduction. Immutable transition ledger
(`inverse_stoplight_transitions`) with factors, closes, policy version, commit
SHA, dedup (no repeated unchanged-state alerts). Beta-aware sizing:
`reduction × exposure × β_book ÷ |β_inv|`, clamped inside the 2–5% hard
envelope; below-floor results DISPLAY but never ticket; overlapping -1×
positions share one envelope. GREEN entry authorizes ONLY the Stage action.
SQQQ/SARK/REW listed LOCKED with reasons. UI: Defense rail + Home posture line,
every light labeled with arithmetic and freshness.

### Scope honesty (v2, validator finding): what the pre-registered framework
did and did not execute

The DECISIVE ENTRY-TIMING comparison was executed in full (grid, walk-forward,
freeze, OOS, now including max holds 5/10/15/20, signal-weighted aggregates,
portfolio-overlay MDD reduction, downside beta and downside capture). NOT
implemented from the registration: the three staging methods (single-entry
only — no tranche simulation), the prior-swing-low exit alternative, and
hedge-ratio rebalance thresholds. The correct claim is therefore: **"the
decisive entry-timing gate failed"** — not that every registered dimension
ran. Because gate (a) inverted its sign (the decisive gate), no unimplemented
dimension could rescue the rule; the timing-corrected overlay evidence
(+0.07 pp vs +0.60 pp MDD reduction) is consistent but SUPPORTING, not
decisive.

## 5. Limitations (honest)

- Thesis proxy in the backtest is mechanical (50DMA-based), coarser than the
  live desk's sector-RS triggers; results transfer with that caveat.
- Per-cell OOS samples are mostly `INSUFFICIENT N`; the rejection rests on the
  consistent aggregate direction plus the training result never being
  significant in the first place.
- Portfolio-overlay MDD metrics used a fixed 4% hedge weight proxy book.
- No live/paper stoplight outcomes exist yet.

## Status language (mandated)

- METHODOLOGY RESEARCHED: **YES**
- TWO-DAY RULE VALIDATED: **NO** (pre-registered gates failed out-of-sample)
- STOPLIGHTS OPERATIONALLY VERIFIED: **PARTIAL** — THESIS/ENTRY display + REAL
  MANAGE/EXIT position wiring (holdings-fed gain/held-sessions; drift labeled
  not-computable until sizing tickets); no completed hedge cycle yet
- PAPER OUTCOMES SUFFICIENT: **NO**
- LIVE EXECUTION ELIGIBLE: **NO**
