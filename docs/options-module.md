# Options Module — Architecture & Operations

The October 5 review repair also adds a **Create standing plan** modal for any symbol, using the
existing ticker directive and options-intent writer. It previews before saving, preserves the
previous plan in the preview, refuses a changed-version overwrite and waits for the scheduled
matcher. Editing a plan invalidates older contract matches. Strategy and risk/reward tooltips
explain capital, upside limits, full downside and assignment; delta is not assignment probability.
An optional **LLM summary of this standing plan** reuses the governed ensemble job/result store,
bound to the exact intent and captured scan. It shows each model's reasoning and recording time;
no result is invented and page loads do not request models. These controls create advisory plans,
not account allocation, trade approval or broad-scan activation. Fixtures verify the UI paths;
organic matcher/model results for newly saved plans remain a runtime acceptance requirement.


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

## Complete coverage and queued scanning (2026-10-05 source change)

The new Options proposal read model includes every recorded holding, active/researched watchlist
security, reentry membership and discovered optionable security. Inventory, chain coverage,
research readiness and approval are separate counts. The UI offers All coverage and four queues:
income, protection, watch/reentry alternatives and new opportunities. GET requests only read
producer snapshots; scan requests are explicit queued POSTs. Additional captured-chain research
covers all eight expression families over 7–365 DTE, with blocked advisory status until the
existing governance and strategy requirements are satisfied.

**Expanded scanning remains disabled pending measured capacity and activation.** The live
watchlist count was 5,541 on October 5; a complete 15-minute refresh requires at least 369.4
chain requests/minute before other work. No provider allowance or achieved refresh SLA is assumed.
The compatibility producer keeps its prior bounded workload and shows omitted chains as pending.
See the [capacity, API, ownership and acceptance contract](ops/OPTIONS_SCAN_CAPACITY_2026-10-05.md)
for exact source/code status, rollout requirements and five-session acceptance. Source completion
and fixture success do not establish deployed or organically effective behavior.

Package payoff/POP display identifies captured bid/ask estimates, IV basis and heuristic
scores. Profit probability includes premium; model estimates are not observed win rates.
Readiness gates and operator-controlled execution policy retain their authority.

## Review repair and captured quote basis (2026-10-05)

The [review/economics repair record](ops/OPTIONS_SCAN_CAPACITY_2026-10-05.md#review-and-economics-repair--2026-10-05)
supersedes earlier display semantics: investment review has its own states and next actions,
independent of execution blocks. Every card's premium, floor, breakeven and risk share one captured
quote basis and contract-lot scope. Standing-intent matches show quote timestamps and links to
existing account-specific ideas; unmatched contracts are explicitly not staged. Ticker decisions
and model votes do not approve an option idea. API GET repair is a read-only projection, not a
quote refresh, new research or mutation of the original snapshot.

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
`research_rerequest_hours` 24, `cio_review_mode: live`, `max_reviews_per_run` 6, `review_max_tokens` 2500 — 1200 truncated the first live reviews).

### Persistence (2026-09-26)
- **Agent memory (M2).** `scripts/options_memory_projector.py` (dry run default; `--apply`) tails
  `data/cio/options_theses.jsonl` and writes through `CIOEnvelopeIntegrator` with
  `source_type=options_thesis_store`, `source_id=event_hash`. Predicates: `options_thesis` (one
  current belief per strategy GUID), `options_cio_decision`, `options_followup`,
  `options_validation`, `options_thesis_outcome` (one identity per event). Payloads are allowlisted:
  no account, contract count or dollar fields. A superseding decision gets a `SUPERSEDES`
  provenance edge. The CIO review reads prior facts back as `prior_decisions`
  (`options_thesis_lifecycle.memory_reads: true`; env `MEMORY_BEHAVIOR_INFLUENCE_OPTIONS` overrides).
