# Article Quality Rating Framework + LLM Enhancement Stages — 2026-06-04

Status:      HISTORICAL
as_of:       2026-06-21T13:36:53-04:00
Measured at: efcc51365 / not measured

Defines (A) the single article-quality rating framework both TradeAI and Hermes now use, and
(B) precisely where/when LLM enhancement is applied in each system, with the target split.

---

## A. Article quality rating — ONE framework (aligned 2026-06-04)

**Canonical scorer: `content_scoring.score_content(title, text, source, channel, symbols)`** →
```
relevance_score : 0.0–1.0   (keyword tiers high/med/low + symbol mention + capped)
quality_score   : 0–100     (SOURCE_QUALITY reputation − penalties: short text, clickbait)
validation_status: ai_validated (q≥60 & rel≥0.3) | low_confidence (q<30 | rel<0.1) | unscored
```

**Applied at ingestion for BOTH engines (the alignment):**
| Entry point | Engine | Scoring | Status |
|-------------|--------|---------|--------|
| `news_ingestion.py` | TradeAI | `content_scoring.score_content` → `relevance_score` | already used |
| `hermes_news_bridge.py` | Hermes→`news_articles` | **now** calls `content_scoring.score_content` (2026-06-04 fix); `relevance_score` from it; `quality_score`/`validation_status` in `raw_payload`; Hermes's own confidence kept as `raw_payload.hermes_confidence` (provenance, not the rating) | **fixed** |

**The divergence that existed (and is now closed):** before today, Hermes-bridged articles used
the Hermes LLM `confidence_score` *as* `relevance_score` — a different scale/criteria than
TradeAI's keyword+source framework. Now every row in `news_articles`, regardless of source, is
ranked by the *same* `content_scoring` framework. (Verified: a freshly-bridged Hermes article got
`relevance 0.13` from content_scoring with `quality 10` / `low_confidence`, replacing the old
confidence-as-relevance 0.7.)

**Two distinct "confidence/quality" objects — don't conflate:**
- `news_articles` quality = **article ingestion quality** (content_scoring) — the shared framework above.
- `hermes_research_intelligence.confidence_score` (0–1) = Hermes's rating of **its own generated
  research/thesis** (LLM-set, evidence-gated >0.85 needs ≥3 refs). Different object, not an article
  score. (Its `quality_score` 0–100 column is currently unused/defaults 0.30 — a separate cleanup.)

---

## B. LLM enhancement — where/when, per system, + target split

**Principle (operator directive):** *most LLM enhancement should be Hermes's job; TradeAI already
leverages external paid resources (Finnhub/NewsAPI/Polygon/FMP/Finviz) + deterministic scoring.*

### Current state — TradeAI LLM stages
| Stage | LLM? | Model | When |
|-------|------|-------|------|
| `content_scoring` (article quality) | NO — keyword/source | — | every article on ingest |
| `topic_ingestion` curation (RAG approve/block + summary) | **YES** | local LLM (gemma3) | per item, real-time on ingest |
| `deep_overnight_llm_queue` → `rag_content_curation` (deep re-curation of pending/low_quality content) | **YES** | gemma (deep) | overnight batch; P1, priority_score 65–75; ≤20 items/night; dequeued `priority_score DESC, queued_at ASC`. Second pass over what real-time topic_ingestion left pending/low. |
| `llm_intelligence_enrichment` (portfolio risk/rebalance/brief) | **YES** | qwen3:14b | daily cron 07:20 |
| `proposal_intelligence_analyzer` | **YES** | local LLM | on pending proposals |
| `catalyst_enrichment`, `research_insight_extractor`, `sentiment_processor` | NO — keyword/lexicon | — | batch |

### Current state — Hermes LLM stages
| Stage | LLM? | Model | When |
|-------|------|-------|------|
| `hermes_autonomous_loop` (research generation: thesis/evidence/confidence) | **YES** | gemma3:4b | coordinator `*/15` |
| embedding worker (RAG vectors) | embed | nomic-embed | per tick |
| librarian backlog, auto-promote | NO — deterministic | — | per tick |

### The split — current vs target
- **Current:** TradeAI runs MORE LLM stages (3: topic curation, intelligence enrichment, proposal
  analysis) than Hermes (1: research generation). That's the inverse of the directive.
