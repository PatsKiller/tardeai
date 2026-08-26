# Transferson universe — two-stage acceptance (PRE_MERGE)

**Date:** 2026-08-25  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Data pin (read):** `55520666b4a742b9ed893c3231b414d089312363`  
**Loader:** local `chore/transferson-canonical-universe` — **not on CURRENT**  
**R17 auto-checkpoint:** blocked until `POST_DEPLOY_LIVE_ACCEPTANCE_PASS`  
**Remote push / deploy:** not performed

Evidence: `docs/_evidence/transferson_universe/PRE_MERGE_ACCEPTANCE.json`

The previous single `LIVE_ACCEPTANCE` gate was circular (B6 forbade deploy; deploy was required to pass). It is replaced by:

1. **`PRE_MERGE_SOURCE_ACCEPTANCE`** — this document (may pass off-CURRENT)
2. After separately authorized merge/deploy: **`POST_DEPLOY_LIVE_ACCEPTANCE`**
3. Only (2) may unblock R17

---

## Verdict

**PRE_MERGE_SOURCE_ACCEPTANCE_PASS**

**POST_DEPLOY_LIVE_ACCEPTANCE** — not run (no authorized deploy)  
**R17** — still blocked

---

## A. B5 — screener/discovery membership

Authorized screener rule (not a blind append):

- `screener_symbol_membership.present_this_run = true`
- `membership_status ∈ {active, present}`
- screener is `screener_config.enabled` **or** `finviz_screeners.active`
- symbol passes `is_held_equity_ticker` (CASH/CUSIP-shaped rejected)
- expired/dropped/stale excluded
- generic dump ids (`screener`, `social`, …) excluded because they are not enabled/active configs

Discovery: `hermes_discovery_candidates` status `READY_FOR_REVIEW` or `APPROVED_RESEARCH_ONLY` only.

| | n |
|---|---:|
| prior canonical (no screener/discovery wiring) | **4154** |
| authorized screener source | **2899** |
| overlap with prior canonical | **1644** |
| genuinely new members | **1255** |
| rejected/invalid | **0** |
| discovery READY/APPROVED | **97** (all already in union) |
| **new canonical unique count** | **5409** |

`4154 + 1255 = 5409`. The 5,536 figure was an **upper bound before overlap** (`4153 + 1383` unfiltered). It is not a denominator.

Missing authorized screener names: **[]**.  
Screener membership reason `SCREENER_ACTIVE` is T3-COLD and is **not** a scheduler dispatch reason.

---

## B. B1 — operator-facing denominators

Every important surface now consumes `TransfersonUniverseManifest@v1` **or** labels its narrower cohort.

| Consumer | Label |
|---|---|
| research scheduler | CANONICAL-ADAPTER |
| free-first | ADAPTER — `120 free-first circulated / 5409 universe` (live graph cohort) |
| graph/profile seeding | ADAPTER — seeds **from** canonical universe |
| CIO cognition pack | ADAPTER — bounded subset, not universe |
| Advisory | ADAPTER — Hub watchlist_items labeled *not Transferson universe* |
| Hermes scope | ADAPTER — S0–S2 scope-scored, labeled *not Transferson universe* |
| re-entry / watch | SOURCE |
| proposal research | CANONICAL-ADAPTER |
| Command Center | ADAPTER — theses projection labeled; thesis-covered = X / eligible subset Y |
| thesis coverage | ADAPTER |

Unacceptable “Universe = 120/126” strings are gone from current `scripts/*.py` and CC v3 src.

---

## C. B2 — identity spine

Hierarchy: `issuer_guid → security_guid → listing_guid → ticker alias`.

| | n |
|---|---:|
| issuer resolved | **2819** |
| security resolved | **2774** |
| listing resolved | **2774** |
| CANDIDATE chains (company/description sourced) | **2672** |
| CONFIRMED (TRS instrument id) | **102** |
| UNRESOLVED_WITH_REASON | **2635** (48.7%) |
| ticker-alias-only | (subset of unresolved) |
| `security_guid == ticker_guid` | **0** |
| duplicate security identities | **none** |

Company/description from `symbol_profiles.description_1s` and graph `company` yields **CANDIDATE**, not CONFIRMED.  
Identical company text across symbols (e.g. GOOG/GOOGL if descriptions match) **does not share a security_guid** (`share_class_unspecified_collision`).

**Unresolved ceiling (explicit, not 100%):** remaining unresolved is the ticker-only remainder after exhausting sourced CIK/CUSIP/ISIN/FIGI/company/description, plus share-class collisions. Those records are **non-authoritative**. R17 must not attach checkpoints to ticker strings. CANDIDATE GUIDs are not CONFIRMED and are not a license to start R17.

---

## D. B3 — graph coverage and provenance

CURRENT graph cohort remains **120 / 5409** (not mutated).

`seed_graph_from_universe` direction:

`canonical universe → identity → graph → free-first/research`

Evidence-only seed (empty root, not CURRENT): **5289** missing profiles created.  
If that seed were applied onto CURRENT’s existing 120: **5409 / 5409**.

New edges carry: source/target GUID, relationship type/class, source_type=`canonical_universe`, producer=`seed_graph_from_universe`, observed_at, recorded_at, valid_from/valid_to, status, confidence, source_refs. Provenance **7598 / 7598**.

Four traversals (NOC CONFIRMED; NVDA/AAPL now CANDIDATE): industry/sector reverse works; `not_supply_chain=true`; peers are not inferred from shared sector/industry.

---

## E. B4 — 126

**126 = UNRESOLVED_WITH_REASON**

Not a denominator. Not dropped. Still no exact producer.

---

## F. PRE_MERGE checks

| Check | Result |
|---|---|
| canonical unique after screener | **5409** |
| membership union of wired sources | complete (screener missing []) |
| missing current holdings | **0** (19/19) |
| sold/re-entry retained | ADBE T3 WAIT remains; ALXO NEAR → T1; CSCO NEAR + proposal → T0-PROP |
| proposal/watch/incubator/screener/discovery missing | all `[]` |
| scheduler vs canonical | 3105 vs 5409; only_in_scheduler **0**; extras are screener-only + Hermes-rank>200 + WAIT/history |
| SCHD sell-sim | TIER_CHANGED only; added/removed empty |
| tests | 66 related passed (`test_transferson_universe`, identity, skip-gate, projection, thesis filter) |
| CURRENT mutated | **no** |

---

## G. After separately authorized merge/deploy

Re-run the same reconciliation on the deployed CURRENT pin and emit exactly one of:

`POST_DEPLOY_LIVE_ACCEPTANCE_PASS`  
`POST_DEPLOY_LIVE_ACCEPTANCE_BLOCKED`

Required then: `source_sha == CURRENT`, counts match live stores, no private denominators, scheduled consumers read the contract, graph/free-first show coverage not universe, identity survives restart, durable manifest/diff, no execution authority change.

Only `POST_DEPLOY_LIVE_ACCEPTANCE_PASS` may unblock R17 auto-checkpoints.