- **Living symbol thesis.** Hermes answers (`q_thesis_check`, `q_catalyst_map`, `q_invalidation`,
  `q_bear_case`) flow through the one existing writer (`research_thesis_delta` ->
  `reconcile_symbol_thesis` -> `publish_symbol_thesis`): invalidation and catalysts are merged,
  the bear case becomes counter-evidence, evidence lists merge rather than replace, and an authored
  summary is never overwritten. The governed **ENRICHES** rule fills *empty* invalidation or
  catalyst fields on grade-A, non-INSUFFICIENT_DATA research without touching stance or summary
  (`options_desk_settings.symbol_thesis_enrich`, 24h cooldown).
- **Drive.** `scripts/export_options_runtime_snapshot.py` writes a **redacted** snapshot (no
  account names, no dollar amounts) to `persistent-state/exports/drive/runtime/options/`, which
  `sync-docs-to-drive.sh` mirrors under `runtime/options/` and preserves. The purge no longer
  re-uploads dated top-level docs every hour.

### Research reads the web (2026-09-26)
**2026-09-27:** this is no longer options-only. Every Hermes CIO research request is web-grounded (`enabled_reasons: ["*"]`), and requests with no symbol search nothing. The governed research producer's recent pages for the symbol (`research_objects.jsonl`, the last 72h, relevance-filtered) are supplied first, so the same page is not searched twice. The answers reach the symbol thesis through `accept_research_result`.
Options-gap research (`reason: options_thesis_gap`) is no longer closed-world. Before the model call,
`scripts/lib/hermes_web_research.py` runs up to `max_queries` searches:
- **Queries:** one per thesis intent (outlook, next earnings, risks and downgrades, bear case), then the
  CIO's own concerns, with house schema words removed.
- **Search order:** the same lanes as the governed research producer. SearXNG goes first (self-hosted,
  free). The Brave router runs only when SearXNG returns nothing (paid, reserved and settled, caller cap
  `hermes_cio_research` 10/day).
- **Filtering:** results must read like investment material; shop, driver and support pages are dropped.

The model answers from `web_results` and cites them by url. `ground_citations` drops any url it was not
given, and the result records `web_research` (queries, provider, supplied and cited counts) plus
`source_urls`.

CIO follow-ups are research tasks ("find dated, sourced facts that resolve this CIO concern"), not
statements. A symbol with no standing thesis (`INSUFFICIENT_DATA`) also gets the four thesis questions,
and their answers feed the living symbol thesis.

- **Why:** the first DELL follow-up cited only internal ids and answered "no authored thesis exists".
- **Result:** the same questions now return dated, cited facts:
  - the 2026-09-01 Q2 earnings;
  - the $95B AI backlog and raised FY27 guidance;
  - the 2026-09-14 HPE-downgrade selloff.
- **Config:** `options_desk_settings.web_research`.

### Escalation when the web is not enough (2026-09-27)
Operator: "if web unsure use chatgpt grok deepseek". The lifecycle checks each delivered CIO follow-up.
It escalates when too few deliverables are fully answered (`escalation_min_answered_ratio`, default 0.6)
or too few web sources are cited (`escalation_min_cited_urls`, default 2).

**How it runs:**
- `hermes_external_researcher.py` is called for the symbol, trying the lanes in order: **ChatGPT
  (OAuth), Grok (OAuth proxy), DeepSeek (governed)**. The first lane that answers wins.
- At most `escalation_max_per_run` escalations per run, with a timeout of `escalation_timeout_s` per
  lane.
- The trigger is `proposal_review:options_escalation`, which is budget-guard tier T0 (an open proposal
  under CIO review).

**The question:** one question per ticker. It asks for:
- the thesis;
- dated catalysts before expiry;
- the analyst rating and target;
- the risks and invalidation.

It lists each open item once and passes on only what the web research found, with its URLs. House-only
findings ("Confirmed: no thesis exists") are left out.

**Where the answer goes:**
- the row is stored in `hermes_external_research` and reconciled into the symbol thesis by that script;
- the thesis store records `OPTIONS_THESIS_ESCALATED` (stage `EXTERNAL_RESEARCH`: lane, status, row id,
  findings);
