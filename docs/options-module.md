# Options Module — Architecture & Operations

> **SUPERSESSION NOTE (2026-07-19):** Open-position MANAGEMENT is now owned by
> the **Options Lifecycle Desk** — see `docs/OPTIONS_LIFECYCLE_DESK.md`
> (canonical) and `docs/_findings/OPTIONS_LIFECYCLE_DESK_DIAGNOSIS_2026-07-19.md`
> + `OPTIONS_LIFECYCLE_V1_1_INTEGRATION_AUDIT_2026-07-19.md`. This document
> remains canonical for PROPOSAL GENERATION (options_engine +
> options_desk_enterprise + approval queue), which the lifecycle desk does not
> touch. The per-leg monitor described below (`monitor_positions`,
> `options_monitored_*` tables) is superseded for management decisions; the
> lifecycle desk's strategy-grouped model + policy engine is authoritative.
> UI: the Options tab's lead view is now **Lifecycle**
> (`/v3/trading?tab=Options&otab=Lifecycle`).

**Location:** Trading hub → **Options** tab (`/v3/trading?tab=Options`)  
**Status:** **Enterprise trade desk** — systematic proposals, income screen, enterprise risk gates, options thesis + CIO review, Schwab validation, operator approval queue, position monitor, Hermes/TradeAI research bridge. Live execution is operator-approved (`options_pilot_arm` + desk queue + per-order 2FA).

**Latest commits:** `5645e068` (audit fixes + Hermes/TradeAI bridge) → `4d7b9c38` (enterprise desk) → `e5d2f9b4` (docs) → `84ccc696` (filters) → `11bb3932` (live R:R + lifecycle) → `606761c5` (UI tooltips).

---

## Current flow (2026-09-26)

This section is canonical for the proposal side. Older sections below are kept for
reference and corrected where they conflict.

```
generate_proposals()                     scripts/options_engine.py
  └─ income screen                       scripts/lib/options_income_quality.py
  └─ enterprise gates                    scripts/options_desk_enterprise.py
  └─ options thesis record + blocks      scripts/lib/options_thesis.py
options thesis lifecycle (cron)          scripts/options_thesis_lifecycle.py → scripts/lib/options_thesis_lifecycle.py
  CREATED → RESEARCH_QUEUED (Hermes CIO research)
          → RESEARCH_COMPLETE (catalyst_map / invalidation / bear_case / thesis_check answers)
          → CIO review → DECISION_ISSUED            scripts/lib/options_cio_review.py
          or ARCHIVED_ABANDONED after abandon_after_hours (48)
Validate against Schwab (read-only)      POST /api/v2/options/validate → scripts/lib/options_validate.py
Operator approval in queue               options_desk_enterprise.resolve_approval()
Per-order 2FA → Schwab submit            operator only (preflight → confirm)
```

Nothing in this flow sizes a position or places an order. Sizing and the 2FA order path are
the operator's. Alpaca paper options are training only: never a live or acceptance path, and
they never alert.

### Gates and thresholds

All keys are under `assets/portfolio_intent.yaml` → `options_desk_settings` unless noted.

