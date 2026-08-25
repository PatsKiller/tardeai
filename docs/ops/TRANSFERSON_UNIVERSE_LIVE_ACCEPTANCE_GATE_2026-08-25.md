# Transferson canonical universe — live CURRENT/DB acceptance gate

**Date:** 2026-08-25  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**CURRENT pin:** `55520666b4a742b9ed893c3231b414d089312363`  
**Loader:** local `chore/transferson-canonical-universe` (worktree) against CURRENT files + live `trade_ai` DB  
**R17 auto-checkpoint:** still blocked  
**Remote push:** not performed · **Deploy:** not performed

Evidence: `docs/_evidence/transferson_universe/LIVE_ACCEPTANCE.json`

---

## Verdict

**LIVE_ACCEPTANCE_BLOCKED**

The skeleton is still the right skeleton. The live body now runs through it. Acceptance is **not** complete because operator-facing denominators, the live identity spine, graph provenance, 126, and screener membership remain open. Do not authorize push/merge. Do not start R17.

---

## 1. Live CURRENT counts

Recalculated. Historical 3,061 is **not** current.

| Metric | Live |
|---|---:|
| `canonical_universe_count` | **4153** |
| `graph_profiled_count` | **120** |
| `graph_coverage_pct` | **2.8895%** |
| `graph_coverage` | `120 graph-profiled / 4153 universe` |
| identity-resolved (`security_guid`) | **103** |
| identity-unresolved | **4050** |
| T0-HOLD | **19** |
| T0-PROP | **31** |
| T1-WATCH | **323** |
| T2-INCUB | **148** |
| T3-COLD | **3632** |

`research_due_count` / `research_executed_count` are 0 here (not a research run).

---

## 2. Membership-source reconciliation

Raw unique counts (CASH excluded):

| Source | Unique |
|---|---:|
| current holdings (equity) | 19 |
| unresolved CUSIPs | 3 |
| historical/sold + re-entry desk | 107 |
| READY/NEAR re-entry | 21 |
| WAIT / OVERBOUGHT WAIT / MISSING* retained | 76 |
| active proposals | 31 |
| recent proposals (21d) | 99 |
| active watch directives | 119 |
| Hermes rank-qualified (rank ≤ 200) | 688 |
| Hermes rank history (all) | 2926 |
| incubator active | 405 |
| symbol_profiles (cold) | 2822 |
| graph profiles | 120 |
| scope-governor S3 overlay | 4472 (3024 already in canonical; **not an add**) |

Naive sum of membership sources = **6651**. Unique union of wired membership sources = **4153**.

**canonical universe = UNIQUE UNION(wired authorized sources) = 4153. `only_in_union = 0`. `only_in_canonical = 0`.**

Overlaps (do not add): holdings∩reentry 10, holdings∩graph 19, watch∩hermes-T1 84, incubator∩profiles 234, proposals active∩recent 15.

Discovery/screener is **not wired**:

- `hermes_discovery_candidates` READY/APPROVED tickers **97 / 97** in canonical.
- `screener_symbol_membership` present-this-run tickers **3119**, of which **1383 missing** from canonical.

Scope-governor is a demotion overlay (ADBE WAIT + S3 → T3-COLD, still a member), not a membership add.

---

## 3. Holdings coverage

`held_equity_tickers()` = 19. **`missing_current_holdings = 0`.**

Every current holding is T0-HOLD, identity CONFIRMED, with a `security_guid` that is **not** equal to `ticker_guid`:

AMANX, ARKX, BAH, BND, CSWC, DIV, JEPI, LDOS, NOC, PFLT, RTX, SCHD, SCHG, SPCX, SRNE, V, XAR, XLB, XLI.

CASH remains excluded. CUSIPs **12507E201 / 543354104 / 628518102** remain in the universe as `UNRESOLVED_IDENTITY` (not T0-HOLD).

---

## 4. Sold / re-entry retention

Re-entry desk 107 names, **0 missing**. Live states: READY TO REVIEW 3, NEAR ENTRY 18, WAIT 57, OVERBOUGHT WAIT 3, MISSING PLAN 6, MISSING MARKET 11, CURRENTLY HELD 10. No live `OVERSOLD` row today.

