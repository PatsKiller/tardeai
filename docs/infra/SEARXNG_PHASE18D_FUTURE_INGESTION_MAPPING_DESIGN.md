# SearXNG Phase 18D — Future Ingestion Mapping Design

**Date:** 2026-05-31
**Status:** DESIGN ONLY — no code changes, no DB writes

---

## Purpose

Map source-discovery candidates to future Hermes staging fields. Define how a Phase 19 capped ingestion would work without implementing it.

---

## Target Table

Primary option: `hermes_research_intelligence` (existing staging table)

| Discovery Field | Maps To | Notes |
|----------------|---------|-------|
| title | `topic` | Source article title |
| url | `source_urls_json` | Array with single URL |
| snippet | `summary` | Sanitized snippet as summary seed |
| engine | `context_type_used` | e.g. "searxng_google" |
| quality_score | `confidence_score` | Normalized to 0–1 scale |
| source_query | `tags` | Discovery query as tag |
| — | `hermes_agent_name` | "source_discovery_agent" |
| — | `research_type` | "source_discovery" |
| — | `source` | "hermes" (enforced by CHECK) |
| — | `model_used` | "searxng_manual" (no LLM used) |
| — | `status` | "staged" (always) |
| — | `symbol` | Extracted from query or NULL |

## Alternative: Dedicated Table

If source discovery becomes a high-volume workflow, a future `hermes_source_discovery_candidates` table could be created with:
- source_url (unique constraint)
- discovery_query
- quality_score
- discovery_date
- reviewed_by
- reviewed_at
- ingestion_status (discovered / reviewed / ingested / rejected)
- ingestion_target_id (FK to hermes_research_intelligence if ingested)

This would require a separate migration approval (Phase 20+).

---

## Source Provenance

Each ingested source must include:
- `source_urls_json`: Original URL
- `context_type_used`: "searxng_<engine>" format
- `tags`: Discovery query string
- `freshness_date`: Discovery date (not article date)
- Metadata JSON: `{"discovery_method": "searxng_manual", "quality_score": N, "engines": [...]}`

---

## Rejection Criteria

A source should be rejected if:
- Score < 3.0
- URL is paywalled or login-required
- Content is social media opinion only
- URL already exists in hermes_research_intelligence.source_urls_json
- Content duplicates an existing Trade AI pipeline source
- Content is older than 180 days
- Content contains PII or credentials

---

## Duplicate Detection

Before staging, check:
1. `SELECT COUNT(*) FROM hermes_research_intelligence WHERE source_urls_json::text LIKE '%<url>%'`
2. `SELECT COUNT(*) FROM news_articles WHERE url = '<url>'`
3. If either returns > 0, skip (duplicate)

---

## Rollback

```sql
-- Remove all source_discovery staged rows
DELETE FROM hermes_research_intelligence
WHERE research_type = 'source_discovery'
  AND status = 'staged';
```

---

## Operator Approval Workflow

1. Run source discovery dry-run (Phase 18B pattern)
2. Review `future_ingestion_candidates.json`
3. Approve specific candidates by URL
4. Run ingestion script with `--apply --urls <url1> <url2>` (max 5)
5. Verify staged rows
6. Separately approve embeddings (Phase 20+)
7. Separately approve promotion (Phase 21+)

---

## Not Implemented

This is a design document only. No code, no DB changes, no ingestion path exists yet. Phase 19 approval required before any implementation.
