---
id: DSN-20261031-market-risk-engine
title: Market Risk Engine — predictive, portfolio-aware market risk alerting
status: IN_PROGRESS
approval: approved (operator, Claude Code session 2026-10-31, plan "Root cause of the missing 2026-10-30 selloff warning, and a predictive Market Risk Engine"); P1+ new stores, schedules, policy values and the independent host remain operator decisions (AGENTS.md §17)
source: docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md
summary: Replace reactive, per-symbol alerting with a deterministic, model-free market-level risk engine (nine signal categories,
  multi-category confirmation, Blue/Yellow/Orange/Red/Green tiers, portfolio-exposure uplift, mandatory Red acknowledgment,
  explainability, scenario-library calibration, independent alert host). P0 fixes the defects the RCA found in the existing path.
phases:
- id: DSN-20261031-market-risk-engine-P0
  title: Hotfixes to the existing path (RCA findings 2, 3, 5, 7, 4, 10)
  status: IN_PROGRESS
  tasks:
  - {id: DSN-20261031-market-risk-engine-P0-T1, title: 'Regime classifier reads the latest collector snapshot only; scan activity not scored', status: IN_PROGRESS, areas: [scripts/market_regime_classifier.py]}
  - {id: DSN-20261031-market-risk-engine-P0-T2, title: 'Regime change into risk_off/high_volatility is a P1 operator-action intent; errors surfaced', status: IN_PROGRESS, areas: [scripts/market_regime_classifier.py]}
  - {id: DSN-20261031-market-risk-engine-P0-T3, title: 'CIO cash gate and S8 recognise high_volatility', status: IN_PROGRESS, areas: [scripts/lib/cio_cash_capital_v1.py, config/cio_situations.yaml, scripts/lib/cio_situation_detector.py]}
  - {id: DSN-20261031-market-risk-engine-P0-T4, title: 'Pre-market dead-man health-tick step (P1, hourly repeats)', status: IN_PROGRESS, areas: [scripts/check_premarket_delivery.py, config/health_tick_steps.json, config/lane_registry.json]}
  - {id: DSN-20261031-market-risk-engine-P0-T5, title: 'Manifest runner: disk preflight pages P1, log fallback, receipt-failure paging', status: IN_PROGRESS, areas: [scripts/pipelines/_manifest_runner.sh, scripts/pipelines/pipeline_disk_alert.py, config/pipelines/runner_disk_policy.json]}
  - {id: DSN-20261031-market-risk-engine-P0-T6, title: 'Index options-flow detector on option_chain_snapshots (first engine module)', status: IN_PROGRESS, areas: [scripts/lib/market_risk/, config/market_risk_policy.yaml, scripts/options_chain_snapshot.py]}
  - {id: DSN-20261031-market-risk-engine-P0-T7, title: 'OPERATOR: promote defense inverse-stoplight notify (SHADOW since 2026-07-18)', status: PROPOSED, owner: OPERATOR, areas: [scripts/defense_inverse_stoplights.py, config/promote_criteria.json]}
  - {id: DSN-20261031-market-risk-engine-P0-T8, title: 'Email/SMS routes for stop_health, regime_change, market_risk — folded into P3-T1 (the incident-notifier mirror carries only comms-intent kinds)', status: HELD, areas: [config/comms_email_mirror.json]}
  - {id: DSN-20261031-market-risk-engine-P0-T9, title: 'Market header honesty: change% from prices, stale says prev close, implausible says n/a', status: IN_PROGRESS, areas: [scripts/market_context.py, scripts/telegram_alert.py, scripts/continuous_runner.py, config/market_context_policy.json]}
  - {id: DSN-20261031-market-risk-engine-P0-T10, title: 'Docs: redacted RCA, this design, OPEN_ITEMS rows, incident record', status: IN_PROGRESS, areas: [docs/audits/, docs/designs/, docs/governance/OPEN_ITEMS.md]}
