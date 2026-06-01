# Hermes Agent Operating Model

**Date:** 2026-05-31
**Status:** AUTHORITATIVE — governance document

---

## Purpose

This document defines the agent operating model for Hermes, Trade AI's advisory research desk, second brain, memory layer, and independent challenger sidecar. It establishes ownership boundaries, source-of-truth rules, and non-negotiable safety constraints.

---

## Source-of-Truth Hierarchy

| Layer | Role | Authority |
|-------|------|-----------|
| **Trade AI Database** | System of record | All execution, portfolio, broker, trade, journal, proposal state |
| **Hermes Staging** | Curated advisory memory | Research intelligence, validation findings, source discovery |
| **Hermes Promoted** | Advisory cache | Promoted advisory intelligence in llm_intelligence_cache |
| **SearXNG** | Shared discovery/search layer | External source discovery, NOT source of truth |
| **RAG / Embeddings** | Retrieval layer | Augments LLM context, does not decide |
| **Dashboard** | Visibility layer | Read-only presentation, no mutation authority |

**SearXNG is discovery/search, not source of truth.** It finds external sources. The Hermes Librarian Agent decides whether those sources are worth staging.

**Trade AI DB is the system of record.** No Hermes agent may contradict or override Trade AI execution state.

**Hermes Librarian owns research curation.** All source candidates pass through the Librarian before staging, embedding, or promotion.

---

## Agent Registry

| # | Agent | Status | Run Mode |
|---|-------|--------|----------|
| 1 | Chief Hermes Coordinator | DESIGNED | Manual/future scheduled |
| 2 | Source Discovery Agent | OPERATIONAL (manual) | Manual CLI |
| 3 | Hermes Librarian Agent | DESIGNED | Manual/future scheduled |
| 4 | Research Backlog Manager | DESIGNED | Manual/future scheduled |
| 5 | Promotion Review Agent | OPERATIONAL (dry-run) | Manual/Phase 13+ |
| 6 | Embedding Curator Agent | DESIGNED | Manual/future pilot |
| 7 | Autonomous Research Manager | DESIGNED (DISABLED) | NOT APPROVED |

---

## Ownership Boundaries

### Chief Hermes Coordinator
- Orchestrates daily/weekly agent plan
- Enforces caps (rows, models, queries)
- Checks kill switch before any agent runs
- Chooses manual/dry-run/staged-only workflows
- Decides which agent should act next
- **Never trades. Never auto-promotes.**

### Source Discovery Agent
- Uses SearXNG and manual source queues
- Produces source candidates (file or staging)
- No ingestion without operator approval
- Caps: 5 queries/batch, 25 candidates/batch

### Hermes Librarian Agent
- Deduplicates, classifies, curates
- Manages research taxonomy
- Evaluates freshness, detects stale/weak intelligence
- Decides canonical source candidates
- Recommends stage/embed/promote/reject/archive
- **Does not embed or promote directly**

### Research Backlog Manager
- Receives vague, stale, weak, or missing-evidence findings
- Creates structured research tasks
- Prioritizes by portfolio impact, income gap, risk, stale age, evidence quality, operator urgency
- Prevents duplicate research tasks
- Assigns task owner (Source Discovery, Librarian, Promotion Review, Embedding Curator)

### Promotion Review Agent
- Reviews staged/promoted intelligence
- Recommends future promotion
- **Never promotes directly**

### Embedding Curator Agent
- Selects records for embedding pilots
- Prevents RAG pollution
- **No embeddings without explicit phase approval**

### Autonomous Research Manager
- Future-only. **DISABLED until explicit approval.**
- When approved: schedules autonomous source tasks, writes staged-only
- No embeddings, no promotion, no broker/proposal/trade/journal mutation

---

## Non-Negotiable Safety Rules

1. No Hermes agent may execute a trade
2. No Hermes agent may mutate proposals, paper_trades, journal, or holdings
3. No Hermes agent may access broker APIs
4. No Hermes agent may auto-promote without operator approval
5. No Hermes agent may create embeddings without phase approval
6. No Hermes agent may override Trade AI execution state
7. No Hermes agent may expose SearXNG publicly
8. No Hermes agent may change model routing
9. No Hermes agent may disable safety gates (ALPACA_MODE, LLM_DISABLE_LIVE_EXECUTION)
10. All Hermes agent outputs are advisory only — never execution authority

---

## Research Backlog Seeding (Future)

Existing Trade AI data should seed the research backlog:
- Portfolio holdings and watchlists
- FinViz data gaps
- Existing news_articles freshness
- YouTube channel coverage gaps
- Transcript/filing queue gaps
- Ticker/sector research gaps
- Pipeline quality findings
- Promotion review needs
- Telegram/AI analyst vague recommendations

---

## Dashboard Role

Dashboard pages display Hermes intelligence as read-only advisory data:
- Hermes Intelligence page: research rows, promotion review, pipeline quality
- System Applications: SearXNG status
- No mutation controls on any Hermes dashboard element
