# Wealth site — FUNCTIONALITY MAP (reference v02 → real capability)

Reference: `docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v02.html`, sha256 `23f96d84199c5a7cabb3837a7bd94fab87d68eed15d3d5bbfb5d07e6f8dde7aa`.
Its anchors are the hash routes `#group/tab` built from its `groups` table: **56 views** in 9 groups, 6 drawers and the shell.
Home addendum reference **v03**: `docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v03.html`, sha256 `6c248c9641137e32cbbfa1a06739625c285fd41785ca01f125cc4522110aafc8` (v02 + three retained Home sections, operator-approved 2026-11-14; v02 stays the spec for everything else).
Watch addendum reference **v04**: `docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v04.html`, sha256 `1f8f87bb8db411acfb79eca53fccd4d147de800e7e2782f7d6a7fab817f6f68d`, 151,907 B, commit `fd4cf683b` (operator-approved as exact code 2026-11-15; v04 = v03 + the Watch decision workspace: one shared 8-column decision table with 5 filters on every Watch list view, phone decision cards, a 7-tab per-security drawer, the metric-definitions and mover-evidence drawers, and a per-security internal score / sector-contribution / queue-rank block). v02 stays the spec for everything outside Watch; the three v03 Home sections stand; the `#watch/sectors` **branch** and the `sectorMap()` (`e36dc515`) and `rotation()` (`744df99c`) it composes are byte-identical to v03 (carried, not new) — `watch()` itself differs only in its overview branch, where v04 moves the list out of the grid column.
Machine-readable twin: `docs/wealth/functionality-register.json`. Keep both in step; the JSON is what checks read.
Preview (fictional data, banner): `https://ms01-openclaw.tail163d14.ts.net/wealth/design-reference/index.html`.

## Rules (operator 2026-11-14)
- v02 is the implementation SPECIFICATION. Port its structure, tokens, type, spacing, charts, responsive layout, nav, drawers and valuation cues. Replace ONLY its fictional data with canonical read-model data.
- One row per page, tab, drawer and action. The owner edits the new code AND this row. The reviewer is never the author.
- Status is one of **VERIFIED_WORKING / EXISTS_UNVERIFIED / PARTIAL / MISSING / NOT_APPLICABLE**.
  - `UNMAPPED` means the owner has not done the first pass yet. It is not a status anyone may ship on.
- Existing code is not proof. VERIFIED_WORKING needs evidence from the **served** route: a request plus its response fields, or a screenshot path, taken at a stated ET time.
- No fake buttons. No silent empty success. No generic "NEEDS BACKEND".
  - A gap names the exact adapter or backend change and who owns it.
  - Unknown renders as unknown, with its age.
- Every row states the contract: canonical account id, security id, session label, metric meaning, source clock, and coverage behaviour.
- Actions:
  - Wire only existing supported actions.
  - Financial approvals and auth are preserved.
  - No order, provider or approval action is ever exercised to "test" a row.
- Source annotations go at component and adapter boundaries only: metric semantics, provenance, clock and coverage behaviour, action constraints.
- A slice is "implemented" only after:
  - reference-vs-build screenshots at 1440 and 390 px;
  - real tab and drawer interaction checks;
  - a release on /wealth/;
  - +15/+30/+60 checks.

## Columns
anchor · owner/reviewer · status · existing route · endpoint/reader/producer · contract (account/security/session/metric/clock) · observed working · evidence · gaps → adapter/backend · next step

`candidate readers` were seeded by the lead from the scaffold registry. They are hints only, not evidence.


## Home

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#home/today` | Investment desk | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/overview, /api/v2/home/do-now, /api/v2/home/priorities-live, /api/v2/home/cio-card |  |  |  |
| `#home/outlook` | Market outlook | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/market-risk/latest, /api/v2/morning-brief (no directional-outlook reader: LQ-946) |  |  |  |
| `#home/needs` | Needs your review | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/needs-action, /api/v2/home/do-now |  |  |  |
| `#home/today:book-movers` | Your book & watch movers (v03) | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/market-movers (finviz-market-movers), holdings read model, market-quotes-extended / market-quotes-offhours-schwab lanes |  | v03 contract: held-position $ and % regular-session move per canonical account; watch-only movers carry NO holding P&L; extended-hours quote labelled separately vs official close with its own time, never overwrites regular-session totals; nothing called live on weekends; futures/overseas coverage stated explicitly; source + session clock on every tile. | owner first pass; repair at producer, no page-load synthesis |
| `#home/today:read-first` | What to read first (v03) | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/news/ (news-ingestion, news-to-catalyst, symbol-news-curation-monitor), CIO history for context links |  | v03 contract: ranked by holdings/watch/thesis relevance with documented method + coverage; why-it-matters; source, publication and observation time; duplicate headlines grouped; headline fact kept separate from model inference; an unverified headline never becomes a trading fact or stop instruction. | owner first pass; repair at producer, no page-load synthesis |
| `#home/today:protection-plan` | Protection plan (v03) | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/atm/protection-coverage, /api/v2/holdings/monitored-stops, /api/v2/atm/profit-protection-advisory (holding-protection-advisor, unified-stop-supervisor, broker-stop-reconcile lanes) |  | v03 contract: account-specific exceptions first; no-change and policy-exempt cards in an expandable section with a visible count; source mark and order clocks + coverage state shown; real order evidence separate from suggestions; stops never from a headline alone; no fill guarantees. READ-ONLY: no order/approval/stop action wired or exercised. | owner first pass; repair at producer, no page-load synthesis |

## Portfolio

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#portfolio/holdings` | Holdings | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/portfolio/holdings, /api/v2/portfolio/book-map, /api/v2/tax-lots |  |  |  |
| `#portfolio/performance` | Performance | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/portfolio/performance |  |  |  |
| `#portfolio/income` | Income | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/income-dashboard, /api/v2/dividends |  |  |  |
| `#portfolio/allocation` | Allocation | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/portfolio/book-map |  |  |  |
| `#portfolio/retirement` | Retirement | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/retirement |  |  |  |
| `#portfolio/fundamentals` | Fundamentals | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | /api/v2/symbol-cards |  |  |  |
| `#portfolio/levels` | Levels & valuation | cc-deepseek-6 → cc-deepseek-8 | UNMAPPED | valuation-assessment@1 (no backend yet, -8), /api/v2/symbol-cards |  |  |  |

