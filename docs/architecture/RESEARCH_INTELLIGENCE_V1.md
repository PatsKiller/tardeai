# Research Intelligence v1 — Architecture (Command Center v3)

**Status:** Implemented (v1 cockpit) · **Date:** 2026-07-15  
**Scope:** First-class Research Intelligence subsystem for Trade AI v12 / CC v3  
**Constraint:** Build on Hermes, agents, `topic_ingestion` / `topic_curator`, SearXNG — do **not** reinvent ingestion.

---

## 1. Taxonomy Definition

Canonical file: `config/research_intelligence_taxonomy.json` (version **1.0**).

Every intelligence item is tagged with **one or more** category ids. Primary = first in ordered list.

| id | Label | Priority | Subcategories (extensible) |
|----|--------|----------|----------------------------|
| `retirement_tax` | Retirement & Tax Strategy | 100 | roth_ladder, conversions, golden_window, rmd, irmaa, medicaid, estate, ssdi |
| `dividend_income` | Dividend & Income | 90 | holdings_dividends, covered_call_etf, bdc_cef, bond_income |
| `risk_regime` | Risk, Volatility & Regime | 88 | stops, heat, regime, volatility |
| `macro_geo` | Macro & Geopolitical | 85 | rates, inflation, geopolitics, regime, liquidity |
| `sector_thematic` | Sector & Thematic | 80 | rotation, defense, ai_infra, staples, healthcare, energy |
| `compounding_wealth` | Compounding & Long-term Wealth | 75 | compounding, allocation, drawdown_buckets |
| `catalyst_event` | Catalyst & Event-Driven | 72 | earnings, news_momentum, catalyst |
| `company_ticker` | Company & Ticker | 70 | auto_research, thesis_challenge, earnings, form4 |
| `academic_pro` | Academic / Professional | 60 | papers, pro_analyst, transcripts |

**Classification rules** (`scripts/lib/research_intelligence.py`):

1. Map known Hermes `research_type` → category (e.g. `momentum_catalyst` → `catalyst_event`, `protection_advisory` → `risk_regime`).
2. Regex keyword rules over topic / summary / thesis / tags (order = priority; multi-tag allowed).
3. Fallback: symbol-ish → `company_ticker`, else `sector_thematic`.

**Priority scoring (item-level):**

- `high` if category includes `retirement_tax`, or holdings-linked dividend/ticker, or conf ≥ 0.85 and fresh (&lt;72h).
- `low` if age &gt; 14 days.
- else `normal`.

Extend taxonomy by editing the JSON only; UI and API load it dynamically.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ SOURCES (existing — unchanged ownership)                                 │
│  SearXNG · news · filings · FRED-adjacent · transcripts · operator topics│
│  Hermes agents (Maria/Steph/Risk/Iris/Alex/Full_chain, librarian, …)     │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
 topic_ingestion.py      hermes_* workers         auto_research /
 topic_curator.py        (stage → promote)        user_research_topics
 topic_monitor           hermes_research_         operator knowledge
                         intelligence
        └───────────────────────┬───────────────────────┘
                                ▼
              scripts/lib/research_intelligence.py
              · load taxonomy · classify · holdings join
              · priority · sources extract · build_feed()
                                ▼
              GET /api/v2/research-intelligence
              GET /api/v2/research-intelligence/taxonomy
                                ▼
              CC v3 ResearchIntelligenceHub
              /research-intelligence  (Nav: Research Intel)
              /research → redirect
