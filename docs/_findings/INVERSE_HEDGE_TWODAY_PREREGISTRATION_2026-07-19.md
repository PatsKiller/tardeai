# Inverse-ETF Hedge — Two-Day Entry Rule: PRE-REGISTERED Backtest Specification

Status:      HISTORICAL
as_of:       2026-07-19T17:00:15-04:00
Measured at: efcc51365 / not measured

**Registered 2026-07-19, BEFORE any performance results were computed.** Committed
to git as the tamper-evident record; the results memo must cite this SHA.

## Hypothesis under test

Within an ACTIVE bearish thesis, entering the -1× inverse ETF after **two
consecutive completed positive underlying-index sessions** produces better
hedge economics than the current baseline (one +0.75% bounce day). Two positive
days are an ENTRY-PRICE FILTER only — they never create the thesis.

## Instruments (research lane)

SH/SPY · PSQ/QQQ · DOG/DIA · RWM/IWM (inception → 2026-07-18, Schwab daily
history, split/distribution-adjusted closes; source documented in the fetch
script). SQQQ/SARK/REW are researched separately and remain LOCKED from
actionable recommendations regardless of results.

## Thesis proxy (mechanical, replayable — HONEST LIMITATION)

The live desk's deterioration triggers (sector RS states, book exposure) cannot
be replayed to 2006. The pre-registered mechanical proxy for THESIS GREEN:

- benchmark close < its 50DMA, AND
- 50DMA slope negative over the trailing 10 sessions, AND
- benchmark close < close 20 sessions ago (down tape).

THESIS exits (RED) when the benchmark closes above the 50DMA for **two
consecutive sessions** (mirrors the desk's 2-close trigger exit).
This proxy is coarser than the live desk; results transfer with that caveat.

## Baseline (current desk behavior, preserved as comparator)

- Eligibility: proxy THESIS GREEN.
- Entry: first session with benchmark day-return ≥ +0.75% while GREEN.
- Tranches: 3 equal thirds on consecutive qualifying bounce days.
- Take-profit: +8% (half) and +15% (rest) on the INVERSE ETF price.
- Hard exit: thesis RED (2-close recovery) closes everything.

## Candidate grid (fixed BEFORE results)

- Min daily return (each of the 2 days): >0, ≥+0.25%, ≥+0.50%, ≥+0.75%
- Two-day cumulative minimum: ≥+0.75%, ≥+1.00%, ≥+1.50%
- ATR(14)-normalized cumulative bounce minimum: 0.50, 0.75, 1.00 ATR
- Anti-chase veto (2-day bounce too extended): >1.5 ATR, >2.0 ATR
- Trend recovery veto: close > 50DMA on day 2 (voids entry)
- Max holding period: 5, 10, 15, 20 sessions
- Exits compared: baseline +8/+15 inverse-price vs underlying −1.5 ATR
  adverse-move stop + prior-swing-low objective vs thesis-exit-only
- Staging compared: single 100% at window-open · 3 equal thirds ·
  25/25/50 (T3 only on renewed rollover: close < min(prior 5 closes))

## Walk-forward design

Expanding window: parameters selected on 2006–2015 (SPY/SH pair primary), then
FROZEN and evaluated 2016–2020, 2021–2026 out-of-sample; per-benchmark results
reported separately. No full-sample selection reported as validation.

## Success metrics (hedge-first ranking, pre-registered order)

1. Portfolio max-drawdown reduction (proxy book: 100% benchmark long, hedged
   at 4% of equity in -1× while position open)
2. Downside beta / downside capture reduction
3. Hedge efficiency per dollar-day of hedge held
4. Avoided adverse entry excursion (entry price vs 5-session-later price)
5. Whipsaw rate (entries closed by thesis-exit within 3 sessions at a loss)
6. False-entry frequency; time held; turnover & friction
   (spread 3 bp + commission $0 + expense accrual 0.90%/yr held-time)
7. Return / win rate / Sharpe reported but NEVER promoted on alone

**Minimum sample: 30 completed signals per arm** — below that, every
conclusion is marked `INSUFFICIENT N`.

## Promotion gates (pre-registered)

PROMOTE TO PAPER only if, out-of-sample, the two-day rule vs baseline shows:
(a) avoided adverse entry excursion improves ≥ 25%, AND (b) whipsaw rate does
not worsen by more than 10% relatively, AND (c) portfolio MDD reduction is not
worse than baseline by more than 0.5 pp, AND (d) N ≥ 30 both arms.
Otherwise KEEP IN SHADOW or REJECT per the evidence.
