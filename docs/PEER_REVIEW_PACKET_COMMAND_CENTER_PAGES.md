# Peer-Review Packet — Command Center v3 Intelligence Pages

_Generated 2026-06-21. Guided entry point for reviewers of the 6 intelligence pages._

This maps each page → its React component tree → backend endpoints → the modules that serve
them → recent commits. Read top-to-bottom per page, or jump to a page's section. All frontend
is the **v3 stack only**: inline styles + CSS vars, `useApi` hook, NO Tailwind/shadcn/lucide.
All LLM work is **free lanes only** (grok :8645, chatgpt :8646, local gemma) — no metered keys.

Repo: `PatsKiller/tardeai` (main). Frontend root: `apps/command-center-v3/src`.
Backend router: `scripts/api_v2.py` (delegates to the modules listed below). HEAD: `4260e655`.

---

## 1. Reports — `pages/ReportsHub.tsx`

The Reports Command Portal: a triaged feed of notifications, alerts, telegram outbox and AI
reports, with an Action Queue and a reader pane.

**Component tree**
- `ReportsHub.tsx`
  - `SynthesizedReportCard.tsx` — professional trade-desk card (severity rail, symbol/sector/
    trend chips, quality/ensemble badge, inline actions). `compact` in the list, full in the reader.
  - `DetailDrawer` (`DrillContext` type) — drill-through.

**Endpoints** (all under `/api/v2/reports/`)
| Endpoint | Purpose |
|----------|---------|
| `GET /categories` (60s) | category rows for the left rail |
| `GET /list` | feed items (the card list) |
| `GET /portal-summary` | header counts |
| `GET /action-items` | Action Queue source |
| `POST /purge` | operator purge |

**Backend** — `scripts/reports_portal.py`
- `list_items`, `_category_rows`, `portal_summary`, `action_items`.
- Categories pull from `notification_log`, `alert_events`, `telegram_outbox`, `ai_reports`.
- `_dedup_rows()` collapses re-emitted alerts at the read layer (IRDM stop-health fired ~18× →
  collapsed with `repeat_count`). `_re = import re` at module top.

**Recent commits**
- `4260e655` Reports: dedup re-emitted alerts (IRDM stop-health flood) at the read layer
- `4533486b` Reports: dedup the Action Queue panel
- `28b90ccc` Reports: fix action links → wrong host + de-clutter the list
- `2051ec05` Reports: professional SynthesizedReportCard (in-stack, trade-desk style)

**Review notes / known fixes**
- Action URLs from the backend are absolute (hardcoded tailscale host for Telegram/email).
  Both `ReportsHub` (`relUrl`) and `SynthesizedReportCard` (`relUrl`) strip the host so links
  stay same-origin. `FQDN` is now `window.location.origin`, not the hardcoded host.
- `dedupedActions` useMemo collapses the Action Queue by symbol+text, merges `_classes` into
  pills, keeps highest severity (verified 538→310).

---

## 2. Intelligence — `pages/IntelligenceHub.tsx`

Central intelligence surface: market intelligence, research topics, rotation summary, the
signal-quality synthesis pages, and the Layer-4 inference panel.

**Component tree**
- `IntelligenceHub.tsx`
  - `CentralIntelligencePages.tsx` — multi-feed signal synthesis + type-aware signal quality.
  - `InferenceLayersPanel.tsx` — Layer-4 inference results (regime/regional/sizing/inferences).
    - `EnsembleValidationCard.tsx` — free-lane ensemble verdict per inference.
  - `IntelligenceWorkflow.tsx`, `ResearchTopicsModal.tsx`.

**Endpoints**
| Endpoint | Component |
|----------|-----------|
| `GET /api/v2/market-intelligence` (120s) | Hub + CentralIntelligencePages |
| `GET /api/v2/research-topics` (120s) | Hub + CentralIntelligencePages |
| `GET /api/v2/rotation/summary` (300s) | Hub |
| `GET /api/v2/command`, `/risk`, `/overview`, `/morning-brief`, `/open-trades/intelligence`, `/watchlist/items`, `/hermes/health`, `/hermes/subject-intel-map`, `/agents/intelligence-feedback`, `/trade-ai` | CentralIntelligencePages (multi-feed) |
| `GET /api/v2/inference/latest`, `/regional`, `/sizing` | InferenceLayersPanel |
| `GET /api/v2/inference/ensemble`, `POST /inference/ensemble/request` | EnsembleValidationCard |