```

**Design principles**

| Principle | Practice |
|-----------|----------|
| Aggregate, don’t rewrite | Feed reads Hermes + `user_research_topics` + `topic_monitor`; no parallel store |
| Cheap classification | Rule-based + research_type map (no LLM per card) |
| Holdings-aware | Symbols joined to `data/portfolios/state/holdings.json` |
| Operator cockpit | Search, taxonomy filter, priority lanes, drill drawer |
| Cost model | No new cloud LLM loops; reuse Hermes budgets (`docs/COST_MODEL.md`, Hermes research budget policy) |
| Closed loop | Hermes promotion / outcome grader / learning scorecard remain upstream |

---

## 3. Data Model

### 3.1 Logical item (API card)

```json
{
  "id": "hermes:12345 | urt:99 | tm:roth_ladder",
  "source_system": "hermes | auto_research | operator_topic | topic_monitor",
  "source_table": "hermes_research_intelligence | user_research_topics | topic_monitor",
  "source_id": 12345,
  "title": "…",
  "summary": "…",
  "thesis": "…|null",
  "symbol": "SCHD|null",
  "categories": ["dividend_income", "company_ticker"],
  "primary_category": "dividend_income",
  "priority": "high|normal|low",
  "confidence": 0.0–1.0 | null,
  "freshness_hours": 12.5,
  "created_at": "ISO-8601",
  "model": "gemma3:12b|null",
  "research_type": "topic_research|auto_research|…",
  "status": "staged|promoted|active|enabled|…",
  "is_holdings": true,
  "sources": [{"title":"…","url":"…","source":"…"}],
  "actionability": "Review Roth/tax plan impact | …"
}
```

### 3.2 Physical stores (existing)

| Store | Role |
|-------|------|
| `hermes_research_intelligence` | Staged/promoted Hermes findings (thesis, evidence_json, source_urls_json, confidence) |
| `user_research_topics` | Auto-research + operator topics (`latest_findings`) |
| `topic_monitor` | Registry of monitored themes (owner hermes/tradeai/shared) |
| `config/research_intelligence_taxonomy.json` | Category SSOT |
| `data/portfolios/state/holdings.json` | Holdings universe for tags / priority |

### 3.3 Feed envelope

```json
{
  "ok": true,
  "as_of": "…",
  "taxonomy": { "version": "1.0", "categories": […] },
  "filters": { "category", "q", "priority", "symbol", "holdings_only", "limit" },
  "stats": {
    "returned", "matched", "high_priority", "holdings_linked",
    "by_category", "holdings_universe", "holdings_count", "lane_counts"
  },
  "items": [ /* page, sorted */ ],
  "priority_lanes": {
    "retirement": [ /* up to 16 from full match */ ],
    "dividends": [ … ],
    "macro_sector": [ … ]
  },
  "note": "…"
}
```

**Sort order (v1.1):** focus boost (retirement → dividends → macro → sector) → priority → holdings → freshness.  
**Lanes:** built from **full matched set**, not the truncated page (avoids empty Retirement when stop-noise fills page 1).

No new DB migration in v1. Future: optional `research_intelligence_feedback` for thumbs / action taken (closed-loop UI).

---

## 4. UI/UX Specification

**Route:** `/research-intelligence` (alias `/research` → redirect)  
**Nav:** Intel → **Research Intel**  
**Page:** `apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx`

### Layout

1. **Header** — title, match count, links to Legacy Research Topics, Retirement hub, Hermes; Refresh.
2. **KPI strip** — In view · High priority · Holdings-linked · Holdings universe · Taxonomy cats.
3. **Priority lanes** (chips) — All · Retirement & tax · Dividends & income · Macro / sector.
4. **Taxonomy bar** — category chips with counts; search box; High only; Holdings only.
5. **Card grid** — responsive `minmax(300px, 1fr)`; institutional density (not a flat topics list).
6. **Footer note** — provenance of feed + ingestion paths.

### Card visual hierarchy

- Left border = priority color (high amber / normal blue / low slate).
- Symbol (mono) · category chip (taxonomy color) · HOLDING badge · priority label.
- Title (2-line clamp) · age · confidence %.
- Summary (3-line) · source_system · research_type · model · actionability CTA.
- Click → DetailDrawer with full JSON row (sources, thesis, actionability).

### Filters (API query)

| Param | Effect |
|-------|--------|
| `category` | Keep items with that category id |
| `q` | Substring title/summary/thesis/symbol |
| `priority` | `high` / `normal` / `low` |
| `symbol` | Exact ticker |
| `holdings_only` | `1` — holdings-linked (+ always keep retirement/macro for context) |
| `limit` | 10–200 (default 80) |

### Design bar

Institutional dark terminal (existing CC tokens `--bg0/1`, `--text0–3`, mono for tickers). Feel: Figma/Tableau cockpit — KPI strip + taxonomy navigation + scannable cards — not a basic research topics table.

---

## 5. Ingestion & Processing Pipeline

### What v1 reuses (no fork)

| Component | Role |
|-----------|------|
| `scripts/topic_ingestion.py` | Periodic multi-source topic pull (tradeai/shared owners) |
| `scripts/topic_curator.py` | Curate / de-dupe / quality |
| `scripts/hermes_topic_monitor_bridge.py` | owner hermes/shared → `hermes_research_intelligence` |
| Hermes autonomous / librarian / source discovery | Stage research rows, evidence, confidence |
| `hermes_coordinator` + promotion path | staged → promoted → advisory cache / RAG |
| Monitors | catalyst, divergence, source attribution, pro-analyst coverage (upstream signals) |
| SearXNG (`infra/searxng`) | Metasearch for Hermes discovery |

### Classification layer (new)

`scripts/lib/research_intelligence.py` — pure read/aggregate. Safe to call from API, crons, or agents.

### Auto vs on-demand

| Mode | Path |
|------|------|
| Auto (daily/periodic) | Existing crons: topic_ingestion, Hermes loops, auto_research |
| On-demand | Operator topics / Hermes research POST paths already in api_v2; appear in feed on next poll |

### Priority intelligence areas (v1 focus)

1. **Retirement & tax** — keyword + topic_monitor + operator knowledge types; high priority always.
2. **Dividends & income** — JEPI/JEPQ/SCHD/PFLT/CSWC etc. holdings + dividend language.
3. **Macro / sector** — Fed/CPI/regime + sector rotation tags.

### Planned extensions (v1.x, not blocking)

- Dedicated retirement RSS / IRS / SSA curated list in Hermes RSS when operator enables.
- Dividend calendar cross-link from Dividends page into RI cards.
- Feedback endpoint (useful / stale / acted) → Hermes outcome bus.
- Subcategory multi-select and saved operator views.

---

## 6. Integration Plan

| Surface | Integration |
|---------|-------------|
| **Nav / Research** | Research Intel primary; `/research` redirect; Intelligence Hub + Hermes remain adjacent |
| **Retirement hub** | Deep-link from RI header; retirement lane feeds tax-strategy awareness |
| **Portfolio / Holdings** | HOLDING badge + holdings_only; symbols from holdings SSOT |
| **Risk** | `risk_regime` category from stop/protection Hermes types |
| **AI Analyst / CIO** | Same Hermes rows already consumed; RI is operator view of that corpus |
| **Rebalance** | Sector/thematic + macro lanes inform allocation context |
| **Agents** | Alex retirement analyses, Iris topics, Hermes librarian — all land in source tables → feed |
| **Overnight Brief** | Continues Aegis path; RI is always-on searchable counterpart |
| **Cost / safety** | Read-only aggregation; paper-only trading posture unchanged |

### API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v2/research-intelligence` | Unified feed |
| GET | `/api/v2/research-intelligence/taxonomy` | Taxonomy only |

