# Watch Directives + Hermes→Trade AI Promotion (canonical)

**Status:** shipped 2026-06-08 (phases D-0 → D-4). Advisory-only; no execution. Paper mode.
Supersedes the component notes under `docs/watch_directives_wiring_*` and `docs/watch_directives_monitor_*`.

Operator standing instructions to **watch a ticker, a sector, or a trend**, honored by both Trade AI
and Hermes. A Hermes/operator lead becomes tradeable only through a **real evaluation** (not a bypass):
Hermes supplies *symbol + thesis* → Trade AI decides *whether it's tradeable* → the operator supplies the *yes*.

## Hard rules (never violated)
- **Scalp firewall:** a directive-sourced symbol can NEVER enter the Bucket-1 scalp fast path. The
  classifier output is filtered to **Bucket 2/3 only**; `momentum_scalp`, `gap_and_go`, and any
  `SAME_DAY`-bucket strategy are hard-excluded with runtime assertions. The `prime_setups` /
  `watchlist_setups` screeners are untouched (byte-identical).
- **Hermes firewall:** Hermes (`hermes_readonly` / `hermes_staging_writer`) has **zero write** on
  `watch_directives`, `watch_directive_hits`, `watchlist_items`, `strategy_watchpool`. It only SELECTs
  directives and INSERTs proposed leads into `hermes_directive_hits_staging`; the **app role** drains it.
- **Advisory / fail-closed / no execution:** promotion only registers + evaluates + watchpools. Every
  resulting proposal still flows through the existing agent-review → operator-approval gate. Unresolvable
  symbols → `needs_review`, never fabricated data. `LLM_DISABLE_LIVE_EXECUTION=true`, `ALPACA_MODE=paper`.

## D-0 — Schema (`migrations/2026-06-08_watch_directives.sql`, additive)
- `watch_directives` (kind ticker|sector|trend, label, spec jsonb, status active|paused|archived|needs_review,
  ttl_days, trade_ai_enabled, hermes_enabled, last_confirmed_at, cold_since, last_serviced_at).
- `watch_directive_hits` (directive_id, symbol, surfaced_by trade_ai|hermes|operator, source_tier, divergence,
  promoted, promotion_status, qualified_strategies).
- `hermes_directive_hits_staging` (Hermes proposes here only; app drains).
- Provenance columns added to **`watchlist_items`** (NB: `watchlist_symbol_master` is a VIEW over it):
  origin_system, origin_detail, directive_id, in_directive_watch, source_tier, first_seen_at,
  last_validated_at, seen_count, provenance_reason. Plus `origin_system`/`directive_id` on `strategy_watchpool`.

## D-1 — The promotion engine (`scripts/directive_promotion.py`) — centerpiece
`promote_directive_lead(symbol, directive_id, reason, source_system, *, auto, actor)`:
1. **Governor** — `auto` iff source tier ∈ {core, trusted} AND not in hard divergence vs Street. Else
   STAGE for one-tap. (`unavailable` Street coverage may auto if tier core/trusted — absence ≠ disagreement.)
   `divergent` always stages. Operator one-tap passes `auto=True` (override; firewall still applies).
2. **Register** provenance on `watchlist_items`.
3. **Enrich on demand** — `finviz_enrichment.get_enriched` (rsi/float/rvol/…) + **price backfill from
   `market_quotes` (Alpaca feed)** since the finviz cache carries no price. No tech → `REGISTERED_NO_TECH`.
4. **Classify** — `multi_strategy_classifier.classify_symbol`, output filtered to Bucket 2/3 (scalp excluded).
5. **Watchpool** — qualifying strategies enter `strategy_watchpool` (mirrors `maybe_write_watchpool`).
- Reads: tier from `data/runtime/source_maturity_latest.json`; divergence + Street consensus from
  `data/runtime/pro_analyst_pills_latest.json`. Runs under the **app role**.
