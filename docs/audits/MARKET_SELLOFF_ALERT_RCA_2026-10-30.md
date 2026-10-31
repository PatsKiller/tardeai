# Why no warning preceded the 2026-10-30 selloff — root cause analysis

```
Status:      ACTIVE
as_of:       2026-10-31T02:30Z
Measured at: live pin ~/trade-ai-releases/portfolio-server/7e9dc51a6-main-exact-phase2-20261030-162403 (served build on 2026-10-30), main fe1366a10
Design:      docs/designs/DSN-20261031-market-risk-engine.md
Author:      Claude (coordinator), operator-requested RCA 2026-10-30 evening
```

Evidence tags (AGENTS.md §4): `[VERIFIED]` a command was run and its output read; `[CODE]` source read; `[EXT]` external
market source, fetched 2026-10-31. This repository is public: no real position, share count, dollar amount or account
label appears here (AGENTS.md §2A). "Held growth-ETF exposure" stands for the positions that were stopped out.

## 1 · What happened

On Friday 2026-10-30 the Nasdaq Composite fell about 2.8–2.9%, the Nasdaq-100 about 4.2% (its third correction of 2026,
10% off the 10-06 record), the S&P 500 about 1.8% (through its 100-day average) and the Dow about 1.2%. Intel fell
25–30% on weak guidance, Amazon 6–12% on a miss and capex, AMD about 10%, Dell about 13%. VIX closed near 19–21
(+10–13%). Breadth: 26% advancers, 448 new 52-week lows against 230 on Thursday. October was the Nasdaq's worst month
since March 2025. `[EXT]`

Two held positions were stopped out during the session. The first word the operator received about either was the
`stop_health` TRIGGERED page at 10:10 ET, after the fills. `[VERIFIED alert_events, communication_events]`

### What the system said in the 72 hours before

| When (ET) | System output | Reality |
|---|---|---|
| 10-27 05:52 | `Market Regime Changed risk_on_trend → risk_off (conf 50%)` as a P2 inside quiet hours → **archived for the digest**, which renders held items only as `• kind ×n` | Inputs were the previous collector run's rows, whose "breadth" was a weekend scan count; a data artifact |
| 10-27 16:05 → 10-30 16:05 | Every snapshot `risk_on_trend`, confidence 0.33, with `trend_state=bearish`, `risk_appetite=bearish`, `liquidity/leadership/macro=unknown` | QQQ −2.7% on 10-29 and −2.1% on 10-30; the 10-30 16:05 collector row said VIX 21.3 `high`, the same-minute snapshot recorded `vix_close: normal` |
| 10-26..10-29 07:30 | Morning CIO brief `RISK ON TREND — SELECTIVE RISK` (10-27: `RISK OFF`) | — |
| 10-29 10:00 / 15:00 / 17:00 | Advice digests with 20 / 36 / 7 items, mostly `HIGH CONVICTION ENTRY` | Entry recommendations into a known mega-cap earnings cluster |
| 10-29 16:40 | `HIGH CONVICTION ENTRY` scalp alert on a semiconductor name | Intel guided down 16:05–16:30; that name was −8–10% by the next pre-market |
| 10-29 16:00 → 10-30 09:30 | No market-level message. 10-30 05:45 premarket pipeline: `No space left on device (os error 28)`; 07:30 morning brief `Brief API failed … RemoteDisconnected`; **0 operator sends 06:00–09:45 ET** | NQ futures −1.5% by 18:04 ET and −2.1% pre-market; Intel −20%+, AMD −8%, Dell −13% pre-market |

`[VERIFIED market_regime_snapshots, market_regime_indicators, communication_events, logs/regime_classifier.log,
logs/pipelines/premarket_cron.log, logs/morning_brief.log]`

## 2 · Signal availability — what existed and whether the system had it