Handlers: `_research_intelligence_feed`, `_research_intelligence_taxonomy` in `scripts/api_v2.py`.

### Frontend files

- `apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx` (new)
- `apps/command-center-v3/src/App.tsx` — routes
- `apps/command-center-v3/src/components/NavRail.tsx` — **Research Intel**

Legacy Research Topics remain under Intelligence hub (`/intelligence?tab=research`) via header link.

---

## 7. Implementation Status (v1)

| Deliverable | Status |
|-------------|--------|
| Taxonomy JSON | Done |
| Architecture + data model (this doc) | Done |
| Aggregator lib + API | Done |
| Dashboard UI + nav | Done |
| Top-3 lanes (Retirement, Dividends, Macro/Sector) | Done (lanes from full match set) |
| Heavy new ingestion streams | Deferred — leverage existing |
| Feedback / closed-loop UI | Deferred v1.x |

### Verify

```bash
# Module
PYTHONPATH=scripts python -c "from lib.research_intelligence import load_taxonomy, classify_text; print(load_taxonomy()['version'], classify_text('Roth ladder'))"

# Live API (portfolio_server :7777)
curl -sS 'http://127.0.0.1:7777/api/v2/research-intelligence?limit=20' | python -m json.tool | head
curl -sS 'http://127.0.0.1:7777/api/v2/research-intelligence/taxonomy'

# UI
# open https://<host>:7777/v3/#/research-intelligence  (or /v3/research-intelligence)
```

After editing `scripts/lib/research_intelligence.py`, restart `portfolio_server` or touch `api_v2.py` **and** ensure the lib module is reloaded (Python caches imports — process restart is safest).

---

## 8. Related docs

- `docs/HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`
- `docs/hermes/HERMES_CLOSED_LOOP_TRACEABILITY.md`
- `docs/HERMES_INTELLIGENCE_ENGINE.md`
- `docs/COST_MODEL.md` / Hermes research budget policy
- `docs/COMMAND_CENTER_PAGE_MATRIX.md` (nav matrix — v3 Research Intel)
- `config/research_intelligence_taxonomy.json`
