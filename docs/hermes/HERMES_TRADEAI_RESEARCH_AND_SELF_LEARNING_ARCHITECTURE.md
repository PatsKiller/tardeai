# Hermes / TradeAI Research & Self-Learning Architecture

Status:      ACTIVE
as_of:       2026-06-07T17:50:18-04:00
Measured at: efcc51365 / not measured

> **Canonical live matrix:** see HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.md (.md/.docx), rebuilt from live v3 portal truth 2026-06-07 (Phase 216).

_ms01-openclaw · 2026-06-07 · advisory-only · paper-only · live trading PROHIBITED_

## 1. Executive summary
Hermes is a research & self-learning layer that exists to **improve TradeAI v12 over time** — never to
trade. It runs a fleet of local-LLM research agents (gemma3 via Ollama) that discover sources, challenge
theses, classify and curate findings, promote knowledge into RAG, and surface advisory intelligence to the
operator. A separate set of **chat profiles** (tradeai/tradeai12b/default/dev/serverops) lets the operator
converse with the system. All Hermes outputs are advisory/staging-only; scoring/strategy/broker changes
remain operator-gated. This document is the peer-review architecture reference.

## 2. Why Hermes exists
To close the learning loop on TradeAI: observe outcomes → evaluate predictions vs reality → learn lessons →
promote durable knowledge → make future advisory better. Hermes is the system's research analyst and memory,
not an executor.

## 3. Current Hermes/TradeAI architecture (three layers)
1. **Global chat profiles** (System → Hermes): default, tradeai, tradeai12b, dev, serverops — interactive,
   tool-less for Trade AI, local Ollama.
2. **Research fleet** (/v3/hermes graph): Coordinator, Source Discovery, Librarian, Embedding Curator,
   Promotion Review, Backlog Manager, Autonomous Research, Momentum Catalyst, Advisory Cache, Shadow Scorer —
   systemd-timer Python jobs writing hermes_* staging tables; reads Trade AI **safe views** (the WALL).
3. **Retired sidecar** — dormant, audit-only (gateway disabled). Not in the runtime path.

## 4. Identity / model / profile matrix
See `HERMES_RESEARCHER_RESPONSIBILITY_MATRIX.md` (Table 1). Summary: tradeai=gemma3:4b/0-tools,
tradeai12b=gemma3:12b-ctx4k/0-tools (experimental, manual-only), default=gemma3:4b, dev=future Codex
(high-risk tools off), serverops=future (HOLD). No automated job uses any chat profile.

## 5. Workflow ownership matrix
See `PHASE209C` / `PHASE209G` / `HERMES_AGENT_FUNCTION_INDEX.md`. 19 workflows, each owned by a dedicated
`scripts/hermes_*.py` on a systemd timer (Coordinator on cron */15). DB writers: research_intelligence
(443/24h), memory_events, promotion_audit, embedding_queue.

## 6. Librarian deep dive
`hermes_autonomous_librarian_backlog_loop.py` (hermes-librarian-backlog-loop.timer): reviews staged
findings in hermes_research_intelligence, routes to embed/promote/backlog (status updates only). Taxonomy
classification is the separate **IRIS Taxonomy Agent** (`iris_taxonomy_agent.py`). See `PHASE209F`.

## 7. Internal deep research lane
**Hermes Deep Research — Local**: gemma3:27b / gemma3-overnight, BATCH_OVERNIGHT, advisory-only, writes
hermes_* staging only. **gemma4 is deferred** (not installed; gates required before promotion). See `PHASE210C`.

## 8. External researcher lanes
Claude (high-stakes: retirement/tax/SSDI/IRMAA, risk synthesis, final challenge), ChatGPT (second opinion,
code/synthesis), Grok (market/social narrative, source-scored), + optional Consensus Panel. All advisory-only,
no in-app credentials, no broker mutation, designed but not enabled. See `PHASE210D` / `PHASE210G`.

## 8b. External lane status (Phase 213, 2026-06-07)
Grok (xai-oauth proxy) = working free automated external lane. Local Ollama = primary automated lane. Claude = high-stakes once Anthropic credits added. ChatGPT/Codex = free + INTERACTIVE-ONLY (`hermes -p dev chat`); automated headless lane UNAVAILABLE on Hermes 0.16.0 (reason hermes_headless_limit), cache-gated so it is NOT retried until Hermes>0.16.0. Nous = auth-pending.

## 9. Self-learning feedback architecture
Observe → Normalize → Evaluate → Learn → Promote → Apply (safely). 11 live loops incl. external_researcher_feedback (Phase 213; usefulness vs outcome → advisory lane routing) (proposal_outcome_chain,
trade_edge_comparison, trade_llm_reviews, shadow scores/efficacy, research_intelligence, promotion_audit,
memory_events, agent_performance_history, RAG, external_researcher_feedback). Each loop is drill-down-able in v3 (process steps, queue/completed, recent timestamped items via /api/v2/hermes/loop-detail). **Scoring changes require a separate operator-gated graft**
(shadow-first; MIN_SAMPLES=20/MIN_HITRATE=0.60). See `PHASE210B` / `PHASE210F`.

## 10. RAG / embedding / promotion path
finding → librarian review → embedding curator (hermes_embedding_queue, gated) → promotion review
(hermes_promotion_audit) → RAG publication (content_embeddings, 39955 rows) → future advisory context.

## 11. Operator chat usage guide
trade advisory → tradeai (deep → tradeai12b); general → default; coding → dev; server-ops → serverops
(future). All advisory; none touch the broker. See `PHASE209E` / `PHASE210E` Table 3.

## 12. v3 Command Center visibility
System → Hermes: profiles + identity editor, Workflow Matrix card, Self-Learning & Research Lanes card,
legacy read-only inventory. /v3/hermes: research-agent graph + SearXNG/infra health + identity strip.
Endpoints: profiles-status, identity, soul, legacy-agents, workflow-matrix, self-learning-loops,
researcher-matrix, external-escalation-policy, codex-dev-status, terminal-commands.

## 13. Safety boundaries
Advisory/staging only; no broker/order/stop/proposal/holdings mutation; no GO/WAIT change; no strategy
scoring change without operator gate; tradeai/tradeai12b tool-less; retired gateway disabled; live trading
ZERO; Level 7 PROHIBITED; external lanes credential-free in-app.

## 14. Current gaps and next gates
- P1: ✓ kill-switch canonical via scripts/hermes_killswitch.py (Phase 214; retired path ignored). Remaining P1: harden serverops tools.
- P2: create dedicated hermes_research_backlog table; implement hermes_external_research + source-credibility
  tables; build internal deep-research overnight runner (operator-approved); wire external lanes (operator OAuth).
- gemma4: deferred until gates pass.

## 15. Appendix
- Scripts: audit_hermes_{identities,souls,job_call_graph,live_fleet_health,workflow_owners,db_lineage,
  self_learning_loops}.py; seed_hermes_identities.py.
- Endpoints: /api/v2/hermes/*.
- DB lineage: `PHASE209D` / `PHASE210B`.
- Phase docs: PHASE208A–L, PHASE209A–L, PHASE210A–M.