- id: DSN-20261031-market-risk-engine-P1
  title: Data — registry rows first, then writers
  status: PROPOSED
  tasks:
  - {id: DSN-20261031-market-risk-engine-P1-T1, title: '§7A registry PR: market_breadth_daily, market_risk_snapshots, market_internals_intraday, institutional_flow_daily, option_chain_strikes, etf_holdings_snapshot, market_risk_episodes rows (nothing calls them yet) — STOP for operator grants', status: PROPOSED, areas: [config/data_source_authority.json, docs/architecture/DATA_DICTIONARY.md]}
  - {id: DSN-20261031-market-risk-engine-P1-T2, title: 'Collector: vol complex ^VIX ^VVIX ^VIX9D ^VIX3M ^VXN ^SKEW (same Yahoo provider; UVXY/VIXY fallback); fetch the declared INDEX_SYMBOLS', status: PROPOSED, areas: [scripts/market_regime_collector.py]}
  - {id: DSN-20261031-market-risk-engine-P1-T3, title: 'FRED ingest: 400-observation window per series (idempotent upsert) so changes and z-scores exist', status: PROPOSED, areas: [scripts/external_market_data_ingest.py]}
  - {id: DSN-20261031-market-risk-engine-P1-T4, title: 'Quotes writer: market_risk_universe on extended-hours cadence 04:00-09:30 / 16:00-20:00 ET (registry + dispatcher change, shared-infra)', status: PROPOSED, areas: [scripts/lib/writers/market_quotes_writer.py, config/lane_registry.json]}
  - {id: DSN-20261031-market-risk-engine-P1-T5, title: 'market_breadth_writer: S&P 500 / Nasdaq-100 membership (Finviz export by header) × Alpaca daily bars → %>20/50/200-DMA, NH/NL, A/D, McClellan', status: PROPOSED, areas: [scripts/lib/writers/market_breadth_writer.py]}
  - {id: DSN-20261031-market-risk-engine-P1-T6, title: 'event_calendar: index-weight earnings concentration (1/3/5 sessions), FOMC/CPI/NFP, OPEX/month-end/election tags', status: PROPOSED, areas: [scripts/lib/market_risk/event_calendar.py]}
  - {id: DSN-20261031-market-risk-engine-P1-T7, title: 'Institutional flow ingest: DIX/GEX (SqueezeMetrics), CFTC COT, ICI flows (new providers, grants first); per-strike chain aggregates + computed GEX/DEX; ETF shares-outstanding deltas; paid sweep/block feeds declared no_coverage until funded', status: PROPOSED, areas: [scripts/lib/writers/institutional_flow_writer.py, scripts/options_chain_snapshot.py]}
  - {id: DSN-20261031-market-risk-engine-P1-T8, title: 'Market internals intraday writer: A/D, up/down volume, TRIN, NH/NL, cumulative A/D, volume breadth every 15 min RTH; probe Schwab $TICK and record honestly', status: PROPOSED, areas: [scripts/lib/writers/market_internals_writer.py]}
  - {id: DSN-20261031-market-risk-engine-P1-T9, title: 'ETF look-through holdings ingest (top-25 per held/watched ETF) + positions_store reader-batch proposal for the engine (§7A rule 8, operator)', status: PROPOSED, areas: [scripts/lib/writers/etf_holdings_writer.py, config/data_source_authority.json]}