### 72 hours and more (through Tue 10-27 close)
| Signal | Value | Did the system have it? |
|---|---|---|
| Semiconductor leadership collapse | SOX −15% month-to-date; 8-session losing streak ending 10-16 (longest since 2008); SMH −6.3% on 10-22 `[EXT; VERIFIED market_quotes]` | Quotes yes (SMH, SOXX); **no consumer** |
| Nasdaq-100 already 6.5% off the 10-06 record by 10-18 `[EXT]` | — | QQQ quotes yes; no drawdown feature |
| Credit, rates, oil stress mid-month | HY OAS 3.18 → 3.40 (10-15 → 10-22); 10-year 5.19% (10-14); WTI $96 → $110 (10-14 → 10-19) `[VERIFIED fred_economic_series]` | Ingested daily; **used only as LLM prompt text** |
| Tech sector state | XLK `LAGGING` 10-26, `WEAKENING` 10-27..29, sector breadth 33–42%; RSP−SPY `WEAKENING` 10-29 `[VERIFIED sector_momentum_state]` | Yes; transition alerts classify as telemetry → digest `[CODE]` |
| Hedge eligibility | PSQ `THESIS GREEN — HEDGE ELIGIBLE` 10-23; entry window `GREEN DAY 2 COMPLETE` 10-27; GREEN again 10-29 17:55 `[VERIFIED inverse_stoplight_transitions]` | Yes; `evaluate_all(..., notify=False)`, desk in SHADOW since 07-18 with an empty promote decision `[CODE]` |
| Scheduled catalyst cluster | FOMC 10-28; MSFT + GOOGL 10-28 after hours; AMZN + INTC 10-29 after hours; month-end 10-30; midterm election 11-03 `[EXT]` | FOMC in the macro calendar, per-symbol earnings dates in `symbol_profiles`; **no aggregation by index weight** |
| Implied volatility falling into the cluster | VIX 19.7 (10-23) → 17.5 (10-27); VVIX about 101; SKEW 151 `[EXT]` | VIX spot yes; VVIX, term structure, SKEW **not collected** |
| Seasonality | Midterm year; October positive in 77% of midterm years; S&P only 1.2% off its record `[EXT]` | Seasonality engine knows the cycle; influence capped at CIO language, **no alert path** |

### 48 hours (Wed 10-28 close)
S&P −1.0% from record, VIX 16.87 (week's low). QQQ closed at the exact 10-21 high (a failed retest the next day).
Alphabet −11–12% indicated after hours. System: `risk_on_trend` 0.33 from stale rows; brief `RISK ON TREND`.
`[VERIFIED market_quotes, fred; EXT]`

### 24 hours (Thu 10-29)
- **10:00 ET:** QQQ put/call open interest 1.375 → **2.856**, put/call volume 0.96 → **3.31**; SPY put/call OI 0.90 →
  1.51. `[VERIFIED option_chain_snapshots]` The system wrote these numbers; nothing read them.
- **Close:** QQQ −2.7%, SMH −2.4%, XLK −1.2%, SPY −0.9%; VIX **16.59, down** on the day (volatility/price divergence);
  RSP−SPY `WEAKENING`; 230 new 52-week lows; more than 60% of S&P constituents at least 20% below their 52-week highs.
  `[VERIFIED; EXT]`
- **16:05–18:04 ET:** Amazon −6%, Intel −21–23% after hours; NQ futures −1.5% to −2%. `[EXT]` No component evaluates
  after-hours prints or futures.
- **17:55:** PSQ `THESIS GREEN` again. Not sent.

### Pre-market 10-30
NQ futures −2.1%; Intel −20%+; AMD −8%; Dell −13%. `[EXT]` System: premarket pipeline dead (disk full), morning brief
dead, zero sends 06:00–09:45 ET. `[VERIFIED]`

## 3 · Root causes, ranked by contribution

1. **No market-level risk model exists.** The regime classifier's inputs are internal activity proxies: `scan_breadth_24h`
   is the number of distinct symbols the scanner touched in 24h (`>50 → broad`), `scan_score_avg` is the mean of the
   system's own scan scores, `gap_volatility_proxy` the mean absolute gap of scanned names. `INDEX_SYMBOLS` and
   `SECTOR_ETFS` are declared and never fetched; `liquidity_state`, `leadership_state` and `macro_state` are the literal
   string `unknown`. `[CODE scripts/market_regime_collector.py, scripts/market_regime_classifier.py]`
2. **The classifier scored stale rows.** `classify(conn)` read `ORDER BY created_at DESC LIMIT 20` across collector
   runs and overwrote the dict key by key, so the oldest of about three runs won each key. The 10-30 16:05 indicator
   rows say `vix_close 21.3 high`, `gap 4.52 high_vol`; the snapshot written one second later says `normal` and
   `neutral`. The label lagged about 1.5 trading days. `[VERIFIED + CODE]` Fixed by PR P0-T1.
3. **The only market alert was a P2 label-change ping that quiet hours buried.** Fires only when the label changes;
   P2 is held 22:00–07:00 ET, so the 05:51 pre-market run is always archived; the digest shows held items as
   `• kind ×n`; a fatigue rule downgrades after three days; exceptions were swallowed. The one `risk_off` alert of the
   week came from a weekend scan-count artifact and reverted the same afternoon. `[CODE alert_dispatcher.py,
   telegram_alert_router.py, lib/advice_digest.py; VERIFIED regime_classifier.log]` Fixed in part by PR P0-T2.
4. **Data the system already owned was never thresholded.** Index put/call OI and volume (`option_chain_snapshots`,
   10:00 and 17:35), FRED credit, rates, oil and dollar series, sector states and style pairs, hedge stoplights
   (`notify=False`), FRED VIX (two-day lag, consumed only into an agent queue at 25+). `[CODE]` Options flow fixed by
   PR P0-T6; the rest is the Market Risk Engine (design P1–P2).
5. **No event-concentration risk and no entry gate.** FOMC plus about a quarter of index market cap reporting within
   48 hours plus month-end plus the midterm election three sessions out was knowable weeks ahead. Nothing aggregates
   `earnings_date` by index weight or by held-ETF look-through. Entry recommendations and a new position inside the
   window had no event or regime gate: `opportunity_conviction.yaml` has no market-risk factor; the cash gate only
   held on the literal label `risk_off` and did not recognise the classifier's `high_volatility` label (same mismatch
   in `config/cio_situations.yaml`). `[CODE]` Label mismatch fixed by PR P0-T3; gating is design P3.
