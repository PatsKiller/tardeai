# Trade AI Institutional Memory + Autonomous Agent Architecture

**Date:** 2026-08-24  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**This is not autonomous trading.**

Memory is context, history, and learning evidence. It is never broker, position, cash, price, order, stop, risk, 2FA, or execution truth. LLMs never own deterministic financial arithmetic.

## Starting live evidence (do not re-prove free-first)

Protected main at R10 start (after docs PR #493): `631800ad`. Application CURRENT remains **`bc6ff5c6`** until an explicit exact-main promote of *application* code.

Natural `tradeai-free-first-circulation.timer` on CURRENT `bc6ff5c6`:

| tick | ET | run_id | shape |
|---|---|---|---|
| 1 | 22:24 2026-08-23 | `433f8a56` | 117/2/1/0/120/0 (`3dd6f8d5`) |
| 2 | 23:23 | `6458ea63` | same (`3dd6f8d5`) |
| post-#492 | 00:23 2026-08-24 | `62652d0c` | same (`bc6ff5c6`) |
| later same pin | 09:23 | `b9b00556` | same (`bc6ff5c6`) |

`TickerResearchState` reloads. Context question is `WHAT_CHANGED`. Graph SHA unchanged on the post-C tick. Official live maturity **65/100**.

## The empty-brain gap

PR C was correct: `NO_NEW_INFO` must not mint a **material** curation version.

It was incomplete: a security with only `NO_NEW_INFO` cycles had **no durable prior cognitive snapshot**, so “what I believed” did not exist to measure deltas against.

PR M1 distinguishes:

| object | meaning | versions |
|---|---|---|
| `HermesCurationSummary` `kind=BASELINE_PROJECTION` version **0** | what the office knew when persistent cognition became authoritative | one per security |
| `HermesCurationSummary` `kind=MATERIAL` version ≥1 | something important changed from that baseline | only on material watermark/evidence |

After baseline exists, `NO_NEW_INFO` writes **zero** new versions.

Tag: `BASELINE_PROJECTION`. It must not claim historical model synthesis.

CLI (after this code is on CURRENT):  
`python scripts/free_first_refresh.py --root CURRENT --project-baseline --json`  
No research, no providers, no thesis rewrite. Replay must create 0 new baselines.

## Memory taxonomy (v2)

Exactly one **primary** plane per persistent object:

| plane | examples |
|---|---|
| WORKING / SESSION | `ContextEnvelope`, thread, checkpoint |
| EPISODIC | `AgentEpisode`, feedback, notifications, outcomes |
| SEMANTIC OPERATOR | confirmed preferences, non-financial operator facts |
| CANONICAL POLICY / BELIEF | `OperatorInvestmentPolicy`, SymbolThesis, CIOPortfolioThesis, `TickerResearchState`, curation |
| DOCUMENT / EVIDENCE RAG | `TickerResearchArtifact`, filings, articles |
| PROCEDURAL / LESSON | CanonClaims, ratified lessons, Financial Senses |
| ORCHESTRATION | timer receipts, Temporal/checkpoints, job runs |

AIF `RESEARCH_REFERENCE` candidates are **research pointers**, not semantic operator memory. Raw research prose belongs in RAG.

`ContextEnvelope@v1` already exists (`scripts/lib/agent_context_envelope.py`). R10 M4 will extend it to `@v2` sections (TICKER_RESEARCH_STATE, LAST_CURATION, SEMANTIC_OPERATOR_MEMORY) consumed by CIO/Hermes/Telegram. M1 does not silently replace it.

## PR sequence (do not one-shot)

| PR | content | live? |
|---|---|---|
| #493 | docs POST-C proof | merged; **no app redeploy** |
| **M1 (this)** | taxonomy + baseline curation + inventory contracts | source until exact-main + backfill + natural |
| D | producer inventory; eligibility hierarchy; **no paid dispatch**; retire only SAFE_TO_RETIRE after replacement proof | not started in M1 |
| M2 | Postgres memory shadow + bitemporal `MemoryFact@v2` | later |
| M3 | MemoryConsolidator + PreferenceCandidate + feedback/outcomes | later |
| M4 | ContextEnvelope@v2 cross-agent | later |
| E | CIO / Ticker Intelligence / Memory Brain UI | after D is safe |
| M5 | cutover / DR / natural acceptance | last |

This prompt **does not authorize new paid spend**. Flash/OAuth/Pro may be marked eligible; they stop before dispatch until an explicit numeric grant.

## Explicitly not in M1

- Retiring `tradeai-hermes-cio-worker` or Grok/ChatGPT crons
- Raising COST_CAP
- Postgres cutover
- pgvector / pgvectorscale / Redis / Mem0 install
- PR E UI
- MEMORY_BEHAVIOR_INFLUENCE ≠ 0
- Broker/order/stop/risk/2FA mutation

## Target

Memory subsystem L6 LIVE after M1–M5 natural proof, with a path to L7 only after real longitudinal feedback/outcomes. Overall office **78–82** is a **program** target, not an M1 claim.

## Convergence with six spec corrections

This M1 document and the six-spec correction (`TRADE_AI_BITEMPORAL_MEMORY_DATA_MODEL_2026-08-24.md`) are both canonical:

- `BASELINE_PROJECTION` is the M1 current design (version 0, not material).
- Local-first embeddings; Titan/cloud disabled by default; no generative GPU on the memory path.
- M2 is Postgres bitemporal SHADOW. Neo4j and HNSW remain `INSUFFICIENT_DATA` until measured.
- Similarity is a candidate, never a self-ratified edge.
- Tenant isolation is logical, not hardware.
- Durable writes store `DecisionRationale`, never private chain-of-thought.
- Yeda's Eye is authorized **after** M1 natural PASS (2026-08-24 11:23 ET run_id `5e9028fb`). First mission is M2 due diligence, not feature spray.

### M1 natural acceptance (LIVE)

CURRENT `5c0a993a`. Baseline 120 v0; replay 0 new; natural tick loaded those baselines, asked WHAT_CHANGED, wrote 0 material versions, 0 paid. Graph RAG persist may add artifacts without minting a curation version.
