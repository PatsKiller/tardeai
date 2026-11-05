# Desks A: approved boards 1–4 (Re-Entry, Strategy, Defense, Agents)

**Status:** Local review candidate on `work/desks-boards-1-4-20261025`; fixture proof, not release evidence.
**Owner:** claude-desks14 (claim `20261025T063723Z-claude-6bb1f6c6`, records takeover of stale W5 claim `e101f785`).
**Updated:** 2026-10-25.
**Authority:** READ_ONLY_ADVISORY. No broker call, order, stop, job, provider call, write or DDL.

Approved layout and copy: `handoffs/desks-redesign-20261024/mockups/{ReEntry,Strategy,Defense,Agents}.dc.html`
(operator, 2026-10-24: "I approve the markups"). Shared frame: `docs/ops/DESKS_REDESIGN_20261024.md` (board 0).

## What shipped

| Board | Route (rail link) | New page | Classic page kept at |
|---|---|---|---|
| 1 Re-Entry | `/portfolio/re-entry` | `pages/desks/ReEntryDesk.tsx` | `/portfolio/re-entry/classic` (also every `?symbol=`, `?classify=`, `?lane=` deep link) |
| 2 Strategy | `/strategy` (`?tab=planner` from Risk) | `pages/desks/StrategyDesk.tsx` | `/strategy/classic` (honours `?tab=Planner`) |
| 3 Defense | `/defense` | `pages/desks/DefenseDesk.tsx` | `/defense/classic` |
| 4 Agents | `/agents` (`?tab=workflow` → Legacy analytics › Workflow) | `pages/desks/AgentsDesk.tsx` | `/agents/classic` |

The rail entries already pointed at these routes; the routes now open the new desks. The classic pages stay reachable,
unchanged, from a link at the foot of every desk until the operator accepts each desk (§28.9: nothing removed).

- **Backend.** `GET /api/v2/desks/<reentry|strategy|defense|agents>` → `api_v2._desks_a_payload` →
  `scripts/lib/desks_a.py`. GET only (405 otherwise), 60 s in-process cache, payloads 4–25 KB on real stores.
- **Frontend.** `components/DeskBoard.tsx` renders the projection inside `DeskPage`: URL tabs, source clocks (writer state from
  `/api/v2/desk-sources`), decisions, panel grid (one column under 1100 px), rows that are links or open a route-backed
  detail sheet (`?detail=<panel>:<row>`, full screen on a phone, ← Back, browser Back closes it). The component formats nothing.
  Every label and value comes from the projection.
- **Read-only.** The desks expose no action. Classify, plan, approve, stage, refresh, rate and lock stay on the classic pages,
  each one link away.

### Why the projection reads stores directly
Several legacy GETs behind these pages act on read (§28.9 "a read never acts"; §28.11 lets the existing ones run until fixed):

- `/defense/core` and `/defense/review` run DDL and commit.
- `/defense/posture` probes the Grok proxy and may rewrite a sector cache.
- `/defense/recommendations` runs `ensure_tables` and commit.
- `/options/lifecycle` runs `crontab -l`.
- `/strategy-desk` rewrites its cache.
- `/paper-trade-readiness` recomputes and writes statistics.
- `/symbol-cards` can fetch Yahoo and write analyst rows.

`desks_a.py` therefore does the following:
- reads the stores with a 4 MB byte cap;
- runs SELECT only, with a guard that refuses anything else;
- imports nothing beyond the standard library (a test checks this through the AST).

It reuses only these readers:
- `buy_ready_packets_index.index_packets`, which reads files;
- `_strategy_leaderboard`, which runs SELECTs only, so both Strategy pages rank strategies the same way;
- `redeploy_capital_book.build_history`, which runs SELECTs only;
- `cio_truth`.

