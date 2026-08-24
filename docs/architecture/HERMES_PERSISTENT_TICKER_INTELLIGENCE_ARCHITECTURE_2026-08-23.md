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

Production timer (source-controlled): `tradeai-free-first-circulation.timer` hourly :23 ET on CURRENT. See `docs/ops/HERMES_FREE_FIRST_NATURAL_SCHEDULER_2026-08-23.md`. Not a substitute: `tradeai-hermes-cio-worker` (paid drain) or rebuild librarian loop.

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

Embedding 503 must not drop acquired evidence (`ACQUIRED_EMBED_PENDING`). **#489 implements** `scripts/lib/artifact_embed.py`: persist first, 503 → `ACQUIRED_EMBED_PENDING`, retry queue idempotent. Live CURRENT default is `embed_deferred` (no embed_fn / no 503 observed this pass).

## Cost / authority

No paid call in this program. `MEMORY_BEHAVIOR_INFLUENCE=0`. No broker/order/stop/2FA mutation.

## Measured live at handoff (`0b7bc9eb`)

120 ticker profiles, 0 research artifacts on CURRENT, 17 unresolved identities, memory mostly CANDIDATE research pointers.

P0 circulation on PR #489 worktree (not CURRENT): **1137 artifacts** projected from existing Hermes; 117/120 Hermes_resolved; 0 paid dispatch.

## POST_MERGE_CURRENT_PROOF (2026-08-23 21:16 ET)

| | |
|---|---|
| PR | #489 merged |
| PR head | `318240d61d94c08127d2b5a61e5a6f28ac090169` |
| merge / new main | `0b63d209d88f9bdfd4afd96c4fa7a4e9c6b230bf` |
| release | `0b63d209-main-exact-phase2-20260823-210821` |
| rollback | `0b7bc9eb-main-exact-phase2-20260823-185856` |
| CURRENT SOURCE_COMMIT | `0b63d209…` pin_match true |
| artifacts on CURRENT after Hermes projection | **1137** (was 0); replay **+0** |
| after FREE_FIRST_ONLY + RAG persist | **1608** (1137 Hermes + 471 RAG `content_embeddings`) |
| Hermes_resolved / RAG_resolved / structured | **117 / 2 (PRSO, VIVS) / 1 (SOPAQ)** |
| SearXNG | **0** (no residual) |
| FRESH_NO_CHANGE | **120** |
| Flash / paid_dispatch / COST_CAP this pass | **0 / 0 / 0** |
| natural free-first/Librarian timer | **NATURAL_PROOF_PENDING** (librarian next ~03:45 ET). Pre-existing `tradeai-hermes-cio-worker` ticked on the new pin and hit live-bridge `COST_CAP_EXCEEDED` — that is the old drain, not FREE_FIRST_ONLY. |
| official maturity | **59/100** until a natural free-first/Librarian cycle is observed |

## NATURAL_PROOF_PENDING_REASON (2026-08-23 21:30 ET)

`R93_FREE_FIRST_NATURAL_PROVEN` remains **false**. Not because a due timer was missed. Because **no production scheduler invokes `FREE_FIRST_ONLY`.**

Measured 2026-08-23 21:29 ET:

| Job | Unit / line | WD | SHA lineage | Next | What it actually is |
|---|---|---|---|---|---|
| FREE_FIRST_ONLY `scripts/free_first_refresh.py --circulate` | **none** | — | code is on CURRENT `0b63d209` | never | CLI + tests only. Zero cron. Zero systemd timer. `hermes_coordinator.py` does not call it. |
| `tradeai-hermes-cio-worker` | `OnCalendar=*:0/15` | CURRENT | `0b63d209` | ~15m | `hermes_cio_worker.py --drain --max 2 --backend live`. Paid live-bridge drain. 21:17 ET claimed 1, HTTP 429 `COST_CAP_EXCEEDED`. **Not free-first.** Observing it as the natural cycle would be `HOLD_PAID_BOUNDARY_LEAK`. |
| `hermes-librarian-backlog-loop` | `07:45 UTC` / 03:45 ET | **rebuild** `$PROJ` | not CURRENT | ~03:45 ET 2026-08-24 | `hermes_autonomous_librarian_backlog_loop.py --apply --max-rows 5`. Last four days: `NO FINDINGS: 0 findings in 0.1s`. Dual-root. Does not load `TickerResearchState` / graph artifacts. |
| `hermes-autonomous-loop` | China-night DeepSeek | CURRENT | `0b63d209` | failed | `ticker_challenger --apply --max-rows 2`. Paid. Must not be started for this proof. |
| crontab Hermes fleet | `$PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | rebuild dirty `feat/two-way-watchlist-curation` | not `0b63d209` | continuous | Historical producers. Not this classifier. |

This prompt forbids: running the classifier manually and calling it natural; editing the schedule; touching timestamps; enqueueing fake research.

PR C (Librarian epistemic + HermesCurationSummary + TickerResearchState maturity) is **not started**. Gate is section-11 PASS of a genuine scheduled FREE_FIRST_ONLY cycle on `0b63d209`.

Live CURRENT graph re-measured at this inspection: **120 profiles, 1608 artifacts** (not a persistence regression).

## FIRST-NATURAL-TICK (supersedes NATURAL_PROOF_PENDING)

`R93_FREE_FIRST_NATURAL_PROVEN=true`. systemd `tradeai-free-first-circulation.timer` LastTrigger **2026-08-23 22:24:15 ET**, finished 22:27:05, exit 0, CURRENT `3dd6f8d5`, run_id `433f8a56-3964-4812-80b0-b1d506ea96d2`. Result: 117 Hermes / 2 RAG / 1 structured / 0 SearXNG / 120 FRESH_NO_CHANGE / 0 paid.
