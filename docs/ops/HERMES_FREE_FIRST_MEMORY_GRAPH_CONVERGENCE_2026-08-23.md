# Hermes free-first + identity v2 closeout

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**Paid calls this program:** 0  
**Status:** `LIVE_FUNCTIONAL_NATURAL_PENDING` — #489 merged and promoted to CURRENT. Persistent artifacts and FREE_FIRST_ONLY proven on CURRENT. Natural free-first/Librarian timer not yet observed.

Official live maturity stays **59/100**.

## Why the first 105/120 result was provisional

The classifier-only pass reported `structured_resolved=105` while also recording:

- `existing_Hermes_reuse=0`
- `RAG_sufficient=0`
- `SearXNG_resolved=0`
- `free_searches=0`
- **ticker research artifacts=0**

That 105 was **canonical-card presence**, not Hermes/RAG circulation. A symbol card can fill an identity/metadata gap. It cannot stand in for thesis evidence, catalysts, or counter-evidence.

## POST-P0 circulation (worktree graph copy, 2026-08-23 20:54 ET)

Canaries NOC SCHD SCHG CSCO ANET: **5/5 HERMES_REUSE**, 60 artifacts, replay **0 new artifacts**, paid 0.

Full 120 FREE_FIRST_ONLY:

| route | n |
|---|---|
| Hermes_resolved | **117** |
| structured_resolved (gap-specific ingested news/primary, not card-only) | **3** |
| RAG_resolved (bucket; Hermes won first) | 0 |
| SearXNG | **0** (no residual after Hermes) |
| unresolved / Flash-eligible | **0** |
| fresh_no_change / NO_NEW_INFO | **120** |
| paid_dispatch_entered | **0** |
| llm_consumption / reservations (15m window) | **0 / 0** |
| COST_CAP this pass | **0** (paid boundary never reached) |
| artifacts on worktree graph | **1137** (was 0) |
| hermes rows examined | **1026** |
| RAG retrieval attempts | **120** (sql_title fallback; embed path returned 0) |
| librarian assessments | **1052** |

CURRENT pin graph was **unchanged** (0 artifacts) until merge+promote. See POST_MERGE_CURRENT_PROOF below.

Replay: second identical canary created 0 new artifacts, 0 provider calls, 0 thesis versions.

## Source

| | |
|---|---|
| starting_main | `0b7bc9eb7b19f16b51404bbf96d93e77b292c019` |
| CURRENT | `0b7bc9eb-main-exact-phase2-20260823-185856` |
| SOURCE_COMMIT / BUILD_SHA | `0b7bc9eb…` |
| pin_match | true |
| process | portfolio_server PID started 2026-08-23 18:59 ET |
| this branch | `feat/r93-hermes-persistent-intel` |
| merge/promote (at writing of this table) | later completed — see POST_MERGE_CURRENT_PROOF |

## Host claims verified

| Claim | Measured |
|---|---|
| 120 ticker profiles / GUIDs | **120 / 120** |
| 103 enriched / issuer GUIDs | **103** |
| 99 sector / 99 industry | **99 / 99** (19 unique sectors, 39 unique industries) |
| 43 catalyst / 43 calendar | **43 / 43** |
| 17 unresolved | **exact list match** |
| ticker research artifacts | **0** |
| memory | **327** rows (not 286): CANDIDATE **323**, ACTIVE **2**, EXPIRED **1**, RETRACTED **1**; RESEARCH_REFERENCE 319 |

Unresolved 17 (no invented metadata):  
`12507E201` `543354104` `628518102` `AMAGX` `CTXR` `EKSO` `FSELX` `GOVX` `LAC` `MSGM` `PRSO` `RANI` `RDHL` `SIBN` `SOPAQ` `WRD` `ZSL`  
CUSIP-like: first three. Fund convention: AMAGX, FSELX.

## FREE_FIRST_ONLY (graph profiles, no SearXNG, no paid)

| bucket | n |
|---|---|
| structured_resolved (canonical card or CUSIP/fund) | **105** |
| unresolved_after_free / Flash-eligible | **15** |
| existing_Hermes_reuse | 0 (Hermes rows not loaded into this pass) |
| SearXNG_resolved | 0 (`--max-searx 0`) |
| paid attempted / completed | **0 / 0** |
| Pro-eligible | **0** |
| no_new_info | **105** |

Flash-eligible (would require synthesis, **not called**):  
ARKX CTXR DIVI EKSO GOVX LAC MSGM PRSO RANI RDHL SIBN SOPAQ WRD XAR ZSL  

ARKX/DIVI/XAR are held names whose graph cards lack company/sector — enrichment gap, not a reason to bulk-Flash 120 tickers.

## What this PR adds (source)

- Issuer / security / listing GUIDs; ticker remains alias (`#488` namespace preserved)
- Bitemporal edge fields
- Evidence-class freshness vs retention
- LibrarianAssessment@v1 + librarian `epistemic` scope
- FREE_FIRST_ONLY classifier; paid transition from PLANNED raises
- Architecture + drift banners on superseded routing docs

## What is not proven live *(historical, pre-merge)*

See POST_MERGE_CURRENT_PROOF for the CURRENT update. Still outstanding after merge:

