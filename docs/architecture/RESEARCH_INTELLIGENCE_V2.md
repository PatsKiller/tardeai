# Research Intelligence v2 — Freshness, Archive, Retirement Pillar

**Status:** Implemented · **Date:** 2026-07-15  
**Builds on:** `docs/architecture/RESEARCH_INTELLIGENCE_V1.md` (commit `6bb863e4`)  
**CC route:** `/research-intelligence` (Nav → **Intel → Research Intel**)

---

## 1. Data freshness & archiving

### Policy file
`config/research_intelligence_freshness.json`

| Tier | Max age | Label example |
|------|---------|----------------|
| `live` | ≤2h | Updated 14m ago |
| `fresh` | ≤24h | Updated 6h ago |
| `aging` | ≤72h | Last refreshed ~1d ago |
| `stale` | ≤14d | Last refreshed 5d ago |
| `archive` | beyond / status=archived | Archived — historical |

### Refresh cadence (hours)
| Scope | Cadence |
|-------|---------|
| Retirement, macro, catalysts, holdings-linked, high priority | 6–12h |
| Dividends, sector, company | 24h |
| Compounding | 72h |
| Academic / pro | 168h |

### Archive rules
- **Never delete.** Hermes rows move to `status='archived'`.
- Default feed **excludes** archived; set `include_archived=1` to search history.
- Auto-archive via `scripts/research_intelligence_refresh.py --archive` after **45 days** (configurable).
- **Never auto-archive** primary `retirement_tax` items (`never_auto_archive_categories`).
- Index: `idx_hri_status_created`, `idx_hri_archived` (migration).

### Ops
```bash
# Report category SLO + stale topic_monitor rows
python scripts/research_intelligence_refresh.py

# Apply archive of old non-retirement Hermes rows
python scripts/research_intelligence_refresh.py --archive

# API
curl -sS 'http://127.0.0.1:7777/api/v2/research-intelligence/freshness'
```

---

## 2. Enhanced taxonomy (v1.1)

`config/research_intelligence_taxonomy.json`

Pillar categories (◆ in UI): **retirement_tax**, **dividend_income**, **macro_geo**, **sector_thematic**, **compounding_wealth**.

Retirement subcategories expanded: roth_ladder, golden_window, irmaa, medicare, medicaid, mapt, ssdi, tax_bracket_room, qcd, …

---

## 3. Professional dashboard (UI)

`apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx`

- KPI strip: matched, high, holdings, needs-refresh, live/fresh, stale topics, starred, archive
- Priority lanes: All · Retirement · Dividends · Macro/sector
- View modes: **cards** · **list** · **compact**
- Filters: taxonomy, search, high, holdings, starred, include archive, freshness tier, sentiment
- Per-item: freshness label, confidence, sources, sentiment, key questions, data gaps, actionability
- Operator loop: **star**, **thumbs ▲/▼**, drill drawer
- Cross-links: Retirement hub, Hermes, Portfolio, Legacy Topics

---

## 4. Retirement intelligence module

### Config
`config/research_intelligence_retirement_topics.json` — 10 seeded topics including:
- roth_ladder, golden_window, roth_conversion, irmaa_medicare, rmd_planning
- ssdi_coordination, medicaid_mapt, tax_bracket_room
- dividend_income, macro_rates_regime (portfolio-adjacent)

### Seed script
```bash
python scripts/research_intelligence_retirement_seed.py          # dry-run
python scripts/research_intelligence_retirement_seed.py --apply   # upsert topic_monitor
```

- Sets `owner=shared` (TradeAI ingestion **and** Hermes bridge)
- `priority` 1–2, `max_age_days` 3–14 (tight for retirement)
- Personal context for Golden Window / IRMAA / SSDI

### Pipeline path
```
retirement seed → topic_monitor
       ↓
topic_ingestion.py (tradeai/shared)
hermes_topic_monitor_bridge.py (hermes/shared)
       ↓
hermes_research_intelligence (topic_research)
       ↓
research_intelligence.build_feed → CC dashboard
```

---

## 5. Content quality fields (feed item)

| Field | Source |
|-------|--------|
| `summary` / `thesis` | Hermes / topics (up to 800/600 chars) |
| `key_questions` | evidence_json + “?” lines |
| `data_gaps` | heuristic on limited/unknown phrasing |
| `actionability` | category + holdings rules |
| `sentiment` | bullish/bearish/neutral keyword heuristic |
| `sources` / `source_count` | evidence_json.grounded_on + source_urls |
| `freshness_*` | age vs policy tiers |
| `needs_refresh` | age &gt; cadence |
| `starred` / `vote` / `operator_note` | `research_intelligence_feedback` |

---

## 6. API layer

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v2/research-intelligence` | Feed (filters: category, q, priority, symbol, holdings_only, include_archived, freshness, starred_only, sentiment, source_system, limit) |
| GET | `/api/v2/research-intelligence/taxonomy` | Taxonomy + freshness policy |
| GET | `/api/v2/research-intelligence/freshness` | SLO report + stale monitors |
| POST | `/api/v2/research-intelligence/feedback` | `{ item_id, starred?, vote?, note? }` |

### Data model
`migrations/2026_07_24_research_intelligence_v2.sql` → `research_intelligence_feedback`

---

## 7. Cost & safety

- Classification + sentiment remain **rule-based** (no new cloud LLM loop).
- Ingestion reuses existing topic_ingestion / Hermes budgets.
- Archive is soft; research remains searchable.
- Feedback is operator-only learning signal (local table).

---

## 8. Files

| Path | Role |
|------|------|
| `config/research_intelligence_taxonomy.json` | Taxonomy v1.1 |
| `config/research_intelligence_freshness.json` | Tiers + archive policy |
| `config/research_intelligence_retirement_topics.json` | Retirement seed catalog |
| `scripts/lib/research_intelligence.py` | Aggregator v2 |
| `scripts/research_intelligence_refresh.py` | Freshness report + archive |
| `scripts/research_intelligence_retirement_seed.py` | Topic monitor seed |
| `migrations/2026_07_24_research_intelligence_v2.sql` | Feedback table |
| `apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx` | Dashboard UI |
| `scripts/api_v2.py` | Routes |

---

## 9. Cron — overnight / non-trading hours only (2026-07-16)

**Policy:** Research Intelligence *content production* (ingest, synthesize, LLM narrative, archive)
runs **only outside** regular session and premarket. Desk **reads** stay 24/7 via
`GET /api/v2/research-intelligence` (DB + short TTL cache).

| Window | Behavior |
|--------|----------|
| RTH 09:30–16:00 ET | No RI write jobs (gate skips) |
| Premarket 04:00–09:30 | No RI write jobs |
| After close / overnight / weekend | Full RI overnight batch + gated hourly synth |

Install / refresh crontab block:

```bash
bash scripts/install_research_intelligence_overnight_cron.sh
```

Scripts:

- `scripts/non_trading_hours_gate.sh` — skip regular + premarket
- `scripts/run_research_intelligence_overnight.sh` — archive, topic bridge, synth, narrative, ingest
- `market_session.is_research_intelligence_window()` — Python helper

```cron
# Installed by install_research_intelligence_overnight_cron.sh
30 20 * * 1-5  after-close full batch
15  2 * * *    deep overnight full batch
15  5 * * *    archive-only
20  * * * *    hourly topic synth (gated — no-op mid-session)
```

Weekly re-seed retirement topics (idempotent, still fine pre-open early):

```cron
30 4 * * 1 cd /path/to/repo && .venv/bin/python scripts/research_intelligence_retirement_seed.py --apply >> logs/ri_seed.log 2>&1
```