## Risk & defense

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#protection/exposure` | Risk exposure | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/risk, /api/v2/market-risk/latest |  |  |  |
| `#protection/coverage` | Stop coverage | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/risk/protection-truth |  |  |  |
| `#protection/defense` | Defense plan | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/defense/posture |  |  |  |
| `#protection/hedges` | Hedge alternatives | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/defense/posture |  |  |  |
| `#protection/scenarios` | Stress scenarios | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/risk |  |  |  |
| `#protection/review-log` | Review history | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |

## Watch

_Pass 1 — 2026-11-14 18:24–18:25 ET (23:24–23:25Z), served R11 `663678405`, loopback `127.0.0.1:7777`; every row below was read over the wire, GET only, HTTP 200, payloads in `/data/agent-tmp/cc-deepseek-5/map/`. Where a view needs an action (alert create, suggestion add/dismiss) the action is **declared in the payload and was not exercised**. No Watch read is account-scoped: held/position facts are book-wide and rows carry `held_accounts`._

_Pass 2 — v04 decision workspace — 2026-11-14 19:22–19:23 ET (2026-11-15T00:22–00:23Z), served R13 `3ac0b4058`, loopback `127.0.0.1:7777`, GET only, all six probes HTTP 200, payloads in `/data/agent-tmp/cc-deepseek-5/v04probe/`. Responses: `watchlist/items?sort=hermes&limit=200` 2,985,078 B / 0.68 s; `sectors/monitor` 40,141 B / **2.72 s**; `watch/status` 1,618 B / 0.03 s; `watchlist/intelligence` 11,276 B / 0.22 s; `cio/sector-opportunities` 9,707 B / 0.56 s; `defense/sector-leaders` 4,547 B / 0.15 s. Backend field inventory behind the v04 score/rank/sector columns: `inbox/claude-lead/READY-WATCH-RANKER-SECTOR-CONTRACT-cc-deepseek-5-20261115T0030Z.md` (review by cc-deepseek-7: ACCEPT WITH FIXES, `bcd342f5`; its four corrections are folded into the rows below). v04 replaces the pass-1 three-row list table on My List / Suggestions / Prospects / Setups / Discover / Pullbacks with one shared decision workspace; the pass-1 rows stay the contract for their readers, and the new workspace rows follow the pullbacks row. **Freshness and population are owned by different readers**: `WatchStatus@v1` computes freshness (verdict STALE, session `off`, three inputs 96.2–98.3 ks vs a 93.6 ks limit), `WatchProjection@v1` reports counts over the page its own items call returned, with a **request-clock `as_of` and no age field** — neither may be read for the other's question._

_**v04 score semantics — read this before building any column.** The `/100` "Core merit", the signed "sector contribution" and the additive "Priority indicator" in v04 are **DEMO FIXTURES** (`DEMO-WATCH@1`, `watchFixture` at v04 line 120). They are not production weights, not the production scale, and not a validated score or expected return. Production keeps three fields separate — security merit, sector contribution and final queue rank — labels the sector adjustment an **experiment**, and ships **no weights** until a walk-forward / out-of-sample comparison against the current baseline exists (plus sensitivity, turnover and coverage). The contract is `watch-rank@1` in the READY above; until it is approved the page must render the existing composite **with its scale, `_coverage` and age**, and `adjustment unavailable` for the sector term — never a fabricated `/100` or an invented contribution._

