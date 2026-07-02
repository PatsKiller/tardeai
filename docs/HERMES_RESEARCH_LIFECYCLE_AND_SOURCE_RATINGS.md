# Hermes Research Lifecycle — Topics, LLM Engine, Website Cataloging & Ratings

_Last updated: 2026-06-20_

How an operator research interest becomes **vetted, web-grounded, continuously-refreshed** intelligence —
and how the sites that feed it are **discovered, cataloged, rated, and retired**. Advisory only; never a
trade. Free LLM lanes only (grok :8645 → chatgpt :8646 → local gemma) — never a metered key.

This is the end-to-end of "do **both** (web + LLM), catalog and find new sites, and grade out the garbage so
research stays fresh and relevant."

---

## 1. Topic lifecycle — from Telegram to the research registry

```
Operator (Telegram add-topic)
   │  Maria / OpenClaw
   ▼
watch_directives  (kind='trend', spec.keywords/seed_symbols)   ← TICKER-DISCOVERY pipeline
   │
   ├─►  directive discovery / promotion engine   (tickers → watchlist)
   │
   └─►  topic_monitor  (owner='shared')   ← KNOWLEDGE-RESEARCH pipeline
         via  scripts/sync_research_directives_to_topics.py  (backfill)
         and  the POST /api/v2/watch/directives endpoint mirror (every NEW trend directive
              auto-creates its topic_monitor row — so future Telegram adds route to BOTH).
```

- **Both routes, always.** A trend directive feeds ticker discovery *and* is mirrored into `topic_monitor`
  so it also gets knowledge research. Planning-themed topics (roth/irmaa/medicaid/ssdi/estate/trust/…) are
  tagged with the operator's planning context and assigned to Steph; market topics to Alex.
- `topic_monitor` is the **system-of-record** (no new table). Key columns: `topic_id` (unique),
  `search_queries`, `llm_generated_queries`, `owner` (tradeai|hermes|shared), `priority`, `max_age_days`,
  `min_articles`, `personal_context`, `last_searched`, `last_found_count`, `saved_search_urls`.

### Owner routing (symmetric — both engines)
| owner | Who researches it |
|-------|-------------------|
| `tradeai` | `topic_ingestion.py` (`owner IN ('tradeai','shared')`) |
| `hermes`  | `hermes_topic_monitor_bridge.py` → `hermes_research_intelligence` (`owner IN ('hermes','shared')`) |
| `shared`  | **BOTH** engines (co-owned) |

---

## 2. Research engine — two lanes that DO BOTH (web crawl + LLM)

### Lane A — TradeAI web crawl (find + catalog new sites)
`scripts/topic_ingestion.py` — the discovery engine.
1. LLM reads `personal_situation` + topic context + DB gaps → generates **targeted, non-static** queries.
2. **Search cascade:** YouTube API → Google News RSS → Brave → DuckDuckGo. Each surfaces new publisher
   sites (e.g. `google_news:Stock Titan`, `MarketBeat`, `GuruFocus`, `simplywall.st`).
3. All results downloaded (not capped at 3-6); transcripts fetched.
4. Saved → `news_articles` (topic articles tagged `symbol=topic_id`, `source='topic_<channel>'`).
5. Every search attempt logged to `iris_library_gap_fills`; productive search URLs saved to
   `topic_monitor.saved_search_urls` for reuse.
- **Throughput controls (2026-06-20):** `--max-topics N` lets a run finish inside the 30-min timeout
  (oldest-first, `last_searched ASC NULLS FIRST` → never-searched/newest topics crawled first);
  `--owner` restricts the lane. Crons run **09:00 and 13:00** so 120+ operator-added topics get crawled
  within days instead of weeks.

### Lane B — Hermes knowledge research
`hermes_topic_monitor_bridge.py` (cron 07:30) stages each shared/hermes topic into
`hermes_research_intelligence` (`research_type='topic_research'`). `hermes_coordinator.py` (every 15 min)
promotes (status flips staged → promoted/embedded).

---

## 3. Synthesis — grounded, graded LLM briefings

`scripts/topic_research_synthesizer.py` (cron :20 hourly, `--reground` daily 14:50) turns each staged
placeholder into a real briefing.

- **DOES BOTH:** pulls what the crawler actually found for the topic — articles tagged `symbol=topic_id`,
  else an OR-keyword fallback over recent news — and **grounds the LLM on those real sources**, preferring
  their specifics over model memory.
- **GRADE FILTER:** only grounds on **graded-good** articles — excludes anything the curator marked
  `low_quality`/`blocked`, or that was `demoted`/de-`hygiene`d. Research never cites garbage.
- **Catalogs provenance:** the sites it used are written to `hermes_research_intelligence.evidence_json
  .grounded_on` (`source`, `title`, `url`) + `grounded_count`.
- **Re-grounding:** `--reground` re-runs rows that grounded on 0 articles once the crawler has since
  ingested+graded the topic, so research upgrades from memory-only to source-cited over time.
- Output: `summary` (120-180w), `thesis`, `considerations`, `confidence_score`, `model_used='synth:<lane>'`.
  Idempotent (only touches bridge placeholders / ungrounded rows).

---

## 4. Article grading — filter the garbage