- **Target:** Hermes = the primary LLM **reasoning/enhancement** engine (research generation,
  curation judgment, thesis synthesis). TradeAI = external-data acquisition + **deterministic**
  scoring (content_scoring keyword/source, catalyst keyword, sentiment lexicon) + execution; it
  should keep LLM use minimal and trade-decision-proximate (e.g. proposal analysis can stay, as
  it's execution-time).
- **Gap / candidate moves (operator decision — not auto-applied):**
  1. **All TradeAI content-curation LLM → Hermes.** Two stages, same class, both candidates to move:
     - **`topic_ingestion` per-item curation** (real-time approve/block + summary) — the heaviest.
     - **`deep_overnight_llm_queue` `rag_content_curation`** (overnight deep re-curation of
       pending/low_quality, ≤20/night, P1 65–75).
     Both are LLM *judgment over ingested content* — exactly what Hermes is meant to own. Target:
     TradeAI keeps deterministic `content_scoring` as the first-pass filter; **Hermes performs the
     LLM curation/re-curation pass** (real-time and overnight). This consolidates content-reasoning
     in Hermes and leaves TradeAI on external-data acquisition + deterministic scoring + execution.
  2. **`llm_intelligence_enrichment`** (portfolio narratives) — judgment call: keep in TradeAI
     (portfolio-proximate) or hand the synthesis to Hermes. Recommend keep for now (it reads
     live portfolio state TradeAI owns).
  3. Hermes's `topic_research` rows (from `hermes_topic_monitor_bridge`) are the channel by which
     Hermes-owned topics get LLM enhancement — already wired.

**Net definition:** *LLM enhancement is applied — TradeAI: at topic-curation, daily intelligence
enrichment, and proposal analysis; Hermes: at research generation (and, once #1 above is moved,
at topic curation). The target is to shift the bulk of curation/reasoning enhancement to Hermes
and keep TradeAI on external-data + deterministic scoring.*

---

## C. Intelligence Command Center signal-quality (UI, 2026-06-21)

Separate from article-quality (§A): the **Intelligence → Command Center** page scores each consolidated
*signal* (risk/stop, command, open-trade, setup, news, research, external-LM…) for trust/actionability.
Computed in `apps/command-center-v3/src/components/CentralIntelligencePages.tsx` (`qscore`/`estError`).

**The bug (fixed 2026-06-21):** every risk/stop/command/open-trade card showed an identical
`quality 39% / est error 61%`. Root cause: those signals were added with no per-signal confidence (flat
0.65 fallback) and no timestamp, so `qscore = 0.65 − 0.18 (missing timestamp) − 0.08 (no LM review) = 0.39`
for every one — with uniform boilerplate reasons.

**The fix (two parts):**
1. **Type-aware `qscore`.** Structural signals (`risk | telegram/action | open-trade | setup`) are FACTS —
   graded on data completeness + signal clarity, NOT penalized for news-freshness or "not LM-reviewed."
   Opinion/research signals keep the freshness/source/LM penalties (so external-LM reports still spread by
   staleness, e.g. 42% @>72h → 70% fresh).
2. **Real per-signal confidence.** Stop signals scale with **distance past the stop** (deep breach = clearer,
   higher-quality alert); open-trade scales with risk-flag count + operator priority. The `/api/v2/command`
   feed omits current price, so command stops **cross-reference price from `/api/v2/risk`**; command items
   that duplicate a triggered risk item are **deduped** (no-noise).
3. **De-dup the external-LM report series.** The `external-lm-report` cards arrive as a daily series
   (`REPORT:aegis_morning_brief_<date>`) repeating the same advice with a newer date — 5+ stale copies at
   42% flooding the board. Group by subject (key with the trailing date stripped) and keep only the
   **freshest entry per subject** (8 → 1).

**Result (verified on the rendered page):** quality spans **32–96%** (no uniform 39%); the 8 defense stops
show once each, ranked by breach — LDOS/NOC/LMT (deep) ≈96%, KBR/CACI (~2% past) ≈66%; the external-LM
morning-brief series collapses 8 → 1 (the current report). Total intelligence dropped ~151 → ~70 by
removing duplicates. Commits `f70342ed` + `1cad708c` + `311fced2`.

---

## Status
- **A (rating alignment): DONE** — `content_scoring` now applied to Hermes-bridged articles; both
  engines rank article quality on the same framework. Verified.
- **B (LLM stages): DEFINED** — current stages mapped per system; target split documented. The
  concrete *moves* (esp. topic-curation → Hermes) are flagged as operator decisions, not yet applied
  (each is a behavior change).

---
*Grounded in live code 2026-06-04. Rating alignment applied to `hermes_news_bridge.py`; LLM-stage
moves are documented recommendations pending operator approval.*