| Rule | Live example |
|---|---|
| SOLD → remains member | **ADBE** T3-COLD, WAIT, `sold_history_present=true` (S3 demotion; still a member) |
| READY/NEAR → may promote to T1 | **ALXO** T1-WATCH NEAR ENTRY (`REENTRY_READY_NEAR`) |
| WAIT may demote but does not disappear | **AMAGX** T3-COLD MISSING MARKET; **ADBE** WAIT |
| Other reasons can keep WAIT at T1 | **ANET** WAIT remains T1 via HERMES_RANK_T1 / watch / incubator — WAIT did not *promote* it |
| Proposal can outrank READY/NEAR | **CSCO** NEAR ENTRY is T0-PROP via `ACTIVE_PROPOSAL` |

A tier change is not an add/remove (see §11).

---

## 5. Proposal / watch / incubator / Hermes-T1

| Set | n | missing |
|---|---:|---|
| active proposals | 31 | `[]` |
| active watch directives | 119 | `[]` |
| Hermes rank ≤ 200 | 688 | `[]` |
| incubator active | 405 | `[]` |

Hermes discovery READY/APPROVED: 97 missing 0. Active screener membership is the gap in §2 / blocker B5.

---

## 6. Scheduler reconciliation

| | n |
|---|---:|
| institutional canonical universe | 4153 |
| `research_scheduler.load_universe()` index | 3105 |
| only_in_canonical | **1048** |
| only_in_scheduler | **0** |
| tier disagreement | **0** |

only_in_canonical reason mass: `HERMES_RANK` 1026, `NO_SCHEDULER_REASON` 1038, `GRAPH_PROFILE` 15, `REENTRY_HISTORY` 12, `SYMBOL_PROFILE` 10, `UNRESOLVED_IDENTITY` 3.

**Institutional membership** includes every Hermes-scored name plus WAIT/sold/graph-only.  
**Active research-scheduler membership** is `SCHEDULER_REASONS` only (holdings, proposals, READY/NEAR, watch, incubator, symbol_profiles, Hermes **T1**). Rank > 200 names stay in the institution and out of the scheduler. That is intentional, not a silent mismatch.

Historical 3,061 (2026-08-22 scheduler split 22/30/331/141/2537) is the ancestor of today's **3105** scheduler index, not of 4153.

---

## 7. 120 is graph coverage

`120 / 4153`

- graph-profiled: 120 (includes the 3 CUSIP-shaped graph rows)
- not-yet-graph-profiled: 4033
- identity-resolved but not graph-profiled: **0** (the 103 CONFIRMED `security_guid`s all sit on the graph cohort via TRS)
- unresolved identity: 4050

`seed_graph_from_universe` exists and is unit-tested. **Not applied to CURRENT.**

String search: no `120 universe` / `126 universe` in `scripts/*.py` or `apps/command-center-v3/src`. Remaining mentions:

- `docs/_evidence/transferson_universe/LIVE_MANIFEST_SUMMARY.json` — **historical file-union**, now labeled
- R15.2 / R16.1 closeouts — historical free-first “120 names” circulation
- `cio_persistent_cognition.py` comment “Do not inject all 120 names” — **operator-facing leftover** (blocker B1)

---

## 8. 126

**126 = UNRESOLVED_WITH_REASON**

No exact producer, query, or function emits 126 as a universe denominator.

Coincidences, **not** producers:

1. holdings 19 + reentry 107 **naive sum** = 126. Unique union is **116** (overlap 10). No code path adds without union.
2. `watch_directives` SQL `COUNT(DISTINCT spec.symbol)` = 120; normalized unique = 119.
3. `docs/ops/RESEARCH_QUALITY_AND_THESIS_GAP_2026-08-22.md` “T0 126” is **research-due arithmetic** in a 545-call day, not membership.

---

## 9. Identity acceptance

| Status | n |
|---|---:|
| issuer GUID on manifest | **0** |
| security GUID | **103** |
| listing GUID | **103** |
| ticker-alias-only | **17** |
| `UNRESOLVED_WITH_REASON` | **4050** |
| CANDIDATE chains | **0** |
| CONFIRMED | **103** |

Proofs that **pass**:

