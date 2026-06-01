# Hermes Agent Contracts and Permissions Registry

**Date:** 2026-05-31
**Status:** AUTHORITATIVE — governance document

---

## 1. Chief Hermes Coordinator

| Field | Value |
|-------|-------|
| Mission | Orchestrate daily/weekly Hermes agent plan, enforce caps, route tasks |
| Inputs | Kill switch status, agent health, row counts, model caps, operator directives |
| Outputs | Agent run plan, cap enforcement log, workflow decisions |
| Allowed reads | All hermes_* tables, Trade AI safe views, SearXNG health |
| Allowed writes | hermes_memory_events (coordination logs only) |
| Forbidden | Trade, promote, embed, mutate proposals/trades/journal/holdings, access broker |
| Run mode | Manual / future scheduled (requires approval) |
| Max caps | 1 plan per day, defers to operator on ambiguity |
| Handoff targets | Source Discovery, Librarian, Backlog Manager, Promotion Review |
| Rollback | Delete coordination log entries |
| Dashboard | Future: coordinator status panel |
| Activation phase | NOT YET — design only |

---

## 2. Source Discovery Agent

| Field | Value |
|-------|-------|
| Mission | Discover external sources via SearXNG for portfolio symbols and themes |
| Inputs | SearXNG search results, portfolio holdings, watchlists, research gaps |
| Outputs | Source candidate files, staged hermes_research_intelligence rows |
| Allowed reads | SearXNG (localhost only), hermes_research_intelligence, Trade AI safe views |
| Allowed writes | hermes_research_intelligence (research_type='source_discovery', staged only) |
| Forbidden | Embed, promote, mutate proposals/trades/journal/holdings, access broker, public SearXNG |
| Run mode | Manual CLI (`scripts/searxng_manual_query.py`) |
| Max caps | 5 queries/batch, 25 candidates/batch, 5 staged rows/batch |
| Handoff targets | Hermes Librarian Agent |
| Rollback | `DELETE FROM hermes_research_intelligence WHERE research_type='source_discovery'` |
| Dashboard | Visible on Hermes Intelligence page (existing) |
| Activation phase | **OPERATIONAL** (Phase 17–19) |

---

## 3. Hermes Librarian Agent

| Field | Value |
|-------|-------|
| Mission | Deduplicate, classify, curate, and manage research taxonomy |
| Inputs | All hermes_research_intelligence rows, source_urls_json, evidence_json |
| Outputs | Curation decisions: stage/embed/promote/reject/archive recommendations |
| Allowed reads | hermes_research_intelligence, hermes_validation_findings, content_embeddings metadata, llm_intelligence_cache sections |
| Allowed writes | hermes_research_intelligence (status updates: reviewed/rejected/archived only) |
| Forbidden | Embed directly, promote directly, mutate proposals/trades/journal/holdings, access broker |
| Run mode | Manual / future scheduled (requires approval) |
| Max caps | 20 reviews per batch |
| Handoff targets | Embedding Curator (embed candidates), Promotion Review (promote candidates), Research Backlog Manager (weak/stale findings) |
| Rollback | Revert status changes |
| Dashboard | Future: curation dashboard |
| Activation phase | NOT YET — design only |

---

## 4. Research Backlog Manager

| Field | Value |
|-------|-------|
| Mission | Manage structured research tasks from vague/stale/weak findings |
| Inputs | Vague Telegram messages, weak intelligence, stale theses, pipeline quality findings, operator requests |
| Outputs | Structured research backlog items with priority, owner, and status |
| Allowed reads | hermes_research_intelligence, hermes_validation_findings, hermes_alerts, alert_events, notification_log |
| Allowed writes | Future: hermes_research_backlog table (NOT YET CREATED) |
| Forbidden | Embed, promote, mutate proposals/trades/journal/holdings, access broker, send messages |
| Run mode | Manual / future scheduled (requires approval) |
| Max caps | 10 backlog items per batch |
| Handoff targets | Source Discovery Agent, Hermes Librarian Agent |
| Rollback | Delete backlog items |
| Dashboard | Future: backlog dashboard |
| Activation phase | NOT YET — design only |

**Backlog item statuses:**
- `candidate` → `needs_research` → `searched` → `staged` → `librarian_reviewed` → `embedding_candidate` → `promoted_advisory` / `rejected` / `archived`

---

## 5. Promotion Review Agent

| Field | Value |
|-------|-------|
| Mission | Review staged/promoted intelligence and recommend future promotions |
| Inputs | hermes_research_intelligence (staged), promotion history, quality scores |
| Outputs | Promotion candidates list, duplicate detection, confidence assessment |
| Allowed reads | hermes_research_intelligence, hermes_promotion_audit, llm_intelligence_cache |
| Allowed writes | NONE (advisory output only) |
| Forbidden | Promote directly, embed, mutate proposals/trades/journal/holdings, access broker |
| Run mode | Manual dry-run |
| Max caps | Review all staged rows (current: 6) |
| Handoff targets | Operator (approval required for actual promotion) |
| Rollback | N/A (read-only) |
| Dashboard | Promotion Review section on Hermes Intelligence page |
| Activation phase | **OPERATIONAL** (Phase 13–14) |

---

## 6. Embedding Curator Agent

| Field | Value |
|-------|-------|
| Mission | Select records for embedding pilots, prevent RAG pollution |
| Inputs | hermes_research_intelligence (staged/promoted), existing embeddings |
| Outputs | Embedding candidate recommendations |
| Allowed reads | hermes_research_intelligence, hermes_embedding_queue, content_embeddings metadata |
| Allowed writes | hermes_embedding_queue (candidates only, requires --apply) |
| Forbidden | Embed directly without phase approval, promote, mutate proposals/trades/journal/holdings, access broker |
| Run mode | Manual / phase-gated |
| Max caps | 2 embeddings per pilot batch |
| Handoff targets | Embedding Worker (scripts/hermes_embedding_worker.py) |
| Rollback | Delete from hermes_embedding_queue + content_embeddings |
| Dashboard | Embedded badge on Intelligence page |
| Activation phase | NOT YET — requires separate Phase 21+ approval |

---

## 7. Autonomous Research Manager

| Field | Value |
|-------|-------|
| Mission | Schedule autonomous source discovery and research tasks |
| Inputs | Research backlog, coordinator plan, kill switch |
| Outputs | Staged research rows (when approved) |
| Allowed reads | hermes_research_intelligence, SearXNG, Trade AI safe views |
| Allowed writes | hermes_research_intelligence (staged only, when approved) |
| Forbidden | Embed, promote, mutate proposals/trades/journal/holdings, access broker |
| Run mode | **DISABLED — NOT APPROVED** |
| Max caps | 2 rows per run (when approved) |
| Handoff targets | Hermes Librarian Agent |
| Rollback | Delete staged rows by run_id |
| Dashboard | Kill switch status on Hermes Chat page |
| Activation phase | **NOT APPROVED — future gate required** |
