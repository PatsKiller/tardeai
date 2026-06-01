# SearXNG Phase 17D — Command Center Query Visibility Design

**Date:** 2026-05-31
**Status:** DESIGN ONLY — no code changes

---

## Purpose

Design how manual SearXNG query outputs could be surfaced in the Command Center in a future gate. No implementation in this phase.

---

## Proposed Future Visibility

### Option A: Read-Only Query History Panel

A read-only panel on the Hermes Intelligence or System Applications page showing:
- Recent manual query summaries from `data/searxng_queries/`
- Query text, timestamp, result count, engines used
- Link to open full summary markdown
- No inline result display (privacy)

### Option B: Dedicated Search Research Page

A new `/v2/search-research` page with:
- List of past manual queries
- Expandable result previews
- Filter by date/engine
- Safety banner: "File-only output — No DB — No Hermes — No Auto-Ingestion"

---

## Why No Query Form Should Be Added Yet

1. **No ingestion path approved** — displaying a form implies actionability
2. **Query privacy** — queries forwarded to external engines, operator should be aware
3. **Scope creep risk** — adding a form invites "search and ingest" shortcuts
4. **Current wrapper is CLI-only by design** — operator runs it deliberately

A query form should only be added after:
- Source discovery dry-run is approved (Phase 19A+)
- Ingestion path is approved
- Safety audit of form → query → display → ingest pipeline is complete

---

## No-Action / No-Ingestion Rules

If query visibility is ever implemented:
- Display ONLY — no "Ingest" or "Save to DB" buttons
- No "Send to Hermes" action
- No "Create Embedding" action
- No "Promote" action
- No auto-refresh or polling of queries
- Explicit "Advisory Only" labeling

---

## Future Approval Gate

| Prerequisite | What It Enables |
|-------------|----------------|
| Phase 18A approval | Read-only query history panel |
| Phase 19A approval | Search form (manual, no auto-ingest) |
| Phase 20A approval | Search → ingest pipeline |

No implementation without explicit operator approval.
