# Session 2026-06-02 — V3 Backtest Intelligence

Status:      HISTORICAL
as_of:       2026-06-03T09:51:24-04:00
Measured at: efcc51365 / not measured

**Scope:** Full port of the v2 Backtesting page into the v3 Strategy → Backtest tab, then a "Backtest Intelligence" layer (entry-quality grading, edge decay, capture/left-on-table, potential-over-time). Read-only UI throughout. All changes confined to `apps/command-center-v3/` plus additive backend (one new table, one new script, one new endpoint, three cron lines).

---

## 1. What shipped

### Frontend (`apps/command-center-v3/`)
- **`src/components/BacktestPanel.tsx`** (new) — full v2 parity port + new tabs. Wired into `src/pages/StrategyHub.tsx` (Backtest tab).
- Ported sub-tabs: Overview, Strategy, Trades, Missed, Results, Runs, Trail Analysis, MFE/MAE, Optimization, LLM Review Coverage.
- New sub-tabs / panels:
  - **Cadence strip** — last run + runs/day sparkline (from `/api/v2/backtesting/runs`).
  - **Entry Quality** — grade distribution, RSI-vs-outcome, coaching bullets, best entries.
  - **Capture** — cumulative money-left-on-table over time, by-trade-type, worst exits.
  - **Potential Over Time** — run-over-run hypothetical performance (append-only history).
  - **Edge Decay** (in Overview) — backtest win-rate vs live paper win-rate per strategy.
- **`src/components/DetailDrawer.tsx`** enriched — sparkline for series rows, entry/exit grade badges, and auto-fetch of the per-trade backtest grade (Journal ↔ Backtest link) via `/api/v2/journal/backtest/{key}`.

### Backend (additive only)
- **Table `backtest_result_history`** (Postgres) — APPEND-ONLY. One permanent row per backtest run (`UNIQUE(run_id)` + `ON CONFLICT DO NOTHING`); never updated or deleted. Backfilled 209 rows from the immutable `strategy_backtest_trades` + `strategy_backtest_runs` history.
- **Script `scripts/backtest_history_snapshot.py`** (new) — idempotent archiver that appends a snapshot for any run not yet recorded.
- **Endpoint `/api/v2/backtesting/result-history`** (in `scripts/api_v2.py`) — read-only, `?run_type=` filter, defaults to `replay_trades`.

### Default behavior
- Backtest views default to **`run_type=replay_trades`** (real differentiated data). Champion rows are seeded/uniform simulations and are not the default.

---

## 2. Key discovery — entry-grade engine was never scheduled

`scripts/trade_backtest_engine.py` reconstructs entry/exit technical context for closed trades (RSI, SMA distances, volume ratio, 52w percentile, ATR, better-entry-existed, left-on-table 5/10/20d) and grades entry/exit A–D into `trade_backtest_results`. **It existed but was not in crontab, so the table was empty** — the v2 journal coaching panels and the v3 Entry Quality tab had no data.

Ran it manually (61 closed trades graded). Findings:
- Entry grades: **B:1 · C:10 · D:48** — entries are timed late.
- **Avg entry RSI 67.8** — buying into overbought.
- **$210,141 left on table (20-day)**; 21 grade-D exits account for **$189,001** of it.

Now scheduled (see cron below). Served by existing endpoints `/api/v2/journal/backtest-summary`, `/api/v2/journal/backtest-analytics`, and per-key `/api/v2/journal/backtest/{key}` (`:` encoded as `__`).

---

## 3. Backtest cadence (crontab — source of truth)

| Job | Schedule | Scope |
|-----|----------|-------|
| Daily active backtest | Weekdays 6:00 AM ET | `strategy_backtester.py` — active strategies |
| Weekly full enterprise replay | Sunday 10:00 PM ET | `enterprise_backtester.py --replay-trades` — all strategies |
| Weekly LLM backtest review | Sunday 11:00 PM ET | 50 unreviewed backtest trades |
| **Entry/exit grade engine** *(new)* | Weekdays 6:30 PM ET | `trade_backtest_engine.py` — grades newly closed trades |
| **Result-history archiver** *(new)* | Weekdays 6:10 AM + Sun 10:10 PM ET | `backtest_history_snapshot.py` — append-only snapshot |

