# Trade AI v12 — Architecture

> **Audience:** engineers and reviewers who need to understand how the major layers connect.
>
> **Deeper references — link, don't duplicate:**
> - [docs/MASTER_SYSTEM_DOCUMENTATION.md](docs/MASTER_SYSTEM_DOCUMENTATION.md) — canonical per-subsystem detail
>   (service architecture §2, database §4, pipelines §5, proposal lifecycle §10, agents §11, LLM subsystem §12,
>   API §13, frontend §14, scheduling §16, safety rules §19, key file locations §20).
> - [docs/EXECUTIVE_ARCHITECTURE_OVERVIEW.md](docs/EXECUTIVE_ARCHITECTURE_OVERVIEW.md) — non-technical summary
>   (four-layer framing: DATA IN → INTELLIGENCE → DECISION → PAPER EXECUTION, plus dashboards and journal/learning).
>
> **Operator procedures:** [OPERATIONS.md](OPERATIONS.md).

## Maturity, honestly

- **Paper trading is fully autonomous.** The ATM lane (`scripts/atm_auto_approver.py`, cron `*/15 9-15 * * 1-5`)
  evaluates pending proposals against gates and, when `mode='active'`, calls the canonical
  `approve_proposal()` + `submit_paper()` chain against Alpaca **paper only**
  (`scripts/alpaca_paper_adapter.py` hardcodes `https://paper-api.alpaca.markets` and is disabled unless
  `ENABLE_ALPACA_PAPER=true`).