| Gate | Rule | Config key(s) | Code |
|------|------|---------------|------|
| Underlying price | no income idea below the floor | `min_underlying_price` (5.0) | `lib/options_income_quality.py` |
| Listed chain | card only from a Schwab-listed contract; Black-Scholes estimates never become cards | `require_chain_for_live` (true) | `options_income_quality.py`, `options_validate.py` (`NOT_A_LISTED_QUOTE`) |
| Liquidity | OI ≥ 50, bid-ask ≤ 12% of mid (both legs for credit spreads) | `min_open_interest`, `max_bid_ask_spread_pct`, `min_volume` | `options_income_quality.py`, `options_desk_enterprise.liquidity_gate` |
| Premium floor | premium ≥ $0.10/sh | `min_premium_per_share` | `options_income_quality.py` |
| Yield floor | annualized ROC ≥ 6% (credit spreads: ROC on width − credit) | `min_annualized_roc_pct` | `options_income_quality.py` |
| Strike picker | prefers liquid contracts, targets delta 0.25 | `cc_target_delta`, `csp_target_abs_delta`, `picker_strike_slack_pct` | `options_income_quality.py` |
| Covered-call edge | premium yield scored via `roc_score`; full credit at 25% annualized | `edge_roc_full_credit_ann_pct` | `options_engine.py`, `options_income_quality.roc_score` |
| IV | chain ATM IV fallback when technicals lack IV; history rank only with ≥ 60 samples over ≥ 90 days; no IV → `IV_UNKNOWN` (the old 12.5 placeholder is gone) | `iv_history_min_samples`, `iv_history_min_span_days` | `options_engine._chain_atm_iv_pct` |
| Spot price | freshest dated price (scan vs `market_quotes`), max age 96h; the Schwab chain underlying wins; proposals carry `price_source` | `price_max_age_hours` | `options_engine.py` |
| Holdings funnel | positions < $250 and < 100 sh are "fractional leftovers"; rows show total shares per account | `funnel_dust_max_market_value` | `GET /api/v2/options/holdings-funnel` |
| Earnings blackout | blocks short premium through the window | `earnings_blackout_days` (14) | `options_desk_enterprise.py` |
| Thesis bar | `thesis_required`, `thesis_missing_*`, `awaiting_cio_decision` (needs a CIO APPROVE) | — | `lib/options_thesis.py` |
| Validate | fresh `VALIDATED` re-quote required to approve | `validation.fresh_minutes` (30), `validation.max_premium_change_pct`, `validation.max_spot_change_pct` | `lib/options_validate.py`, `options_desk_enterprise._validation_refusal` |

Income screening applies to covered calls, cash-secured puts and credit spreads.

### Options thesis record

`scripts/lib/options_thesis.py` stores `OptionsThesisRecord@v1`, keyed by
`option_strategy_guid`, in the append-only hash-chained `data/cio/options_theses.jsonl`.
A catalyst may come from the earnings calendar (`calendar_catalyst`, labelled "Calendar", never
researched judgment). Thesis blocks join the enterprise blocks, so the card reads
"Not approvable" until both clear.

### Thesis lifecycle

`scripts/options_thesis_lifecycle.py` (dry run by default; cron `7,22,37,52 * * * * … --apply`)
advances each thesis. Ideas that carry liquidity or enterprise blocks are skipped.
Config: `options_desk_settings.options_thesis_lifecycle` (`abandon_after_hours` 48,
`research_rerequest_hours` 24, `cio_review_mode: live`, `max_reviews_per_run` 6).

### CIO review

`scripts/lib/options_cio_review.py`: agent `alex` via `llm_router` task `cio_synthesis`
(DeepSeek, governed caps). Outcomes `APPROVE` / `REJECT` / `MORE_RESEARCH` / `MONITOR_ONLY`, each
with confidence, reasoning, concerns, assumptions challenged and evidence for/against. No sizing;
numbers must trace to supplied facts. The Decision GUID (`dec_<uuid>`) is stored on the thesis and
in `cio_decisions` (`action_class` `options_thesis_review`). The operator confirms.

### Validate

`POST /api/v2/options/validate` (`scripts/lib/options_validate.py`) re-quotes the contract from
the Schwab chain, read-only. Statuses: `VALIDATED`, `CHANGED`, `CONTRACT_NOT_FOUND`, `ILLIQUID`,
`NO_QUOTE`, `NOT_A_LISTED_QUOTE`, `UNAVAILABLE`. `resolve_approval` refuses approval without a
`VALIDATED` result inside `validation.fresh_minutes` (30), failing closed.

### Aegis review (advisory)

`enqueue_ensemble_for_proposals()` queues an Aegis review per proposal. Lanes come from
`config/inference_layers.yaml` `ensemble.options_lanes: [grok, chatgpt, deepseek-flash]` and are
carried on each job row (`options_engine._options_ensemble_lanes`); general ensemble use stays on
`ensemble.lanes: [grok, chatgpt]`. There is no local/Gemma lane. Aegis judges the card against
house facts (thesis, research answers); it fetches no news, earnings or filings. A model vote is
not research and not a CIO decision. Cost cap: `config/llm_process_registry.json`
`options_ensemble` (`daily_cost_cap_usd` 0.5).

