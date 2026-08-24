# Hermes free-first + identity v2 closeout

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**Paid calls this program:** 0  
**Status:** `IMPLEMENTED_NOT_LIVE`

This is not `HERMES_PERSISTENT_INTELLIGENCE_L6`. Identity skeleton exists; circulation is not closed. Official R9.2 score stays **59/100**.

## Source

| | |
|---|---|
| starting_main | `0b7bc9eb7b19f16b51404bbf96d93e77b292c019` |
| CURRENT | `0b7bc9eb-main-exact-phase2-20260823-185856` |
| SOURCE_COMMIT / BUILD_SHA | `0b7bc9eb…` |
| pin_match | true |
| process | portfolio_server PID started 2026-08-23 18:59 ET |
| this branch | `feat/r93-hermes-persistent-intel` |
| merge/promote | **not done** (no operator grant) |

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

## What is not proven live

- Hermes → artifact → graph (artifacts still 0)
- SearXNG job-level hard gate
- Embedding 503 decoupling
- Duplicate OAuth producer retirement
- CIO consuming TickerResearchState
- Natural NO_NEW_INFO replay with Hermes evidence loaded
- Postgres knowledge_* tables

## Runtime still split

Hermes CIO worker WorkingDirectory=CURRENT. Crontab `$PROJ` is still rebuild. Overnight 22:35 ET 2026-08-22 fired `SKIPPED_LLM_UNHEALTHY: model_missing` every hour.

## Maturity (no live credit for source-only)

identity L4→**L5 source** (not L6 live). free-first **L4 source**. Librarian epistemic **L3**. artifacts **L2**. overall **59/100 unchanged**.