| anchor | tab | owner → reviewer | status | served reader(s) | observed working · evidence (ET) | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#watch/overview` | Overview | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/watch/status`, `/api/v2/watch/priority`, `/api/v3/data-broker/watch-curation?view=mine`, `/api/v3/cio/latest`, `/api/v2/market-risk/latest` | status `STALE` (regime 94,813 s > 93,600 s); priority 6 cards; curation 111 names / 17 starred; cio digest 94 d; sectors 16 groups; 18:24–18:25 | no overview reader; five counts of "how many names" (7,398 / 113 / 200 / 111 / 273); "what changed" digest is 94 d old with a placeholder hash | adapter `WatchOverviewRead@v1` names each tile's population + clock; cc-deepseek-5 · digest producer decision → lead |
| `#watch/my-list` | My List | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v3/data-broker/watch-curation?view=mine` | 200, 210,931 B, 1.78 s; `WatchCuration@v1`; 111 names, **11 rows returned of 111** (210 KB budget); starred 17; 18:24:47Z | interim adapter ("CIO prospect store not live"); row budget truncates the page without a "showing 11 of 111" field; server facet groups overlap and must not be summed | adapter renders server facets as shipped + pagination honesty; cc-deepseek-5 |
| `#watch/suggestions` | Suggestions | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v3/data-broker/watch-curation?view=suggests` | 200, 219,032 B, 10.7 s; 1,642 eligible / 1,738 ranked; **14 rows returned of n=20**; ranking 2026-11-13T21:30:34Z | `price`/`price_as_of` null on sampled row; 8 held/mine names skipped; ranking clock 25.9 h; actions are POST (declared, not exercised) | adapter shows returned-vs-promised and unknown price; cc-deepseek-5 |
| `#watch/prospects` | Prospects | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v3/data-broker/watch-prospects` | 200, 14,469 B, 0.53 s; `WatchProspects@v1`; counts total 273 (forming 179, reentry 29, manage 22, expired 43, actionable 0); 18:24 | every lane `items: []` with overflow only; `pagination.total 0` contradicts 273; lane membership partly unverified (77 unevaluated) | adapter renders lanes from counts/overflow and labels the pagination defect; data broker fixes the pagination block |
| `#watch/setups` | Setups | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/watchpool?status=all` | 200, 9,305 B, 0.20 s; 7,605 rows, **`by_status` has one key `ACTIVE`**; 25/page; as_of 2026-11-13T19:02 ET | read drops the stored entry snapshot (no price/RSI/RVOL/ATR/trend — `SETUPS_EVIDENCE_GAP`); no reaper: `current_status` is the insert default, so expiry never shows | projection adds entry snapshot + expiry status (data broker); until then unknown with the reason; cc-deepseek-5 |
| `#watch/sectors` | Sectors | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/watch/sectors`; `/api/v2/market-risk/latest` → `sectors` | membership 20 sectors + 10-symbol sample, 2026-11-14T18:17 ET; `MarketRiskSectors@v1` 16 groups with r1/r5/r20 + rs1/rs5/rs20, as_of 2026-11-13 | two readers, no sector contract; returns/RS only in market-risk; 11 of 16 groups measured; membership clock is the universe clock | adapter joins by sector label, renders 5 unmeasured as unknown; cc-deepseek-5 |
| `#watch/discover` | Discover | cc-deepseek-5 → cc-deepseek-7 | MISSING | `/api/v2/screener-finds/candidates` | 200, `BrokerReadEnvelope@v1`, `gap.kind:"no_producer"`, as_of 2026-07-16 (121 d), count 0, 13,093 stored rows, **writer null** | the read is honest; the product has no producer. No page can be populated from it | render declared gap + age; producer decision → lead (data broker / screener), not an app-side engine |
| `#watch/alerts` | Alerts | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/watch/alerts/list` | 200, 31,113 B, 0.16 s; active_count 18, 100 rows, newest 2026-11-11T10:20 ET; evaluator `store_missing: true`, liveness null | rows carry no delivery/acted-on state; evaluator liveness is UNKNOWN forever until its runs record is written; create-alert POST not exercised | page shows alert ages + "evaluator never ran" verbatim; the lane's runs writer is an ops fix |
| `#watch/pullbacks` | Pullbacks | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/pullback-macd/candidates` | 200, 9,655 B, 0.23 s; 14 candidates, 4 trigger (0 live / 4 stale), 10 watch; last scan Fri 2026-11-13 16:40:20 ET, 503 screened, 0 errors | score formula is uncapped (VLO 106.7) and is not a percentage; 4 stale triggers are the Saturday session, not a lane failure; next scan Mon 16:40 ET | label score as a rank/points scale and stale as "no live session"; cc-deepseek-5 |
| `#watch/{my-list,suggestions,prospects,setups,discover,pullbacks}:decision-table` | Investment decision table + phone cards (v04) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/watchlist/items?sort=hermes` (one row per security; `limit`, `?symbols=`); `/api/v2/watch/projection` (page counts over the same read); `decision_packets` (live packet per symbol); `/api/v2/sectors/monitor` (sector state) | 200, 2,985,078 B / 0.68 s; 200 rows + `universe_count 7,461`; per-row presence price 192/200, change_pct 185/200, profile_sector 196/200, profile_industry 196/200, support 196/200, resistance 196/200, atr_pct 195/200, volatility_band 195/200, plan_stop_dist_pct 197/200, hermes_rank 199/200, hermes_composite_score 200/200, hermes_score_components 200/200, entry_tag 197/200, freshness_state 200/200; 19:22 ET | generic `sector`/`industry` are **absent** on 200/200 (no row carries the key — absent, not null; use `profile_*`); **no `held` key on any row** either (absent, not null) — `in_portfolio` (200/200) is the ownership flag, refreshed from live holdings at `api_v2.py:10500-10517`, and no account identity is on any row; `/api/v2/watch/projection` composes `_wl_items()` itself, so for the **same query** its counts match the items read (`?sort=hermes&limit=200` → `counts.held 7` = the 7 `in_portfolio` rows); an unsorted call returns a different page (held 4) — different query, not a source disagreement; `active_filters` is `{}` even when a sort is applied, and `counts.catalog 200` is a page of `universe_count 7,461`, not the population; no distance field (the adapter computes (level − mark)/mark); `atr_20_pct` 49/200 vs `atr_pct` 195/200; the read is a page of 200, not a population and carries no facet counts | adapter renders the 8 columns from one read, states "page of 200" against the population and gives each field its own clock; distance is computed, never stored; an absent cell renders unknown + reason, never 0; ownership renders from `in_portfolio` for the returned page, and no count is presented as a universe total |
| `#watch/*:toolbar` | Decision filters — find · ownership · sector · horizon · order (v04) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | items route accepts `sort=hermes` only; ownership/sector/horizon have no server parameter | `profile_sector` 196/200 supports a sector facet over the returned page; `in_portfolio` 200/200 supports ownership; **no horizon field on any row**; `watch_lists` 34/200 and a " · "-joined string, not a structure; 19:22 ET | no server-side filtering for ownership/sector/horizon; horizon is absent as a per-row field (`watchlist_strategy_cards.time_horizon` is the constant `medium_term` on 5,866/5,866); "Nearest support" is computed and "Sector contribution" has no comparator to sort by | adapter filters the returned page and says so ("filtering this page of 200, not the population"); server-side facets + a horizon field are a data-broker ask; never present a page filter as a universe filter |
| `#watch/*:score-column` | Internal merit · sector contribution · queue rank · prior rank (v04) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `watchlist_items.hermes_composite_score` + `hermes_score_components` + `hermes_rank` on the items read; `hermes_score_history` is a **change log**, not a per-run substrate (`_write_score` `:1054` suppresses the append when ·Δcomposite· < 0.05 and the rank is unchanged; ~1 row/symbol over 2 days; no `run_id`); `_rank_delta` (`:1011`, applied `:1037`) computes every symbol's prior-vs-new rank each run and **discards it**; `hermes_weight_calibration` (in-sample) | components 200/200 with per-factor {score, weight, detail} + `_coverage`/`_confidence`/`_raw_score`/`_regime`/`_vix`; `_coverage` min 0.1 / median 0.5 / max 1.0; component presence analyst 186, risk_reward 119, sector_strength 60, social 56, options_edge 52, thesis_outcome 12, news_catalyst 4, technical_momentum 200, setup_quality 199; **weight ranges after renormalization**: technical 0.010→**1.000** (at least one row is scored on technical alone), analyst 0.515→0.962, risk_reward 0.126→0.861, sector_strength 0.068→0.572, setup 0.010→0.500; ranks 1…4,076 in this page over a 5,252-symbol ranked universe; score age p50 27.8 h / p90 267.9 h / max 2,936 h; 19:22 ET | **there is no separate merit vs sector-contribution field** — the only sector term is `sector_strength`, a 1-day ETF-vs-SPY move `clamp(55 + rel·25)` joined via `intelligence_entities.sector` (16/71 active; `symbol_profiles.sector` has 58/71), and it behaves like market direction rather than sector leadership (see field table); rank is global, not a Watch rank; no prior rank, `rank_change`, `why_moved` or per-row model version in the payload; the calibrator is in-sample (sector +0.034, analyst +0.084, risk_reward +0.073, technical −0.089, setup −0.178, n=51,897) and composite-vs-20-day-return rank correlation is −0.0065 | build nothing until `watch-rank@1` is approved (merit_score / sector_contribution / queue_rank / prior_queue_rank / rank_change / why_moved / coverage / model_version); then n8n computes and stores, the GET only reads, the frontend never recomputes. Prior rank needs a **schema addition**, not a new producer: persist `_rank_delta`'s output (prior_rank, rank_changed_at, run id) instead of discarding it. Meanwhile render the existing composite labelled "Hermes composite · 0–100, renormalized over present factors" with its coverage and age and "sector adjustment unavailable" — never the v04 `/100` |
| `openDrawer('watch:<id>')` | Watch detail — Decision / Fundamentals / Levels / Risk / News / Score & sector / History (v04) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v3/watchlist/intelligence/{symbol}` (fundamentals, catalysts, `identity.missing`); items read (levels, ATR, risk); `decision_packets` (2,033 live symbols, `packet_version 1.1.0-shadow`; 34/71 active, newest 2026-11-13T11:03 ET, mean age 569.8 h); `watchlist_entry_plans` (27,974 plans / 4,025 symbols, latest 2026-11-13T17:50 ET) | detail serves pe/forward_pe/peg/eps_growth/margins from the enrichment cache (cache 2,278 `pe` / 2,431 `forward_pe` of 6,816; active 41/71 and 46/71); catalysts for 52/71 active in 60 d; plans store `entry_thesis` and `invalidation` text | **dividend: equities carry no dividend field at all** (`_fundamentals_block` equity branch `:936-945` emits none); the fund/ETF branch `:929` reads `dividend_yield`/`dividend_yield_pct`, which the cache does not have — its only dividend key is `div_yield_pct` (1,963 symbols); peer context null by construction (`relative_performance.versus_*` — "null until sourced") although `finviz_group_performance` holds 143/144 industries with `pe` + `dividend_yield` dated 2026-11-14 and is joined to nothing; `plan.entry_thesis` / `plan.invalidation` are stored and dropped by every reader (`lib/data_broker/entry_plan.py`); packets are shadow-mode; no History reader for prior rank | serve what exists and mark the rest unknown with its reason; four named backend asks — equity dividend field, industry/sector peer band (join finviz_group_performance), thesis/invalidation text projection, prior-rank read |
| `openDrawer('watch-definitions')` | Watch metric definitions (v04) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | none — a definition contract over the fields above | drawer key `watch-definitions` present in v04; the served payloads already fix the terms it must state (score scale + coverage, distance = (level − mark)/mark, ATR is volatility not loss-at-risk, session label per row) | definitions must be generated from the served field names and limits, not hardcoded prose; a threshold the operator has not set renders `UNSET` | definitions bound to the adapter's field map; reviewer checks each definition against the payload key it names |
| `openDrawer('watch-movers')` | Watchlist mover evidence (v04) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL — cross-ref `#home/today:book-movers` | `/api/v2/market-movers` + the exact security's watch context (items / intelligence) | drawer key `watch-movers` present in v04; watch-only movers carry no holding P&L (contract recorded on the Home movers row) | same producer gaps as the Home movers row; the watch context is a second read and must carry its own clock | reuse the Home movers adapter — no second mover computation on this page |
| `#watch/sectors:rotation` | Defensive-rotation scenario (carried from v03; reachable at `#watch/sectors` and `#reposition/rotation`) | cc-deepseek-5 → cc-deepseek-7 | PARTIAL | `/api/v2/sectors/monitor` (rs5/rs20/rs60 + state + candidates); `/api/v2/cio/sector-opportunities` (9 opportunities, `rs20`, `slope`, `current_exposure_pct`, `target_posture_pct`, `target_is_placeholder`); `/api/v2/defense/sector-leaders` (`rank`, `rank_change`, `book_weight_pct`, `as_of`); `/api/v2/rotation/summary` | monitor 200, 40,141 B / 2.72 s; 11/11 sectors classified, `stale:false`, **`rs_as_of 2026-11-13`** — the payload `as_of 2026-11-15T00:15:02Z` is the request clock, not the evidence clock; per-sector `rank` + `rank_change` + `book_weight_pct`; `rs_score` null on the opportunity rows; 19:15–19:23 ET | no graded outcome table for sector states (the backfill ledger is hypothetical and labelled as such); the v04 quadrant plot is a normalised demo axis, not an RRG calculation; `target_is_placeholder` is served but never surfaced; three sector vocabularies coexist (ETF labels / Finviz / `symbol_profiles` — "Financial Services" has no ETF in the scorer map); canonical 5/20/60 RS (`lib/sector_signals.relative_strength`) is used by no Watch score | render each sector with its own evidence clock (`rs_as_of`), the measured/unmeasured split and `adjustment unavailable` where evidence is missing; relative strength is not inflow, not absolute return and not predicted profit; the scenario stays review-only (`No automatic allocation`) |

