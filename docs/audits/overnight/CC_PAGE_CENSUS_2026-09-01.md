# CC_PAGE_CENSUS_2026-09-01

**Agent:** Cursor · Wave 1 (read-only)  
**as_of:** `2026-08-31T16:50:48Z` (v2 probe) · `2026-08-31T16:53:15Z` (v3 probe) · `2026-08-31T16:54:41Z` (CIO home frozen check)  
**roots:** `live_api:127.0.0.1:7777` · code `/tmp/wt-cio-phase-a@efcc51365` · served release `efcc51365-main-exact-phase2-20260831-114929`  
**Authority:** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0` · no writes

Machine artifacts: `/tmp/cc_census_probe.json`, `/tmp/cc_census_page_rollup.json`, `/tmp/cc_census_v3.json`.

---

## Headline counts

### Endpoint probes (static `useApi`/`fetch` paths on page modules)

| class | v2 page-linked (n=201) | v3 page-linked (n=40) |
|---|---|---|
| **EMPTY** | **5** | 0 |
| **STALE** (>24h or `stale:true`) | **25** | **3** |
| **LIVE** | 117 | 32 |
| HARDCODED (non-JSON 200) | 4 | 1 |
| GET→404 raw | 50 | 4 |

**Correction [VERIFIED]:** of 50 v2 GET→404s, **48 are registered routes that are POST/action or require params** — not missing pages. Treat raw `ORPHANED_ROUTE` as **inflated**. True “page reads a path nothing serves as GET data” cases are rare; the EMPTY/STALE rows below matter more.

**Age > 7 days (backing timestamp >168h)** — **10 endpoints** named below.

### Page rollup (worst child endpoint; EMPTY > STALE > LIVE)

| page verdict | count (of 35 modules) |
|---|---|
| EMPTY | 4 |
| STALE | 16 |
| LIVE | 15 |

EMPTY pages: `TradingHub`, `HermesHub`, `JournalHub`, `PortfolioHub` (each has ≥1 EMPTY child; other children may be LIVE).

---

## EMPTY endpoints (data empty or error — page still loads)

| endpoint | producer (follow-symbol) | last moved | pages | bug class |
|---|---|---|---|---|
| `/api/v2/trade-ai/scanner` | [CODE] `trade_ai_scanner` → `trade_ai` → disk `data/runtime/trade_ai_cache.json` + `trade_ai_scans` | cache `_cached_at=2026-08-28T04:06:13Z`; tickers=[] | TradingHub | **Data empty** (not wrong path). Same as bisect → **Claude Code**. |
| `/api/v2/scalp/live` | [CODE] `_scalp_live_poll` → `data/scalp_live_signals.json` | file **missing** on served cwd | TradingHub | **Path nothing writes** *and* upstream silence. Split: missing ringbuffer file vs producer. Handoff producers → Claude Code. |
| `/api/v2/hermes/promotion-review` | Hermes promotion queue handler | n=0, no ts | HermesHub | EMPTY queue |
| `/api/v2/holdings/share-drift` | holdings drift handler | n=0 | PortfolioHub | EMPTY |
| `/api/v2/journal/review` | journal review | HTTP **400** (needs params) | JournalHub | not a dead store — probe artifact |

[VERIFIED] Trade page emptiness = **200 with no rows + stale cache**, not a frontend mis-route. Confirmed in `BISECT_TRADE_REGRESSION_2026-09-01.md`.

---

## Backing store not written in >7 days (name every route)

[VERIFIED] from parsed payload timestamps vs as_of `2026-08-31T16:50:48Z`:

| age_h | endpoint | last_moved | surfaces |
|---|---|---|---|
| 2661 | `/api/v2/local-llm-status` | 2026-05-12 | SystemHub |
| 2439 | `/api/v2/admin/accounts` | 2026-05-22 | SystemHub |
| 2186 | `/api/v2/system/queue-control-tower` | 2026-06-01 | SystemHub |
| 2125 | `/api/v2/admin/strategy-enablement` | 2026-06-04 | SystemHub |
| 1924 | `/api/v2/broker-orders/activity` | 2026-06-12 | ManualTosDesk |
| 1106 | `/api/v2/research-intelligence/staged` | 2026-07-16 | ResearchIntelligenceHub |
| 793 | `/api/v3/alerts/settings` | ~33d | AlertSettingsModal |
| 593 | `/api/v2/journal/tagging-queue` | 2026-08-07 | JournalHub |
| 568 | `/api/v2/health/coders` | 2026-08-08 | HealthHub |
| 568 | `/api/v2/health/dispatches` | 2026-08-08 | HealthHub |
| 446 | `/api/v3/watch/cio/latest` | ~18.6d | WatchLegacy |
| 243 | `/api/v2/watch/alerts/list` | 2026-08-21 | WatchHub, ReEntry V2/V3 |

Also STALE but <7d that hit home/chrome: `/api/v2/trade-ai/summary` (~85h), `/api/v2/overview` (~65h by coarse date parse).

---

## Route / tab / field census (primary hubs)

Provenance classes per AGENTS §9.5 / R24: deterministic · template · model-assisted · agent-originated · snapshot.

| route / tab / field | producer | provenance | as_of | last moved | verdict |
|---|---|---|---|---|---|
| `/v3` MetricStrip portfolio $ | `GET /api/v2/overview` | snapshot | inherits overview | ~2026-08-29 (parsed) | STALE |
| `/v3` MetricStrip setups GO/WAIT | `GET /api/v2/trade-ai/summary` → `trade_ai` cache | snapshot | `cached_at` on payload | 2026-08-28T04:06:13Z | **EMPTY/STALE** (zeros) |
| `/v3` MetricStrip regime | `GET /api/v2/risk-regime/latest` | deterministic | payload | (LIVE in probe) | LIVE |
| `/v3` MetricStrip health | `GET /api/v2/health` → `_health_agent_dashboard` | agent-originated findings | `detected_at` | 2026-08-31T16:42:59Z | LIVE |
| `/v3` HomeHub | overview, risk, command, hermes/health, trade-ai/summary, … | mixed | per child | trade-ai STALE; others mixed | STALE |
| `/v3/trading` Trade AI / Market Opportunities Scanner | `trade_ai_scanner` | snapshot of orchestrator scan | `cached_at` / `run_date` | empty since 2026-08-28 | **EMPTY** |
| `/v3/trading` Scalp strip | `_scalp_live_poll` | snapshot ringbuffer | none | file absent | **EMPTY** |
| `/v3/cio` home | `GET /api/v3/cio/home` | composition + spine | **own `as_of` + `block_as_of` (oldest contributor)** | as_of now | LIVE |
| `/v3/cio` temperament.portfolio_implication | investment product temperament | **template demoted** (`null` + `standing_policy_template`) | temperament.as_of | template constant | HARDCODED-as-template (honest) |
| `/v3/cio` decisions.next_review | universe theses / home | demoted to `null` | — | all null | frozen-null (honest post W3_3b) |
| `/v3/cio` universe theses symbols | `GET /api/v3/cio/universe-theses` | model-assisted / agent | payload `as_of` | now | LIVE |
| `/v3/watch` alerts list | `GET /api/v2/watch/alerts/list` | snapshot | last alert ts | 2026-08-21 | **STALE >7d** |
| `/v3/watch` intelligence (unified) | `GET /api/v3/data-broker/watch-intelligence` | data-broker | as_of now | n=24 | LIVE |
| `/v3/watch` legacy cio latest | `GET /api/v3/watch/cio/latest` | snapshot | ~18d | STALE >7d | STALE |
| `/v3/health` | `/api/v2/health` | agent | detected_at | now | LIVE (child coders/dispatches STALE) |
| `/v3/system` local-llm / accounts / queue tower | admin/system endpoints | snapshot | May–Jun 2026 | **STALE ≫7d** | STALE |
| `/v3/research-intelligence` staged | staged RI | snapshot | 2026-07-16 | **STALE ≫7d** | STALE |
| `/v3/defense` industries/recommendations | defense snapshots | snapshot | ~2026-08-25/26 | STALE | STALE |
| `/v3/active-trader` | `/api/v3/active-trader/*` | mixed | now | LIVE | LIVE |
| `/v3/control-plane/*` | R24 baseline paths | explicit data-source enum | per R24 | LIVE/preview | LIVE |

Full endpoint×page map: see `/tmp/cc_census_probe.json` → `page_endpoint_map` + `probe_results`.

---

## Frozen fields (constructed identity + positive control)

**Method:** compare judgment-like fields across rows on live CIO payloads; positive-control with a known-varying field (`symbol`).

[VERIFIED] `GET /api/v3/cio/universe-theses` as_of `2026-08-31T16:54:21Z`:

- `symbols`: **n=80**, `sym_unique=80` → **POSITIVE_CONTROL PASS** (detector sees motion).
- `next_review`: **unique=1 value `null`** across all sampled → frozen-null, consistent with overnight W3_3b demotion (not a stealth judgment).

[VERIFIED] `GET /api/v3/cio/home` as_of `2026-08-31T16:54:41Z`:

- `block_as_of` present with note: *"Block age is the oldest contributing evidence… product_composition is when the brief was composed — never read it as cash age."* — matches FILE 3 / §9.5 intent.
- `temperament.portfolio_implication` = `null`; `standing_policy_template` = constant paragraph with `portfolio_implication_role` / `*_class` labels → **constant labeled as template**, not rendered as live judgment.
- All discovered `next_review` values on home: unique `{null}`.

**Residual risk for Wave 3:** any UI that still titles `standing_policy_template` as if it were a per-case judgment. Code-side demotion looks done; display audit is Wave 3 scope.

---

## Corrections (what this census got wrong first)

1. **ORPHANED_ROUTE inflation** — GET without body/params on POST/action routes → 404. Corrected narrative: not 50 dead pages.
2. **`age_h=-0.0` on some v3** — timestamps slightly in the future vs probe clock / composition `as_of`; treated as LIVE, not negative age.
3. **`/api/v2/journal/review` EMPTY** — HTTP 400 without query; not proof the journal store is empty.
4. **Page rollup EMPTY** means “has an empty child,” not “entire page blank.” TradingHub still has LIVE children (open trades, proposals, etc.).
5. **Did not deep-field every panel** (489 total `/api/v2` string refs in the app). Scope = page-module primary fetches (201 v2 + 40 v3). MetricStrip included as chrome.

---

## Bisect cross-link

Trade scanner EMPTY is **upstream data** (Finviz screeners dead since 2026-08-27; cache empty since 2026-08-28). **Not a CC route bug.** Handoff remains Claude Code. Cursor Wave 3 will not “fix” the scanner by rewriting the client.

---

## Wave 1 handoff / next

- Wave 2: watch-intelligence vs `InstrumentRecord` spine (`CC_WATCH_INTELLIGENCE_WIRING_2026-09-01.md`).
- Wave 3 candidates (CC-owned only): surface `as_of`/`block_as_of` on STALE chrome tiles; demote display of unlabeled templates; fix any client path that points at missing files when an alternate live API exists — **no producer changes, no dollar changes.**
