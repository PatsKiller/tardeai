# Hermes Phase 37A — Current Hermes-to-Trade AI Context Path Map

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Current Context Paths

### 1. hermes_research_intelligence → Dashboard (Immediate)

| Path | Latency | Mechanism |
|------|---------|-----------|
| Hermes Intelligence page | **Immediate** (on page load) | API reads DB directly |
| Research Backlog card | **Immediate** (on page load) | API reads DB directly |
| Hermes Chat sidebar | **Immediate** | API reads DB directly |

Dashboard reads are real-time — no cron delay.

### 2. hermes_research_intelligence → RAG (Requires Embedding)

| Path | Latency | Mechanism |
|------|---------|-----------|
| content_embeddings | **Manual only** | Operator runs embedding worker |
| RAG retrieval | After embedding | cosine similarity search |

Embedding is not automated for new Hermes rows. Latency = until operator runs Phase 31-style pilot.

### 3. llm_intelligence_cache → LLM Context Builder (Immediate Read)

| Path | Latency | Mechanism |
|------|---------|-----------|
| Trade AI LLM context | **Immediate on next LLM call** | LLM context builder reads cache per-request |
| Promoted sections | Available once promoted | Manual promotion (Phase 15 style) |

Once a row is promoted to llm_intelligence_cache, any Trade AI LLM call that reads that section sees it immediately.

### 4. Hermes → Cron/Pipeline Refresh (Polling)

| Path | Latency | Mechanism |
|------|---------|-----------|
| No cron reads Hermes | N/A | Trade AI cron jobs do not poll hermes_* tables |
| No pipeline ingests Hermes | N/A | No automated pipeline pulls from Hermes staging |

**Hermes research does not flow into Trade AI pipelines automatically.** This is by design (safety), but it means new Hermes intelligence is invisible to automated Trade AI workflows until manually promoted.

---

## Summary: What Sees Hermes Today?

| Consumer | Sees Hermes? | Latency | Notes |
|----------|-------------|---------|-------|
| Dashboard (Intelligence, Backlog) | YES | Immediate | API reads DB |
| Hermes Chat | YES | Immediate | Shows staged rows |
| LLM context builder (promoted cache) | YES | Immediate after promotion | Manual promotion required |
| RAG retrieval | PARTIAL | After embedding | Manual embedding required |
| Trade AI automated pipelines | **NO** | N/A | No pipeline reads hermes_* |
| Trade AI cron jobs | **NO** | N/A | 187 crons, none read Hermes |
| Proposal enrichment | **NO** | N/A | Does not use Hermes intel |
| Morning brief generator | **NO** | N/A | Does not read Hermes |

## How Long Until Trade AI Reflects a New Hermes Row?

| Destination | Current Latency |
|-------------|----------------|
| Dashboard | 0 sec (on refresh) |
| LLM advisory cache | Manual (hours to days) |
| RAG | Manual (hours to days) |
| Automated pipelines | **Never** (not connected) |

## What Is Polling-Based?

Nothing polls Hermes today. All Hermes context paths are either:
- Immediate (API reads DB on request)
- Manual (operator runs embedding/promotion)
- Disconnected (pipelines don't read Hermes)

## The Gap

New Hermes research that could improve proposal quality, catalyst enrichment, or morning briefs sits in staging until manually promoted. There is no low-latency notification path from Hermes staging to Trade AI context refresh.