### Watch — v04 field provenance

Every field and control v04 adds, with the read that carries it. Verdict vocabulary: **EXISTS** (served today) · **PARTIAL x/y** (coverage) · **NOT EXPOSED** (stored, no reader) · **NOT BUILT** (no source) · **DEFECT** (a reader names a key that does not exist). Owner is the adapter (cc-deepseek-5) unless named; reviewer cc-deepseek-7.

| v04 field / control | served source · field | clock | verdict |
|---|---|---|---|
| Symbol · company | items `symbol`, `company` | quote clock | EXISTS 200/200 |
| Sector · industry | items `profile_sector`, `profile_industry` (`symbol_profiles`) | profile `updated_at` | EXISTS 196/200 — no row carries a generic `sector`/`industry` key (absent, 0/200) |
| Ownership label ("Owned · IRA / Not held") | items `in_portfolio` (live holdings override, `api_v2.py:10500-10517`); **no `held` key**; no account id per row | holdings sync | PARTIAL — book-wide only; the projection re-composes this same page, so its counts agree with the items read for the same query (`?sort=hermes&limit=200` → held 7 of 7) |
| List membership ("· My List") | `watchlist_items.source` (single value); `watch_lists` | continuous | PARTIAL 34/200, joined string |
| Horizon ("Long-term / Swing / Income") | — | — | **NOT EXPOSED** — `watchlist_strategy_cards.time_horizon` is the constant `medium_term` |
| Current mark | items `price` + `price_as_of` | 2026-11-13T16:45 ET (last) | EXISTS 192/200 |
| Day % | items `change_pct` | same | EXISTS 185/200 |
| Session label | items `market_session` | per row | EXISTS 199/200 (Saturday: afterhours 185 / closed 14) |
| Support + signed distance | `support` (20-session close min, 60-day window, ≥10 closes); distance | `watchlist_strategy_cards.updated_at` 2026-11-13T17:52 ET | EXISTS 196/200; distance **computed** — no stored field |
| Resistance + distance | `resistance` (same method) | same | EXISTS 196/200; distance computed |
| Level method label ("daily pivot") | stored method is 20-session close min/max, **not pivots** | — | copy must change: state the real method |
| Trailing P/E | enrichment cache `pe` | cache sweep | PARTIAL 41/71 active; detail route only, no `pe` key on the list |
| Forward P/E | cache `forward_pe` (period labelled) | same | PARTIAL 46/71; detail only |
| Income context (yield) | equity detail emits **no dividend field at all** (`:936-945`); the fund/ETF branch `:929` asks for `dividend_yield`/`dividend_yield_pct`, which do not exist — cache key is `div_yield_pct` (1,963 symbols); the **list** route does carry `dividend_yield_pct` (200/200 present, 4/200 non-null) and `ttm_dividend` (0/200 non-null), so the absence is in the detail reader, not the whole surface | same | **NOT BUILT** for equities · **DEFECT** for funds |
| Peer / industry comparison | `finviz_group_performance` 143/144 industries + 11/11 sectors, `pe` + `dividend_yield` | snapshot 2026-11-14 | EXISTS, **NOT JOINED** to any Watch card |
| Internal merit `/100` | `hermes_composite_score` (0–100, renormalized over present factors) | `hermes_scored_at` | EXISTS — but this is **not** the v04 demo scale; carry coverage + age |
| Signed sector contribution | `hermes_score_components.sector_strength` = `clamp(55 + 25·(ETF day% − SPY day%))` | same | PARTIAL 60/200 — component only; the v04 field is **NOT BUILT**. It is a score component, **not** a rank contribution. Measured Friday: 10 of 11 sectors read "leading", cross-section compressed 21.8→100, mean +0.90 pp while SPY fell 0.69 %; ρ with canonical rs5 0.086 / rs20 0.136 / rs60 0.564 — **it largely encodes market direction and defensive beta**, and `_regime_weights` multiplies it ×1.25 at VIX>25. Replace it; if displayed before that, name it `sector_beta_1d` |
| Queue rank · prior rank ("#2 · was #1") | `hermes_rank` (global); prior rank is computed each run by `_rank_delta` (`:1011`) and discarded; `hermes_score_history` is a change log (`_write_score` `:1054`), not a per-run record | per run | PARTIAL — current rank EXISTS, prior rank **NOT EXPOSED**, no `rank_change`/`why_moved`; persisting `_rank_delta` is a schema change, not a new producer |
| Sector state + frame ("Weakening · Daily + weekly") | `/api/v2/sectors/monitor` `state`, `momentum`, `rs5/20/60` | `rs_as_of 2026-11-13` | EXISTS, **NOT JOINED** to the list rows |
| Risk: ATR(14) % | items `atr_pct`, `atr_20_pct`, `volatility_band` | quote clock | EXISTS 195/200 (`atr_20_pct` 49/200) |
| Risk: protection / uncovered shares | items `risk_status`, `stop_loss`; holdings coverage | protection lanes | PARTIAL 72/200 |
| Coverage label | `hermes_score_components._coverage` | per score | EXISTS 200/200 (0.1–1.0) |
| Decision action · why · next condition | items `entry_urgency` + `entry_tag` 197/200; `decision_packets` 34/71 active, shadow, newest 32 h; plan `entry_thesis` | plan 2026-11-13T17:50 ET | PARTIAL — the rationale text is **NOT EXPOSED**. **READY is unreachable by construction**: the tag needs urgency=ready AND confidence ≥ 0.70 (`watchlist_entry_planner.py:71,725`), and every plan since 2026-11-09 carries ≤0.62 (501/501). 16 symbols still show a latest plan tagged READY (all ≤2026-11-06T18:07 ET) — the table is **stale of READY**, not merely empty, and the lane reports nothing about it |
| Orderings: opportunity / nearest support / sector contribution | `hermes_rank`; (level − mark)/mark; — | — | PARTIAL — sector ordering **NOT BUILT** |
| "No order implied · sizing not supplied" | design constraint, not a field | — | NOT_APPLICABLE — copy only |

