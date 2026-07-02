# Shared Taxonomy Alignment — Scope

**Status:** Scoping / design (not yet built) · 2026-06-03
**Goal:** One canonical content taxonomy, owned by Iris, referenced consistently across TradeAI and Hermes — so content is categorized the same way end-to-end (ingestion → curation → RAG → agents), and coverage/yield can be reasoned about across both systems on one vocabulary.

---

## 1. Current state (grounded in the live system)

| Concern | TradeAI (Iris) | Hermes | Aligned? |
|---|---|---|---|
| **Owner** | `iris_taxonomy_agent.py` (sole writer of `youtube_channels.category`) | Hermes coordinator/librarian | separate owners |
| **Vocabulary** | 8 content categories: `investment_general, dividend_income, retirement_planning, disability_retirement, macro_economics, tax_strategy, etf_indexing, financial_education` | `research_type` (purpose: momentum_catalyst, youtube_discovery…) + free-form `tags` | different axes |
| **Defined where** | **Hardcoded in code + DB values** — no config file | code | no single source of truth |
| **Topic axis** | `topic_monitor.agent_owner` + `strategy_tags` (Alex/Steph/Maria) — a *third* vocabulary | — | not aligned even within TradeAI |

**Critical gaps found:**
- **No canonical taxonomy table or config** — the category list lives only in `iris_taxonomy_agent.py` and as distinct values in `youtube_channels.category`.
- **`content_embeddings` (the RAG convergence point, ~28k rows) has NO `category` column** — retrieval is by embedding similarity + `source_type` only. The place where both systems' content actually meets is **untagged**.
- **Hermes has the columns to align** (`hermes_research_intelligence.tags/strategy_tags/agent_tags`) but `strategy_tags` is **never populated** (0/252); `tags` is free-form (214/252), not the Iris vocabulary.
- **No cross-propagation:** a channel Iris files under `dividend_income` carries no category into Hermes research or into the embedding it produces.

---

## 2. Target architecture

```
            ┌─────────────────────────────┐
            │  taxonomy_categories (NEW)  │  canonical vocabulary, single source of truth
            │  owned by Iris              │  (also config/taxonomy.yaml)
            └──────────────┬──────────────┘
                           │ referenced by
     ┌─────────────────────┼───────────────────────────┐
     ▼                     ▼                            ▼
 youtube_channels   content_embeddings (NEW         hermes_research_intelligence
 .category          .category col + classify        .strategy_tags / category
 (already)          on write + backfill)            (populate via classifier)
                           ▲
                           │ one shared classifier
                  classify_category(text|symbol) → slug[]   (gemma3, reused by both systems)
```

**Principle:** Iris remains the **taxonomy authority** (proposes + curates the category set); everything else *references* it. One classifier function categorizes content against the live canonical set, called by both the TradeAI ingestion/RAG path and Hermes.

---

## 3. Components to build

1. **Canonical taxonomy** — `taxonomy_categories` table (`slug, label, parent_slug, axis, description, owner_agent, active, created_at`) + `config/taxonomy.yaml` as the editable source of truth. Seed from the 8 Iris categories + sector categories (from Maria's topics: ai_chips, datacenter, defense…) + reconcile with topic_monitor strategy_tags.
2. **Shared classifier** — `taxonomy_classifier.py::classify(text, symbol=None) -> [slug]` (gemma3, against the live category set, confidence-scored). One implementation, imported by both systems.
3. **Tag the convergence points:**
   - `content_embeddings`: add `category` column; classify on write; **backfill ~28k rows** (batch).
   - `hermes_research_intelligence`: populate `strategy_tags`/category on write (columns exist); backfill 252 rows.
   - `youtube_channels.category` already *is* the source vocabulary (no change).
3b. **Iris taxonomy self-learning** — extend `iris_taxonomy_agent` to propose **new categories** (not just channels); `iris_proposal_curator` applies high-confidence category additions → the canonical set self-grows, gated.
4. **Consumption** — category-aware RAG retrieval (filter/boost by category); per-category coverage reporting across both systems in v3 (Pipeline tab + Hermes hub).

---

## 4. Phased plan

| Phase | Work | Risk | Behavior change |
|---|---|---|---|
| **1 — Foundation ✅ BUILT (2026-06-03)** | `taxonomy_categories` table (33 cats, 3 axes) + `config/taxonomy.yaml` + `scripts/taxonomy.py` (`classify()`/`get_categories()`/`seed()`). LLM (gemma3) classify with keyword-heuristic fallback for when the shared GPU is saturated. | Low | none (additive) |
| **2 — Tag the corpus ✅ BUILT (2026-06-03) → ⏸ CRON RETIRED (2026-07-02)** | Added `category_content/sector/lifecycle` to `content_embeddings` + `hermes_research_intelligence` via `scripts/taxonomy_tagger.py`. **Hermes Maturity-5 audit found ZERO readers of the 3-axis columns repo-wide** — the hourly tag-forward cron was pure write cost (plus a churn loop + hourly lock, both fixed: `no_match` sentinel, DDL behind `--ensure-schema`) and is retired (commented in crontab; script kept). Strategy-dimension tagging moved to `scripts/hermes_tag_engine.py` (registry vocabulary, outcome-graded — see `docs/design/HERMES_MATURITY_5_DESIGN.md` Phase 4). Phases 3–4 below should revisit taxonomy only WITH a consumer. | Medium | tag writes stopped; reads were never wired |
| **3 — Close the loop** | Iris proposes new categories; curator applies; Hermes classifies against live set; per-category coverage in v3 | Medium | taxonomy self-grows |
| **4 — Consumption** | Category-aware RAG retrieval + cross-system coverage dashboard | Medium | retrieval quality + new views |

Phase 1 is a safe, standalone foundation. Phases 2–4 are independently shippable.

---

## 5. Key decisions — DECIDED (2026-06-03)

1. **Axes: ALL THREE** — `content` (primary), `sector`, `lifecycle`. The classifier returns one slug per axis where applicable.
2. **Backfill: tag-forward + partial** — classify all new content on write; backfill the newest/most-retrieved subset (not the full 28k).
3. **Authority: fully autonomous** — `iris_proposal_curator` decides all category add/merge/rename on confidence thresholds; no per-category operator gate.

---

## 6. Effort estimate
- Phase 1: small (1 session) — table, config, classifier, seed.
- Phase 2: medium — schema + backfill job + classifier accuracy validation (LLM cost on 28k).
- Phase 3–4: medium each.

Total: a multi-session build; Phase 1 delivers the shared foundation with zero behavior risk and immediately lets new content be tagged consistently.
