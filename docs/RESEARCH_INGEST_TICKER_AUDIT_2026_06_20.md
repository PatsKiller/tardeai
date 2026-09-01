# Research Ingestion + Ticker Extraction + Connector Audit — 2026-06-20

Status:      HISTORICAL
as_of:       2026-06-20T22:34:50-04:00
Measured at: efcc51365 / not measured

Audit of **how new articles are written**, **how new tickers are extracted from research**, and a **test of
the API/RSS connectors**. Validated against the live DB. Advisory pipeline; free LLM lanes only.

---

## 1. How a new article is written  ✅ VALIDATED (live)

Path: `topic_ingestion.py::_save_article()` (topic crawl) and `news_ingestion.py` (RSS feeds).

```
search cascade (YouTube / Google News RSS / Brave / DuckDuckGo)  OR  RSS feed pull
      │  per item: {title, url, source, published, description}
      ▼
DEDUP   SELECT 1 FROM news_articles WHERE source_url = %s   → skip if exists
      ▼
SCORE   score_content(title, summary, source) → relevance_score (0..1)
TAG     tag_content(summary, title) → strategy_tags[] + agent_tags[]  (merged w/ topic config)
      ▼
INSERT INTO news_articles
   symbol        = topic_id        (topic articles tagged by topic, e.g. 'd105_glp_1…')
   strategy_type = topic_id
   source        = 'topic_<channel>'  (topic_google_news_rss / topic_duckduckgo / …)
                   or 'yahoo_rss' / 'benzinga_rss' (RSS path)
   relevance_score, strategy_tags, agent_tags
   rag_status    = 'pending'        (DEFAULT — ungraded until the curator rates it)
      ▼
GRADE   topic_curator.rate_pending_content → approved / low_quality / blocked
        (auto-approve relevance ≥ 0.4; else LLM; blocked → blocked_content)
```

**Validation (live, 7 days):** `yahoo_rss` 3,562 · `topic_google_news_rss` 388 · `benzinga_rss` 73 — new
articles are being written and deduped continuously. Grading: 163 approved / 23 blocked on the last curator
run. **Write path is healthy.**

Key facts:
- **Dedup key = `source_url`** (exact). Same story from two publishers = two rows (different URLs).
- New rows are **`rag_status='pending'`** until graded — research grounding ignores ungraded-as-garbage
  only for `low_quality`/`blocked`; `pending` is still groundable (see lifecycle doc §3).

---

> **UPDATE 2026-06-20 — both gaps now WIRED + validated (see §2a).**

## 2. How new tickers are extracted from research  ⚠️ VALIDATED — works, but currently yields 0 tickers

Path: `topic_curator.py::extract_and_link_entities()` (STEP 2, runs by default, not gated).

```
articles without entity links (ALL sources, limit 100)
      │  LLM (free lane): "extract tickers / topics / sectors"
      ▼
content_entity_links  (entity_type ∈ ticker|topic|sector, extracted_by='llm_curator')
   ticker validation: upper(), strip(), len ≤ 6   ← shape-only (NOT checked vs real symbol universe)
      ▼
[a] topic_curation_feedback.tickers_extracted   (learning loop → better queries)
[b] agent_event_queue  event_type='TOPIC_INTELLIGENCE'  → notifies tagged agents "use RAG"
```

**Validation finding (live):** `content_entity_links` = **54 topic + 31 sector links, 0 ticker links.**
- Mechanically the extractor runs (topic/sector links exist), but **0 tickers** because the only topics
  crawled so far were planning-themed (SSDI / Medicaid / dividends) which legitimately contain no tickers,
  and the prompt explicitly allows "if no tickers, use topics/sectors."
- **Two real gaps:**
  1. **No symbol validation** — extracted tickers are accepted on shape (`len ≤ 6`) only; "CEO"/"AI"/"USA"
     would pass. Needs a check against `symbol_profiles` before linking.
  2. **No promotion to the watch universe** — extracted tickers only notify agents (`agent_event_queue`)
     and feed the query-learning loop. A ticker discovered in research does **not** become a watchlist /
     discovery candidate. "New tickers from research" surface to agents via RAG, but do not enter the
     tradeable watch universe automatically. (By design today — flagged for a decision, not auto-wired,
     because auto-adding LLM-extracted tickers to a trading surface is risky.)