### Card

The card shows the committee memo, a plain-English explainer (`scripts/lib/options_plain_english.py`),
the ticker CIO view (`scripts/lib/ticker_cio_view.py`: symbol thesis, latest decision with its source
— rule engine vs CIO review — change since previous, research on file), status pills with STATUS
filters, an evidence ladder and a Validate button (`OptionValidateButton.tsx`).

### CIO Desk Telegram

`scripts/lib/cio_action_notify.py` + `config/cio_notification_policy.json`: material actions only,
one readable message per run, repeats suppressed for 7 days (`repeat_suppress_days`). No run-id
check-ins.

---

## Architecture

```
Cron (10m) ──► run_options_monitor.py
                    ├─► options_engine.generate_proposals()
                    │       ├─ portfolio sleeve (CC, protective puts)
                    │       ├─ conviction sleeve (CSP, long calls, spreads)
                    │       ├─ quality gates + per-strategy slots
                    │       └─ options_desk_enterprise (blackout, liquidity, vol, tiers)
                    ├─► options_engine.monitor_positions() + book greeks
                    └─► options_research_bridge.run() → Hermes + TradeAI runtime

Daily 15:45 ──► options_iv_snapshot.py ──► options_iv_history (52-week IV rank)

Thesis lifecycle ──► CIO review ──► Validate (Schwab) ──► Operator approve ──► preflight ──► 2FA ──► Schwab submit
(see "Current flow (2026-09-26)" above)
```

---

## Reuse Audit (what existed before)

| Asset | Path | Reused for |
|-------|------|------------|
| Schwab option chain (read) | `scripts/schwab_transport.py` → `get_option_chain()`, `normalize_option_chain()` | Live premium, IV, delta, OI |
| Covered-call scan (estimated) | `scripts/portfolio_options.py` → `scan_covered_calls()`, `_get_earnings_dates()` | BS fallback; **FMP earnings calendar** |
| Aegis CC scoring | `scripts/aegis_synthesis.py`, `GET /api/v2/aegis/covered-calls` | Catalyst / verdict context |
| Holdings | `data/portfolios/state/holdings.json` | CC eligibility (≥100 shares); protective puts (≥$15k MV) |
| Technical snapshot | `technical_snapshot.json` | RSI, SMA200, IV proxy, IV rank |
| Layer 4 inferences | `inference_results` via DB | High-conviction universe |
| Fused signals | `fused_signals` table | Primary conviction source (confidence, severity, direction) |
| Portfolio intent | `assets/portfolio_intent.yaml` | CC candidates, DTE/OTM/IV gates, **options_desk_settings** |
| UI cards | `OptionProposalCardV4` (live), `OptionPositionCardV4`, `OptionReviewBar`, `GreeksOverview` | Proposal + position + ensemble review; v3 cards retained for reference |
| Execution pilot | `options_pilot_arm`, `options_order_pilot`, `options_execution_policy` | Live Schwab submit path |

**Gaps filled:** unified `options_engine.py`, enterprise layer (`options_desk_enterprise.py`), balanced desk slots, Hermes/TradeAI bridge, approval queue, book greeks, vol analytics.

---

## Components

### Backend — `scripts/options_engine.py`

| Function | Purpose |
|----------|---------|
| `generate_proposals()` | Full desk pass: CC + protective puts + defined-risk + spreads |
| `monitor_positions()` | Open-leg lifecycle (hold/close/roll) + **book greeks** |
| `get_overview()` | Desk KPIs + enterprise risk summary |
| `build_options_desk_summary()` | Compact summary for TradeAI / Hermes |
| `enqueue_ensemble_for_proposals()` | Aegis review on `ensemble.options_lanes` (grok, chatgpt, deepseek-flash; advisory) |

**Two sleeves:**

| Sleeve | Strategies | Routing |
|--------|-----------|---------|
| **Portfolio / income** | Covered calls, protective puts | Holdings-driven; CC from `covered_call_candidate` in intent YAML |
| **Conviction / defined-risk** | CSP, long calls, credit spreads | `fused_signals` + Layer 4; **CSP on non-owned names only** |

