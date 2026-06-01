# Hermes Phase 28C — Momentum Scout and Catalyst Enrichment Audit

**Date:** 2026-06-01
**Status:** COMPLETE — read-only audit

---

## Momentum Scout Pipeline

| Component | Script | Function |
|-----------|--------|----------|
| Screener runner | finviz_screener_runner.py | Fetches Finviz CSV, dedupes, classifies new symbols |
| Morning digest | morning_digest.py | Pre-market Telegram digest (6:55 AM, 9:25 AM), surfaces building-momentum tickers |
| Run health | screener_run_health.py | Tracks go_count, wait_count, no_go_count per run |
| Incubator | incubator_universe | Symbol lifecycle: ACTIVE → ROLLED_ON → proposal |

### Scout Candidate Storage

| Table | Key Fields |
|-------|-----------|
| screener_run_health | run_id, screener_name, go_count, wait_count, no_go_count, status |
| incubator_universe | symbol, status, score, last_seen, catalyst_flags |
| incubator_events | symbol, event_type, score_delta, roll_off_reason |

### Hermes Visibility

**NOT VISIBLE** — no safe view exists for screener or incubator data.

---

## Catalyst Enrichment Pipeline

| Component | Script | Function |
|-----------|--------|----------|
| Multi-source scraper | catalyst_enrichment.py | Finnhub, NewsAPI, Polygon, FMP, Alpha Vantage, Finviz, Yahoo — 72h lookback |
| LLM analyzer | catalyst_intelligence.py | Ollama-powered, scores 0–15, flags GO/WATCH/TRAP/DILUTION/AVOID |
| News→catalyst | news_to_catalyst.py | Converts news_articles to catalyst_events (15 categories) |
| Quality scorer | proposal_catalyst_quality.py | 0–100 score, grades STRONG/MODERATE/WEAK/NONE/STALE |

### Catalyst Quality Fields

| Field | Type | Values |
|-------|------|--------|
| quality_score | Numeric 0–100 | 80+=Strong, 60+=Moderate, 40+=Weak, 20+=None, <20=Stale |
| grade | Text | STRONG_COMPANY_SPECIFIC, MODERATE_COMPANY_SPECIFIC, WEAK_GENERIC, NO_CATALYST, STALE_CATALYST |
| catalyst_type | Text | earnings_beat, fda_approval, contract_win, sector_sympathy, etc. (15 types) |
| company_specific | Boolean | True if catalyst is company-specific |
| headline_age_hours | Numeric | Freshness since last headline |

### Weak Catalyst Detection

**YES — exists and is active:**
- WEAK_GENERIC grade (score 40–59) detected by proposal_catalyst_quality.py
- catalyst_intelligence.py pre-flags dilution/trap keywords before Ollama analysis
- Score <40 triggers NO_CATALYST or STALE_CATALYST gate, blocking proposal advancement
- recent_news_missing flag in enrichment validation

### News Auto-Attachment

- proposal_enrichment_loop.py checks `recent_headlines` as enrichment gate
- Missing news flags `recent_news_missing` in validation
- Not auto-attached but validated as required field

### Hermes Visibility

- **News: VISIBLE** via hermes_v_news_research_context (4.9K rows)
- **catalyst_events: NOT VISIBLE** — no safe view
- **Catalyst quality scores: NOT VISIBLE** — embedded in proposal enrichment, not exposed
- **Weak catalyst flags: NOT VISIBLE** to Hermes

---

## Research Backlog Opportunities

| Opportunity | Trigger | Owner |
|-------------|---------|-------|
| Weak catalyst at proposal time | grade == WEAK_GENERIC or STALE_CATALYST | Source Discovery Agent |
| Missing news for incubator symbol | recent_news_missing flag | Source Discovery Agent |
| Scout candidate with no catalyst | incubator symbol with empty catalyst_flags | Source Discovery Agent |
| Momentum building but no analyst coverage | morning_digest mentions, no SA/Yahoo source | Source Discovery Agent |
| Catalyst score declining over time | quality_score trend analysis | Hermes Librarian |

---

## Safe Next Steps (Future Phase)

1. Create hermes_v_screener_context (symbol, score, catalyst_flags, status)
2. Create hermes_v_catalyst_quality_context (symbol, grade, quality_score, freshness)
3. Add catalyst-quality-aware Librarian checks
4. Route weak-catalyst findings to Research Backlog
5. SearXNG enrichment for WEAK_GENERIC catalysts (requires pipeline approval)

**No changes made in this phase. Read-only audit only.**