- `security_guid` fabricated solely from ticker text: **0**
- `security_guid == ticker_guid`: **0**
- duplicate security identities: **none**
- GOOG / GOOGL both present, both unresolved, not collapsed (no GUID to collapse)

Wiring defect: CURRENT graph profiles already carry **103 `issuer_guid`s** (company-bearing CANDIDATE issuers). The universe loader copies TRS `security_guid` and does **not** copy graph `issuer_guid` / `company`. Manifest issuer count stays 0. That is why R17 still cannot attach a populated issuer→security→listing spine for the live book.

---

## 10. Multi-lineage

Representative names (NOC, SCHD, ADBE, ALXO, ANET, plus NVDA/AAPL/MSFT cold):

| Traversal | Result |
|---|---|
| A. ticker / identity | Graph LINEAR ticker→issuer on profiled names. Manifest listing GUID only where TRS security_guid exists. NVDA/AAPL/MSFT: unresolved, no graph profile. |
| B. industry | NOC Aerospace & Defense → 52 related. `not_supply_chain=true`. |
| C. sector | NOC Industrials → 355 related. `not_supply_chain=true`. |
| D. catalyst / mention | Shared generic `earnings` GUID; NOC reverse 42. Not article-level. |
| Reverse | Catalyst GUID → related symbols works. |
| Provenance | Live CURRENT edges have `relationship_guid` / source / target / kind. **`producer` / `source_type` / `source_refs` = 0** (code emits them for new edges; CURRENT graph not re-seeded). |
| Fake supplier/customer | Graph `peers` empty. Shared sector/industry explicitly `not_supply_chain`. |

---

## 11. Manifest / diff

Canonical manifest (gzipped) + slim summary + securities index written under `docs/_evidence/transferson_universe/`.

SCHD sell-sim (drop from holdings, rebuild):

- before T0-HOLD CURRENTLY_HELD
- after T1-WATCH (HERMES_RANK_T1 + watch + reentry history)
- **added = [] · removed = [] · `TIER_CHANGED` only**
- false remove+add: **false**

`as_of`: 2026-08-25T20:05:22Z  
`source_pin`: `55520666b4a742b9ed893c3231b414d089312363`

---

## 12. Consumer audit

| Consumer | Label |
|---|---|
| research scheduler | **CANONICAL-ADAPTER** |
| free-first | **ADAPTER** (`not_the_canonical_universe=true`) |
| ticker graph / profile seeding | **NOT_MIGRATED** (fn exists, CURRENT still 120 profiles) |
| CIO intelligence fabric | **LEGACY_PARTIAL** (“all 120 names”) |
| Advisory | **NOT_MIGRATED** (private watch-hub / reentry desk counts) |
| Hermes | **NOT_MIGRATED** (scope-governor universe is separate) |
| re-entry / watch | **SOURCE** (feeds membership; does not read the manifest) |
| proposal research | **CANONICAL-ADAPTER** (via scheduler) |
| Command Center | **NOT_MIGRATED** (`UniverseProjection@v1`) |
| thesis / coverage metrics | **LEGACY_PARTIAL** (`held_equity_tickers` correct; theses projection old) |

This is **not** complete: operator-facing denominators still use private universes.

---

## 13. Decision

**LIVE_ACCEPTANCE_BLOCKED**

Exact blockers:

1. **B1** Operator-facing denominators not on the canonical contract (CC theses, Advisory, CIO 120-name comment, Hermes scope universe).
2. **B2** Live identity spine not populated (`issuer_guid=0` on manifest; 4050/4153 unresolved). Semantics pass; coverage does not.
3. **B3** Graph coverage 120/4153; CURRENT not seeded; live edges lack provenance fields.
4. **B4** `126 = UNRESOLVED_WITH_REASON`.
5. **B5** Active screener membership 1383 names not in the union and not wired.
6. **B6** Loader is not on the CURRENT pin. Measured, not deployed.

Do not push. Do not merge. Do not deploy. Do not start R17 auto-checkpoints.

Local working-tree note: `_q` now imports `scripts.db_adapter` first (fail-soft `db_adapter` was why the earlier run reported 120/120 with empty DB). That defect fix is required for this measurement. It is **not** a deploy.