`scripts/topic_curator.py` (standalone crons **09:30 / 13:30 / 18:30**, plus the post-ingestion trigger).
- Auto-approves topic articles with `relevance_score ≥ 0.4`.
- LLM rates the rest **approved / low_quality / blocked** (5-at-a-time, tight prompt).
- `blocked` → `blocked_content` (never re-downloaded) + `news_articles.rag_status='blocked'`.
- Extracts entities → `content_entity_links`; links to holdings/watchlist; triggers RAG re-index.
- **Why a standalone cron:** grading previously only ran on the post-ingestion trigger, so a 1,100+ article
  backlog sat `pending` (ungraded = potential garbage). The cron drains it independently of ingestion.

`rag_status` values: `pending` (not yet rated) → `approved` (RAG-worthy) / `low_quality` / `blocked`.

---

## 5. Website / source lifecycle — cataloging + ratings

`scripts/hermes_source_curation.py` (cron weekly, **23:30 daily** wired) maintains the source registry
`research_sources` (`source_type`, `source_name`, `source_url`, `credibility_score`, `specialty`,
`active`, `notes`). ~97 active / 352 total — the rest are **candidates pending vetting**.

**FULLY AUTONOMOUS — no human ever flips a source active.** Every run re-decides `active`:
- **Track A — quality scoring:** each web domain scored by **yield = (promoted+embedded)/total** of the
  research it produced. **Auto-promote** when `total≥2 AND yield≥30%`; **auto-retire** when
  `total≥5 AND yield==0`. Decayed sources self-demote the next run.
- **Track A½ — OUTCOME yield outranks throughput yield (Phase 3, 2026-07-02):**
  `hermes_outcome_learning.py` (nightly 03:05) computes each domain's **graded outcome yield**
  (share of its research actioned per `hermes_outcome_ledger`, n≥10) and retires below
  `baseline − 1σ` / reinstates at baseline, writing `OUTCOME_LEDGER retired/reinstated` markers to
  `notes`. Track A **cannot re-activate** an outcome-retired domain (throughput yield is
  self-referential — it counts promotion, not whether anything came of it); markers survive the
  nightly note rewrite. First pass retired 8 domains (apnews.com 4%, cnbc.com 8%, … vs 53.5%
  baseline actioned-yield).
- **Track B — new-site discovery + LLM validation:** first-seen / not-yet-proven domains are validated by
  an **LLM (free lane: grok→chatgpt→local)** for credibility+relevance and **auto-activated immediately**
  if approved — no waiting for yield, no human flip. Spam/low-value domains are auto-rejected (verified:
  approves seekingalpha.com & irs.gov, rejects content farms). Verdicts are cached in `notes` so lanes
  aren't re-spent; new validations are capped per run. Lifecycle: **first-seen → LLM-validated (or
  yield-proven) → active → decay → auto-retire**, all hands-off.
- **Connector registry:** every source TYPE (social, youtube, sec, rss, ai-apis, seeking-alpha) is
  registered with an honest live/dormant/needs-key status that drives the UI badge. (Key-gated connectors
  stay dormant until a key exists — the one genuinely non-autonomous bit, by necessity.)
- Related read-models: `source_learning_scores`, `source_performance`, `source_weights`,
  `rec_source_quality`, `data_source_health`.

---

## 6. Continuous freshness — what keeps it fresh & relevant

| Cron | When | Job |
|------|------|-----|
| `topic_ingestion.py --max-topics 14` | 09:00, 13:00 | crawl/find-new-sites for stalest topics first |
| `topic_curator.py` | 09:30, 13:30, 18:30 | grade new-site articles (approved/low_quality/blocked) |
| `hermes_topic_monitor_bridge.py` | 07:30 | stage shared/hermes topics for research |
| `hermes_coordinator.py` | every 15 min | promote staged research |
| `topic_research_synthesizer.py --max 15` | :20 hourly | fill placeholders with grounded+graded briefings |
| `topic_research_synthesizer.py --reground` | 14:50 | upgrade ungrounded rows to source-cited |
| `hermes_source_curation.py` | 23:30 | score domains by yield + discover/catalog new sites |

Staleness levers: `topic_monitor.max_age_days` / `min_articles` drive gap-fill; `last_searched NULLS FIRST`
ordering guarantees new topics are picked up first; `--reground` keeps research synced to fresh crawls.

---

## 7. Surfaces

- **RetirementHub → Planning Research tab** (`/v3/retirement`): research grouped into 6 themes
  (Roth & conversions, Medicare & IRMAA, Medicaid & asset protection, Estate & trusts, SSDI & taxes,
  Income & dividends), each item showing summary, thesis, confidence, status, model, **vetted source
  chips**, and a "N vetted src" provenance count.
- **API:** `GET /api/v2/retirement/planning-research` → themes + items + `sources[]` (cataloged
  `grounded_on`, graded-good only). Read-only, advisory.

---

## Files
- `scripts/topic_ingestion.py` — web crawl / new-site discovery (`--max-topics`, `--owner`)
- `scripts/topic_curator.py` — article grading (approved/low_quality/blocked)
- `scripts/topic_research_synthesizer.py` — grounded+graded LLM synthesis (`--reground`)
- `scripts/hermes_source_curation.py` — source registry scoring + new-site cataloging
- `scripts/sync_research_directives_to_topics.py` — Telegram-directive → topic_monitor backfill
- `scripts/hermes_topic_monitor_bridge.py` — topic → Hermes research staging
- `scripts/api_v2.py::_retirement_planning_research` — themed surface w/ source provenance
- `apps/command-center-v3/src/pages/RetirementHub.tsx` — Planning Research tab

See also: `RESEARCH_TOPIC_REGISTRY_2026_06_04.md`, `HERMES_INTELLIGENCE_ENGINE.md`,
`AGENT_AND_HERMES_WORKFLOWS.md`.