- M2 gets it as an `options_followup` fact;
- the CIO re-review receives it as `research_answers.external_research`, next to the follow-up answers.

The external lanes see only the redacted house context and the question, so they supply a second opinion
on the web findings, not new searches. Config: `options_desk_settings.options_thesis_lifecycle.escalation_*`.

### Reopen an archived thesis (operator, 2026-09-27)
`scripts/options_thesis_reopen.py --symbol DELL --reason "..." [--apply]` (dry run by default)
appends `OPTIONS_THESIS_REOPENED` with the actor and the reason. The earlier archive no longer holds,
and the follow-up round count and the abandon clock restart from the reopen. Nothing is removed: the
archive and every earlier decision stay in the history. M2 records it as an `options_thesis_outcome`.

First use: DELL was archived at 00:37 ET after three rounds of research that read only house data,
three minutes before web research went live.

### Workers and schedule (24/7, 2026-09-26)
Every step runs unattended. Nothing waits for market hours or for the operator, except approval.

| Worker | When | Does | Log / proof |
|---|---|---|---|
| `options_thesis_lifecycle.py --apply` (cron) | `7,22,37,52 * * * *` | Queues research, reads answers, runs the CIO review, runs follow-ups, archives after 48h. Reads prior M2 facts (the M2 read credentials come from `/run/user/$UID/tradeai/env`, `M2_DSN=$M2_AGENT_DSN`) | `logs/options_thesis_lifecycle.log`; events in `data/cio/options_theses.jsonl` |
| `tradeai-hermes-cio-worker.timer` (systemd user) | `*:0/15` | Drains the Hermes CIO research queue that the lifecycle fills. Off-peak deferral is **off** for this unit (`offpeak-defer.conf`: `LLM_DEFER_OFFPEAK=0`, operator 2026-09-26 "research worker should run everyday 24/7"). Process cost caps still apply | `journalctl --user -u tradeai-hermes-cio-worker`; `data/cio/hermes_research_projection.json` |
| `options_memory_projector.py --apply` (cron) | `9,24,39,54 * * * *` | Two minutes after the lifecycle, writes new thesis-store events to M2. Idempotent (watermark `data/cio/options_memory_projector_state.json`; skips an `event_hash` it already holds) | `logs/options_memory_projector.log`; M2 rows `source_type='options_thesis_store'` |
| `export_options_runtime_snapshot.py --apply` (cron) | `3 * * * *` | Writes the redacted snapshot two minutes before the `:05` Drive sync | `logs/options_runtime_export.log`; Drive `runtime/options/` |
| `run_ensemble_worker.sh` (cron) | `*/3 * * * *` (24/7; before 2026-09-26 `*/3 9-16 * * 1-5`) | Drains `inference_ensemble_jobs`, including Aegis options reviews on the row's lanes (grok, chatgpt, deepseek-flash); `options_ensemble` cap $0.50/day | `logs/ensemble_worker.log` |

Every chain step reads what the previous one wrote, so a stalled worker shows as a queue that stops moving:
- research stays `queued` in the projection;
- the card's research ETA grows;
- the projector reports pending events.

Lanes are declared in `config/lane_registry.json` (`options-thesis-lifecycle`, `options-memory-projector`, `options-runtime-export`). Crontab backups are in `~/backups-crontab/`.

### After a CIO decision (continuous, 2026-09-26)
- **MORE_RESEARCH** is an assignment, not an end state: the next lifecycle run requests follow-up
  research whose questions are the CIO's own unknowns/concerns (up to `max_deliverables` 5), due in
  `followup_due_hours` (24). When delivered, the CIO reviews again and issues a **new Decision GUID**
  (`supersedes` links the previous one). Not delivered by the due time, or more than
  `max_followup_rounds` (2) follow-ups, archives the idea with the reason.
- **MONITOR_ONLY** re-reviews automatically after `monitor_recheck_hours` (24).
- **REJECT** is final. **APPROVE** waits for the operator (Validate within 30 min, approve, 2FA).
- The card shows the deliverables, due time, research-queue position/ETA and the decision history.

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