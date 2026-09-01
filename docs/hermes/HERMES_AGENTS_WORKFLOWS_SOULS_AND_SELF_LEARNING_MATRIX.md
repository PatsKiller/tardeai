# Hermes Agents, Workflows, SOULs & Self-Learning Matrix

Status:      ACTIVE
as_of:       2026-06-07T18:49:05-04:00
Measured at: efcc51365 / not measured

_ms01-openclaw · 2026-06-07 · **generated from canonical status snapshot** (`data/runtime/hermes_canonical_status_latest.json`, Phase 217) · advisory-only · paper-only · live trading PROHIBITED_

> This document and its `.docx` are regenerated from the single canonical snapshot built by
> `scripts/build_hermes_canonical_status.py` (which merges live `/api/v2/hermes/*` + systemd state). Portal
> cards (`researcher-matrix`), system state, and these docs therefore agree.

## 1. Executive summary
Hermes is the research & self-learning layer that improves TradeAI v12 over time — it never trades. This
document is regenerated from the **live Command Center v3 / `/api/v2/hermes/*` API** (source of truth), with
GitHub/Drive architecture docs as supporting references. It supersedes earlier generated Markdown/Word docs
where they disagreed with the portal (see §20 and PHASE216B).

## 2. Source-of-truth hierarchy
1. **Live v3 portal / `/api/v2/hermes/*`** (canonical, this capture: PHASE216A).
2. This matrix document (regenerated from #1).
3. Architecture reference (`HERMES_TRADEAI_RESEARCH_AND_SELF_LEARNING_ARCHITECTURE.md`).
4. Older generated docs (deprecated where they conflict).

## 3. Live v3 portal snapshot (2026-06-07)
- Hermes **v0.16.0**; CLI `~/.local/bin/hermes`; venv `~/.local/share/hermes-agent-venv`; home `~/.hermes`.
- Portal header: **38 timers · 209 crons · 2 services · 6 LLM jobs** (System page scope).
- **19 workflows · 9 graph nodes · 6 DB tables · 13 safe views · CLI profile used by automation: false**.
- DB writes/24h: **research_intelligence=436 · memory_events=95**.
- Kill-switch: INACTIVE, canonical `data/runtime/HERMES_DISABLED` (retired path ignored).
- Retired/legacy agents: **24** (gateway failed/disabled).

## 4. Hermes global profiles
| Profile | Model | Tools | Status | SOUL hash |
|---|---|---|---|---|
| default | gemma3:4b | none | active | 7a3aa0e6b3d18ac1 |
| tradeai | gemma3:4b | none | active | fc060ad139e96d48 |
| tradeai12b | gemma3:12b-ctx4k | none | experimental | 9ed7b8a993469452 |
| dev | gpt-5-codex | 14 (no terminal/code_exec/computer_use) | unconfigured/human-invoked | 8df596720c9103a3 |
| serverops | unset | **18 incl terminal/code_execution/computer_use/x_search** | unconfigured · **P1 hardening** | aebf7b52c57e8bba |

## 5. Agent and identity matrix
Chat profiles are interactive and **tool-less for Trade AI** (tradeai/tradeai12b). No automated job uses any
chat profile (`CLI profile used by automation: false`). Research-fleet agents are standalone
`scripts/hermes_*.py` on systemd timers / cron — they are NOT chat profiles. See §6, §9.

## 6. Workflow ownership matrix (19 workflows, 9 graph nodes)
Graph nodes (live): Chief Hermes Coordinator (`hermes_coordinator.py`, cron */15) · Source Discovery ·
Hermes Librarian (`librarian-backlog-loop`) · Embedding Curator · Promotion Review (`embedding-promotion-review`) ·
Research Backlog Manager (`backlog-health-check`) · Autonomous Research Manager (`autonomous-loop`) ·
SearXNG (docker :18888) · TradeAI safe views (read-only WALL). DB writers: research_intelligence (436/24h),
memory_events (95/24h), promotion_audit, embedding_queue. Full owner table: `/api/v2/hermes/workflow-matrix`.

## 7. LLM / Auth lane matrix (live)
| Lane | Route | Authed | Headless automation | Notes |
|---|---|---|---|---|
| ChatGPT (Codex) | openai-codex OAuth (free, ChatGPT sub) | YES | **unavailable** (`hermes_headless_limit`) | interactive `hermes -p dev chat` only; runtime enabled=false |
| Grok (xAI) | xai-oauth proxy (free) :8645 | YES | **ready** | working free automated external lane |
| Claude (Anthropic) | API key | YES | **credits_required** | add Anthropic credits to use |
| Nous Portal | OAuth | NO | auth_pending | `hermes auth add nous --type oauth` |
| Local (Ollama) | local gemma3 | YES | **ready** | primary automated lane |

## 8. Chat usage matrix
trade advisory → **tradeai** (deeper → **tradeai12b**); general → **default**; coding → **dev** (Codex,
interactive); server-ops → **serverops** (HOLD pending P1 hardening). All advisory; none touch the broker.

## 9. Research fleet graph nodes
See §6. Coordinator orchestrates the fleet on cron */15 (flock-guarded), per-tick caps, canonical kill-switch.
Each node = a `scripts/hermes_*.py` on its own systemd timer; reads TradeAI **safe views** (the WALL).

## 10. Librarian deep dive
`hermes_autonomous_librarian_backlog_loop.py` (hermes-librarian-backlog-loop.timer) reviews staged findings
in `hermes_research_intelligence`, routes to embed/promote/backlog (status updates only). Taxonomy =
separate IRIS Taxonomy Agent. Kill-switch: `data/runtime/HERMES_DISABLED` or `LIBRARIAN_DISABLED`.

## 11. RAG / embedding / promotion workflow
finding → librarian review → embedding curator (`hermes_embedding_queue`, gated) → promotion review
(`hermes_promotion_audit`) → RAG publication (`content_embeddings`, ~39,955 rows) → advisory context at
prompt-time (via `llm_context_engine.get_hermes_knowledge`).

## 12. Self-learning loops (live: 11 loops, PARTIAL by design)
Closed-loop **PARTIAL** — observe/normalize/evaluate/promote wired (advisory + RAG); **0 loops mutate
scoring** (separate operator-gated graft, shadow-first MIN_SAMPLES=20/HITRATE=0.60). **9** loops feed prompts.
Each loop is drill-down-able in v3 (`/api/v2/hermes/loop-detail?loop=NAME`): process steps, queued/completed
counts, recent timestamped items. Loops: closed_trade_outcomes, post_exit_edge_comparison,
trade_close_llm_reviews, shadow_candidate_scoring, shadow_efficacy_graft_gate, research_intelligence,
promotion_audit, coordination_memory, agent_calibration, rag_embeddings, **external_researcher_feedback**.

## 13. External feedback loop
`scripts/hermes_external_feedback_loop.py` (daily `hermes-external-feedback.timer` 04:00) scores each external
recommendation's usefulness (local gemma3, intrinsic + outcome-aware) → `usefulness_score` + per-lane average
(advisory lane routing; **no scoring mutation**). Verified: AAPL 0.30, GCTS 0.70, grok avg 0.50.

## 14. Internal deep research lane
**Hermes Deep Research — Local**: gemma3:27b / gemma3-overnight, BATCH_OVERNIGHT, advisory + staging only.
Lane status: **built + nightly-scheduled (advisory/staging, operator-run)** — runner
`hermes_deep_research_local.py` built; `hermes-deep-research-local.timer` **enabled** (02:30 local, `--apply`
self-gated to overnight); writes `hermes_research_intelligence` staging; kill-switch + health-gate. gemma4 deferred.

## 15. External researcher lanes
`scripts/hermes_external_researcher.py` (redaction-first, dry-run default, `--apply`, advisory, stores
`hermes_external_research`). Lanes: Claude (high-stakes: retirement/tax/SSDI/IRMAA, final challenge) — credits
needed; ChatGPT/Codex (second opinion, synthesis) — interactive-only on 0.16.0 (cache-gated, `--force-retest`);
Grok (market/social narrative) — **live free**; Consensus — designed. Governance: EXTERNAL_LLM_USAGE_POLICY.

## 16. Retired sidecar / legacy agents
**24** retired items (audit-only): legacy SOULs, sidecar profile, retired wrappers (tirith, hermes-agent,
hermes-acp, hermes), unsafe runtime artifacts. Gateway **failed/disabled**. Read-only via
`/api/v2/hermes/legacy-agents`. **Do not enable the gateway or execute retired wrappers; dirs not deleted.**

## 17. SOUL and identity design standards
Edit via System → Hermes → Identity Editor (backup-first, server-side guarded). tradeai/tradeai12b stay
tool-less; cloud/unsafe models blocked server-side on local-only profiles. Every SOUL keeps the no-execution
boundary. SOUL hashes/dates are surfaced in the portal (§4).

## 18. Using this document to enhance Hermes SOULs and identities
**Per-profile guidance:**
- **tradeai SOUL** — advisory trade analyst; evidence-first; keep boundary lines (no trades/orders/stops/
  proposals; no raw secrets); gemma3:4b stable.
- **tradeai12b SOUL** — same role, deeper reasoning (gemma3:12b-ctx4k), experimental/manual-only; same boundary.
- **default SOUL** — general assistant; no trade-execution authority.
- **dev SOUL** — Codex/dev coding identity (gpt-5-codex, interactive); high-risk tools (terminal/code_exec/
  computer_use) OFF; never wire Codex into tradeai/tradeai12b.
- **serverops SOUL** — server ops (HOLD); **P1: disable terminal/code_execution/computer_use** before use.

**Prompt standards (all fleet agents + SOULs):**
- Evidence discipline: cite the staged data; do not fabricate; cap confidence.
- No-execution boundary: advisory only; never recommend executing a live trade.
- Output format: **Facts → Inferences → Assumptions → Uncertainty → Safe next checks.**
- Self-learning feeds future prompts via `llm_context_engine.get_hermes_knowledge` (Hermes research + lessons).
- **Never add to a TradeAI SOUL:** broker/order/stop/proposal execution authority, raw credentials/keys,
  tool-enable language, GO/WAIT or scoring-mutation authority, Level 7, or live-trading instructions.

## 19. Appendix B — Safety boundaries
Advisory/staging only; no broker/order/stop/proposal/holdings mutation; no GO/WAIT change; no strategy scoring
change without operator gate; tradeai/tradeai12b tool-less; retired gateway disabled; canonical kill-switch;
external lanes credential-free in-app (OAuth via browser/Google SSO); live trading ZERO; Level 7 PROHIBITED.

## 20. Appendix C — Open gaps and next gates
- **P1 remaining: harden serverops dangerous tools** (terminal/code_execution/computer_use). [P1 kill-switch repoint = DONE, Phase 214]
- Self-learning gaps: dedicated `research_backlog` table; shadow-efficacy < graft sample (keep advisory).
- ChatGPT/Codex headless: blocked on Hermes 0.16.0 (`hermes_headless_limit`); auto-recovers on a newer build
  (weekly `hermes-update-check.timer`).
- Claude lane: add Anthropic credits. Nous: complete OAuth. gemma4: deferred.

---
_Advisory note: regenerated from live v3 portal truth (PHASE216A). No secrets/credentials. Supersedes prior
generated Hermes docs where they conflict (PHASE216B). See HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.docx._