**Backend**
- `scripts/inference_api.py` — `/api/v2/inference/*` read-only router (delegated from api_v2).
- `scripts/inference_layer_engine.py` — orchestrator (`--run`), persists `inference_runs/results`.
- `scripts/inference_layers.py` — the 4 layers (Ingestion/Feature/Regional/HigherOrder); Aegis
  signals ingested first-class (`aegis_portfolio_briefs` + `advisor_observations`).
- `scripts/inference_ensemble.py` + `inference_ensemble_worker.py` — free-lane ensemble
  (`ensemble_validate`), enqueue→worker model, finance rubric (`_FIN_RX` + `_finance_rubric`).
- `scripts/inference_hermes_query.py`, `inference_financial_modeling.py` (NAV), `inference_sizing.py`.

**Recent commits**
- `c994408d` Ensemble: auto-enqueue high-severity inferences + Signal Quality card
- `05d6ff65` Ensemble card: auto-load persisted verdict on mount
- `75b1568b` Ensemble auto-enqueue: cover ALL high-severity (uncap)
- `94ea1471` Ensemble: standardize on queued auto-enqueue (disable validate_in_loop)
- `3cb24ea5` Ensemble finance rubric: broaden gate to portfolio-reasoning terms
- `cd1daa46` Ensemble: finance-specific scoring rubric (NAV/income/retirement)
- `f7af2c8a` Wire Aegis as a first-class Layer-4 signal
- `af8b7a6b` Wire free-lane ensemble into the Layer-4 inference loop
- `f70342ed`, `1cad708c`, `311fced2` CentralIntelligencePages signal-quality fixes

**Review notes / known fixes**
- Signal quality was degenerate (every card 39% from a flat 0.65 conf + null freshness).
  Fixed: type-aware `qscore`, per-signal confidence from breach magnitude, `STRUCTURAL` regex,
  command-feed price cross-ref via `priceBy`, external-LM series collapse via `lmGroups`.

---

## 3. Strategy — `pages/StrategyHub.tsx`

Strategy desk: leaderboard, backtests, incubator, plan-vs-performance, paper-trade readiness.

**Component tree**
- `StrategyHub.tsx`
  - `BacktestPanel.tsx`, `StrategyPlanner.tsx`.

**Endpoints**
| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/strategy-leaderboard` (60s) | live strategy leaderboard |
| `GET /api/v2/strategy-intelligence` (120s) | per-strategy intelligence/tilt |
| `GET /api/v2/strategy-desk` (120s) | desk overview |
| `GET /api/v2/strategy-configs` (120s) | config-locked strategy params |
| `GET /api/v2/backtesting/results` (120s) | BacktestPanel |
| `GET /api/v2/incubator` (120s) | incubator list |
| `GET /api/v2/setup-advisory/candidates?entity=incubator` (120s) | setup advisory |
| `GET /api/v2/plan-vs-performance` (120s) | plan vs performance |
| `GET /api/v2/paper-trade-readiness` (120s) | readiness gate |

**Backend** — served by `scripts/api_v2.py` strategy handlers + backtest/strategy-intelligence
modules. Per-strategy allocation tilt, leaderboard expectancy (fib #1 2.03R, momentum_scalp excluded).

---

## 4. Rotation — `pages/RotationIntelligence.tsx`

Rotation engine + free-lane LLM oversight (grok review, rebalance review, ETF proposals).

**Endpoints**
| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/rotation/summary` | rotation state |
| `POST /api/v2/rotation/ask` | operator query |
| `POST /api/v2/rotation/feedback` | feedback→ranking |
| `POST /api/v2/rotation/grok-review`, `/grok-rebalance-review` | free-lane oversight |
| `POST /api/v2/rotation/oversight` | oversight pass |
| `POST /api/v2/rotation/propose-etf` | ETF/short PENDING proposals (manual-review, never auto-exec) |
| `GET /api/v2/rotation/research-gaps` | gaps |
| `GET /api/v2/llm/oauth-lanes`, `POST /oauth-lanes/keepalive` | free-lane health/keepalive |