6. **No extended-hours or pre-market market evaluation.** After-hours collapses of index heavyweights are not mapped
   to held-ETF look-through exposure; futures and ETF extended prints are not read; the 04:00/07:00 "Market:" header
   printed `+0.00%` against stale closes. `[CODE; VERIFIED communication_events]` Header fixed by PR P0-T9; the
   evaluation is design P1–P2.
7. **Operational outage on the day.** Disk full at 05:45 killed the 37-step premarket pipeline (FRED, regime,
   catalysts); the morning brief failed at 07:30; no dead-man paged "pre-market brief not delivered". The disk was a
   known open item. `[VERIFIED]` Dead-man added by PR P0-T4; runner resilience by PR P0-T5.
8. **Volatility is a confirmation input, not a forecast.** VIX above 20 adds one point to risk-off; a VIX falling while
   the Nasdaq drops 2.7% into a catalyst cluster cannot be represented. No VVIX, no VIX9D/VIX3M term structure, no
   SKEW, no realized-versus-implied. `[CODE]`
9. **Stops are static percentage bands.** The only regime linkage is a one-point cap shrink on a `risk_off` label that
   never held, flowing through a 17:05 advisor into a 17:35 ratchet-up alert. The hybrid trailing policy is disabled by
   policy. `[CODE config/stop_policy.yaml, scripts/holding_family.py]`
10. **Channel saturation.** 642 ops/info messages on 10-27 alone; scalp headers with impossible values
    (`SPY +29.30%` on a +0.29% day, a percent field multiplied by 100). A real warning would compete with hundreds of
    telemetry messages. `[VERIFIED communication_events; CODE scripts/market_context.py]` Header fixed by PR P0-T9;
    noise scoring is design P2.

### Flawed assumptions in the existing framework
- "Breadth" can be proxied by how many names the scanner touched.
- An argmax of seven points is a risk measure, and 0.33 confidence is actionable.
- A P2 label-change alert is sufficient market-risk communication; quiet hours apply equally to pre-market market risk.
- Per-symbol stop-proximity alerts protect the book; market-level drawdown risk needs no separate signal.
- Sector state relative to SPY detects a broad selloff (it cannot: relative strength is unchanged when everything falls).
- Hedge logic that arms only after the index is below its 50-day average and bounces is "defense".
- Entry conviction is independent of the market event calendar.
- A green pipeline receipt yesterday means today's pre-market ran.

## 4 · Verdict and what should have happened

**Partially predictable.** Direction and the elevated probability of a large move inside 72 hours were knowable. The
exact day and the size of the Intel reaction were not knowable before 10-29 16:05 ET.