### One CIO source
`cio_truth` is the only source for the CIO stance (`stances_for_symbols`), regime (`resolve().regime`), holdings, quote clock,
positions and stops (`resolve().positions/stops`). The desks recompute none of them. The defense engine's own per-name stance
is deliberately not shown, so it never competes with the CIO stance. Conflicts belong to the conflict engine (§28.10).

## Field trace (zero-hallucination contract)

Gap vocabulary:
- "not on file": the store has no value.
- "not measured": no writer computes this value.
- "could not be read": the read failed, and a gap note names the store.
- A date-only or zone-less clock is never promoted to an instant: the source clock says "date only" or "recorded without a time zone".

All file paths below are relative to the served tree root (`STATE_DIR.parents[2]`).

### Board 1 · Re-Entry

| On screen | Projection field | Store / key | Writer / lane |
|---|---|---|---|
| Ready now rows `SYM · zone $lo–$hi`, stage | `tabs.ready-now.ready.rows[]` | `data/runtime/buy_ready_packets/<SYM>.json` via `index_packets` (`equity.entry_low/high`, `equity.state`); ≤48 h only | `cio_entry_state_runner.py` · `cio-entry-state` |
| "N packets older than 48 h … kept in history" | panel `gap`, decision `packet-expiry` | `index_packets().stale` (age from `saved_at`) | same |
| Detail: price, planned stop/target, plan R:R, catalyst, saved | `detail.fields` | packet row keys `price, stop, target, rr_plan, catalyst, saved_at` | same |
| Detail: CIO stance · conviction | `detail.fields["CIO stance (cio_truth)"]` | `cio_truth.stances_for_symbols` (GUID-confirmed) or "CIO stance not on file" | CIO record |
| Classification: stopped out / classified (saved by you) | `classification.rows` | `ui_prefs` `portfolio.reentry.event-classifications.v1` → `eventType` | operator (classic overlay) |
| Sold names with no resistance level on file | `cls-res` | exit symbols (sells) minus `ui_prefs` `portfolio.reentry.resistance.v1.symbols` with a state ≠ UNAVAILABLE | `watch_alerts_eval.py` · `watch-alerts-eval` |
| Exit workbench rows (last 30 days), proceeds, your classification | `workbench.rows` | `trade_transactions` sells vs `deploy_events` (`build_history`) + classification pref | trade import / broker sync |
| Reclaim price vs now | detail field | **not measured**: no writer computes it | — |
| Resistance & levels | `levels.rows` | resistance pref `state, resistance, distance_pct, hold_days, tests, method, as_of` | `watch-alerts-eval` |
| Analyst consensus target, opinions, upside | `analyst.rows` | `data/runtime/pro_analyst_pills_latest.json` `pills[].target_mean_price, number_of_analyst_opinions, upside_to_mean_target_pct` | `build_pro_analyst_read_model.py` · `hermes-analyst-coverage`, `pro-analyst-fetch` |
| Revisions, 30 days | detail field | **not measured**: the read model has no revisions field | — |
| Clocks: regime, holdings priced | `sources` | `cio_truth.resolve().regime.as_of`, `.portfolio.quote_as_of` | `market-regime-classifier` (registry RETIRED → decision), `portfolio-repricer` |
| Clock: dividends | `sources.dividends` | `data/portfolios/state/dividend_calendar.json` `last_updated` (no zone, so shown as a gap) | `portfolio-ai-analyst`; upstream `sync-dividend-data` RETIRED |
| Owned elsewhere | links | board 13 | — |

The mockup's symbol-cards clock is not shown. `/symbol-cards` carries no timestamp, and its GET can fetch Yahoo. The cards
remain on the classic page.

### Board 2 · Strategy