**Backend** — `scripts/api_v2.py` rotation handlers + rotation engine + ETF instrument layer
(`classify_instruments`, `etf_analyst_enrich`). LLM via free OAuth lanes only.

---

## 5. Watchlist — `pages/WatchlistHub.tsx`

Watchlist with Hermes intelligence ranking, Finviz strips, discovery candidates, exit ladders,
fib confluence, and operator watch directives.

**Component tree**
- `WatchlistHub.tsx`
  - `ProAnalystPill.tsx` (+ `useProAnalystMap`), `DiscoveryPanel.tsx`, `ToSWatchlists.tsx`,
    `FibConfluencePanel.tsx`.
  - `lib/exitLadder` (`exitLadder`, `planWarnings`, `MONITOR_RULES`).

**Endpoints**
| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/watchlist/items?sort=hermes` (60s) | Hermes-ranked items |
| `GET /api/v2/watchlist/summary` (120s) | header |
| `GET /api/v2/hermes/curate-top20` (20s), `POST` | Hermes top-20 curation |
| `GET /api/v2/hermes/external-intel-map` (60s) | external LLM intel |
| `GET /api/v2/hermes/intel/...` | per-ticker intel |
| `GET /api/v2/finviz-strip-map` (300s) | inline Finviz strips |
| `GET /api/v2/symbol-cards` (300s) | card layer (description/analyst/news) |
| `GET /api/v2/setup-advisory/candidates?entity=watchlist` (120s) | setup advisory |
| `GET /api/v2/rec-intel/outcomes` (300s) | rec-intel outcomes |
| `GET /api/v2/watch-directives` (60s), `GET /watch/directives`, `GET /watch/sectors` (600s) | operator directives |

**Backend** — `scripts/api_v2.py` watchlist/hermes/finviz/symbol-card/watch-directive handlers;
Hermes intelligence engine (composite scoring/ranking); `refresh_symbol_cards.py` (06:40 cron).

---

## 6. Rec Intelligence — `pages/RecommendationIntelligence.tsx`

Recommendation intelligence: unified ticker lineage, lifecycle journaling, return-by-origin-source.

**Endpoints**
| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/rec-intel/summary` | summary + return-by-origin |
| `GET /api/v2/rec-intel/ticker` | per-ticker lineage |
| `POST /api/v2/rec-intel/lifecycle` | lifecycle journal |
| `GET /api/v2/rec-intel/lifecycle-performance?limit=300` | lifecycle performance |
| `GET /api/v2/rec-intel/open-positions` | open positions |

**Backend** — `scripts/api_v2.py` rec-intel handlers over `rec_ticker_attribution` +
`rec_rotation_links` (ingests all sources → attribution + executed).

---

## Cross-cutting invariants (apply to every page)

- **Free LLM lanes only** — `llm_lane.py` (grok :8645 / chatgpt :8646 / local gemma). No metered
  keys, no anthropic/xai/ollama SDKs.
- **Advisory only** — inference/ensemble/sizing never place or modify orders; sizing is
  re-validated through `risk_gate` for operator review.
- **v3 stack** — inline styles + CSS vars + `useApi`. No Tailwind/shadcn/lucide.
- **Same-origin links** — backend action URLs are absolute (tailscale host); strip with `relUrl`.
- **No hardcoded broker/account values** — all config from env/DB/config.

See also: `INFERENCE_LAYERS_LAYER4.md`, `INTELLIGENCE_RATING_AND_LLM_STAGES_2026_06_04.md`,
`FINVIZ_INTEGRATION_AND_DATA_SOURCE_MONITORING.md`, `HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`,
`MASTER_SYSTEM_DOCUMENTATION.md`.