**Per-strategy desk slots** (prevents CC crowding):

| Strategy | Default cap | Env override |
|----------|-------------|--------------|
| Covered call | 5 | `OPTIONS_SLOT_COVERED_CALL` |
| Cash-secured put | 3 | `OPTIONS_SLOT_CSP` |
| Protective put | 2 | `OPTIONS_SLOT_PROTECTIVE_PUT` |
| Long call | 2 | `OPTIONS_SLOT_LONG_CALL` |
| Credit spread | 2 | `OPTIONS_SLOT_CREDIT_SPREAD` |

**Edge models:**

- **Credit** (`_edge_score`) — covered calls
- **Debit** (`_edge_score_debit`) — protective puts, long calls
- **Wheel** (`_edge_score_wheel`) — CSP, credit spreads (POP + annualized ROC)
- Covered-call edge also scores premium yield via `roc_score` (full credit at `edge_roc_full_credit_ann_pct` 25%)
- Covered calls, CSPs and credit spreads all pass the income screen first (`scripts/lib/options_income_quality.py`)

**Quality gates (default):**

- Edge ≥ 62 (52 for income sleeve / conviction wheel plays)
- POP ≥ 52%
- IV rank ≥ 20 (12 for high-conviction names via `OPTIONS_CONVICTION_MIN_IV`)
- DTE 7–60

**Price resolution** for conviction symbols missing from `technical_snapshot.json`:
holdings → `trade_ai_scans` → `market_quote_provider.check_fresh_quote()`.

Caches:
- `data/portfolios/state/options_proposals.json` (10 min TTL; bypassed when `force=True`)
- `data/portfolios/state/options_monitor.json` (5 min TTL)
- `data/runtime/options_desk_latest.json` (TradeAI enrichment)
- `data/runtime/options_desk_enterprise.json` (risk + tier summary)

---

### Enterprise layer — `scripts/options_desk_enterprise.py`

Institutional controls applied after quality gates, before desk allocation.

| Control | Description |
|---------|-------------|
| **Earnings blackout** | FMP calendar; blocks short premium / directional entries through earnings window |
| **Liquidity gates** | Min OI, min volume, max bid-ask spread % |
| **Vol analytics** | Term structure + put/call skew from live Schwab chain (persisted to `options_chain_snapshots`) |
| **Book greeks** | Net Δ, Γ, Θ, ν aggregated across open legs |
| **Portfolio risk** | Concentration + net-delta exposure warnings |
| **Desk tiers** | A (edge ≥72), B (≥62), C (below B) |
| **Approval queue** | DB-backed operator review before live submit |

Config: `assets/portfolio_intent.yaml` → `options_desk_settings`, overridable via env (`OPTIONS_MIN_OI`, `OPTIONS_APPROVAL_REQUIRED`, etc.).

**Live eligibility:** proposals with enterprise blocks or BS-only estimates (when `require_chain_for_live: true`) are advisory-only until chain confirms and operator approves.

---

### Hermes + TradeAI bridge — `scripts/options_research_bridge.py`

After each monitor pass:
- Publishes `data/runtime/options_desk_latest.json`
- Stages `hermes_research_intelligence` rows (`research_type=options_desk`, 6h dedup per symbol)

Wired into:
- `run_options_monitor.py` (every cron pass)
- `hermes_coordinator.py` (each tick)
- `trade_ai_orchestrator.py` (step 10c — per-ticker `options_desk` context)
- `api_v2.py` `_compute_trade_ai()` (top-level + per-ticker block)
- `hermes_subject_enhance.py` (`options_proposal` gatherer for external LLM review)

```bash
.venv/bin/python scripts/options_research_bridge.py --apply
.venv/bin/python scripts/options_research_bridge.py --apply --symbol RTX --force
```

---