| On screen | Field | Store | Writer / lane |
|---|---|---|---|
| Leaderboard rows, rank order, detail | `leaderboard.rows` | `_strategy_leaderboard()`: `paper_trades` closed, `strategy_backtest_results`, `strategy_performance_snapshots`, `strategy_tilt_multipliers` | paper engine; `feedback-loop-processor`; `strategy-tilt` |
| Paper-trade readiness: phase, closed / 2,000, win rate, next gate | `readiness.rows` | `data/paper_trading/paper_trade_statistics_latest.json` `level, closed_usable, win_rate, timestamp` (read, never recomputed) | **no lane** (the legacy GET recomputes it) → decision |
| Plan vs performance, last 100 closed | `pvp.rows` | `paper_trade_outcome_analytics.planned_r/realized_r`, falling back to `trade_thesis_outcomes.expected_r/actual_r` | outcome analytics writers |
| Biggest drift (≥3 trades) | `pv-drift` | avg(`realized_r − planned_r`) per strategy | same |
| Desk · state changes (30 d), registry by status | `desk.rows` | `strategy_state_transitions`, `strategy_registry.status` | `strategy_weekly_review.py` · `strategy-weekly-review` |
| Incubator candidates / active / promoted, setup advisory rows | `incubator.rows` | `incubator_universe` (`status`, `promoted_to_proposal_at`, `updated_at`), `candidate_setup_advisory` | `daily-incubator-refresh`, `weekly-incubator-builder`, `incubator-proposal-promoter`; `setup-quality-prior` |
| Backtests count, newest 10 | `backtests.rows` | `strategy_backtest_results WHERE run_id IS NOT NULL` | `proposal-backtest-engine` |
| Backtest detail panels (moved, board 13) | retained `BacktestPanel`, `ExecutionHypothesesPanel` | unchanged existing read-only GETs | unchanged |
| Planner | link to `/strategy/classic?tab=Planner` | — | planner POSTs stay on the classic page |

**Finding.** The mockup says setup advisory has "no scheduled writer". The registry lists `setup-quality-prior` as ACTIVE
(`0 22 * * *`, stage shadow). The desk shows the registry state and the date-only snapshot; it does not repeat the mockup claim.

### Board 3 · Defense

| On screen | Field | Store | Writer / lane |
|---|---|---|---|
| Market regime (CIO) | `act-regime` | `cio_truth.resolve().regime` | CIO regime source |
| Sector transitions today | `act-trans` | `data/runtime/sector_momentum_latest.json` `transitions_today[]` | `sector_momentum_engine.py` · `sector-momentum-engine` |
| Recommendations by group | `act-recs` | `data/runtime/defense_recommendations_latest.json` `groups.*` | `defense-recommendations` |
| Open intents and execution | link to classic | execution subsystem out of scope (§0 rule 2) | — |
| Your book rows, value, stop state and source, distance | `book.rows` | `cio_truth.resolve().positions.rows` and stops (stop_last_known before stops.json) | CIO record |
| Positions without an active broker stop, unprotected value | `bk-unprot`, `bk-heat` | `resolve().stops.unprotected_count`, `positions.unprotected_value_usd` | CIO record |
| (2026-10-25 stop desks) Positions / value with no broker stop, pending, filled awaiting sync, state not recorded | `bk-unprot`, `bk-heat`, `bk-pending`, `bk-filled`, `bk-unknown` | `resolve().positions.stop_breakdown.{none,planned,pending_activation,filled,unknown}` (counted positions); falls back to the rows above when absent | CIO record |
| Hedged share of book, most exposed (beta), defensive score | `bk-hedged`, `bk-exposed`, detail fields | **not measured**: no writer computes them for held names | — |
| Inverse-ETF stoplights | `stoplights.rows` | `data/runtime/inverse_stoplights_latest.json` `candidates[].lights.*.state/reason` | `defense-inverse-stoplights` |
| Short side ideas | `short.rows` | recommendations `groups.short_side[]` | `defense-recommendations` |
| Options protection counts and gap | `options` | `data/runtime/options_lifecycle_latest.json` `counts`, `generated_at` | `options-lifecycle-run` **PAUSED** → gap and decision |
| Cash alternatives yields and gap | `cash` | `data/runtime/defense_cash_alternatives_latest.json` `top3[].yield_data` | **no lane** → gap and decision |
| Review log | `review` | `config/promote_criteria.json` `criteria_locked, locked_at, amendments, decisions` | operator POST (classic console) |

