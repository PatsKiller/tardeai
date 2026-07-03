# Peer-Review Packet — Command Center v3 Intelligence Pages

_Generated 2026-06-21. Guided entry point for reviewers of the 6 intelligence pages._

This maps each page → its React component tree → backend endpoints → the modules that serve
them → recent commits. Read top-to-bottom per page, or jump to a page's section. All frontend
is the **v3 stack only**: inline styles + CSS vars, `useApi` hook, NO Tailwind/shadcn/lucide.
All LLM work is **free lanes only** (grok :8645, chatgpt :8646, local gemma) — no metered keys.

Repo: `PatsKiller/tardeai` (main). Frontend root: `apps/command-center-v3/src`.
Backend router: `scripts/api_v2.py` (delegates to the modules listed below). HEAD: `ee0e14d1`.

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

Central intelligence surface: consolidated command, signal quality, Layer-4 inferences, news
library, research topics, sources/RAG coverage, pipeline workflow, and rotation summary.
URL-synced tabs: `/v3/intelligence?tab=command|inferences|quality|news|research|sources|workflow|rotation`.

**Component tree**
- `IntelligenceHub.tsx` — tab shell + header stats (articles, Hermes coordinator, RAG %)
  - `CentralIntelligencePages.tsx` — multi-feed signal synthesis + type-aware signal quality.
  - `InferenceLayersPanel.tsx` — Layer-4 inference results (regime/regional/sizing/inferences).
    - `EnsembleValidationCard.tsx` — free-lane ensemble verdict per inference.
  - `components/intelligence/IntelligenceNewsTab.tsx` — paginated news articles.
  - `components/intelligence/IntelligenceResearchTab.tsx` — user + monitor topics, gaps.
  - `components/intelligence/IntelligenceSourcesTab.tsx` — RAG coverage, Hermes pipeline, library.
  - `components/intelligence/IntelligenceRotationTab.tsx` — rotation summary embed.
  - `IntelligenceWorkflow.tsx`, `ResearchTopicsModal.tsx`.

**Endpoints**
| Endpoint | Component |
|----------|-----------|
| `GET /api/v2/market-intelligence` (120s) | Hub header + CentralIntelligencePages |
| `GET /api/v2/hermes/health` (120s) | Hub header + Sources + Signal Quality KPI |
| `GET /api/v2/news/articles` (60s) | IntelligenceNewsTab |
| `GET /api/v2/research-topics` (120s) | IntelligenceResearchTab + CentralIntelligencePages |
| `GET /api/v2/rag/status`, `/intelligence/library`, `/intelligence-sources`, `/search-sources` | IntelligenceSourcesTab |
| `GET /api/v2/rotation/summary` (300s) | IntelligenceRotationTab (lazy — tab only) |
| `GET /api/v2/command`, `/risk`, `/overview`, `/morning-brief`, `/open-trades/intelligence`, `/watchlist/items`, `/hermes/subject-intel-map`, `/agents/intelligence-feedback`, `/trade-ai` | CentralIntelligencePages |
| `GET /api/v2/inference/latest`, `/regional`, `/sizing` | InferenceLayersPanel |
| `GET /api/v2/system/pipeline-health` (60s) | IntelligenceWorkflow |
| `GET /api/v2/inference/ensemble`, `POST /inference/ensemble/request` | EnsembleValidationCard |

**Backend — autonomous intelligence**
- `scripts/hermes_coordinator.py` — fleet orchestrator (*/15m cron); auto-promote + embed worker.
- `scripts/hermes_embedding_enqueue.py` — enqueue promoted research → `hermes_embedding_queue`.
- `scripts/hermes_embedding_worker.py` — Ollama embed → `content_embeddings` (`hermes_research`).
- `scripts/rag_indexer.py` — universal indexer includes `hermes_research` source type.
- `scripts/iris_taxonomy_agent.py` — `get_library_status()` uses direct DB (no HTTP self-deadlock).

**Backend — inference**
- `scripts/inference_api.py` — `/api/v2/inference/*` read-only router (delegated from api_v2).
- `scripts/inference_layer_engine.py` — orchestrator (`--run`), persists `inference_runs/results`.
- `scripts/inference_layers.py` — 4 layers; Aegis signals first-class.
- `scripts/inference_ensemble.py` + `inference_ensemble_worker.py` — free-lane ensemble.