### API (`scripts/api_v2.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/options/proposals` | Filtered proposals — see query params below |
| `GET /api/v2/options/positions` | Open legs + monitoring + book greeks (filterable) |
| `GET /api/v2/options/monitor` | Alias for positions |
| `GET /api/v2/options/overview` | Strategy summary + enterprise risk |
| `GET /api/v2/options/desk/risk` | Book greeks, concentration, live-eligible count |
| `GET /api/v2/options/desk/vol-analytics?symbol=RTX` | Term structure + skew |
| `GET /api/v2/options/approval-queue` | Pending/blocked desk items (`?status=pending`) |
| `POST /api/v2/options/approval-queue/resolve` | `{proposal_id, action: approve\|reject, note?}` |
| `GET /api/v2/options/execution/status` | Pilot arm + policy state |
| `POST /api/v2/options/preflight` | Build intent + 2FA (requires desk approval when enabled) |
| `POST /api/v2/options/confirm` | Confirm + Schwab submit |
| `POST /api/v2/options/validate` | Read-only Schwab re-quote of one proposal's contract (required before approval) |
| `GET /api/v2/options/holdings-funnel` | Owned-book drop reasons (CC + protective put) |
| `POST /api/v2/options/ensemble/enqueue` | Batch Aegis review (grok, chatgpt, deepseek-flash) |
| `GET /api/v2/schwab/option-chain` | Chain drill-down |

**Proposal filter query params:** `symbol`, `strategy`, `group` (income\|hedge\|directional\|spread), `option_type` (call\|put), `side` (BUY\|SELL), `sleeve` (portfolio\|conviction), `leg_style` (single\|spread), `desk_tier` (A\|B\|C), `live_eligible` (1\|0), `min_pop`, `min_edge`, `min_dte`, `max_dte`, `force=1`. Response includes `filter_facets` with counts per chip.

**Position filter query params:** `symbol`, `option_type`, `side` (buy\|sell), `working_only`, `force=1`.

TradeAI: `GET /api/v2/trade-ai` includes `options_desk` block (top-level + per-ticker).

---

### Frontend — `apps/command-center-v3/src/pages/OptionsHub.tsx`

Tabs: **Proposals**, **Open Positions**, **Strategy Overview**

Components: `OptionProposalCardV4`, `OptionPositionCardV4`, `OptionChainPanel`, `OptionReviewBar` (ensemble), `GreeksOverview`, `OptionsPnLProfile`, `OptionsNovicePanel`, `optionsCardSemantics.ts`.

**Filter chips (Proposals):** income / hedge / directional / spreads, calls / puts, sell / buy, single-leg / spread pairs, portfolio / conviction sleeve, desk tiers A–C, live-eligible. Counts from `filter_facets`.

**Position cards:** lifecycle badges (`LET MATURE` / `HARVEST` / `DEFEND`), dynamic R:R, `% captured`, maturity note, expiry P/L profile toggle.

**Tooltips:** centralized in `src/lib/optionsTooltips.ts`; rendered via `OptionsTip.tsx` (`Tip`, `TipChip`, `TipKpi`, `TipLabel`, `TipSection`). Hover ⓘ markers on header, filters, KPIs, greeks chart, proposal/position badges, review bar, and beginner-hints panel.

Wired into `TradingHub.tsx` as the **Options** tab.

---

### Monitor cadence — `scripts/run_options_monitor.py`

```bash
.venv/bin/python scripts/run_options_monitor.py
```

Cron (`crontab_backup.txt` + `linux_launchers/run_options_monitor.sh`):
- `35,45,55 9`, `*/10 10-15`, `5 16` weekdays → proposals + monitor + Hermes bridge (`force=True`)
- `45 15` weekdays → `options_iv_snapshot.py` (52-week IV rank history)

One live `schwab_transport.get_option_chain()` read per (symbol, width) per generation pass; the IV lookup and contract picker share it (`options_engine._CHAIN_CACHE`).

---

## Proposal types

| Type | Source | Notes |
|------|--------|-------|
| **Covered call** | Holdings ≥100 shares | ~6% OTM, ~30 DTE; Aegis + intent overlay; Fidelity manual path |
| **Protective put** | Holdings ≥$15k MV | ~5% OTM long put; debit edge model |
| **Cash-secured put** | High-conviction, **not owned** | Wheel entry; ~8% OTM; conviction bias routing |
| **Long call** | Explicitly bullish + conf ≥60% | Defined risk; debit edge model |
| **Credit spread** | Bull put vertical | `NET_CREDIT` two-leg; wheel edge model; income-screened (both legs liquid, ROC on width − credit) |

