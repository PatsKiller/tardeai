# SearXNG Phase 19D — Staged Source Visibility Design

**Date:** 2026-05-31
**Status:** DESIGN ONLY — no code changes

---

## Current Visibility

The existing Hermes Intelligence page (`/v2/hermes-intelligence`) already displays all `hermes_research_intelligence` rows including the 5 new `source_discovery` rows. They appear with:
- research_type: "source discovery"
- Status badge: "staged"
- Symbol column: SCHD, TRX, APAM, FJSCX
- Summary truncated in table row
- Full detail in modal (View button)

No additional UI work is strictly needed — the rows are already visible.

---

## Future Enhancement Options

### Option A: Source Discovery Filter Tab

Add a filter option to the Intelligence page: "Source Discovery" alongside "All", "Promoted", "Staged", "Embedded". This would let operators quickly isolate SearXNG-discovered sources.

### Option B: Source Discovery Badge

Add a visual badge or icon indicating `source_discovery` type rows — e.g., a search icon or "External Source" label — to distinguish them from LLM-generated thesis challenges and reflections.

### Option C: Provenance Panel

In the detail modal, show a "Provenance" section with:
- Discovery method (SearXNG manual)
- Discovery engine (startpage, duckduckgo, etc.)
- Original query theme
- Discovery phase
- Advisory-only status

---

## Why No Query Form Should Be Added

1. No autonomous ingestion approved
2. Query form implies "search and save" workflow
3. Current manual CLI wrapper is the approved interface
4. Form-based search would need its own safety audit

---

## No Implementation in This Phase

This is docs-only. No UI code, no API endpoints, no DB writes. Implementation requires separate approval.