- Status ∈ {PROMOTED, MONITORED_NO_QUALIFY, REGISTERED_NO_TECH, STAGED_FOR_REVIEW}.

## D-2 — Resolution + cold-pause (`scripts/watch_directives_service.py`)
Reconciled to route ALL promotion through the D-1 engine (was a flat watchlist-add).
- **ticker** → exact symbol, `auto` (operator named it; scalp firewall still applies).
- **sector** → operator universe + sector ETF (reused `continuous_runner` map) + DISTINCT Finviz-sector
  constituents from `incubator_universe`, **capped at 25 and logged**. Constituents stage for one-tap.
- **trend** → operator seed_symbols; Hermes discovers symbols → `hermes_directive_hits_staging` → app drains.
- **Hermes drain** → governed promotion (`source_system='hermes'`).
- **Auto-pause-on-cold** (trend, advisory): new credible hits reconfirm (`last_confirmed_at`, clear
  `cold_since`); none starts `cold_since`; cold ≥14d → `status='paused'` (NOT archived) + Telegram to both
  chat IDs. Operator-only un-pause.

## D-3 — API + UI
- `GET /api/v2/watch/provenance/{symbol}` — unified pill contract (origin, tier, freshness, directive link,
  ACTIVE watchpool, Street consensus [Yahoo-authoritative; null = uncovered], divergence).
- `POST /api/v2/watch/directives` (operator-create, app role) · `POST /api/v2/watch/directives/promote`
  (one-tap, auto=True) · `GET /api/v2/watchpool` (unified list) · `GET /api/v2/watch-directives`
  (directives + hits + staging + **health**) · `GET /api/v2/watch/sectors` (Finviz sector list +
  DISTINCT constituent counts + sample, for the Add-Watch sector dropdown/preview).
- **Two operator UI surfaces (same provenance pill row):**
  - **`/v3/watchlist`** (`WatchlistHub.tsx`) — the primary page. **"+ Add Watch" full-circle modal**
    (Ticker/Sector/Trend; sector dropdown with live constituent-count + first-10 preview; trend
    keywords+seeds; rationale/priority/TTL + TA/Hermes toggles + read-only governor preview → POST
    create). **Filter bar** (origin / advisory band / kind / directive / search). **Watch Directives
    section** (sector/trend first-class; click to filter to a directive's hits). **Provenance pill
    row** (origin=violet for directives, source-tier, freshness, divergence) replacing the old
    `source · bucket` text; row click → `/watch/provenance` drill.
  - **`/v3/watchpool`** (`WatchpoolHub.tsx`) — directives manager + unified watchpool with one-tap
    **Promote** on staged hits. System→Hermes shows directives + a servicing-health line.
- **Provenance backfill** (`migrations/2026-06-08_provenance_backfill.sql`): one-time additive map of
  `watchlist_items.source → origin_system` (10,230 rows) so existing rows show real origin pills, not
  blanks. Touches only the additive provenance columns — never `source`/screener output.

## D-4 — Telegram + morning brief
- Telegram (`telegram_command_handler.py`): `watch ticker SYM [because <thesis>]`, `watch sector NAME`,
  `watch trend KEYWORDS`, `promote SYM`. Creates under app role / one-taps via the engine; broadcasts to
  both chat IDs (6993102664, 8797974247); `created_by='operator'`.
- Morning brief (`aegis_morning_brief_delivery.py`): "Watch Directives" section — active/paused counts,
  24h hits with tier+divergence, staged-awaiting-tap, auto-paused-cold.
- Health monitor (`scripts/watch_directives_monitor.py`, read-only): servicing snapshots →
  `data/runtime/watch_directives_history.json`; surfaced via `/api/v2/watch-directives → health`.

## Operator quickstart
- UI: `/v3/watchpool` → Add Watch Directive. Or Telegram: `watch ticker RKLB because launch cadence`.
- Sector/trend hits **stage**; tap **Promote** (UI) or `promote SYM` (Telegram) to evaluate them.