**Conviction bias routing** (`_conviction_bias`): uses `direction`, `severity`, `inference_type` from fused signals — empty severity no longer defaults to bullish.

**Chain resolution:** Schwab live chain first. When technicals lack IV, IV comes from the chain ATM (`_chain_atm_iv_pct`). A Black-Scholes estimate (`_bs_option_premium`) never becomes a card; Validate reports it as `NOT_A_LISTED_QUOTE`.

---

## Enterprise workflow (operator)

```
1. Desk scan generates proposals (cron, ~10m market hours) through the income screen
2. Enterprise layer enriches: blackout, liquidity, vol, tier, live_eligible
3. Options thesis record written; thesis blocks join enterprise blocks
4. Approval queue upserted (options_approval_queue table); blocked rows read "Not approvable"
5. Thesis lifecycle: Hermes CIO research → CIO review → Decision GUID (or archived after 48h)
6. Aegis review on grok, chatgpt, deepseek-flash (advisory, non-blocking)
7. Operator runs Validate (fresh VALIDATED re-quote, 30 min)
8. Operator approves; resolve_approval refuses with blocks or without a fresh VALIDATED result
9. Preflight checks: desk approval + enterprise blocks + policy + pilot arm
10. Per-order 2FA → Schwab submit (operator only)
```

Reject or blocked proposals remain visible on the desk with `enterprise.blocks` — advisory review only.

---

## Monitoring logic

Positions sourced from Schwab `get_positions()` with OCC symbol parse.

Per position (refreshed every 5–15 min with live Schwab mark):
- Moneyness (ITM / ATM / OTM)
- POP OTM / ITM (Black-Scholes N(d2))
- Unrealized P/L vs mark
- **Dynamic R:R** (`risk_reward`) vs max loss at open
- **Premium captured %** on short legs (`profit_captured_pct`)
- **Lifecycle phase:** `let_mature` | `harvest` | `defend` | `monitor`
- **Maturity note** — plain-English when to sell vs let contract mature
- Recommended action: Hold, Close for Profit, Roll, Close

Book-level (`monitor_positions` → `book_greeks`):
- Net delta (share-equivalent), gamma, theta/day, vega
- Per-underlying breakdown

---

## Safety & execution

**Advisory default.** Proposals include `execution_note` reflecting arm state.

**Enterprise gates (when `approval_required: true`):**
- Earnings blackout (FMP, configurable days)
- Liquidity: min OI 50, min vol 5, max spread 12%
- BS estimates blocked from live path when `require_chain_for_live: true`
- CIO APPROVE decision on the options thesis (`awaiting_cio_decision` otherwise)
- Fresh `VALIDATED` Schwab re-quote (`validation.fresh_minutes` 30) before approval
- Desk approval required before preflight

**Live submit requires (all):**
1. Policy `ENABLED` (`options_execution_policy.py`)
2. DB `options_execution_enabled` (`options_pilot_arm.py --approve`)
3. Desk approval (`options_approval_queue.status = approved`)
4. `live_eligible = true` (no enterprise blocks)
5. Per-order 2FA (`preflight` → `confirm`)

| Component | Path |
|-----------|------|
| Policy | `scripts/brokers/options_execution_policy.py` |
| Operator arm | `scripts/options_pilot_arm.py --approve --confirm "APPROVE OPTIONS EXECUTION YYYY-MM-DD"` |
| Enterprise desk | `scripts/options_desk_enterprise.py` |
| Pilot | `scripts/brokers/options_order_pilot.py` |
| Guard | `execution_guard.py` → `OPTIONS_EXECUTION_MARKER` |
| API | `POST /api/v2/options/preflight` → 2FA → `POST /api/v2/options/confirm` |

CSP copy reminds operator to verify SSDI / income impact before entry.

---

## Database tables

