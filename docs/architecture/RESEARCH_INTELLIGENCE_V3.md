# Research Intelligence v3.0 — Decision Desk

Status:      ACTIVE
as_of:       2026-07-16T11:10:02-04:00
Measured at: efcc51365 / not measured

**Shipped:** 2026-07-16 (commits `45bfa56b`, `a6fd0962`, `e5e7507c`, `27cb0e67`, `9649cd8a`)
**Surface:** CC v3 → Intel → Research Intel (`apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx`)
**Backend:** `scripts/lib/research_intelligence.py` (feed builder), `_narrative.py`, `_portfolio.py`, `_stage.py`; routes in `scripts/api_v2.py`; queue in `scripts/research_intelligence_queue.py`
**Mode:** Advisory-only, paper-only. All Hermes integration is read-only. Feed `version: "3.0"`.
**Diagnosis:** `docs/_findings/ri_v3_diagnosis_2026-07-16.md` (Phase 0 — actual mechanisms differ from prompt guesses in several places; the live schema won).

## A — Trust: one corpus, real lanes, honest header
- Every number on the page (`by_category`, `by_freshness`, `lane_counts`) is computed over the **same post-dedupe universe the desk renders**. Root cause of the old "248 shown vs 6 filtered" / "freshness Σ=778 vs 278" was counting *pre*-dedupe (duplicate-titled stop_health rows), **not** archive inclusion.
- `lane=` is a real `build_feed` filter param (`LANE_CATEGORIES`: retirement→retirement_tax, dividends→dividend_income, macro_sector→macro_geo+sector_thematic), in the route + single-flight cache key. The hub sends `lane` in the query string; the old client-side lane substitution (and its silent full-feed fallback) is gone. `priority_lanes` preview arrays remain for compatibility.
- Book-weights rail total is labeled **"securities (ex-cash)"** (`load_portfolio_context()` skips `is_cash` rows) — the delta vs the top-strip Portfolio (broker `/api/v2/overview`, includes cash) is a definition difference, not drift. Global `MetricStrip` untouched.

## B — Content quality gates
- **Stub partition** (`_is_stub_item`): registry echoes ("from the Research Topic Registry"), thin title-restating bodies, and all `topic_monitor` standing-watch rows are pulled out of the desk *before* dedupe/counts. They render as a compact **Queued research** section (`queued_research[]`, 40 shown, `stats.queued_research` = full count) — never featured, never Tier-A, never in brief counts. Stop-signal types (`stop_health` etc.) stay real briefs.
- **Prose dedupe** (`_dedupe_prose` in `_polish_narrative_depth`): repeated sentences, lede-restating paragraphs, lede-substring sentences/takeaways — exact match after whitespace normalization only.
- **Ticker scope** (`scope: brief|book` on `ticker_recommendations`): book context comes from `funding_sources()` / `_context_concentration_tickers()` / compounding-book reviews and renders **once** at desk level (concentration banner); per-card strips and rich security cards are brief-scope only, with an explicit "No ticker mapping" state. A book ticker the brief itself names upgrades back to brief.
- **Honest CTAs:** "Map thesis to sleeves" removed; no-theme sector/macro briefs return `next_action: null` (advisory omission is authoritative — narrative never resurrects a generic label). `freshness_report` + `research_intelligence_refresh.py` print the action-label distribution with a 20 % cap check.