### Watch — pass-1 detail

**`#watch/overview` — PARTIAL.** v02 asks for 4 metric tiles, "What changed on your watchlist", the my-list table, a sector map and CIO memory. No single reader composes them; each tile exists somewhere and they are not one population.
- `/api/v2/watch/status` → `WatchStatus@v1`: `verdict: STALE`, `cause: "Regime: last write 94813 s ago, limit 93600 s"`, `computed_at 2026-11-14T23:25:15Z`, `session: "off"`; inputs `my_list OK 584 s`, `prospects OK 93,089 s`, `alerts OK 92,699 s`, `regime STALE 94,813 s`.
- `/api/v2/watch/priority` → `watch_priority.v1`, `generated_at 2026-11-14T18:25:15 ET`, 6 cards (FTH DETERMINISTIC_FAIL, NUAI AVOID, AXTI/SWBI/CECO BLOCKED, PFLT MANAGING), flags `watch_card_v2_visible:false`, `watch_card_v2_shadow:true`.
- `/api/v3/cio/latest` → `NO_MATERIAL_CHANGE`, artifact `nmc-2026-08-04-aaaaaaaaaaaa`, generated **2026-08-12T22:47:30 ET (94 d)**, `watchlist_material_hash` is 64 × `a` (placeholder). This is the only "what changed" product and it cannot back a tile without its age.
- **Five populations, none named at the field:** `watchlist_summary.total_active 7,398` while its own `by_status.active` is `71`; `/api/v2/watchlist` returns 113 items (`active_directives_count 102`); `WatchProjection@v1` (source `/api/v2/watchlist/items`, counts computed from returned rows only) reports `catalog 200 / matched 199 / held 5 / starred 17` with `observation.observed_at: null`; curation membership is 111; prospects 273.
- Gap → adapter `WatchOverviewRead@v1` with a named `population` per tile and a clock per tile; the digest producer (94 d, placeholder hash) is a lead decision. Owner cc-deepseek-5 (adapter), data broker (digest).

