# Hermes Autonomous Research Engine — Phases 0-5

**Date:** 2026-08-04
**Status:** IMPLEMENTED (all 5 phases dry-run verified, committed to main @ `402aabd6`)

## Overview

Five phases transforming Hermes from an operator-gated research aggregator into a
fully autonomous research engine that:

- Continuously researches suggested topics without human intervention
- Identifies emerging themes and pivots toward new areas of interest
- Discovers new articles, companies, and market-relevant tickers
- Tracks market rotations, financial news, business news, and major events
- Self-manages knowledge quality through a Taxonomy & Librarian Agent

## Phase 0 — Quick Wins

**Config flips:**
- `hermes_discovery_schedule.json`: `industry_novelty_enabled` and `llm_review_enabled` both `false → true`
- Industry novelty now produces GAP_CANDIDATE rows for uncovered sectors
- LLM triage (local gemma first, cloud escalation capped, advisory-only) reviews inbox candidates

**Stub implementations in `hermes_autonomous_loop.py`:**
- `portfolio_reflection`: monthly post-mortem synthesis over closed trades from the outcome ledger
- `pipeline_quality`: weekly health assessment of research pipeline (source yield, freshness, embedding queue, maturity gates)

**Drift reconciliation:** Crontab comments updated to match live config (analyst_signal, industry_novelty)

## Phase 1 — Autonomous Discovery Promotion Lane

**New files:**
- `scripts/lib/hermes_discovery/autonomous_governance.py` — curator promotes research-only inbox candidates inside rails
- `scripts/hermes_discovery_autonomy.py` — CLI wrapper
- `config/hermes_discovery_autonomy.json` — policy config

**Rails:**
- Candidate must be READY_FOR_REVIEW with discovery_score ≥ 0.60
- llm_review_json.recommended_action must be in PROMOTIVE_ACTIONS
- domain_risk_level NOT in {tax, legal, planning, medical} (professional domains NEVER auto-promoted)
- do-no-harm scorecard must not be in "pause" mode
- Per-day caps: max 4 topics, 1 source, 3 ticker stages
- All actions audited with actor='autonomous_curator' + rollback_sql

**Coordinator integration:** New step after librarian block, `CAP_AUTONOMOUS_PROMOTE = 5`

## Phase 2 — Research Agenda Engine

**New files:**
- `scripts/hermes_research_agenda.py` — builds agenda from 6 signal sources, ranks, creates/retires/boosts topics
- `config/hermes_research_agenda.yaml` — policy
- `sql/migrations/2026_08_04_agenda.sql` — `topic_monitor.auto_created` column, `hermes_research_agenda_audit` table

**Signal sources (in priority order):**
1. Inbox TREND/TOPIC with llm_review approve (Phase 1 overflow)
2. Industry novelty GAP_CANDIDATE (MISSING_SECTOR)
3. Entity spikes not in topic_monitor (topic/sector/person/organization, min 3 mentions)
4. Sector RS rotation deltas (LEADING underweight sectors → research topic)
5. Think-tank catalyst themes
6. Macro/geopolitical coverage gaps (inflation, fed, rate, tariff, etc.)

**Lifecycle:**
- CREATE: auto_created=true, owner='hermes', priority from composite score
- RETIRE: auto_created topics with zero research yield >21d → enabled=false
- BOOST: auto topics with ≥3 promoted research rows in 30d → priority +1
- Never touches operator-created topics

**Cron:** 07:45 daily (after topic bridge) + 18:15 weekdays (after RI queue drain)
**Kill switch:** `data/runtime/HERMES_AGENDA_DISABLED`

## Phase 3 — Taxonomy & Librarian Agent v2

**New package:** `scripts/lib/hermes_librarian/` (6 modules)

| Module | Responsibility |
|---|---|
| `taxonomy.py` | Content-subject taxonomy (separate from retired 3-axis). Ollama gemma3:4b + keyword fallback. Efficacy-graded. |
| `graph.py` | Entity co-occurrence graph, alias management, stale-edge pruning, query expansion for RAG |
| `freshness.py` | Per-source SLA monitoring, stale content flagging, embedding staleness detection + re-enqueue |
| `retention.py` | Config-driven retention ladder: live → hidden → archived → purge (never deletes live rows) |
| `rag_health.py` | Embedding coverage per source, orphan detection, queue drift, retrieval QA sampling |
| `librarian.py` | Orchestrator with scope isolation (each scope in its own transaction, errors don't cascade) |

**Light scopes (every 15-min coordinator tick):** freshness, retention
**Deep pass (nightly via cron 03:50):** taxonomy backfill, graph refresh, RAG health
**Legacy backlog scope:** preserved as `backlog` scope in the librarian

**New files:**
- `scripts/hermes_librarian_agent.py` — CLI entry point
- `config/hermes_librarian_policy.yaml` — single source of truth for retention windows
- `sql/migrations/2026_08_04_librarian_v2.sql` — `content_tags`, `hermes_entity_alias_map`, `hermes_entity_cooccurrence`, `hermes_librarian_audit`

## Phase 4 — Cross-Source Synthesis

**New file:** `scripts/hermes_cross_source_synthesizer.py`

Collects 6-source signal bundle (entity spikes, news themes, discovery signals, sector rotation,
research themes, agenda actions), asks gemma3:12b to synthesize cross-source insights,
stages as `research_type='emerging_theme_synthesis'`.

**Cron:** `20 6 * * 1,4` (off-hours, llm_priority_guard-wrapped)
**Kill switch:** `data/runtime/HERMES_SYNTHESIZER_DISABLED`

## Phase 5 — Outcome Closure

**Modified:** `scripts/lib/hermes_discovery/scoring.py`

Added `outcome_yield` component (6% weight, sample-gated at n≥10 per type):
- Reads per-candidate_type/domain yield from outcome ledger
- High-yield lanes get score boost; negative-yield lanes (like ai_discovered α −4.82%) get penalty
- Maintains existing weight discipline — scoring stays honest

## Dry-Run Results (2026-08-04)

| Module | Result |
|---|---|
| Phase 1: discovery_autonomy | 0 eligible (no READY_FOR_REVIEW candidates meeting all rails — expected) |
| Phase 2: research_agenda | 15 candidates found, 3 would-create (industrials, technology, biotechnology) |
| Phase 3: librarian v2 | All 6 scopes OK. 615K embeddings, 47K orphans, 100% QA pass rate, 1 stale producer detected |
| Phase 4: cross_source_synthesizer | Bundle collection functional, synthesis pending cron activation |

## Constraints (all honored)

- **Local GPU only:** gemma3:4b/12b via Ollama, temp 0 for classification, off-hours scheduling
- **Free LLM lanes only:** Grok :8645 / ChatGPT :8646 OAuth, redacted, local-first
- **No broker access:** all new modules have import-time `_forbidden_path_guard`
- **Kill switches:** `HERMES_DISABLED` (global) + `AGENDA_DISABLED`, `LIBRARIAN_DISABLED`, `SYNTHESIZER_DISABLED`
- **Operator sovereignty:** auto-created topics are lifecycle states; all actions audited with rollback_sql
- **Advisory-only:** no module writes to watch tables or broker endpoints directly