## C — Hermes joins (read-only, fail-open)
- `_attach_hermes_context(page)`: one `watchlist_items` query (`DISTINCT ON (symbol)`, `hermes_composite_score/rank/scope_tier`) → `★#rank · score · S-tier` chips on items and ticks. Material disagreement (RI tier A vs composite <40, or C vs ≥70) renders a **divergence flag with both numbers — never blended**.
- `hermes_external_research` (14d) → ✦ lane badges with thesis/counter-view tooltip. Currently renders empty: **external lanes have produced nothing since 2026-07-02** (operator attention; separate ops issue).
- `_hermes_wire()`: "Hermes wire" strip on Top stories from `alert_events` (`hermes_score_move` |Δ|≥8, `hermes_rank_surge` ≥20 ranks, factor shifts, `analyst_alert`), 48h, symbol-deduped, cap 10. **Note:** `hermes_score_alerts` table from older docs does not exist — alerts live in `alert_events`.
- Active ticker `watch_directives` → amber Directive chips; "Create Watch Directive" button posts through the existing `/api/v2/watch/directives` (dedup + knowledge-theme routing built in).

## D — Research orchestration
- **Queue:** `ri_research_queue` table + `scripts/research_intelligence_queue.py` (thin subprocess wrapper over `topic_ingestion.py --topic`, per-topic timeout 900s). `POST /api/v2/research-intelligence/run-topic {topic_id|category}`, `GET /queue`. **Drain is cron-only:** 16:45 ET weekdays + 02:40 daily catch-up, flock-guarded, ≤10 topics/run, Telegram digest (`telegram_alert.send_telegram`, chat IDs from env). RTH never runs content production; buttons show "queued for after close".
- **Actionable staleness:** desk-status strip has per-monitor **Queue** buttons; queued-research rows have **Run research** when a `topic_monitor` id is linked ("no monitor linked" otherwise — no fabricated topic ids).
- **Compounding pillar:** `config/research_intelligence_compounding_topics.json` (4 topics) seeded via `research_intelligence_retirement_seed.py --config …` (new flag, idempotent upsert).
- **Coverage gaps:** `coverage_floors` in `config/research_intelligence_freshness.json`; `freshness_report` emits `coverage_gaps` (live+fresh under floor) → rail card with per-category Queue.
- **Discovery bridge:** Proposed-topics rail lists Discovery Inbox `TOPIC_CANDIDATE`s and decides through the **existing governed endpoints** (`/api/v2/hermes/discovery-inbox/{id}/approve-research-topic` / `reject`) — no parallel promotion path, no auto-registration. Recurrence signal unavailable (keys pre-deduped upstream); proposals rank by inbox order.

## E — Staged-idea lifecycle
- Statuses: `staged → watchlisted | directive_created | proposed_paper | dismissed | expired` (14d default, lazy expiry on read, Expired fold in the panel; nothing deleted). Store stays JSON (`data/portfolios/state/ri_staged_ideas.json`).
- **Stage gate:** `data_complete` rule (v2.7) **plus** a caller-provided exit/stop note — the silent boilerplate default is gone; the hub prompts inline (`stop_note_required`).
- **Promotions** (`POST /research-intelligence/stage/promote {id, target}` — operator-clicked only):
  - `watchlist` / `directive` → existing governed ticker-directive create (that is the entry into the watch universe; there is no separate watchlist-add API).
  - `paper_proposal` → `PENDING` row in `paper_trade_proposals` (`strategy_id/discovery_source='ri_staged'`, `manual_review_required=true`, advisory review levels from `market_quotes`, per-symbol dedup) — enters the normal review chain. Verified live: XLV → proposal **#2719**.
  - Telegram notification per promotion. No path to any live order surface; approvals chain untouched.

## Known limitations / follow-ups
- External-intel badges are dry until the Grok/ChatGPT external lanes produce rows again (stalled since 2026-07-02).
- Registry-echo stubs (hermes rows) without a `topic_monitor` link have no Run-research button.
- `alert_events.parsed_payload` is empty for hermes alerts — wire thresholds parse `raw_text`; if the alert text format changes, `_WIRE_SCORE_RE`/`_WIRE_RANK_RE` need updating.
- Paper-proposal promotion uses placeholder advisory stop/target bands (like the rotation-ETF path); the operator sets the real plan in review.
- `freshness_report` measures over the page (limit 200) — floor tuning should account for that window.