**Maturity doc:** `docs/intelligence_maturity_20260622.md`

**Review notes / known fixes**
- Hermes→RAG was broken (queue never populated). Fixed 2026-06-22 with enqueue on promote + backfill.
- Signal quality degenerate cards fixed: type-aware `qscore`, breach confidence, `STRUCTURAL` regex,
  command-feed price cross-ref, external-LM series collapse via `lmGroups`.
- Research gaps UI was showing raw JSON; API uses `display_name`, `reason`, `detail`.

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

Decision-first watchlist at `/v3/watch`: one full-width card per symbol with CIO view, plan
levels, data-quality strip, reasoning line, R:R badge, Fib confluence, and a unified verdict →
CTA matrix. Operators propose entries from the card (cash-sized modal) without waiting for the
cron bridge.

**Maturity doc:** `docs/COMMAND_CENTER_V3_WATCHLIST.md`

**Component tree**
- `WatchlistHub.tsx` — hub shell, filters, propose-modal state
  - `WatchlistCard.tsx` — decision panel (header, DATA strip, hero, plan grid, Fib, More)
  - `WatchlistProposeModal.tsx` — cash-based 1–2% risk sizing + account picker
  - `ProAnalystPill.tsx` (+ `useProAnalystMap`), `DiscoveryPanel.tsx`, `ToSWatchlists.tsx`,
    `FibConfluencePanel.tsx`.
  - `lib/watchlistCardAction.ts` — verdict matrix, CTAs, data-quality flags, reasoning
  - `lib/watchlistProposeSizing.ts` — `computeRiskSizedShares`, `resolveSizingBase`
  - `lib/exitLadder` (`exitLadder`, `planWarnings`, `MONITOR_RULES`).

**Endpoints**
| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/watchlist/items?sort=hermes` (60s) | Hermes-ranked items |
| `GET /api/v2/watchlist/summary` (120s) | header |
| `GET /api/v2/proposal-accounts` (30s cache) | Schwab + Fidelity accounts for propose modal (`sizing_base` = cash) |
| `POST /api/v2/watchlist/<SYMBOL>/propose` | Queue broker proposal from card (cash risk guards) |
| `GET /api/v2/hermes/curate-top20` (20s), `POST` | Hermes top-20 curation |
| `GET /api/v2/hermes/external-intel-map` (60s) | external LLM intel |
| `GET /api/v2/hermes/intel/...` | per-ticker intel |
| `GET /api/v2/finviz-strip-map` (300s) | inline Finviz strips |
| `GET /api/v2/symbol-cards` (300s) | card layer (description/analyst/news) |
| `GET /api/v2/setup-advisory/candidates?entity=watchlist` (120s) | setup advisory |
| `GET /api/v2/rec-intel/outcomes` (300s) | rec-intel outcomes |
| `GET /api/v2/watch-directives` (60s), `GET /watch/directives`, `GET /watch/sectors` (600s) | operator directives |

**Backend** — `scripts/api_v2.py` (`_proposal_accounts`, `_wl_propose_symbol`, watchlist/hermes
handlers); `scripts/account_policy.py` (`sizing_cash_base`, `cash_for_account`); Hermes
intelligence engine; `refresh_symbol_cards.py` (06:40 cron).

**Recent commits**
- `ee0e14d1` Watchlist: stronger CTAs, DATA strip, sizing hints on WAIT cards
- `caad93ad` Propose: explicit cash-based sizing math + IRA cash-only guard
- `25e9c27e` Propose: cash sizing + Schwab/Fidelity account load
- `ee225be5` Watchlist: decision-first cards — CIO, reasoning, R:R, data quality
- `9aa8119c` Watchlist: restore pullback zone, plan line, Fib on cards
- `bd642190` Propose modal: size on available cash, include Fidelity accounts

**Review notes**
- Propose modal must use `sizing_base` (cash), not `account_value` (equity). IRA accounts are
  cash-only — no buying-power assumption.
- Restart `portfolio-server.service` after `account_policy.py` changes or
  `/api/v2/proposal-accounts` may 500 with stale module attributes.
- Card verdict matrix: READY → Propose; WAIT → Review setup + Monitor; STALE → Refresh; FIX →
  Fix plan / Review exit. See `deriveRecommendedAction` in `watchlistCardAction.ts`.

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