| Table | Purpose |
|-------|---------|
| `options_iv_history` | Daily ATM IV snapshots for true 52-week IV rank |
| `options_approval_queue` | Desk operator approval queue (migration `2026_06_25_options_desk_enterprise.sql`) |
| `options_chain_snapshots` | Vol term structure + skew persistence |
| `hermes_research_intelligence` | `research_type=options_desk` rows from bridge |
| `inference_ensemble_jobs` | `target_type=options_proposal` Aegis review; lanes on each row (grok, chatgpt, deepseek-flash) |
| `cio_decisions` | CIO review decisions (`action_class` `options_thesis_review`) |

File store: `data/cio/options_theses.jsonl` (options thesis records, append-only, hash-chained).

---

## Environment knobs

```
OPTIONS_SLOT_COVERED_CALL=5
OPTIONS_SLOT_CSP=3
OPTIONS_SLOT_PROTECTIVE_PUT=2
OPTIONS_SLOT_LONG_CALL=2
OPTIONS_SLOT_CREDIT_SPREAD=2
OPTIONS_CONVICTION_MIN_IV=12
OPTIONS_CONVICTION_MIN_EDGE=52
OPTIONS_EARNINGS_BLACKOUT_DAYS=14
OPTIONS_MIN_OI=50
OPTIONS_MIN_VOLUME=5
OPTIONS_MAX_SPREAD_PCT=12.0
OPTIONS_REQUIRE_CHAIN_LIVE=1
OPTIONS_APPROVAL_REQUIRED=1
OPTIONS_MAX_NET_DELTA_PCT=35.0
OPTIONS_SNAPSHOT_RETENTION_DAYS=45   # prune options_chain_snapshots older than N days
```

`options_chain_snapshots` retention runs two ways: a cheap per-symbol prune on each
`persist_chain_snapshot` insert (active desk names), plus a global sweep
(`prune_chain_snapshots()`) from the daily IV-snapshot cron (`scripts/options_iv_snapshot.py`,
`45 15 * * 1-5`) that catches the tails of symbols that have gone quiet.

---

## CLI

```bash
# Proposals + monitor + overview
python scripts/options_engine.py --proposals
python scripts/options_engine.py --monitor
python scripts/options_engine.py --overview
python scripts/options_engine.py --force          # bypass 10m cache

# Full monitor pass (cron equivalent)
python scripts/run_options_monitor.py

# Hermes + TradeAI bridge
python scripts/options_research_bridge.py --apply --force

# IV history snapshot (daily)
python scripts/options_iv_snapshot.py

# Operator arm (live submit unlock)
python scripts/options_pilot_arm.py --approve --confirm "APPROVE OPTIONS EXECUTION $(date +%F)"
```

---

## Extending

1. **Approval queue** — the proposal card shows queue status, approvability and a Validate button (2026-09-26); a dedicated queue tab calling `POST /api/v2/options/approval-queue/resolve` is not wired in OptionsHub (verified 2026-09-26)
2. **Fidelity option legs** — extend `monitor_positions()` beyond Schwab-only
3. **Roll automation** — wire monitor `roll` action to preflight with new expiration
4. **Edge calibration** — log closed proposal outcomes → edge model tuning

Hard portfolio risk blocks are implemented in `evaluate_hard_risk_blocks()` — live path only.
Central readiness: `scripts/brokers/execution_readiness.py`. State: `scripts/execution_state.py`.

---

## Maturity comparison

| Capability | Retail advisory | Current (enterprise desk) | Prop-shop target |
|------------|----------------|---------------------------|------------------|
| Systematic screening | ✓ | ✓ | ✓ |
| Live chain pricing | partial | ✓ | ✓ |
| Earnings blackout | ✗ | ✓ (FMP) | ✓ |
| Liquidity gates | ✗ | ✓ | ✓ |
| Operator approval queue | ✗ | ✓ | ✓ |
| Book greeks | ✗ | ✓ (Δ, Θ, ν) | ✓ (streaming) |
| Vol surface | ✗ | term structure + skew + strike×DTE heatmap (Options Trends tab) | full 3D surface |
| Multi-broker book | ✗ | Schwab only | all brokers |
| Auto-execution | ✗ | operator-approved path (readiness + evidence + 2FA) | policy-driven |
| Execution readiness | ✗ | central resolver + audit ledger | streaming |
| Kill switches | ✗ | multi-level + circuit breakers | automated |