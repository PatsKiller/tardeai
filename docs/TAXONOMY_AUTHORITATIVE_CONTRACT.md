# Authoritative Taxonomy Contract

Status: **ACCEPTED** — 2026-08-12
Owner: Hermes intelligence pipeline

## Purpose

The Trade AI system had accumulated several overlapping tagging systems that wrote
to different columns with no single owner. This contract declares **one canonical tag
axis** and retires the write-only/dormant experiments so "tagging everything
accordingly" is a real, verifiable property.

## Canonical axes

| Axis | Column | Meaning | Sole writer |
|---|---|---|---|
| `strategy_tags` | `hermes_research_intelligence.strategy_tags`, `news_articles.strategy_tags`, `youtube_transcripts.strategy_tags`, `social_posts.strategy_tags`, `sec_form4.strategy_tags` | What the content is about (theme/strategy), drawn from the `strategy_registry` vocabulary | `scripts/hermes_tag_engine.py` |
| `agent_tags` | same tables, `agent_tags` column | Routing hint: which agent(s) should consume the content | ingestion paths (`news_ingestion.py`, `topic_ingestion.py`) |

### Vocabulary

- `strategy_tags` MUST use slugs from `strategy_registry` (`active = true`). No ad-hoc
  slug families; no non-registry slugs may be written.
- `agent_tags` is a routing layer (Iris delegates into `strategy_tags` vocab) — it must
  not invent a competing theme vocabulary.

## Single-writer rule

- `scripts/hermes_tag_engine.py` is the **single owner** of `strategy_tags`. It runs
  nightly (`5 3 * * *`), re-tagging rows whose `strategy_tags` are null/empty/fallback.
- Ingestion paths may *seed* `strategy_tags`, but any seeded value must pass the
  registry vocabulary check (non-registry slugs are dropped, never persisted).
- `iris_taxonomy_agent.py` is routing-layer only; it reads the same registry and does
  not maintain a second theme vocabulary.

## Retired

| Item | Column / artifact | Disposition |
|---|---|---|
| Librarian content-subject taxonomy | `hermes_research_intelligence.content_tags` | **RETIRED** — never scheduled, zero consumers, write-only. No new writes. Column left in place, no new rows written. |
| `content_subject` axis | `taxonomy_categories` (axis = `content_subject`) | RETIRED — never seeded; no slugs. |
| `scripts/lib/hermes_librarian/taxonomy.py` | `backfill_content_tags`, `retire_tag`, `content_tag_efficacy` | RETIRED — no-op returning `{"status": "retired"}`. `classify_content` kept harmlessly for future reuse but not wired. |
| 3-axis taxonomy tagger | `scripts/taxonomy_tagger.py` | RETIRED (pre-existing) — zero readers. |
| Legacy `tags` array | `hermes_research_intelligence.tags` | DEPRECATED — retained for history; new logic reads `strategy_tags`. |

## Verifiability

The single-writer rule is enforced by tests and a read-only coverage report that
answers, per table: what fraction of rows have non-empty `strategy_tags`, and how many
rows fall back to the generic tag. The target is `< 15%` fallback share (see
`hermes_tag_engine.py` `fallback_share_30d`).
