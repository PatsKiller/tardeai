# Hermes Persistent Ticker Intelligence Architecture

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**Memory:** `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Status:** source on `feat/r93-hermes-persistent-intel` — **not live production credit** until a natural cycle is observed on CURRENT.

Ticker string GUIDs (#487/#488) are a **compatibility spine**. They are not issuer/security identity. This document is the v2 contract.

## Identity model

```
Issuer GUID  (CIK if known, else provisional company-name GUID, never invented)
  └── Security / Instrument GUID  (issuer + share class + instrument)
        └── Listing GUID  (security + exchange + symbol)
              └── Ticker alias  (historical ticker_guid = UUIDv5(symbol))
                    valid_from / valid_to
```

- `ticker_guid` remains `uuid5(NAMESPACE_URL, "tradeai:ticker:{SYMBOL}")` so #488 re-ingestion cannot fork.
- Symbol reuse must not collapse listings: two issuers both using META get different `security_guid` / `listing_guid`.
- CUSIP / ISIN / FIGI / CIK are recorded only when an approved source provides them. Never invented.

## Graph schema

JSONL `data/cio/ticker_research_graph.jsonl` remains the forensic projection.

Preferred mature write path (not required to land Neo4j): Postgres tables
`knowledge_entities`, `knowledge_entity_aliases`, `knowledge_edges`,
`knowledge_edge_sources`, `evidence_artifacts`, `ticker_research_state`.
Not implemented in this PR. No new vector DB.

Edges are bitemporal: `valid_from`, `valid_to`, `observed_at`, `recorded_at`,
`last_confirmed_at`, `status` ∈ CANDIDATE|CONFIRMED|DISPUTED|SUPERSEDED|EXPIRED|RETRACTED.

Classes: LINEAR, LATERAL, VERTICAL, MACRO, CALENDAR.

Do not infer supply-chain edges from shared industry.

## Free-first lifecycle

`SYMBOL_EVIDENCE_REFRESH` **must not** enter a paid provider from `PLANNED`.

```
last TickerResearchState
→ existing Hermes
→ RAG
→ structured adapters (SEC/FRED/calendar/market)
→ SearXNG discovery (not reasoning)
→ LibrarianAssessment
→ EvidenceDelta
→ NO_NEW_INFO | LLM_ELIGIBLE
```

Modes: `FREE_FIRST_ONLY` | `LLM_ELIGIBLE` | `PAID_AUTHORIZED`.

This prompt authorizes **FREE_FIRST_ONLY only**. Cap is not raised. `COST_CAP_EXCEEDED` is not bypassed.

## Librarian contract

Keep: taxonomy, graph, freshness, retention, RAG health, backlog.

Add: `LibrarianAssessment@v1` — source valid, duplicate, primary/derived, material, freshness_state, what_changed. Deterministic first. LLM classification only when rules cannot decide. Never for price/cash/position.

## Freshness vs retention

| | Decision freshness | Retention |
|---|---|---|
| news/catalyst | hours–days | staged 90d |
| Hermes promoted default | 7d (legacy hybrid_evidence) | promoted 365d |
| SEC filing | until later filing (~400d) | keep |
| earnings result | until next cycle | keep |
| industry structure | months–year | keep |

Expiration marks CURRENT|AGING|STALE|SUPERSEDED|RETRACTED. It does not delete history.

## Curation / memory taxonomy

| Object | Meaning |
|---|---|
| EvidenceArtifact | what sources said |
| HermesCurationSummary | last material review (not an article dump) |
| TickerResearchState | what we currently know |
| SymbolThesis | investment belief |
| RESEARCH_REFERENCE memory | GUIDs + purpose, not prose |
| OperatorInvestmentPolicy | explicit mandate |

NO_NEW_INFO creates no new thesis version, no new memory row, no Telegram.

## LLM escalation

| Level | When |
|---|---|
| 0 no LLM | default |
| 1 DeepSeek V4 Flash | material new evidence only; one call per (security_guid, prior_curation, evidence_delta_hash, prompt_version) |
| 2 one OAuth challenger | Grok **or** ChatGPT, not both by default |
| 3 DeepSeek V4 Pro | exceptional portfolio/invalidation/operator deep review; never bulk |

Family A scheduler + Family B paired grok,chatgpt crons are **historical duplication**. Retirement only after replacement is proven. Not in this PR.

## CIO integration

CIO/Advisory must consume `TickerResearchState` rather than rebuilding research. Not wired on CURRENT in this PR.

## Failure states

`FRESH_NO_CHANGE` `FREE_REFRESH_PENDING` `EMBED_PENDING` `LLM_ELIGIBLE_NOT_AUTHORIZED` `COST_CAP_BLOCKED` `SOURCE_UNRESOLVED`

Embedding 503 must not drop acquired evidence (`ACQUIRED_EMBED_PENDING`). Not fully wired this PR.

## Cost / authority

No paid call in this program. `MEMORY_BEHAVIOR_INFLUENCE=0`. No broker/order/stop/2FA mutation.

## Measured live at handoff (`0b7bc9eb`)

120 ticker profiles, 0 research artifacts, 17 unresolved identities, memory mostly CANDIDATE research pointers. Official maturity remains **59/100** until a natural cycle is observed.