**`#watch/my-list` — PARTIAL.** `/api/v3/data-broker/watch-curation?view=mine`, 200, 210,931 B, 1.78 s.
- Contract: account = **book-wide** (no account scope; rows carry `held_accounts`/`held_account_labels`); security = `symbol` + `security_guid` + `issuer_guid`, `identity_status CONFIRMED`; session = `held` facts refresh 18:00 ET, ranking Fri 21:30Z; metric = membership + stage + conviction + next trigger; clocks = `composed_at 2026-11-14T23:24:47Z`, `position_facts.as_of 2026-11-14T23:24:55Z`, `held.as_of 2026-11-14T18:00:06 ET`, `ranking.as_of 2026-11-13T21:30:34Z`.
- Rows are `WatchProspectRow@v1`, 56 fields including `stage`, `why`, `next_trigger`, `next_action`, `evidence_at`, `conviction` + `conviction_components` (`conviction_coverage 1.0`), `conflicts`, `review_state` — v02's Stage / Next condition / Evidence / Review columns all have a source.
- `my_watchlist`: `count 111`, `starred 17`, `pagination {limit 25, total 111, returned 11, has_more true, budget_bytes 210000}`; `kind_counts {directive 42, operator_added 74, personal_watchlist 15}`; `position_facets.stage {actionable 0, reentry 22, forming 77, manage 12, blocked 97, has_catalyst 60}` — facet groups overlap; never sum them.
- Gap: `interim: true`, `source_label: "interim — CIO prospect store not live"`; the page is capped at 11 rows with no "showing 11 of 111" statement in the payload. Next: adapter renders server facets/filters as shipped and states returned-vs-total.