### Board 4 · Agents

| On screen | Field | Store | Writer / lane |
|---|---|---|---|
| Jobs completed / failed / queued (24 h) | `runtime.rows` | `watchlist_agent_jobs` counted with FILTER and no row cap (the legacy pipeline counted a 200-row capped list) | `run-watchlist-agent-jobs-offpeak` |
| Agent runtime lanes registered · active | `rt-catalog` | `config/lane_registry.json` `tradeai-agent-runtime-*` states | registry |
| **Run timeline** (board fix) | `timeline.rows`, source clock | `data/runtime/agent_runtime_journals/<agent>/<run_id>.jsonl` record `ts`, `job_type`, `model_error` | `tradeai-agent-runtime-*` producers |
| Run model state per row: none · **No model by design** (info) · model error (red) | `run-<id>.tone`, detail `Model` / `Model error` | journal `model_error` compared with `desks_a.GATE_B_PLACEHOLDER` (exact text) | Gate-B sentinel `agent_runtime_live_providers._build_governed_gateway_provider` |
| No model by design: N of M newest runs, per-agent 24 h runs / Gate-B / retrieval_count 0 | `run-gate-b` row + detail sheet | journal `ts`, `model_error`, `retrieval_count` over the last 24 h (file mtime picks candidates with 2 h slack, at most 10,000 files; record `ts` decides) | same producers |
| Decision: `tradeai-agent-runtime@{…}` timers, runs in 24 h, no model by design (links to the `run-gate-b` sheet) | `decisions[runs-gate-b-shadow]` | same 24 h counts, agents whose runs carry the placeholder | same producers |
| Calibration last run, best and worst Brier | `calibration.rows` | `agent_calibration_windows` latest per agent, `brier_score`, excluding `low_sample_size` | `agent-calibration-engine` (Sun 12:00) |
| Learning: newest lesson | `ln-newest` | last appended record of `data/runtime/advisory_kb_lessons.jsonl` (2 MB tail read, `ts`) | `advisory-lessons-reflect` |
| Trade reviews (30 d), newest | `ln-weekly*` | `paper_trade_multi_reviews.created_at` | `multi-tier-trade-reviewer-*` |
| Memory records / active / admitted today / by type | `memory.rows` | `data/cio/aif_memory.jsonl` (latest row per `memory_id`), `aif_memory_admissions.jsonl` `admitted_at` (newest 2 MB) | CIO memory admission |
| Cases | `cases.rows` | `data/cio/cio_production_cases.jsonl` newest events (tail) | CIO case writers |
| Promotion snapshot | `promotions` | `data/cio/maturity_promotions.json` (not on file today) | maturity control |
| Legacy analytics (Roster, Calibration, Workflow, Weekly Learning) | retained `AgentsHub` (`initialTab`) | unchanged existing GETs | unchanged |

**Run timeline root cause.** The old reader reads `agentic_runtime.agent_runs`. Since `aedac0989` (2026-08-11) the live
producers (`agent_runtime_live_providers._process`) write only per-run journals and `cio_goal_laps.jsonl`. Their database hook
calls `persistence.record_shadow_outcome`, which no class defines, so `hasattr` is False and nothing is inserted. The desk
reads the journals: file mtime only picks which files to open, and the clock is each record's own `ts`. On the 2026-10-25 tree
the journals hold 90,125 runs, the newest at 06:41 UTC. The 12 newest all record `PROVIDER_BLOCKED` model errors, which the
desk surfaced as a decision.

