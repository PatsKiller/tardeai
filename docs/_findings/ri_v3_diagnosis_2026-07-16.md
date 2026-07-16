# RI v3.0 Phase 0 Diagnosis — 2026-07-16

All items verified against live code + live DB (user `trade_ai`, not `johnclaw` — prompt's psql commands were wrong on user). Documentation drift confirmed in several places; live schema wins below.

| # | Item | Expected (prompt) | Actual (live) | Adapt / Flag |
|---|------|-------------------|---------------|--------------|
| 0.1 | RI modules + configs + staged store | exist | All exist: `scripts/lib/research_intelligence{,_narrative,_portfolio,_security,_stage,_themes}.py`, 3 configs, `data/portfolios/state/ri_staged_ideas.json` | adapt (as documented) |
| 0.2 | Feed route params | lane may exist | `GET /api/v2/research-intelligence` accepts category/q/priority/symbol/holdings_only/limit/include_archived/freshness/starred_only/sentiment/source_system/primary_only. **No `lane` param anywhere.** Server caps `limit` at 50 (Tailscale payload guard) — "279" figures are stats, not page rows. Feed has 60s single-flight cache keyed on params | adapt: add `lane` to build_feed + route + cache key |
| 0.3 | Lane filter no-op? | P0-2 suspected | **Confirmed, two-part bug.** Backend: lanes are 16-item preview arrays (`priority_lanes`) built from the full universe, not filters. Frontend (`ResearchIntelligenceHub.tsx:1296-1315`): renders server lane array when non-empty, else **silently falls back to the full feed**; the "Showing N of M" strip always renders `stats.matched/universe`, never lane-aware. Not intentional-views: no such comment; fix in backend per prompt | fix backend `lane=` filter + lane-aware stats |
| 0.4 | Counts corpus mismatch | archive-inclusive corpus suspected | **Different root cause: counts are computed PRE-dedupe.** `build_feed` computes `by_category`/`by_freshness` over ~600 raw rows *before* the title-dedupe pass collapses duplicate-titled rows (stop_health etc.) to one winner; the visible desk is post-dedupe (universe 278). "Risk & Regime 248 vs 6 filtered" and "freshness Σ=778 vs 278" are both this. Archive default is already false | fix: compute every count after dedupe, one corpus |
| 0.5 | Registry-echo stubs ≥10? | ~18 rendered | DB: **registry_echo=40, thin(<120 chars)=1620, total=3664** non-archived. Feed reads latest 600 → ~18 render. Decision tree: **Workstream B is P0** | adapt |
| 0.6 | SCHG/SCHD boilerplate source | portfolio module stamping | Confirmed: `research_intelligence_portfolio.py` — `funding_sources()` (SCHG trim_candidate) + `_context_concentration_tickers()` (hold_review) append book-context tickers into per-card `ticker_recommendations[]` regardless of brief content | adapt: split "this brief" vs "book context" per B3 |
| 0.7a | `watchlist_items` Hermes cols | score/rank/scope/lifecycle | Has `hermes_composite_score`, `hermes_rank`, `hermes_score_components`, `hermes_scored_at`, `scope_tier`. **No lifecycle column** | FLAG: C1 chip = rank·score·S-tier only, no lifecycle stage |
| 0.7b | `hermes_external_research` 14d | rows expected | 26,752 rows total but **latest = 2026-07-02** → 0 in 14d window. External Grok/ChatGPT lanes appear stalled for ~2 weeks (separate ops issue, out of scope) | C2 ships fail-open, renders verified-empty; flag lane stall to operator |
| 0.7c | `hermes_score_alerts` table | exists | **Does not exist.** Hermes alerts live in `alert_events`: 48h counts — hermes_rank_surge 3,363 · hermes_score_move 429 · hermes_factor_shift 30 · analyst_alert 5. Firehose volume → C3 needs thresholds + hard cap | FLAG: C3 adapts to `alert_events` |
| 0.7d | pro_analyst_pills_latest.json | exists | Exists, 1.0 MB, refreshed 06:11 today | adapt |
| 0.8 | Header shows two totals (drift) | multiple-sources race | **Not a race — two definitions.** Global `MetricStrip` (App shell, every page) uses `/api/v2/overview.portfolio_value` (broker-fed, incl. cash) ≈ $1,268,426. RI rail "household" uses `portfolio_context.total_mv` from holdings.json where `load_portfolio_context()` **skips `is_cash` rows** ≈ $1,167,420. Δ≈$101K ≈ cash | A3: relabel RI figure "securities ex-cash" (or add cash line); do NOT touch MetricStrip |
| 0.9 | "Map thesis to sleeves" source | next-action generator | `research_intelligence_portfolio.py:1168` — fallback for sector_thematic/macro_geo when `detect_themes_from_title()` finds no theme. 44% prevalence = theme detection failing on most titles | B4: extend theme/category-specific CTAs, else omit CTA |
| 0.10 | Per-topic research entrypoint | may need wrapper | `topic_ingestion.py` already supports `--topic <topic_id>` (plus --dry-run/--no-llm/--limit). topic_monitor has 370 rows | D1: thin queue wrapper calls `--topic`; **no refactor needed** |
| 0.10b | Queue table reuse | prefer reuse | Existing queues are semantically different (`watchlist_research_queue` is symbol-NOT-NULL agent requests). Discovery Inbox = `hermes_discovery_candidates` (323 rows, all ≤14d) + `hermes_discovery_feedback` | D1: new thin `ri_research_queue` table; D5 feasible against discovery tables |

## Decision-tree outcomes
- Registry echo 40 ≥ 10 → **Workstream B = P0**.
- Lane filter is a backend no-op → **P0-2 confirmed, backend fix**.
- `hermes_external_research` empty in window → C2 badges ship fail-open (verified-empty state); external-lane stall reported to operator.
- `--topic` exists → D1 is a thin queue wrapper, `topic_ingestion.py` untouched.

## Flag-backs (per session contract)
1. `hermes_score_alerts` table does not exist → C3 built on `alert_events` (hermes_* alert types), threshold-gated, cap 10.
2. No lifecycle column on `watchlist_items` → C1 chip omits lifecycle stage.
3. External research lanes (Grok/ChatGPT) produced nothing since 2026-07-02 — operator attention needed; not fixed in this session (out of scope).
4. Prompt's count hypothesis ("archive-inclusive") was wrong — actual cause is pre-dedupe corpus; fixing per actual mechanism.