**`#watch/suggestions` — PARTIAL.** `?view=suggests`, 200, 219,032 B, 10.7 s.
- `n 20` (`n_max 30`) but **14 rows returned**; `eligible 1,642`, `ranked 1,738`; `ranking.as_of 2026-11-13T21:30:34Z`, run `opp-20261113T213034Z-93b302`, store `data/cio/cio_opportunity_projection.json`; rotation `available:true`, prev 21:00Z → current 21:30Z, `exit_band 30`, `displace_margin 10`; `skipped.mine` 8 (ELVN #1, CECO #9, OUST #12, BHVN #16, VRT #34, DLR #39, AVGO #55, LMT #58).
- Row fields v02 needs: `stage`, `lane`, `why`, `next_trigger {zone, level_ref, inside, distance_pct, observed_by}`, `next_action {kind, label, reason}`, `evidence_at 2026-11-13T21:07:27Z`, `conviction 68.14`, `universe_rank 2`; sampled `price` and `price_as_of` are **null**.
- Actions declared, not exercised: `POST /api/v2/watch/directives` (`created_by: operator`), `POST /api/v3/watch/commands/suggest-dismiss`.
- Gap: returned 14 of 20 with no partial-page flag; null price must render unknown. Next: adapter; owner cc-deepseek-5.

**`#watch/prospects` — PARTIAL.** `/api/v3/data-broker/watch-prospects`, 200, 14,469 B, 0.53 s, `WatchProspects@v1`.
- `counts {actionable 0, forming 179, reentry 29, manage 22, expired 43, total 273, mine 111}`; lanes carry `cap` + `overflow` (symbol lists) and **`items: []` everywhere**, `actionable.mine 1`; `unevaluated_overflow 77`; `conflict_count 0` scoped `flagged_names_on_page`; `cio_prospect_status: shadow`.
- **Defect:** `pagination {offset 0, limit 25, total 0, returned 0, has_more false}` while `counts.total` is 273 — the pagination block is computed from an unpaged read. A renderer that trusts it says "0 prospects".
- Gap: adapter renders lanes from `counts`/`overflow` and labels the pagination contradiction; backend pagination is the data broker's. Next: adapter; cc-deepseek-5.

**`#watch/setups` — PARTIAL.** `/api/v2/watchpool?status=all`, 200, 9,305 B, 0.20 s.
- `count 7,605`, `by_status {ACTIVE: 7605}` — **no terminal status ever appears**; `by_origin {hermes 5,236, trade_ai 1,393, screener 652, operator 324}`; `pagination {limit 25, total 7,605, budget_bytes 480000}`; `as_of 2026-11-13T19:02:00 ET`, `as_of_basis: strategy_watchpool.entered_at` (newest entry, not a scan clock).
- Row fields: `id, strategy_id, symbol, screener_id, bucket, current_status, entered_at, expires_at, origin_system, directive_id/label`. **No price, entry, RSI, RVOL, ATR or trend** — `apps/command-center-v3/src/lib/watchSetupsV002.ts:290-294` states the bounded read drops the stored entry snapshot and that those fields are stored, so this is a missing projection, not a missing producer.
- `current_status` is the insert default; no reaper flips expired rows (`poolValidity`, apps/command-center-v3/src/lib/watchSetupsV002.ts:299), which is why 7,605 rows are all ACTIVE.
- Next: projection change owned by the data broker; meanwhile the page renders unknown for price/mechanics with that reason. Adapter: cc-deepseek-5.

**`#watch/sectors` — PARTIAL.** Two readers, no shared contract.
- `/api/v2/watch/sectors`: 20 sectors, `count` + 10-symbol `sample`, `as_of 2026-11-14T18:17:16 ET`, `as_of_basis: incubator_universe.updated_at` (a universe clock, not a market clock).
- `/api/v2/market-risk/latest` → `sectors` (`MarketRiskSectors@v1`): 16 groups with `r1/r5/r20` and `rs1/rs5/rs20`, `dd20`, `state`, `evidence`, `symbols`; `as_of 2026-11-13` (Fri close); benchmark SPY `r1 −0.36 / r5 +2.59 / r20 −1.16`; `sectors_measured 11`, `sectors_down 4`, `dispersion 1.32 (z −1.0)`.
- v02's sector map needs absolute return + 5-session relative strength — present only in market-risk, and only for 11 of 16 groups. Gap: adapter joins by sector label and renders the 5 unmeasured as unknown (never 0). Next: adapter; cc-deepseek-5.

**`#watch/discover` — MISSING.** `/api/v2/screener-finds/candidates`, 200, `BrokerReadEnvelope@v1`.
- `gap {kind: "no_producer", declared_behaviour: "declared_gap_no_producer"}`, `as_of 2026-07-16T17:00:04Z`, `age_hours 2910.42` (121 d), `stale: true` (48 h), `source.writer: null`, table `watch_candidate_events` holds 13,093 rows, `count 0`, `candidates: []`, `items: []`, `buy_side_only: true`.
- The read is honest about being empty; the product does not exist. Next: render the gap with its age; the producer decision is the lead's (no app-side discovery engine).

**`#watch/alerts` — PARTIAL.** `/api/v2/watch/alerts/list`, 200, 31,113 B, 0.16 s.
- `active_count 18`, 100 rows, `as_of`/`rows_newest_at 2026-11-11T10:20:02 ET`; `liveness_at: null`, `liveness_basis: "evaluator_last_run"`; `evaluator {readable: true, last_run_at: null, store_missing: true, reason: "no runs record has been written yet (the evaluator has not completed a pass since its writer landed)"}`.
- Rows: `id, symbol, condition_type, threshold, recurring, cooldown_days, active, created_at, last_fired_at`. No delivered/acted-on field. `POST /api/v2/watch/alerts` exists — not exercised.
- Gap: liveness is UNKNOWN by construction until the lane writes its runs record; the page must show "evaluator has never run" verbatim and age every alert, never "all clear". Runs writer = ops fix (lane `watch-alerts-eval`); adapter = cc-deepseek-5.

**`#watch/pullbacks` — PARTIAL.** `/api/v2/pullback-macd/candidates`, 200, 9,655 B, 0.23 s.
- `14 candidates`, `trigger_count 4`, `trigger_live_count 0`, `trigger_stale_count 4`, `watch_count 10`, `held_count 0`; `hit_stats {window 90 d, triggers 39, evaluated 17, target1_first 2, median 4 d}`.
- `last_run` id 779: `scan_date 2026-11-13`, `screened 503`, `pullback_count 14`, `proposals_emitted 7`, `data_errors 0`, `duration_s 18.1`, created `2026-11-13 16:40:20 ET`; cron `40 16 * * 1-5` → next scan Mon 16:40 ET. **The 4 stale triggers are the Saturday session, not a lane failure.**
- Rows carry `price, entry, stop, target1, rr, atr, vwap, macd_prox_pct, proposal_status, proposal_live`; sampled VLO `proposal_status REJECTED`, `proposal_live false`, `score 106.7` under `score_formula base 100 + trend − |pullback−20|×1.5 − (macd_prox/0.6)×30` — **uncapped, so score is points, not a percentage**.
- Next: adapter labels the score scale and the stale reason; cc-deepseek-5.

## Reposition

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#reposition/rotation` | Defensive rotation | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/rotation/summary |  |  |  |
| `#reposition/reentry` | Re-entry | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/recovery, /api/v2/reentry/decision-desk |  |  |  |
| `#reposition/exits` | Exit reviews | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED | /api/v2/recovery |  |  |  |
| `#reposition/capital` | Capital book | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |
| `#reposition/comparison` | Plan comparison | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |
| `#reposition/plan-lab` | Plan lab | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |
| `#reposition/event` | Market events | cc-deepseek-7 → cc-deepseek-5 | UNMAPPED |  |  |  |  |

## Trade

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#trade/desk` | Trade desk | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/strategy-desk |  |  |  |
| `#trade/active` | Active positions | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `#trade/options` | Options | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `#trade/strategies` | Strategies | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED |  |  |  |  |
| `#trade/journal` | Journal | cc-deepseek-4 → cc-deepseek-3 | UNMAPPED | /api/v2/journal |  |  |  |

## CIO & research

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#intel/desk` | CIO desk | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED | /api/v3/cio |  |  |  |
| `#intel/questions` | My questions | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/research` | Research | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/company-files` | Company files | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/reports` | Reports | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED | /api/v2/reports/list |  |  |  |
| `#intel/communications` | Investment alerts | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `#intel/history` | Decision history | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED | /api/v3/watch/cio/history |  |  |  |

## Operations

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#ops/health` | Readiness | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED | /api/v2/system/platform-health |  |  |  |
| `#ops/jobs` | Jobs & schedules | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/data` | Data quality | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/incidents` | Incidents | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED | /api/v2/home/incidents |  |  |  |
| `#ops/releases` | Releases | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/agents` | Agents & resources | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/memory` | Memory integrity | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |
| `#ops/delivery` | Delivery audit | cc-deepseek-9 → cc-deepseek-2 | UNMAPPED |  |  |  |  |

## Design review

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `#review/guide` | Review guide | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |
| `#review/site-map` | Whole-site plan | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |
| `#review/backend` | Backend contract | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |
| `#review/coverage` | Approval register | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review chrome; not part of the app |  |  |

## Drawers

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `openDrawer('memory')` | memory | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `openDrawer('question')` | question | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `openDrawer('alert')` | alert | cc-deepseek-2 → cc-deepseek-9 | UNMAPPED |  |  |  |  |
| `openDrawer('phone')` | phone | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review tool |  |  |
| `openDrawer('guide')` | guide | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review tool |  |  |
| `openDrawer('feedback')` | feedback | claude-lead → cc-opus-3 | NOT_APPLICABLE |  | design-review tool |  |  |

## Shell (cc-opus-3)

| anchor | tab | owner → reviewer | status | candidate readers (unverified) | observed working · evidence | gaps → adapter/backend | next step |
|---|---|---|---|---|---|---|---|
| `main nav (9 groups, tabs)` | main nav (9 groups, tabs) | cc-opus-3 → cc-deepseek-3 | PARTIAL |  | nav click -> URL, h1, active, aria-current, title; tab click -> active tab, aria-current=page; unknown address -> bad note · local vite preview (loopback) of wt/wealth-shell-20261114@576adbe36, 2026-11-14 18:29 ET; s2/wealth-shell/shots/*.png, shots.json, drawer.json (NOT served on /wealth/) | view slices not built: every v02 address now resolves to the family's or the group's *Not built yet* page (route patch folded fa97dd624); the ten legacy family routes whose id is not a NAV group do not render behind the shell's known-address gate (carried, shell owner) | screenshot on served /wealth/ after release |
| `account scope selector (all / per account)` | account scope selector (all / per account) | cc-opus-3 → cc-deepseek-3 | MISSING | /api/v2/overview | not ported: the v02 select is demo-only | needs a canonical account-id list reader; /api/v2/overview is a candidate, unverified (portfolio owner -6) | -6 names the account-scope reader + id contract |
| `header account value` | header account value | cc-opus-3 → cc-deepseek-3 | MISSING | /api/v2/overview | renders "? UNKNOWN" (NEUTRAL, text+icon+tooltip), never a number · local vite preview (loopback) of wt/wealth-shell-20261114@576adbe36, 2026-11-14 18:29 ET; s2/wealth-shell/shots/*.png, shots.json, drawer.json (NOT served on /wealth/) | no reader bound; /api/v2/overview candidate unverified; asked -6 | -6 names the reader; bind via api/readers.ts with as_of + max age |
| `header regular-session move` | header regular-session move | cc-opus-3 → cc-deepseek-3 | MISSING | /api/v2/overview | renders "? UNKNOWN", never a number · local vite preview (loopback) of wt/wealth-shell-20261114@576adbe36, 2026-11-14 18:29 ET; s2/wealth-shell/shots/*.png, shots.json, drawer.json (NOT served on /wealth/) | no reader bound; session label + clock contract needed; asked -6 | -6 names the reader and its session clock |
| `mobile menu + phone layout` | mobile menu + phone layout | cc-opus-3 → cc-deepseek-3 | EXISTS_UNVERIFIED |  | 390: aside hidden, menu button opens nav (body.menu-open), closes on navigation; no horizontal scroll; 0 console errors · local vite preview (loopback) of wt/wealth-shell-20261114@576adbe36, 2026-11-14 18:29 ET; s2/wealth-shell/shots/*.png, shots.json, drawer.json (NOT served on /wealth/) |  | served /wealth/ check at 390 after release |
| `drawer/overlay system` | drawer/overlay system | cc-opus-3 → cc-deepseek-3 | EXISTS_UNVERIFIED |  | 1440: role=dialog aria-modal, no-scroll, focus on Close, Tab/Shift+Tab trapped, Escape closes + focus returns to opener, overlay click closes, Close closes. 390: full-width drawer; opener hidden by v02 CSS so opened by DOM click; Escape/Close work · local vite preview (loopback) of wt/wealth-shell-20261114@576adbe36, 2026-11-14 18:29 ET; s2/wealth-shell/shots/*.png, shots.json, drawer.json (NOT served on /wealth/) |  | served /wealth/ check after release |
| `security detail drawer` | security detail drawer | cc-opus-3 → cc-deepseek-3 | MISSING |  | not built | needs the security detail reader (security id contract) from the page owners | after a page binds a security row |
| `valuation cues (colour+bold/italic+text+icon+tooltip)` | valuation cues (colour+bold/italic+text+icon+tooltip) | cc-opus-3 → cc-deepseek-3 | PARTIAL |  | CueBadge carries text + glyph + tooltip + aria-label; colour never alone; UNKNOWN is NEUTRAL · local vite preview (loopback) of wt/wealth-shell-20261114@576adbe36, 2026-11-14 18:29 ET; s2/wealth-shell/shots/*.png, shots.json, drawer.json (NOT served on /wealth/) | bold/italic valuation styling and binding to valuation-assessment@1 not done | port v02 valuation cue styles against contracts/valuation.ts |


## ADMIN (required parity, operator 2026-11-14) — slice `admin@1`
Owner cc-deepseek-9 · reviewer cc-deepseek-2 · visual cc-opus-3 → cc-deepseek-3. Entry: Wealth header settings → Admin modal.
LEAN (operator 18:29 ET): one modal, two sections — Connections · Essential settings — plus optional recent-change/undo disclosure. Diagnostics, logs, n8n internals, service/agent controls, expert tuning stay in Ops/background. Placement of each existing function: contracts/admin@1.md.
Rows and current classification: `contracts/admin@1.md` (all EXISTS_UNVERIFIED/PARTIAL/UNRESOLVED; none VERIFIED_WORKING).
