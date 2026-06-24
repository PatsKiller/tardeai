# Hermes Agent Contracts and Permissions Registry

**Date:** 2026-05-31 (updated 2026-06-24 with maturity remediation notes)
**Status:** AUTHORITATIVE — governance document

> **Recent Operational Hardening (2026-06-24):** See [HERMES_MATURITY_AUDIT_REMEDIATION_20260624.md](HERMES_MATURITY_AUDIT_REMEDIATION_20260624.md) for the six prioritized fixes executed after the Hermes maturity audit:
> - Embedding worker timeout/retry + caps
> - Deprioritized openai-codex for interactive profiles
> - Auto-promote backpressure
> - Retired artifact hygiene + cleanup script
> - New smoke tests for coordinator/promotion
> - Directive B now explicitly surfaced in maturity dashboard + logs



> **🔓 WALL OPENED BY OPERATOR DIRECTIVE — 2026-06-02 (John, "Option B").** The challenger wall is intentionally opened: the **Chief Hermes Coordinator** (`scripts/hermes_coordinator.py`) was built and is scheduled **continuously** (cron `*/15`, flock-guarded) to run the **entire fleet LIVE (`--apply`)**, including:
> - **Auto-promote (ungated)** — staged research auto-promotes into the intelligence/RAG the **core trading agents read** (no confidence floor, no operator review). Every promote is logged to `hermes_promotion_audit` with `rollback_sql` (reversible).
> - **RAG Embedding Worker live** — writes `content_embeddings` (the shared RAG index). Reversible by deleting the embedded rows.
> - **Autonomous Research Manager ENABLED** (was disabled).
> - **Kill switch OFF** (un-tripped) but still checked every tick — `touch hermes_sidecar/.hermes/DISABLED` halts the whole fleet next tick.
>
> **Risk accepted by operator:** unattended autonomous research now writes into the core trading brain with no human gate and no active emergency stop. Mitigations in place: per-tick caps, flock, full audit + one-command rollback on every promote/embed, instant kill-switch re-arm. To revert: `touch …/.hermes/DISABLED`, then roll back via `hermes_promotion_audit.rollback_sql` + delete embeddings.

> **⚠ Approval reconciled to execution (operator-authorized 2026-06-02).** Footprint was validated against the live DB (`/api/v2/hermes/agent-footprint`); three agents were already running in their `hermes_*` staging sandbox ahead of formal approval. Per operator directive (John, 2026-06-02), governance has been **reconciled to reality**: the three staging-only running agents are now **APPROVED**, the Coordinator stays design-pending (smoke-test only, not really built), and the Autonomous Research Manager stays **DISABLED** (not directed; higher-risk autonomous scheduling).
>
> | Agent | Approval (now) | Validated execution footprint | Notes |
> |---|---|---|---|
> | Source Discovery | ✅ operational | `source_discovery_agent` 13 rows | already approved |
> | Promotion Review | ✅ operational | `hermes_promotion_audit` 15 rows | already approved (advisory/dry-run) |
> | Hermes Librarian | ✅ **APPROVED 2026-06-02** | `autonomous_librarian_loop`+`expanded_librarian_agent` 13 rows | staging-only (status updates); reconciled to footprint |
> | Research Backlog Manager | ✅ **APPROVED 2026-06-02** | `research_backlog_manager` 5 rows | staging-only (backlog-tagged intelligence rows); dedicated table still optional |
> | Embedding Curator | ✅ **APPROVED 2026-06-02** | `hermes_embedding_queue` 9 completed | staging-only — stages candidates to `hermes_embedding_queue`; the actual RAG write (`content_embeddings`) remains a **separate, still-gated** Embedding Worker |
> | Chief Hermes Coordinator | DESIGN — pending approval | `hermes_memory_events` 1 (smoke-test) | not built beyond a smoke test; design-for-approval |
> | Autonomous Research Manager | ⛔ DISABLED — NOT APPROVED | none | unchanged; requires explicit future gate |
>
> **Scope of this approval:** formalizes the three agents' existing **staging-only** behaviour (no new powers — their Forbidden lists still bar core/proposal/trade/broker writes). Reversible by reverting the Activation phases. Embedding Curator approval does **not** approve direct RAG/`content_embeddings` writes — that worker stays gated.

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
| Activation phase | **BUILT + OPERATIONAL — operator directive B 2026-06-02** (`scripts/hermes_coordinator.py`, cron `*/15`, flock; orchestrates the full fleet live; kill-switch-checked each tick) |

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
| Activation phase | **APPROVED — operator-authorized 2026-06-02** (staging-only: status updates to hermes_research_intelligence; reconciled to validated footprint of 13 rows) |

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
| Activation phase | **APPROVED — operator-authorized 2026-06-02** (staging-only: backlog-tagged hermes_research_intelligence rows; dedicated hermes_research_backlog table optional/not required) |

**Backlog item statuses:**
- `candidate` → `needs_research` → `searched` → `staged` → `librarian_reviewed` → `embedding_candidate` → `promoted_advisory` / `rejected` / `archived`

> **Verified 2026-06-02 (endpoint vs agent — avoid confusion):** the dedicated `hermes_research_backlog` table is confirmed **NOT created** (`to_regclass` = null). The read-only `GET /api/v2/hermes/research-backlog` endpoint does **not** read a Backlog-Manager-owned table — it surfaces `hermes_research_intelligence` rows tagged `research_type IN ('research_backlog','ops_backlog')` (produced by the staging/Source-Discovery path and the autonomous-librarian backlog feed). So returning items from that endpoint does **not** mean this agent is operational — the Research Backlog Manager remains **design-only**. The v3 Hermes Workflow graph renders it as designed-only on this basis.

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
| Activation phase | **APPROVED — operator-authorized 2026-06-02** (staging-only: stages candidates to hermes_embedding_queue). NOTE: the actual RAG write to `content_embeddings` is performed by the separate Embedding Worker, which remains **gated** and is NOT approved by this. |

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
| Run mode | **ENABLED — operator directive B 2026-06-02** (live via Coordinator autonomous loop, capped, kill-switch-gated) |
| Max caps | 2 rows per run (when approved) |
| Handoff targets | Hermes Librarian Agent |
| Rollback | Delete staged rows by run_id |
| Dashboard | Kill switch status on Hermes Chat page |
| Activation phase | **ENABLED — operator directive B 2026-06-02** (was disabled; now run live under caps + kill switch) |