- id: DSN-20261031-market-risk-engine-P2
  title: Engine (shadow)
  status: PROPOSED
  tasks:
  - {id: DSN-20261031-market-risk-engine-P2-T1, title: 'features/scoring/probabilities/analogs/alerts modules; market_risk_evaluate.py (--dry-run default, --as-of replay, --receipt); snapshot store; data_broker projection market_risk; GET /api/v2/market-risk/latest', status: PROPOSED, areas: [scripts/lib/market_risk/, scripts/market_risk_evaluate.py, scripts/lib/data_broker/catalog.py, scripts/api_v2.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T2, title: 'Backtest harness over market_ohlcv_bars + FRED CSVs; tier timeline, hit rates per horizon, Brier → docs/audits/MARKET_RISK_ENGINE_BACKTEST_<date>.md', status: PROPOSED, areas: [scripts/market_risk_backtest.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T3, title: 'Replay acceptance test reproducing the RCA §4A timeline (Yellow 10-16 17:30, Orange 10-28 16:30, confirmed 10-29 10:15, Red 10-29 18:15 with uplift, repeats until ACK; no Red 10-26..10-28; ≤2 Orange sessions in a calm month; five contributors sum to the score)', status: PROPOSED, areas: [tests/test_market_risk_replay_20261030.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T4, title: 'Ten-trading-day shadow run via the dispatcher in dry_run, reviewed daily on the Risk page', status: PROPOSED, areas: [config/lane_registry.json]}
  - {id: DSN-20261031-market-risk-engine-P2-T5, title: 'Correlation anomaly engine (SPY↔VIX/TLT/UUP/HYG/RSP/GLD, QQQ↔SMH; 20-session corr vs 1y z; sign flips held 3 sessions) with positive-control test', status: PROPOSED, areas: [scripts/lib/market_risk/correlations.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T6, title: 'AI concentration module (basket weight, participation, RS vs RSP, drawdown, earnings sensitivity ≥15% of cap in 48h → event STRESS)', status: PROPOSED, areas: [scripts/lib/market_risk/ai_concentration.py, config/market_risk_policy.yaml]}
  - {id: DSN-20261031-market-risk-engine-P2-T7, title: 'Explainability: top-5 contributors with points that sum to the score, as_of per contributor, de-escalation sentence; BEHAVIOR_FIELDS scan at the card boundary', status: PROPOSED, areas: [scripts/lib/market_risk/explain.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T8, title: 'Exposure-aware severity: portfolio vulnerability 0-100 (sector/style/AI/look-through/earnings-48h/stop distance/unprotected/recent entries) and one-tier uplift', status: PROPOSED, areas: [scripts/lib/market_risk/exposure.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T9, title: 'Portfolio risk budget: proposed defaults in config/portfolio_risk_budget.yaml (operator sets), breach lines in every card, shared uplift cap; never resizes', status: PROPOSED, areas: [scripts/lib/market_risk/risk_budget.py, config/portfolio_risk_budget.yaml]}
  - {id: DSN-20261031-market-risk-engine-P2-T10, title: 'Confidence decay 1.0/0.8/0.6/0.4 at 0/24/48/72h unless reconfirmed; UNKNOWN rendered, never zero', status: PROPOSED, areas: [scripts/lib/market_risk/scoring.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T11, title: 'Opening shock detector 09:16-09:46 ET: gap/ATR, opening range, first-15 internals; gap-and-go / gap-fade / panic open (single-evaluation Red)', status: PROPOSED, areas: [scripts/lib/market_risk/opening_shock.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T12, title: 'Scenario replay library (COVID, 2022 bear, 2023 bank panic, 2024-08 vol shock, 2018-12 → 2019-01, 2023 AI melt-up, 2024-09 cut rally, 2023-12 Santa, three 2026 corrections, calm controls); probability tables regenerated from it; analogs excluded from scoring by test', status: PROPOSED, areas: [tests/fixtures/market_risk_scenarios/, scripts/market_risk_backtest.py]}
  - {id: DSN-20261031-market-risk-engine-P2-T13, title: 'Signal-to-noise scoring per category; weekly noise report; elevated_risk_quiet_mode router rule (P1 stop_health and market_risk always deliver) — delivery policy PR, shared-infra', status: PROPOSED, areas: [scripts/lib/market_risk/snr.py, scripts/telegram_alert_router.py]}
- id: DSN-20261031-market-risk-engine-P3
  title: Delivery, UI, integration
  status: PROPOSED
  tasks:
  - {id: DSN-20261031-market-risk-engine-P3-T1, title: 'comms_categories market_risk; pre-market quiet-hours exemption for market_risk P2; email route; Red → delivery_failure_alerts pager transport (delivery policy, §24.1)', status: PROPOSED, areas: [config/comms_categories.yaml, scripts/telegram_alert_router.py, config/comms_email_mirror.json]}
  - {id: DSN-20261031-market-risk-engine-P3-T2, title: 'Risk page panel + Home/Watch banner: design/pages/risk/vNNN (412/390 px) → operator approval → UI PR', status: PROPOSED, areas: [design/pages/risk/, apps/command-center-v3/src/]}
  - {id: DSN-20261031-market-risk-engine-P3-T3, title: 'CIO integration: market_risk projection in cio_market_context_state; brief/digest open with the tier line; opportunity_conviction market_risk_gate (operator policy)', status: PROPOSED, areas: [scripts/lib/cio_market_context_state.py, config/opportunity_conviction.yaml, scripts/cio_opportunity_curator.py]}
  - {id: DSN-20261031-market-risk-engine-P3-T4, title: 'Stop review at Orange+: holding_protection_advisor ad-hoc run (regime forced risk-off) → P1 list of held names and look-through exposure; no stop values written', status: PROPOSED, areas: [scripts/holding_protection_advisor.py]}
  - {id: DSN-20261031-market-risk-engine-P3-T5, title: 'Hedge notify: inverse stoplight transitions as P2 when tier ≥ Orange (depends on P0-T7)', status: PROPOSED, areas: [scripts/defense_inverse_stoplights.py]}
  - {id: DSN-20261031-market-risk-engine-P3-T6, title: 'Lane activation: market-risk-evaluate, market-breadth-daily, market-internals-intraday, institutional-flow-daily, etf-holdings-weekly, extended-hours quotes → §25.10.2 in-session approval, forced run, natural fire monitored', status: PROPOSED, areas: [config/lane_registry.json]}
  - {id: DSN-20261031-market-risk-engine-P3-T7, title: 'Mandatory escalation + ACK: market_risk_episodes store, repeats +15/+30/+60 then hourly (cap 12) inside the evaluate lane, Telegram ACK RED → operator_decisions, POST /api/v2/market-risk/ack, 75-min stalled-escalation dead-man', status: PROPOSED, areas: [scripts/lib/market_risk/escalation.py, scripts/api_v2.py]}
  - {id: DSN-20261031-market-risk-engine-P3-T8, title: 'Independent alert host: design doc; Host A mirror_client.py + alert_heartbeat.py; Host B receiver/sender/market-shock watchdog; operator provisions host + credentials; 20-minute egress drill', status: PROPOSED, areas: [docs/architecture/INDEPENDENT_ALERT_HOST.md, scripts/lib/market_risk/mirror_client.py, scripts/alert_heartbeat.py]}
- id: DSN-20261031-market-risk-engine-P4
  title: Learning and calibration
  status: PROPOSED
  tasks:
  - {id: DSN-20261031-market-risk-engine-P4-T1, title: 'Outcome scorer: +24h/+72h/+1w realized SPX/NDX and VIX per tier transition → alert_effectiveness; weekly calibration report (Brier, precision/recall)', status: PROPOSED, areas: [scripts/market_risk_calibration.py]}
  - {id: DSN-20261031-market-risk-engine-P4-T2, title: 'Green (opportunity) tier tuning on the 2026 corrections recovery legs', status: PROPOSED, areas: [config/market_risk_policy.yaml]}
  - {id: DSN-20261031-market-risk-engine-P4-T3, title: 'Threshold proposals as PRs with calibration evidence; never auto-applied', status: PROPOSED, areas: [config/market_risk_policy.yaml]}
  - {id: DSN-20261031-market-risk-engine-P4-T4, title: 'Weekly SNR noise report + digest-only routing proposals; quarterly scenario re-run with live data appended (10-30 becomes a permanent fixture)', status: PROPOSED, areas: [scripts/lib/market_risk/snr.py, tests/fixtures/market_risk_scenarios/]}
---

# Market Risk Engine (MRE)

```
Status:      ACTIVE (design approved; P0 in PRs; P1+ proposed)
as_of:       2026-10-31T02:40Z
Measured at: not measured — design; the RCA it answers is measured at pin 7e9dc51a6
```

**Why.** The 2026-10-30 selloff RCA (`docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md`) found no market-level risk
model, a classifier scoring stale rows, a single P2 alert path that quiet hours bury, owned data never thresholded,
no event-concentration or extended-hours evaluation, and a silent outage on the morning itself. Verdict: partially
predictable — Yellow from 10-16, Orange by the 10-28 close, Red by 10-29 18:00 ET. The engine exists to produce that
timeline before the move, portfolio-aware, acknowledged, explained, and on a path that survives a dead host.

**Principles.** Deterministic feature layer; no model in detection; probabilities from empirical conditional
frequencies over a scenario library, never from an LLM or nearest-neighbour similarity (analogs explain, never score);
`MBI_BEHAVIOR = 0` — every output is a recommendation to review, never a size, order or stop value; escalation only on
multi-category confirmation; notify on transitions; every number carries `as_of` and its root (AGENTS.md §5);
thresholds live in `config/market_risk_policy.yaml` and `config/portfolio_risk_budget.yaml` (operator-owned).

## 1 · Components and reuse

| Layer | Build / reuse | Home |
|---|---|---|
| Quotes (ETFs, vol proxies, heavyweight set, extended hours) | reuse `scripts/lib/writers/market_quotes_writer.py`; extend cadence 04:00–09:30 and 16:00–20:00 ET for a declared `market_risk_universe` | P1-T4 (§17) |
| Volatility complex (^VIX ^VVIX ^VIX9D ^VIX3M ^VXN ^SKEW) | extend `market_regime_collector.collect_vix` (same Yahoo provider); UVXY/VIXY fallback | P1-T2 |
| Options flow (index put/call OI and volume, skew, ATM IV) | reuse `scripts/options_chain_snapshot.py` + `option_chain_snapshots`; z-scores vs trailing median (**P0-T6 shipped the detector**); add 09:45 and 15:30 runs; per-strike aggregates → GEX/DEX | P0-T6, P1-T7 |
| Macro / credit (HY OAS, DGS10, T10Y2Y, DXY, WTI, VIXCLS) | reuse FRED ingest; 400-observation window; 5d/20d change and z features | P1-T3 |
| Breadth (% > 20/50/200-DMA, NH/NL, A/D, McClellan) | new store `market_breadth_daily` from Finviz membership × Alpaca bars | P1-T1, P1-T5 |
| Market internals (A/D, up/down volume, TRIN, cumulative A/D, volume breadth; $TICK probed) | new store `market_internals_intraday`, 15-min RTH | P1-T8 |
| Institutional positioning (put/call, GEX/DEX, DIX, COT, ETF/fund flows, retail counterweight) | new providers (operator grants) + computed from the chain the snapshot already pulls; paid sweep/block feeds `no_coverage` until funded | P1-T7 |
| Event concentration (index-weight earnings 1/3/5 sessions, FOMC/CPI/NFP, OPEX/month-end/election) | new `event_calendar.py` on `symbol_profiles.earnings_date`, `macro_calendar_overrides.json`, seasonality tags | P1-T6 |
| ETF look-through + positions | new `etf_holdings_snapshot`; `positions_store` reader batch (§7A rule 8, operator) | P1-T9 |
| Features / scoring / probabilities / analogs / explain / exposure / budget / decay / correlations / AI concentration / opening shock / SNR | new modules under `scripts/lib/market_risk/` | P2 |
| Snapshot store, projection, API | `market_risk_snapshots`, `data_broker` projection `market_risk`, `GET /api/v2/market-risk/latest` | P2-T1 |
| Alerts | `MarketRiskAlert@v1` through `telegram_alert.send_telegram` only (§24.1); dedupe key `market_risk:<tier>:<session_date>:<transition>` | P2-T1, P3-T1 |
| Escalation + ACK | `market_risk_episodes`; repeats; `ACK RED`; `POST /api/v2/market-risk/ack`; stalled-escalation dead-man | P3-T7 |
| Independent host | Host B mirror, heartbeat, market-shock watchdog | P3-T8 |
| Learning | `alert_effectiveness`, `counterfactual_ledger`, weekly calibration and noise reports | P4 |

## 2 · Signal categories and states
Nine categories, each CALM / WARN / STRESS / UNKNOWN (unknown is never zero): technical, breadth, volatility,
options_flow, macro_credit, cross_asset (incl. correlation anomalies), event, seasonal, extended_hours. Institutional
positioning feeds options_flow and a sentiment divergence term (extreme hedging while retail is bullish forces
options_flow and sentiment to STRESS). The AI concentration module feeds technical (leadership participation, RS) and
event (earnings sensitivity). Each observation carries `observed_at`; its weight decays 1.0 → 0.8 → 0.6 → 0.4 at
0/24/48/72 h unless reconfirmed, then UNKNOWN past `stale_after`.

## 3 · Tiers (config, none hardcoded)
| Tier | Condition | Delivery |
|---|---|---|
| Blue | 1 category WARN or score ≥ 25 | P3 → digest; signal, confidence, analog, assets |
| Yellow | ≥ 3 categories WARN+ or score ≥ 40 | P2, pre-market exempt from the quiet hold; P(move ≥1.5%, 1–5d), P(up)/P(down), stop / exposure / sizing review |
| Orange | ≥ 4 categories incl. one of {options_flow, cross_asset, event} at STRESS, or score ≥ 60 | P1; score, regime class, top-3 analogs, P(move 24–72h), hedge and stop-adjustment evaluation; one repeat at +60 min then session boundaries |
| Red | ≥ 5 categories incl. extended_hours or breadth at STRESS, or score ≥ 75, or Orange + extended-hours proxy ≤ −1.5% | P1 + email + SMS; **repeats +15/+30/+60 then hourly until acknowledged (cap 12)**; critical warning, risk level, confidence, analogs, defensive actions to evaluate, triggering factors |
| Green | breadth expansion, participation, falling vol, improving credit; score ≤ 20 with ≥ 3 categories CALM→IMPROVING | P2; bullish confidence, breakout probability, leadership sectors, risk/reward |

Escalation needs two consecutive evaluations (15-min cadence) except Red from an extended-hours shock or a panic
open, which escalate on one. De-escalation needs 3 sessions below the lower bound while the displayed score decays.
**Portfolio uplift:** market Orange + vulnerability ≥ 70 → Red; Yellow + ≥ 80 → Orange; a risk-budget breach ≥ 1.25×
any limit shares the same single-tier uplift. Blue never uplifts.

## 4 · Explainability (every alert)
Top-5 contributors with point attribution that sums to the score, `as_of` per contributor, analogs used, the one
change that would de-escalate, and "Market X / Portfolio vulnerability Y → tier Z" with the positions driving the
vulnerability (symbol and distance to stop only). An LLM may rephrase the "why" sentence after the card exists
(`lib/alert_curation.py` pattern); `agent_number_grounding` holds; `BEHAVIOR_FIELDS` scanned at the card boundary.

## 5 · Mandatory escalation and acknowledgment
A Red is a P1 operator-action intent (`dedupe_minutes=0`, §9.1): never buried, archived, deferred or digested. ACK via
Telegram reply `ACK RED` (recorded in `operator_decisions` through `scripts/lib/operator_approvals.py`) or the Risk-page
button (`POST /api/v2/market-risk/ack`, safe direction, one click §27.3). A tier upgrade or a new STRESS category
re-opens the episode. `health_tick` pages "escalation stalled" if an OPEN Red has no repeat receipt for 75 minutes.

## 6 · Elevated-risk quiet mode and SNR
Per-category signal-to-noise from `communication_events`, `communication_deliveries`, `alert_effectiveness`: deliveries
per day, ack rate, false-positive rate, predictive value, duplicate ratio. When the tier is Orange or Red the router
moves non-P1, non-`market_risk`, non-`stop_health` categories to the digest and tightens dedupe (the system gets
quieter as risk rises). Weekly noise report; digest-only routing proposals by PR only.

## 7 · Opening shock (09:16–09:46 ET)
Indicative gap from extended prints, first-print gap vs ATR, 5/10/15-minute opening range, first-15 internals, VIX
first-15. Gap-and-go, gap-fade, panic open (gap ≤ −1.5 ATR, advancers < 20%, TRIN > 2.0, VIX +10% → Red on one
evaluation). Opening-auction imbalance feeds are `no_coverage` until a source is granted.

## 8 · Scenario replay library and calibration
Public daily data fixtures (redacted, committed): COVID 2020-02/03, the 2022 bear (three legs), the 2023-03 bank
panic, the 2024-08 vol shock, 2018-12 → 2019-01, the 2023 AI melt-up, the 2024-09 cut rally, the 2023-12 Santa rally,
the three 2026 Nasdaq corrections and recoveries, calm controls 2017 and 2021-H1. Each has a tested expectation (lead
time, tier, no false Red). Options-flow and institutional categories run as UNKNOWN before the system's own history and
a test asserts detection still works without them. Probability tables are regenerated from the library; the backtest
report is regenerated, never edited. The 10-30 episode becomes a permanent fixture.

## 9 · Independent alert host (disaster path)
Host B (operator-provisioned; own Telegram and SMS credentials in its own secret store; Host A never sees them)
receives Orange/Red intents over HTTPS+HMAC (tier, score, text, episode id; no account or position data), sends
independently when Host A's delivery receipt is absent for 3 minutes, repeats Reds if Host A stops, pages "host
silent" when the 5-minute heartbeat is missing for 15 minutes on market days, and runs a 60-line market-shock
watchdog (SPY/QQQ extended and regular change from a free quote source) that pages directly on a Red-class move with
no Host A alert. P0/P1 never depend on n8n (§23.6). Acceptance: a 20-minute egress drill with both receipts quoted.

## 10 · Schedule (all §17, proposed)
`market-risk-evaluate` every 15 min 04:00–20:00 ET weekdays via the dispatcher as an advisory market-data lane
(§23.20), full re-collection at 05:00, 06:30, 08:30, 12:00, 15:45, 16:30, 18:00, 20:00; opening-shock evaluations
09:16–09:46; Sunday 18:30 ET weekend check. Collectors: extended-hours quotes, vol complex, options chain
09:45/15:30/17:35, FRED 06:15, breadth 16:45 and 06:20, internals */15 RTH, institutional flow daily/weekly.

## 11 · Operator decisions this design needs (propose and stop)
1. §7A grants for the seven new stores and their single writers; the new free providers (SqueezeMetrics, CFTC, ICI);
   a funding decision on paid options-flow data; the `positions_store` reader batch for the engine.
2. The schedules in §10 (digest approval of the registry PRs, or §25.10.2 in-session activation).
3. `config/market_risk_policy.yaml` thresholds and tier rules; `config/portfolio_risk_budget.yaml` limits;
   `opportunity_conviction.yaml` `market_risk_gate`; `cio_situations.yaml` labels (P0-T3 PR).
4. Defense desk SHADOW → promote (P0-T7).
5. Delivery policy: `market_risk` category, pre-market quiet-hours exemption, email/SMS routing, elevated-risk quiet mode.
6. Risk page / banner design approval (`design/pages/risk/vNNN`).
7. Independent alert host: provisioning or funding, its credentials, the HMAC mirror route, the heartbeat timer install.
8. The acknowledgment control as a safe-direction operator control.

## 12 · Verification
Every change: tests under `TRADE_AI_CI=1` with mutation evidence, `--dry-run` output quoted, forced run under the exact
schedule form from a neutral cwd proven by a dated artifact. Engine: replay test (P2-T3) green; backtest report
committed; ten shadow days of receipts; first live P1 observed as `SENT` with a provider id. Dead-man: stale receipt
staged in a temp PROJECT_ROOT, never the prod journal. Quiet mode: forced Red fixture still delivers `stop_health`
and `market_risk` P1. Disaster drill once Host B exists. No live-server traffic 04:00–16:15 ET (§28.8); no real
positions in any fixture (§2A).