**Gate-B placeholder is not a model error (2026-10-25 follow-up).** That `PROVIDER_BLOCKED` text is the deliberate Gate-B
sentinel returned by `_build_governed_gateway_provider()` in `scripts/agent_runtime_live_providers.py`: no provider is
contacted, the response is empty, so no AI finding is produced. Every alex/steph/morgan run since 2026-08-11 carries it, so
counting it as a model error made the desk read "12 of the 12 newest runs recorded a model error" and would hide a real
provider failure. The desk now classifies a `model_error` equal to `desks_a.GATE_B_PLACEHOLDER` (exact text) as
"No model by design (Gate-B: reasoning goes through the CIO governed bridge)": the run row is `info` (neutral), its sheet shows
`Model` instead of `Model error`, a `run-gate-b` row counts them, and they are left out of the timeline gap and the
"recorded a model error" decision. Any other `model_error` (including other `PROVIDER_BLOCKED` text) is still red and still
counted. `desks_a` mirrors the text rather than importing the producer (the module stays import- and side-effect-free);
`test_gate_b_placeholder_is_pinned_to_the_producer_text` reads the producer's AST and fails CI if the two drift.
A neutral "Decisions for you" item states the shadow timers' measured 24 h volume, the placeholder count and the
retrieval_count 0 count, and names the choice (pause or slow the timers, or wire the agents to the CIO governed bridge) with no
recommendation; it links to the `run-gate-b` detail sheet. The 2026-10-25 audit reported about 1,600 such runs a day;
the desk shows the live measured count, not that figure.

The producer-side fix is not in this branch. It would implement `record_shadow_outcome` or restore the `agent_runs` insert,
and the producers are agent-runtime code outside this desk.

## Board 13 duplicate removals in this branch

| Content | Home (board 13) | Removed from | How |
|---|---|---|---|
| Fund look-through | Portfolio › Look-through | New Re-Entry desk | Link only; classic page unchanged until acceptance |
| Rotation workspace | Rotation | New Re-Entry desk | Link only |
| Sector momentum and leaders | Watch › Sectors | New Defense desk | Link only |
| Backtests | Strategy | TradeInView classic `Backtesting` tab (`JournalHub.tsx`) | Tab shows a link to `/strategy?tab=backtests`; `BacktestPanel` + `ExecutionHypothesesPanel` now render under Strategy › Backtests; StrategyHub "Backtest →" points there |
| Questions to the advisor | Ask the CIO bar + My questions | Rotation "Ask the Rotation Advisor" box | Replaced by a link card (My questions) that keeps "Refresh Summary"; earlier answer panel still renders |

Not done in this branch. Each home page lacks the content, so the move belongs to that board's build:
- **Intelligence Trade AI rows:** mixed into the Command Center feed; board 5.
- **Research topics → Research Intel:** `ResearchTopicsModal` exists only on Intelligence; boards 5/9.
- **Hermes Discovery tab → Research Intel:** `HermesDiscoveryInbox` exists only on Hermes; boards 7/9.

## Proof (fixtures only, no :7777 traffic)

- `tests/test_desks_a_20261025.py` (gate `config/ci_gates/desks_a_20261025.json`): pinned fixtures for every board, gaps never zero,
  SELECT-only, no writes (tree digest), AST import and side-effect guard, payload under 500 KB, tabs equal the boards, GET-only
  route, rail and classic routes, board 13 links.
- `apps/command-center-v3/e2e/desks-a.fixture.mjs`, wired into `.github/workflows/desks-a-fixture.yml`: the actual desk pages
  bundled against `e2e/fixtures/desksA.fixture.json`, which is generated from `desks_a.py` with the test inputs. It runs at
  1440, 412 and 390, and fails on any non-GET request or external host. It checks:
  - every tap target is at least 44 px;
  - detail sheets are full screen on phones, with focus inside, and ← Back closes them;
  - deep-linked detail, `?tab=planner`, `?tab=workflow`, `?tab=evidence`, and `?symbol=` → classic;
  - there is no horizontal scroll.
- Screenshots `impl-{1,2,3,4}-<state>-{1440,412,390}.png` beside the mockups; receipt `desks-a-mobile-receipts-20261025.json`.