- **Live (Schwab) is fenced fail-closed.** `scripts/brokers/execution_guard.py` defaults Schwab to
  `BROKER_DISABLED`. The one remaining operator gate on any live order is **per-order 2FA approval**
  (`scripts/brokers/approval_service.py` + `execution_readiness.py`: gate roster includes
  `operator_2fa_confirmed`; unlock message reads "live enabled via operator unlock — per-order 2FA still
  required"). The protective-stop pilot creates the approval set with `REQUIRED_CHANNELS=1` — either web
  typed-ticker **or** Telegram code suffices. All other Stage-2c stop gates were removed
  (`brokers/protective_stop_policy.py`: `GATES_REMOVED = True` — "the universal per-order 2FA … still
  confirms EVERY order before it reaches Schwab").
- **Validation status:** the system is in its paper-trading validation phase.
  [docs/EXECUTIVE_ARCHITECTURE_OVERVIEW.md](docs/EXECUTIVE_ARCHITECTURE_OVERVIEW.md) documents a 6-month
  validation gate (target 55% win rate, 1.3 profit factor).
- **Hermes and all learning loops are advisory-only** — they never touch orders, status, gates, or 2FA.

## System flow

```
                         DATA IN                                 INTELLIGENCE
  screeners (finviz_screener_runner, incubator_llm_screener)   Hermes closed loop (advisory-only)
  broker syncs (Schwab, SnapTrade/Fidelity read-only)          hermes_scope_governor.py  (S0-S3 tiers)
  price/news/catalyst ingestion                                hermes_outcome_feedback_agent.py
        │                                                      state/hermes/outcome_bus.json
        ▼                                                      config/hermes_*.yaml (14 files)
  paper_trade_proposals  ◄──────────────────────────────────────────┘ (feedback_to_governor)
        │
        ▼  DECISION PIPELINE
  auto_proposal_generator.py ─► proposal_enrichment_loop.py ─► proposal_agent_review.py
        │                        (price/technicals/catalyst)    (Maria / Risk / Steph)
        ▼
  proposal_llm_review_worker.py (proposal_llm_review_queue — analysis only, cannot approve)
        │
        ▼
  proposal_decision_gate.py ─► proposal_route_risk_gate.py (fail-closed) ─► broker_promote_oversight.py
        │                                                                    (paper → broker promote)
        ├──────────────► PAPER LANE (autonomous)              ┌────────► LIVE LANE (gated)
        │   atm_auto_approver.py ─► proposal_paper_submitter  │   brokers/execution_guard.py (fail-closed)
        │   ─► alpaca_paper_adapter.py (paper API only)       │   ─► per-order 2FA (approval_service.py)
        │                                                     │   ─► brokers/schwab_order_adapter.py
        ▼                                                     ▼
  portfolio_loader.py (holdings.json = source of truth) · portfolio_trade_journal.py · journal_* learning
        │
        ▼  SERVING
  scripts/portfolio_server.py :7777 (systemd user unit) ─ mounts ─► scripts/api_v2.py (/api/v2/*)
        │                                                           scripts/reports_portal.py (/v3/reports data)
        ▼
  apps/command-center-v3 (Vite + React, served under /v3) — 16+ hubs, card v4 locked
        │
  PostgreSQL `trade_ai` (db_adapter.py) + data/ + state/ runtime files (gitignored)
```

## 1. Server layer

- **`scripts/portfolio_server.py`** is the single HTTP server, built on stdlib `http.server` +
  `socketserver` (**not** Flask). It binds port **7777** on all interfaces.
- Concurrency: `ReusableHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer)` — multi-threaded
  since 2026-06-29, bounded by a semaphore (`DASHBOARD_MAX_CONCURRENCY`, default 16) with
  `request_queue_size = 128` and daemon threads. Each request thread gets its own DB connection, closed in
  `PortfolioHandler.finish`.
- Run by the **systemd user unit** `config/systemd/portfolio-server.service`:
  - `ExecStart=…/.venv/bin/python scripts/portfolio_server.py`
  - `Restart=on-failure`, `RestartSec=5`, `WantedBy=default.target` → manage with `systemctl --user`.
  - Deliberately no `fuser -k` in `ExecStartPre` (overlapping restarts once caused orphan-listener churn).
- Sibling units in `config/systemd/`: `tradeai-schwab-stream`, `tradeai-health-agent`,
  `tradeai-continuous`, `grok-oauth-proxy`, `chatgpt-oauth-proxy`.
- **Hot-reload covers exactly two modules: `api_v2` and `reports_portal`.** `_get_api_v2()` tracks both
  files' mtimes; when one changes, a single thread wins a **non-blocking** lock and `importlib.reload()`s
  the changed module while other threads keep serving the current one. Any other module edit
  (e.g. `portfolio_loader.py`, `account_policy.py`, `inference_api`) requires a full server restart —
  see [OPERATIONS.md § Server restart](OPERATIONS.md#6-server-restart).

## 2. API layer

- **`scripts/api_v2.py`** (~39.6k lines) is a plain Python module — not a Flask blueprint — exposing
  `handle(path, method, body, query)` plus a `ROUTES` dict. Its header: "Normalized API for Command
  Center v2. All endpoints return stable, frontend-friendly JSON shapes. Read-only aggregation + journal
  review write layer."
- Largest endpoint groups by route count: `hermes`, `journal`, `atm`, `paper-proposals`, `admin`,
  `broker-proposals`, `watchlist`, `backtesting`, `reports`, `broker-orders`, plus many smaller groups
  (aegis, system, options, iris, topics, holdings, rotation, snaptrade, stops, …).
- `/api/v2/inference*` is delegated to a separate `inference_api` module (which is **not** hot-reloaded).
- Notable for sizing: **`GET /api/v2/proposal-accounts`** ("Schwab + Fidelity destinations with
  equity/cash for propose modal", 30s cache) returns per account:
  `sizing_base`, `sizing_base_label` (`cash` or `buying_power`), `cash`, `buying_power`, `is_retirement`,
  `sizing_ready`, `balances_status`, `max_position_pct_of_equity`; and a top-level `sizing_policy`
  (`max_deploy_pct_of_cash` default 20, `max_risk_pct: 2`) with the note:
  *"Risk sizing uses sizing_base (cash/buying power), not total equity. Retirement accounts are cash-only."*

## 3. Frontend — Command Center v3

- **`apps/command-center-v3`**: Vite + React 18 + TypeScript, `react-router-dom` with `basename="/v3"`.
  It is the canonical UI; `command-center-v2` is a frozen fallback, `broker-admin` a separate app.
- Hub routes (`src/App.tsx`): home, portfolio, risk, trading, strategy, agents, intelligence, hermes,
  retirement, journal, watch, reports, rotation, rec-intel, health, system.
- **Card v4 family is LIVE** on all card surfaces — watchlist, broker proposals, open-trades positions,
  options desk (operator decision 2026-07-05). `readCardsV4()` in `src/lib/cardsV4.ts` always returns
  `true`; v3 components remain in-tree for reference only. Options desk semantics (debit/credit labels,
  blocked-action gating, route vs data-source copy, PRIME bands, liquidity warnings) ship in
  `OptionProposalCardV4` + `lib/optionsCardSemantics.ts`, enriched API-side by `card_semantics.py`.
- **Market-aware staleness:** `src/lib/watchlistCardV4.ts` `marketAwareStale()` — data ≤1h old is never
  STALE; older data is STALE only if the market has actually moved since enrichment. A Friday-evening
  enrichment stays fresh all weekend and re-arms at Monday 09:30. This mirrors the server-side grace in
  `scripts/pipeline_freshness_monitor.py`, which extends freshness thresholds by the number of consecutive
  non-trading days (capped at 14).
- Frontend sizing preview: `src/lib/watchlistProposeSizing.ts` (see §7).

## 4. Hermes closed-loop intelligence (advisory-only)

Design law, stated across the module headers: **"outcome yield outranks throughput yield."**

- **Scope Governor** — `scripts/hermes_scope_governor.py` + package `scripts/lib/hermes_scope_governor/`
  (`engine.py`, `reactions.py`, `scoring.py`, `universe.py`, `watchlist_lifecycle.py`, …).
  "Sole owner of `watchlist_items.scope_tier`": Hot/Warm/Cold map to **S0+S1 / S2 / S3** monitoring tiers.
  Has a `HERMES_DISABLED` kill switch and `--apply/--dry-run/--inspect/--reaction-review` modes.
  Capital-exposed S0 positions are never bus-demoted (`if cur_tier == "S0": return None`).
- **Outcome bus** — `scripts/lib/hermes_outcome_bus/` writes the versioned read model
  `state/hermes/outcome_bus.json` (`outcome-bus-v1`) with `global`, `by_symbol`, `by_tag`, and
  `feedback_to_governor` sections.
- **Feedback agent** — `scripts/hermes_outcome_feedback_agent.py` "turns graded ledger outcomes into a
  structured, versioned outcome_bus.json that the Scope Governor and Research Agent consume."
  Nightly cadence: 02:50 `hermes_outcome_grader.py` → 03:05 `hermes_tag_engine.py` →
  03:25 `hermes_outcome_feedback_agent.py` → 03:35 `hermes_outcome_learning.py`.
- **Config** — 14 `config/hermes_*.yaml` files govern the loop without code changes: alerts
  (conservative/non-spammy), holdings lifecycle (no auto-sell), maturity model (`maturity-v2`,
  composite 0–100), outcome feedback/grader (rules-first, SQL+JSON, zero LLM), outcome learning
  (every loop gated by sample size), reactions, research budget (`ALLOW | DEFER | METADATA_ONLY | BLOCK`),
  scope-governor tiers/caps, score weights (+ scalp variant), tag engine, adaptive thresholds
  (proposals require human approval, `review_mode: true`), watchlist lifecycle.
- **UI** — `HermesClosedLoopPanel.tsx`, embedded in the `/hermes` hub (`HermesHub.tsx`): hit-rate trends,
  gate states (`promote_eligible`, `demote_pressure`, `pause_eligible`, `promote_blocked_bad_tag`),
  alerts (`hit_rate_declining`, `efficiency_declining`, `scope_creep`, `stop_quality_divergence`), and the
  maturity breakdown (`outcome_yield / scope_discipline / stop_quality / feedback_loop /
  research_actionability`).
- **Discovery → strategy pipeline** — white-space research discovery (`hermes_discovery_*`) can promote
  an operator-approved candidate into a real strategy config. First promotion: candidate #339
  (`APPROVED_RESEARCH_ONLY`) → `config/strategies/deep_itm_call.yaml`, a **paper-only** options strategy
  (model → paper → validate → operator decision); every proposal carries `meta.discovery_ref` back to the
  candidate so paper outcomes close the discovery loop. See
  [docs/OPTIONS_STRATEGY_PIPELINE.md](docs/OPTIONS_STRATEGY_PIPELINE.md).

## 5. Portfolio & journal layer

- **`scripts/portfolio_loader.py`** — "holdings.json is the SINGLE SOURCE OF TRUTH for share counts."
  It never zeros an account and never changes share counts during a pipeline run; the Import Data modal
  (`/api/import`) is the only way to update share counts, with an abort if a new total is <50% of the
  previous total.
- **`scripts/portfolio_trade_journal.py`** — classifies trades DAY/SWING/SHORT/LONG by hold duration;
  feeds the journal views.
- **`scripts/journal_*`** (11 scripts) — the learning surface over closed trades:
  - `journal_agent_coach.py` — agents analyze the journal and provide coaching.
  - `journal_ai_critique.py` — automated post-trade AI critique (TradeZella-style).
  - `journal_analytics_engine.py` — read-only analytics for the v3 Journal hub.
  - `journal_review_builder.py` — LLM entry/exit grades + lessons into `journal_trade_reviews`.
  - `journal_trade_in_view.py` — TradeInView analytics (exit intelligence, Zella score, tilt, sectors).
  - `journal_ask.py` — natural-language Q&A over the journal.
  - Plus reminder/tilt/lifecycle/queueing helpers (`journal_annotation_reminder.py`,
    `journal_tilt_morning_hook.py`, `journal_ticker_lifecycle.py`, `journal_backtest_high_llm_enqueue.py`,
    `journal_tab.py`).

## 6. Proposal pipeline (screeners → execution)

1. **Generation** — `scripts/auto_proposal_generator.py`: "Auto-create PENDING paper proposals from
   planned strategy signals … Does NOT approve trades or submit orders. Populates the review queue."
   Screener inputs include `finviz_screener_runner.py` and `incubator_llm_screener.py`.
2. **Enrichment** — `scripts/proposal_enrichment_loop.py`: continuous enrichment toward "decision-grade
   packets: price refresh, strategy identity, technical snapshots, catalyst quality, execution readiness,
   agent + LLM review queueing."
3. **Agent reviews** — `scripts/proposal_agent_review.py` routes each proposal to the required agents by
   strategy type (local LLM when available, deterministic fallback otherwise).
4. **LLM review queue** — `scripts/proposal_llm_review_worker.py` drains PENDING rows from the
   `proposal_llm_review_queue` table through `proposal_llm_reviewer.py`; "LLM is ANALYSIS ONLY — cannot
   approve or override risk gate." (Naming note: "Stage 2b" in this codebase refers to the Schwab
   live-canary preflight, `scripts/schwab_stage2b_canary_preflight.py`, not this queue.)
5. **Decision & risk gates** — `scripts/proposal_decision_gate.py` (states such as
   `APPROVE_READY_PAPER_TEST`, `CAUTIOUS_PAPER_TEST`, `RESEARCH_INCOMPLETE`, `AI_REVIEW_MISSING`,
   `REJECT_RECOMMENDED`, `BLOCKED_BY_RISK_GATE`) and `scripts/proposal_route_risk_gate.py`, a fail-closed
   risk gate with distinct contexts for paper approval (`approval_ready`) vs. broker submit
   (`broker_submit`).
6. **Oversight for live promotion** — `scripts/broker_promote_oversight.py`: paper→broker promote requires
   completed local agent reviews (default `maria,risk_agent,steph`, env-overridable) plus optional
   Grok/ChatGPT cloud second opinions before an intent reaches the live broker queue.
7. **Execution** — paper lane via ATM (autonomous), live lane via per-order 2FA (§7).

**Options paper-strategy lane (Stage A/B, 2026-07-05; lifecycle monitor 2026-07-07):** parallel to the
equity pipeline, the options desk has a discovery-fed **paper-only** strategy lane —
`scripts/options_strategy_scanner.py` runs `scripts/lib/options_pipeline/` generators (first:
`deep_itm_call`, 0.80–0.95Δ stock replacement) over held + buy-rated underlyings and queues winners
into the **existing** `options_approval_queue` manual-review lane with `live_eligible=false` and hard
paper flags (triple fail-closed: generator, desk approve/preflight refusals, no broker/2FA imports —
test-enforced). Alpaca paper execution (`alpaca_paper_options_executor.py`) fills real paper orders;
reconcile + `options_monitored_positions` registry track open legs with Schwab-chain marks, advisory
alerts (UI + Telegram), and the **Open Options** hub tab (`GET /api/v2/options/open-positions`).
Closed paper trades land in `options_paper_outcomes`; `scripts/lib/options_pipeline/validation.py` +
`scripts/options_validation_status.py` report progress against the config's validation gate
(30 trades / WR ≥55% / PF ≥1.3 / 3 months) — **advisory only**: a met gate reads "operator decision
required", nothing auto-enables. Card semantics distinguish paper rows (**NO LIVE PATH**) from true
desk blocks (**BLOCKED**). Cron: `bash scripts/install_options_paper_monitor_cron.sh`. Details:
[docs/OPTIONS_STRATEGY_PIPELINE.md](docs/OPTIONS_STRATEGY_PIPELINE.md).

## 7. Trading execution & position sizing

- **Paper (autonomous):** `atm_*` scripts — `atm_auto_approver.py`, `atm_market_open_watch.py`
  (read-only), `atm_config_manager.py`, `atm_position_reconciler.py`, `atm_technical_gate.py`, … —
  drive Alpaca paper through `alpaca_paper_adapter.py` and `proposal_paper_submitter.py`
  ("This script ONLY submits to paper trading. Live trading is permanently blocked.").
  Operator controls: [docs/operator/ATM_RUNBOOK.md](docs/operator/ATM_RUNBOOK.md).
- **Real (Schwab, gated):** `scripts/brokers/` holds the broker abstraction —
  `schwab_order_adapter.py`, `approval_service.py` (per-order 2FA), `evidence_approval.py`,
  `execution_guard.py` (fail-closed, Schwab default `BROKER_DISABLED`), `execution_readiness.py`
  (in `submit` mode a missing 2FA is a hard block), `kill_switches.py`, `canary_gate.py`,
  `protective_stop_pilot.py` / `protective_stop_policy.py` (live stop submits; `GATES_REMOVED = True`,
  per-order 2FA is the sole remaining confirm), `order_intent.py`, `order_lifecycle.py`,
  `reconcile_orders.py`. Root-level Schwab tooling: `schwab_transport.py`, `schwab_token_manager.py`,
  `schwab_stream_daemon.py`, `schwab_oco_bracket.py`.
- **Fidelity (read-only):** `scripts/brokers/snaptrade_read.py` — "Scope today is READ-ONLY SYNC: list
  accounts, pull positions/balances/activities." Persistence is owned by `scripts/snaptrade_sync.py`
  (dry-run by default, `--apply` required). A future order path exists but is gated OFF
  (`brokers/snaptrade_trade.py`: `ENABLED` must be flipped in a commit *and* the per-order confirm wired;
  the 401k is intentionally never tradeable).
- **Position sizing:** `scripts/account_policy.py` is the "single source of truth for account sizing/risk
  policy … used by BOTH auto_proposal_generator.normalize_size() and risk_gate so the two can never
  disagree" (percent-of-equity since 2026-06-19; policy rows live in `account_automation_policies`).
  - `compute_sizing()` implements the `percent_equity` engine — `max_dollar_risk = base × risk_pct/100`,
    `max_dollar_size = base × pos_pct/100` — which is labeled **`percent_cash`** when a cash `sizing_base`
    is passed ("pass sizing_base=cash for live broker promotes").
  - `sizing_cash_base()` forces **retirement accounts (rollover/roth/ira/401k) to settled cash — no
    margin, no buying-power fallback**; taxable accounts may fall through to buying power.
  - Fallback engine: `fixed_dollar` ($150 risk / $2,000 size) when no base is available.
  - Frontend mirror: `apps/command-center-v3/src/lib/watchlistProposeSizing.ts` — 1–2% of cash/buying
    power, max-risk gate at 2%, deployment cap default 20% of cash, per-account
    `max_position_pct_of_equity` override.

## 8. Data stores

- **PostgreSQL `trade_ai`** via `scripts/db_adapter.py`: psycopg2 with thread-local connections,
  `application_name` set to the calling script, JSON fallback if the DB is unreachable.
- Every db_adapter connection sets `idle_in_transaction_session_timeout='120s'`, `lock_timeout='3s'`,
  `statement_timeout='180s'`; raw psycopg2 callers are covered by role-level defaults — see
  [docs/runbooks/DB_HANG_PREVENTION.md](docs/runbooks/DB_HANG_PREVENTION.md).
  **Never hold a transaction open across slow work — idle-in-transaction sessions are killed at 120s.**
- **Runtime files are gitignored:** `.gitignore` excludes all of `data/` ("All portfolio/personal data —
  PII, holdings, AI outputs"), `state/` (including `state/hermes/`), `/reports/` (regenerable), and
  explicitly `data/runtime/*_latest.json` / `data/runtime/*_history.json`. Do not re-commit runtime state.
- The Hermes read model lives at `state/hermes/outcome_bus.json` (+ history dir); health snapshots at
  `data/portfolios/state/health_agent_status.json` and the `health_agent_snapshots` table.

## 9. Health & monitoring

- `scripts/health_agent.py` computes a single 0–100 Health Score with per-category breakdown:
  `data_quality`, `execution_health`, `intelligence_quality`, `risk_protection`, `retirement_planning`,
  `pipeline_freshness` — six categories in code (the docstring's "5 categories" prose predates the sixth).
- Alerts flow to Telegram with a throttle (status change / score drop ≥5 / 6h heartbeat) —
  see [OPERATIONS.md](OPERATIONS.md#3-health-agent-score--alerts).
- It runs under the `tradeai-health-agent` systemd user unit and surfaces in the v3 **Health** hub.
- Adjacent monitors: `scripts/system_health_agent.py` (execution-integrity layer),
  `scripts/pipeline_freshness_monitor.py` (pipeline staleness with market-closure grace).