- Natural scheduled FREE_FIRST_ONLY / Librarian cycle (`NATURAL_PROOF_PENDING`)
- Duplicate OAuth producer retirement (PR D)
- CIO consuming TickerResearchState (PR E)
- Postgres knowledge_* tables
- Embedding 503 in a live Ollama outage (implemented + unit-tested; this CURRENT pass used `embed_deferred`)
- Evidence-class TTL completeness (Librarian marks most projected Hermes rows `STALE` under the default `news_catalyst` 36h window — PR C)

## Runtime still split

Hermes CIO worker WorkingDirectory=CURRENT. Crontab `$PROJ` is still rebuild. Overnight 22:35 ET 2026-08-22 fired `SKIPPED_LLM_UNHEALTHY: model_missing` every hour.

## POST_MERGE_CURRENT_PROOF (2026-08-23 21:09–21:16 ET)

| | |
|---|---|
| merge_sha / main_after | `0b63d209d88f9bdfd4afd96c4fa7a4e9c6b230bf` |
| PR489_head | `318240d61d94c08127d2b5a61e5a6f28ac090169` |
| deployed release | `0b63d209-main-exact-phase2-20260823-210821` |
| CURRENT_before | `0b7bc9eb-main-exact-phase2-20260823-185856` |
| pin_match | true |
| rollback | pre-#489 release above |
| health / cio / advisory | 200 / 200 / 200 |
| artifacts_before → Hermes projection | 0 → **1137** (1026 rows, 117 symbols) |
| projection replay | **+0** artifacts, **+0** GUID forks, 120 profiles unchanged |
| FREE_FIRST_ONLY | Hermes **117**, RAG **2** (PRSO, VIVS), structured **1** (SOPAQ), SearXNG **0**, FRESH_NO_CHANGE **120**, Flash **0** |
| RAG | attempts **120**, items **471** (all SUPPORTING stored polarity), sufficient-alone **2** |
| Librarian | **1608** assessments: CURRENT 75, AGING 142, STALE 1391, duplicate 0 |
| NOC replay | `NO_NEW_INFO`, new artifacts 0, state_wrote false, paid 0 |
| memory | 327 unchanged (CANDIDATE 323 / ACTIVE 2 / EXPIRED 1 / RETRACTED 1) |
| paid_dispatch / COST_CAP / spend_delta this pass | **0 / 0 / 0** |
| natural | `NATURAL_PROOF_PENDING`. Pre-existing `tradeai-hermes-cio-worker` 21:17 ET on the new pin claimed 1 live-bridge job and received HTTP 429 `COST_CAP_EXCEEDED` — old drain, not FREE_FIRST_ONLY. |

Do not treat PRE-P0 105/15 as current truth.

## NATURAL_PROOF_PENDING_REASON (2026-08-23 21:30 ET)

Re-measured CURRENT before any further work: **120 profiles, 1608 artifacts, 120 TickerResearchState=NO_NEW_INFO, memory 327**. Persistence did not regress.

Natural proof **cannot pass** under this prompt because the production scheduler for `FREE_FIRST_ONLY` **does not exist**.

- `scripts/free_first_refresh.py --circulate` is CLI-only. No crontab line. No systemd timer. No `hermes_coordinator` call.
- Editing a timer or kicking the CLI would violate “do not create a fake natural run.”
- `tradeai-hermes-cio-worker` (CURRENT, every 15m, `--backend live`) is the old paid drain. Treating its COST_CAP 429 as the free-first cycle would be `HOLD_PAID_BOUNDARY_LEAK`.
- `hermes-librarian-backlog-loop` next 03:45 ET runs in **rebuild** (`WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`), not `0b63d209`. Recent ticks: `NO FINDINGS: 0 findings`.
- Crontab `$PROJ` is still rebuild.

PR C is not opened. Official maturity remains **59/100**. `R93_FREE_FIRST_NATURAL_PROVEN=false`.

Operator next (not done here): after an explicit grant, add a CURRENT-pin systemd timer that runs `free_first_refresh.py --circulate` with FREE_FIRST_ONLY / zero paid, then observe **that** timer. Do not use Family A live drain or Family B OAuth crons as the proof vehicle.

## FIRST-NATURAL-TICK (2026-08-23 22:24–22:27 ET) — supersedes NATURAL_PROOF_PENDING

`R93_FREE_FIRST_NATURAL_PROVEN=true`

| | |
|---|---|
| timer | `tradeai-free-first-circulation.timer` |
| service | `tradeai-free-first-circulation.service` |
| trigger | systemd LastTrigger **22:24:15 ET** (not `systemctl start`, not CLI) |
| finished | **22:27:05 ET** Result=`success` exit 0 |
| run_id | `433f8a56-3964-4812-80b0-b1d506ea96d2` |
| CURRENT / source_sha | `3dd6f8d5bc1d0403a55487cf51f5ec2a58b7853b` (PR #491 merge) |
| WorkingDirectory | CURRENT exact-main pin |
| Hermes / RAG / structured / SearXNG | **117 / 2 / 1 / 0** |
| FRESH_NO_CHANGE | **120** |
| paid / Flash / COST_CAP this run | **0 / 0 / 0** |
| next timer | 23:23 ET |

NATURAL_PROOF_PENDING_REASON above is **historical**. The scheduler now exists and has fired once.

## Maturity

Official live score after first natural tick: **62/100** (+3 autonomy for systemd-triggered FREE_FIRST_ONLY on CURRENT, $0). PR C source-only work does not add live points until merged/deployed/observed.