→ Will be confirmed once market topics (semiconductors / GLP-1 / etc.) are crawled (currently only 3 of
127 topics crawled; the 09:00/13:00 backfill is working through them newest-first).

## 2a. WIRED (2026-06-20) — symbol validation + discovery promotion + free OAuth lanes  ✅ LIVE

`extract_and_link_entities` now:
- **Validates every extracted ticker** against a broad real-symbol universe (`watchlist_symbol_master ∪
  ticker_snapshot_daily ∪ symbol_profiles` ≈ 5k US symbols) before linking. Non-symbols ("CEO"/"AI"/
  "CEOX") are dropped. Verified live: 18 ticker links created, all real (AAPL/NVDA/TSLA/HOOD/INTC/MPC/GEV/
  ANDE/BCHT/AIBZ), zero garbage; fake `CEOX` correctly rejected.
- **Promotes** each validated, not-already-watched ticker into the watch universe as a **PENDING discovery
  candidate**: `watchlist_items` `origin_system='topic_research'`, `status='researched'` (**never `active`
  → never auto-trades**), `bucket='research_discovery'`, `source_tier='candidate'`, `in_directive_watch=
  false`, full provenance. Idempotent; never disturbs an existing/held watch entry. Verified live: ABNB
  promoted then guarded on re-run (no dup).
- **Uses the FREE OAuth lanes** (`_free_lane_gen`: grok :8645 → chatgpt :8646 → local gemma) instead of
  local-only — same lanes the synthesizer/reground use.

Operator reviews these candidates on the watchlist (origin = `topic_research`, bucket `research_discovery`)
and manually promotes any worth trading. Nothing auto-trades from this path.

---

## 3. Connector / API / RSS test  ✅ TESTED — registry corrected for honesty

| Connector | Registry said (before) | Tested reality | Action |
|-----------|------------------------|----------------|--------|
| RSS feeds | `active=False`, "connector ready (hermes_rss_ingest.py)" | **LIVE** — yahoo_rss 3,562/7d + benzinga + google_news RSS; **`hermes_rss_ingest.py` does not exist** (vaporware), but RSS flows via `news_ingestion.py` + `topic_ingestion` | registry → `active=True`, note corrected |
| xAI (Grok) | `active=False`, "needs XAI_API_KEY" | **LIVE** — free xAI-OAuth proxy `:8645` → HTTP 200; already used by synthesizer + source-validator | registry → `active=True` (free proxy) |
| OpenAI (ChatGPT) | `active=False`, "needs OPENAI_API_KEY" | **LIVE** — free codex proxy `:8646` → HTTP 200 | registry → `active=True` (free proxy) |
| Anthropic (Claude) | `active=False`, "needs ANTHROPIC_API_KEY" | arbitration only, no free lane | unchanged (honest dormant) |
| Seeking Alpha | `active=False`, "needs SEEKING_ALPHA_API_KEY" | dormant (official API key only; cookies not used) | unchanged |
| social / youtube / sec | `active=True` | live ingestion paths | unchanged |

**Fix applied** to `hermes_source_curation.py::CONNECTOR_TYPES` so the registry (and the UI badge it drives)
tells the truth: RSS + Grok + ChatGPT are LIVE.

---

## Recommendations
1. ~~Validate extracted tickers~~ — **DONE** (§2a, validated vs ~5k-symbol universe).
2. ~~Promote research-discovered tickers to discovery~~ — **DONE** (§2a, PENDING candidates, never auto-trade).
3. ~~Remove the dead `hermes_rss_ingest.py` reference~~ — **DONE** (registry corrected).
4. ~~Grading (`rate_pending_content`) on local gemma~~ — **DONE** — switched to free OAuth lanes
   (`_free_lane_gen` grok→chatgpt→local). Article + transcript rating now use the free lanes; local is the
   built-in fallback. Verified live: 10/10 rated via grok. (Query-improvement step `improve_queries` still
   local — low priority, not grading.)

## Files
- `scripts/topic_ingestion.py::_save_article` — article write + dedup + score
- `scripts/news_ingestion.py` — RSS feed ingestion (yahoo/benzinga)
- `scripts/topic_curator.py::extract_and_link_entities` — ticker/topic/sector extraction
- `scripts/hermes_source_curation.py::CONNECTOR_TYPES` — connector registry (corrected)

See also `HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`.