| Should-have | Tier | Evidence available at that time |
|---|---|---|
| Thu 10-16 close | **Yellow** | SOX 8-session losing streak, −15% MTD; VIX 19.99 on OPEX day; HY OAS widening; 10-year at or above 5% |
| Fri 10-23 close / Mon 10-26 | **Yellow → Orange watch** | QQQ −3% from 10-21, SMH −6% day; XLK LAGGING with 33% breadth; PSQ hedge-eligible (the system's own stoplight); catalyst cluster T−3/T−4 with tech book weight at the hedge trigger; no new entries in the window |
| Wed 10-28 close | **Orange** | QQQ failed retest of the 10-21 high; FOMC done; GOOGL −11% after hours; AMZN/INTC next; VIX at the week's low (divergence). Action: stop review on growth-ETF exposure and recent entries; hedge evaluation |
| Thu 10-29 10:15 ET | **Orange (confirmed)** | QQQ put/call OI 2.86 and volume 3.31 (system data) plus QQQ −2% intraday |
| Thu 10-29 18:00 ET | **Red** | AMZN −6%, INTC −22% after hours, NQ −1.5–2%, 230 new lows at the close, RSP−SPY weakening. Action: stops to band minimum on mega-cap growth exposure, pre-market stop review, hedge evaluation, hold cash deployment |
| Fri 10-30 05:00–09:00 ET | **Red (reaffirmed)** | NQ −2.1%, INTC −20%, AMD −8%, DELL −13% pre-market |

The stop on the held growth-ETF exposure sat about 4% under the 10-29 close; a Red-tier "raise to band minimum or
consider a pre-open trim" was the only decision that could have changed the outcome, and the system owned no
recommendation for it. The position opened 10-26 inside the event window should have been flagged by an event gate.

### Ranking of missing indicators by predictive value for this event
1. Extended-hours heavyweight earnings reaction → index futures or ETF extended prints → look-through to held ETFs (Red at 10-29 about 18:00)
2. Event-concentration score: FOMC + mega-cap earnings cluster + month-end + election (Orange from 10-26)
3. Index put/call OI and volume surge — data already in `option_chain_snapshots` (Orange 10-29 10:15)
4. Semiconductor leadership drawdown and losing-streak features (Yellow from 10-16)
5. Volatility/price divergence, VIX term structure, VVIX (Orange 10-29 close)
6. Market breadth: new-low expansion, percent above 20/50/200-day averages, A/D, RSP−SPY (Yellow 10-29)
7. Existing sector-state and hedge-stoplight outputs, simply delivered (Yellow 10-23 / 10-27)
8. Credit, rates and oil stress (background Yellow mid-month; tightened into the event)
9. Seasonality (low value; bullish-biased for a midterm October)

## 4A · The operator failure question — exact time, channel, severity, message

System-owned data is marked ◆, external market data ○. Message bodies are what the engine would have sent; every
number is one the system held or could have fetched at that minute. Portfolio figures are redacted.

| # | Timestamp (ET) | Tier | Channel | Message |
|---|---|---|---|---|
| 1 | **Fri 10-16 17:30** | YELLOW | Telegram P2 + digest header + Risk page | `MARKET RISK YELLOW 42/100 · Semis: SOX 8th straight down day (longest since 2008), −11% this week ○ · VIX 19.99 on OPEX (+21% w/w) ◆ · HY OAS 3.31 (+8bp w/w) ◆ · 10y 5.09% ◆. Confirming: volatility, cross_asset, technical (3). Review: stops on growth/semis exposure; no new tech entries without a catalyst gate. P(SPX ≥1.5% move, 5d) 38%.` |
| 2 | Mon 10-26 06:30 | YELLOW (reaffirmed, event flag) | Telegram P2 (pre-market exempt from quiet hold) + morning brief line | `MARKET RISK YELLOW 47/100 · Event cluster T−2..T−3: FOMC Wed 14:00; MSFT+GOOGL Wed AH; AMZN+INTC Thu AH ≈ 25% of index cap in 48h; month-end Fri; midterms Tue ○◆ · XLK LAGGING (breadth 33%) ◆ · PSQ hedge thesis GREEN since 10-23 ◆ · VIX 18.4 falling ◆. Your book: held growth-ETF and tech look-through exposure is above its budget; no event gate on new entries this week.` |
| 3 | **Wed 10-28 16:30** | **ORANGE** | Telegram P1 + email | `MARKET RISK ORANGE 63/100 · QQQ 725.59 = failed retest of 10-21 high ◆ · VIX 16.9 at week low into 2 mega-cap earnings nights (complacency divergence) ◆ · Event concentration 88/100 ○◆ · XLK WEAKENING 42% breadth ◆. Confirming: event, volatility, technical, breadth (4). Analogs: 2026-03, 2025-03. P(NDX ≥3% move, 72h) 61%, P(down) 58%. Evaluate: raise stops toward band minimum on the growth-ETF exposure (top holdings report tonight and tomorrow) and the 10-26 entry; hedge evaluation (PSQ window per stoplight).` |
| 4 | Wed 10-28 about 18:30 | ORANGE (update) | Telegram P1 | `ORANGE update · GOOGL −11% after hours on FCF miss ○; MSFT +2% ○. Growth-ETF look-through to GOOGL+AMZN+MSFT ≈ 20% ◆. Tomorrow: AMZN, INTC after close. Pre-market re-evaluation 05:00.` |
| 5 | **Thu 10-29 10:15** | ORANGE (confirmed) | Telegram P1 | `ORANGE confirmed 68/100 · QQQ put/call OI 1.38 → 2.86, put/call volume 0.96 → 3.31 at 10:00 (2.9× 20-day median) ◆ · SPY put/call OI 0.90 → 1.51 ◆ · QQQ −2.1% intraday ◆ · VIX 16.9 unchanged (divergence) ◆. Institutional hedging surge while retail scalp flow is bullish. Stop review now: the growth-ETF stop is about 4.5% below last; book growth exposure at the 85th percentile.` |
| 6 | **Thu 10-29 18:15** | **RED — ack required** | Telegram P1 + email + SMS; repeat 18:30, 19:00, 20:00 until ACK | `🔴 RED ALERT ACTIVE — acknowledgment required · Risk 83/100 · Contributors: futures/extended-hours −18 (NQ −1.6% 18:04) ○, event −17 (INTC −22% AH on Q4 guide; AMZN −6% AH) ○, options flow −15 (QQQ P/C vol 3.31) ◆, breadth −14 (230 new lows; RSP−SPY turned WEAKENING) ◆, semis −11 (SMH −2.4%, SOX −15% MTD) ◆○. Portfolio vulnerability 78/100 (growth ETF + semis-adjacent + a 4-day-old entry with earnings 11-03) → tier uplift applied. Defensive actions to evaluate before 09:30: stops to band minimum on event-exposed holdings, pre-open trim, PSQ hedge, hold cash deployment, cancel pending entries. Reply ACK RED or tap Acknowledge.` |
| 7 | Fri 10-30 05:00 and 08:30 | RED (reaffirmed; repeats until ACK) | Telegram P1 + SMS | `🔴 RED still active (not acknowledged) · NQ futures −2.1% ○ · INTC −20%, AMD −8%, DELL −13% pre-market ○ · VIX 19.4 (+17%) ◆ · Two held positions have stops within 2% of their pre-market indication ◆. Pre-market brief: DEGRADED (pipeline disk full) — this alert is on the independent host path.` |

What actually went out: none of the above. The first market-relevant operator message was `CRITICAL STOP ALERT` after
the fills at 10:10 ET on 10-30.

## 5 · What this RCA changed, and what it hands to the design

| Finding | Fix | Where |
|---|---|---|
| 2 classifier stale read; 3 P2 ping | PR P0-T1/T2: latest snapshot only, scan activity not scored, risk-off change is a P1 operator intent, errors surfaced | `scripts/market_regime_classifier.py` |
| 5 label mismatch | PR P0-T3: `high_volatility` recognised by the cash gate and S8 | `scripts/lib/cio_cash_capital_v1.py`, `config/cio_situations.yaml`, `scripts/lib/cio_situation_detector.py` |
| 7 silent outage | PR P0-T4 dead-man (health-tick step, P1 with repeats); PR P0-T5 runner disk preflight, log fallback, receipt-failure paging | `scripts/check_premarket_delivery.py`, `scripts/pipelines/_manifest_runner.sh` |
| 4 unread options flow | PR P0-T6: index put/call versus its own median → P1/P2 card | `scripts/lib/market_risk/options_flow.py`, `config/market_risk_policy.yaml` |
| 6, 10 header | PR P0-T9: change% from prices, stale says prev close, implausible says n/a | `scripts/market_context.py`, `scripts/telegram_alert.py`, `scripts/continuous_runner.py` |
| 1, 4, 5, 6, 8, 9 | Market Risk Engine, phases P1–P4 | `docs/designs/DSN-20261031-market-risk-engine.md` |
| Stoplight notify (operator) | P0-T7 proposal: promote SHADOW → notify on hedge transitions | operator decision |

Open items opened by this RCA: see `docs/governance/OPEN_ITEMS.md` rows OI-136 onward.
