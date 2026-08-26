# TRADE_AI_R71_LIVING_THESIS_INTELLIGENCE_INTEGRATION_RESULT

## FINAL_STATUS: `READY_WITH_VERSIONED_CURSOR_DEPENDENCY`

merge_authorized=**NO** · deploy_authorized=**NO** · production thesis backfill=**NO**

Not `HOLD_ON_UNVERSIONED_LIVE_DEPENDENCY` — Cursor Gap A–F is **committed+pushed**.

---

## SOURCE

| field | value |
|---|---|
| main | `ff2037d45c582fa164fc6cb1136088fc80d8edcd` |
| PR397 | #397 (draft) |
| PR397_head | see latest `wt/symbol-thesis-universe` |
| Cursor_branch | `feat/two-way-watchlist-curation` |
| Cursor_head | `e683e90f9a24b9cd56399054da33cc6c3b4ba8bb` |
| Cursor_remediation_versioned | **true** |
| Cursor_PR | **none open** (preferred: land via own reviewed PR) |
| dependency_strategy | `DECLARE_SHA_CONSUME_DATA_PLANE_NO_WHOLESALE_MERGE` |

Declared in `config/r71_cursor_dependency.json`.

---

## CURSOR_WATCHLIST_FABRIC (map)

| component | class |
|---|---|
| sync_social_to_intelligence / social_sentiment_history | CONSUME_DIRECTLY |
| research_watchlist_discovery → watchlist_items | CONSUME_DIRECTLY |
| candidate_discovery_events | CONSUME_DIRECTLY |
| provenance origin_system/origin_detail | CONSUME_DIRECTLY |
| source-health migration / health_agent_policy | CONSUME_DIRECTLY / SHARED |
| cron_self_heal / job_coverage_monitor | SHARED_DEPENDENCY |
| install_watchlist_remediation_cron / drain / two_way_curation producers | **DO_NOT_IMPORT** |
| options_* / protection_pipeline | ACTIVE_TRADER_ONLY (not #397 blockers) |

Natural runs observed live: research_discovery rows, candidate_discovery_events (n=100), social fold (42 entities with social_score), crons installed.

**CURATION_AUTO_APPLY=1** preserved. Promotion ≠ research confidence. Bootstrap floor 0.65 ≠ measured alpha.

---

## RAG

| | |
|---|---|
| schedule | **crontab `0 */4 … rag_indexer.py` present** |
| job_coverage | **FALSE_POSITIVE_NOT_SCHEDULED** (`schedule_match='embedding'` misses script name) — fix on Cursor branch |
| freshness | embeddings last today; ~20k / 24h |
| duplicate cron | **not created** |
| RAG_first | yes · support + contradiction |

---

## HERMES

| | |
|---|---|
| coordinator crontab | scheduled `*/15` |
| class | EXPECTED_IDLE_OR_STALE_FALSE_POSITIVE (log idle ≠ missing schedule) |
| process_watchlist_agent_jobs | scheduled; log fresh |
| Flash | synthesis/challenge only after curated evidence |
| orphaned jobs | not reset via timestamp; replay-safe wakes |

---

## THESIS / DISCOVERY_TO_THESIS

Universe baseline unchanged (5135 / 125 RESEARCH_REQUIRED / 0 current symbol theses).

Recent research_discovery sample: **30** candidates → **0** expensive-material / **30** ignored (T3) — budget protection working.

| canary | tier | expensive | RAG sufficient | acquisition | Hermes gate |
|---|---|---|---|---|---|
| SCHG | T0_CURRENT_HOLDING | yes | no | PLANNED | BLOCKED_PENDING… |
| CSCO | T1_REENTRY_NEAR | yes | no | PLANNED | BLOCKED_PENDING… |
| ANET | T2_MATERIAL_WATCH | yes | yes | SKIP | READY_FOR_SYNTHESIS |

Membership ≠ evidence. social_score = derived only.

---

## MODULES ADDED (#397)

- `config/r71_cursor_dependency.json`
- `scripts/lib/r71_cursor_fabric_map.py`
- `scripts/lib/symbol_thesis_materiality.py` (T0–T4)
- `scripts/lib/symbol_thesis_supply_plane.py`
- `scripts/lib/thesis_research_context.py` (ThesisResearchContext@v1)
- `scripts/lib/symbol_thesis_event_wake.py` (existing `watch.new_signal` etc.; no auto thesis version)
- `scripts/lib/searxng_client.py` (shared SearXNG)
- `scripts/r71_health_audit.py`
- APIs: `/thesis-research-context/{SYM}`, `/r71-fabric-map`

---

## REMAINING

**P0** — Cursor branch own PR → main; fix job_coverage `rag_embeddings` schedule_match; natural-run soak of auto-apply + wake path with emit enabled under gate  
**P1** — CC front-end UNIVERSE & THESES panel; broader CI matrix green; Hermes coordinator log heartbeat hygiene  
**P2** — canary thesis creation only after separate production-write authorization  

---

## AUTHORITY / GIT / MERGE / DEPLOY

READ_ONLY_ADVISORY · MBI unchanged · broker/order/stop/risk/2FA = **0**  
owned changes committed+pushed on #397 · merge=**NO** · deploy=**NO** · no bulk 125 thesis backfill · no 5135 crawl