All new jobs guarded by `safe_flock.sh`. Crontab backed up to `logs/crontab.backup.*` before edit.

---

## 4. Design decisions

- **cron vs systemd:** services = systemd (`tradeai-portfolio-server.service`); scheduled batch jobs = cron + `safe_flock.sh`. The new archiver and engine are batch jobs → cron, matching the existing pattern.
- **Append-only history:** honors the "never overwrite historical" requirement. `strategy_backtest_results` is an overwritten latest-snapshot table; `backtest_result_history` is the permanent record.
- **Read-only UI:** all v2 write/POST controls (Replay Trades/Proposals buttons, per-tab "Run Analysis" buttons) were dropped. Empty tabs show honest empty states, never fabricated data.
- **Derived fields labelled in-UI:** Missed "Outcome" (derived from `simulated_pnl` sign — endpoint has no `verdict` field) and Optimization config fields (`current_config`/`optimized_config`, not v2's non-existent `*_breakeven`).

---

## 5. Honest caveats

- **Potential Over Time** on the default `replay_trades` filter is sparse (2 points — all the replay history that exists today) and fills in daily. Switch the run-type filter to `champion` for the full 206-point series.
- Entry-grade sub-scores in the MFE table (`slippage`/`timing`/`setup`) are mostly 0 today; only `context` is populated. The richer entry grading lives in `trade_backtest_results` (this engine), which the Entry Quality tab uses.

---

## 5b. AI Trade Eval (structured LLM evaluation) — added 2026-06-02

A structured LLM trade-evaluation layer (post-trade research / journaling only — **not live trading advice**).

- **Engine extension** (`trade_backtest_engine.py`): now also computes, from the daily OHLCV it already fetches, **MACD** (line/signal/hist/state), **Bollinger** (%position/state), **ADX**, **Fibonacci** (nearest retracement level + swing leg), **daily candlestick** pattern, and a **market-structure** tag. Stored in 13 new `trade_backtest_results` columns. VWAP and intraday signals are **not** captured (no intraday data retained) and are explicitly excluded from judgment.
- **Evaluator** (`trade_close_llm_analyzer.py --structured`): self-contained path (does not touch the existing prose review). Reads enriched `trade_backtest_results`, builds a structured prompt, calls **gemma3:12b** locally, and stores a structured review on `trade_llm_reviews` (`review_stage='structured_backtest_eval'`): six scores (confluence / entry_timing / exit_quality / risk_reward / management / overall), a verdict (one of 12 labels), entry/exit assessment, improvements, data_gaps. Headline columns `eval_overall_score` + `eval_verdict` added. Outcome and quality are scored separately ("a winning trade can still be a bad trade"). Dedup by symbol+close_date; `model_error` rows retry. Non-mutating, so the slow CPU preflight is advisory (warn-not-abort).
- **Endpoint** `/api/v2/backtesting/trade-evaluations` — read-only; returns evaluations + verdict distribution + disclaimer.
- **v3 UI**: new **AI Trade Eval** sub-tab in Backtest — disclaimer banner, avg score, verdict distribution, per-trade table; drill into full scores/assessment/improvements via DetailDrawer.
- **Cron**: weekdays 9 PM ET, `--limit 12`, flock-guarded (after the 6:30 PM entry-grade engine). gemma3:12b ≈ 1–4 min/trade on CPU.
- First eval sample: BNAI graded **"weak setup," overall 20** — "entered prematurely and exited early, leaving significant profit on the table."

## 5c. Feedback loop → ATM proposal advisory (setup-quality prior) — added 2026-06-02

Closes the loop from post-trade findings into forward advisement. **Advisory-only: never writes to `paper_trade_proposals`, never affects any gate or execution.**

- **`scripts/setup_quality_prior.py`** (new) distills the entry grades (`trade_backtest_results`) + structured LLM evals (`trade_llm_reviews`) into an aggregate **setup-quality prior** by RSI band, then attaches a per-proposal **advisory** to recent proposals whose entry profile matches a weak band. Rebuilds two derived tables each run: `setup_quality_prior` (one row/band: n, win_rate, avg_left, grade_score, llm_score, dominant_verdict, confidence) and `proposal_setup_advisory` (one row per proposal-with-RSI: band, prior_score, flag caution/neutral/favorable, note).
- **The prior is monotonic in the LLM scores** (more data is decisive): RSI 40-55 → 60 ("good entry, poor exit"); 55-70 → 32 ("weak setup"); >70 → **10 ("weak setup")**. Every output labelled by sample size + confidence (high/med/low); `<40` band is low-confidence (n=2).
- **Endpoint** `/api/v2/atm/setup-advisory` — prior + advisories + disclaimer.
- **v3 UI**: "Setup-quality prior" panel in the AI Trade Eval tab; **caution badge on Trading-hub proposal rows** (e.g. ARM/EVER @ RSI>70 → "⚠ setup ~10"), with the full note in the drill drawer.
- **Cron**: nightly 10 PM, flock-guarded, after the evals.
- Reality at build time: prior is thin (59 closed trades) and there were no truly-pending proposals — flagged to operator, who chose to wire it live anyway with confidence labels intact. It strengthens automatically as evals/closed trades accumulate.

## 5d. Feedback loop extended → Incubator + Watchlist + new v3 Watchlist page — added 2026-06-02

The setup-quality prior now also advises **candidate symbols** (not just proposals). **Advisory-only — never changes incubator scoring/promotion or watchlist status.**

- **`setup_quality_prior.py`** extended with `build_candidate_advisories()`: for each ACTIVE incubator symbol and `active` watchlist item, looks up the symbol's latest RSI from `ticker_snapshot_daily` (2,725 symbols, ~93% incubator coverage), maps to the prior's RSI band, and writes a row to new table `candidate_setup_advisory` (entity_type incubator|watchlist, symbol, rsi, band, prior_score, flag, note). Dedup via `ON CONFLICT (entity_type,symbol)` (incubator has same symbol under multiple strategies). Result: **302 incubator advisories (174 caution), 38 watchlist (22 caution)**.
- **Endpoint** `/api/v2/setup-advisory/candidates?entity=incubator|watchlist&flag=` — advisories + counts + disclaimer.
- **v3 UI:**
  - **Incubator tab** (StrategyHub): caution/favorable badge per row ("⚠ setup ~10"), advisory in the drill drawer.
  - **NEW v3 Watchlist page** (`WatchlistHub.tsx`, nav `/v3/watchlist`): active items + setup-advisory strip (caution/favorable counts) + per-item RSI/band/score badge; drill shows the full note. v3 previously had no watchlist page.
- Same nightly 10 PM cron builds proposals **and** candidate advisories — no cron change.
- Scope note: this surfaces advice; it does **not** alter promotion, rolloff, or ranking logic. Incubator/watchlist remain decision-by-operator.

## 5e. Fixes (post-build)

- **Optimization tab blank** — `trailing-optimization` returns `current_config`/`optimized_config` as **objects** (`{breakeven: 1.5}`); rendering them as raw React children crashed the tab. Fixed with `cfgLabel()`/`cfgBE()` helpers (render "BE 1.5R") and corrected the detail-chip highlight to compare against the optimized breakeven value.
- **Overnight eval daemon died after 7 trades** — a single gemma3:12b call hit `TimeoutError` (CPU under load > 420s) and the unhandled exception killed the loop. Wrapped the per-trade call in try/except (logs + retries next run), and stopped writing `model_error` rows. Relaunched the resilient batch (skips the completed 7, processes the remaining ~33). Also added a one-shot **morning check** (`scripts/morning_eval_check.sh`, cron `0 7 3 6 *`, Telegram-verified) that reports batch + prior status.

## 5f. Agents hub rebind + workflow graph (core fleet)

v3 Agents hub was mis-wired (showed "Agent 0…9", raw JSON, bare numbers). **Fixed the bindings** (real field is `agent` not `name`; Calibration from `/agent-calibration/windows`; Performance table not JSON) + added **roles + real runtime model gemma3:12b** (stale qwen3:14b label suppressed). Added a **React Flow Workflow tab**: ★ Alex/CIO orchestrator hub, live edges from `/agent-pipeline` (`from_agent→to_agent`+escalated, "Alex"→"alex" normalized), non-roster pipeline nodes (synthesis/auto_research/human_review) shown grey with **descriptive drawers** (human_review = operator escalation sink, surfaces escalated symbols+reasons), configured chain maria→steph→risk→tax dashed/labeled. Calibration tab = the agent-trust gate (PROPOSAL-ALLOWED vs SHADOW-ONLY). See `project_v3_agents_hub` memory.

## 5g. Hermes workflow + VALIDATED run-state (challenger fleet)

Separate React Flow graph in the **Hermes hub** (challenger wall: NO control edge to core; only a one-way "reads Trade AI safe views" arrow). Built a footprint endpoint **`/api/v2/hermes/agent-footprint`** that validates each agent's real DB rows. Key finding: the contract doc's "design only" labels are **approval state, not execution** — 3 agents (Librarian, Backlog Mgr, Embedding Curator) have **real autonomous-loop/dry-run footprint but are NOT governance-approved** (rendered amber "running — NOT approved"). Graph shows **two axes** (approval vs validated footprint) with real counts; drawer separates them. `hermes_research_backlog` table confirmed not created (endpoint surfaces backlog-tagged `hermes_research_intelligence` rows). Contracts doc updated with the validated table. Governance flag raised: autonomous writers running ahead of approval.

## 5h. Global modal/UX overhaul (DetailDrawer + Hermes backlog)

- **DetailDrawer (every v3 modal)**: humanizes keys (snake_case → Title Case + acronym map: RSI/MACD/P&L/RACI…), **parses JSON-string blobs into readable nested fields** (e.g. dual-opinion `tradeai_original` → Score/Decision/Summary instead of raw `{"score":31…}`), formats ISO timestamps, color-codes statuses/verdicts (agree/operational green, disagree/disabled red, staged/caution amber), renders `— Section —` keys as headers.
- **Hermes Research Backlog**: raw findings (`backtest_weak_strategy: WR=…`) → clean cards with plain-English **title + meaning + suggested resolution + where to resolve**, severity dots (critical/warning/info), dedup, severity-sorted. Honest note that Hermes is advisory-only (flags, doesn't auto-run).

## 6. Files touched

| File | Change |
|------|--------|
| `apps/command-center-v3/src/components/BacktestPanel.tsx` | NEW — full backtest panel |
| `apps/command-center-v3/src/components/DetailDrawer.tsx` | enriched (sparkline, grades, backtest link) |
| `apps/command-center-v3/src/pages/StrategyHub.tsx` | Backtest tab wired to BacktestPanel; removed thin block |
| `scripts/backtest_history_snapshot.py` | NEW — append-only archiver |
| `scripts/api_v2.py` | +1 endpoint `/api/v2/backtesting/result-history` |
| `crontab` | +3 lines (archiver ×2, engine ×1) |
| DB `backtest_result_history` | NEW table, backfilled 209 rows |

See also: `project_v3_dashboard.md` (canonical v3), `COMMAND_CENTER_PAGE_MATRIX.md`, `MASTER_SYSTEM_DOCUMENTATION.md` §4 (schema) + cron schedule.
