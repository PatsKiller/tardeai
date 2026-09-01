# Phase 210F — Hermes Learning Feedback Architecture (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:45:15-04:00
Measured at: efcc51365 / not measured

Standard chain: **Observe → Normalize → Evaluate → Learn → Promote → Apply (safely).**

## Observe
trade outcomes (proposal_outcome_chain), research outcomes (hermes_research_intelligence), operator choices
(advisory choices), advisory accuracy, source usefulness, profit-left-on-table (trade_edge_comparison),
false pos/neg, failed jobs (systemd Result), stale evidence.

## Normalize
structured event rows; SIEM/digest classification; evidence-quality + confidence scoring; outcome labels.

## Evaluate
prediction vs outcome (trade_edge_comparison, trade_llm_reviews); TradeAI vs Hermes vs external; score
model/source/agent usefulness; detect repeated failure patterns.

## Learn
update hermes memory / RAG embeddings / source scars / agent calibration; generate lessons WITH provenance
(trade_instance_id lineage); store confidence deltas; record what should change vs stay advisory.

## Promote
librarian review → embedding curator → promotion review → RAG publication → v3 visibility.

## Apply safely
future prompts/advisory context include lessons; **scoring changes require a separate operator-approved
gate** (shadow-first; candidate_shadow_efficacy MIN_SAMPLES=20 / MIN_HITRATE=0.60); **no silent strategy
mutation; no live-trading mutation.**

## Schema recommendations (additive, future)
- `hermes_research_backlog` (dedicated backlog, currently tagged rows).
- `hermes_external_research` (external lane packets + usefulness-vs-outcome score).
- `hermes_source_credibility` / source scars (per-domain trust deltas).
