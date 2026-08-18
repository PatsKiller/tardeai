# CIO + Advisory — Living Operator Status

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Revision** | **R4 — 2026-08-18T16:04Z** (closed-loop P0 live after exact-main `244b7a41`) |
| **Status** | **RECONCILIATION / PARTIAL_WITH_EXPLICIT_GAPS** |
| **Authority** | `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0` · `broker_write=NONE` |
| **Owner** | Alex desk · operator: John |
| **Live CURRENT** | `244b7a41-main-exact-phase2-20260818-120315` |
| **CURRENT SHA** | `244b7a41b0c9e973e2ea874c8e0b2c3986fd2982` |
| **origin/main** | `244b7a41b0c9e973e2ea874c8e0b2c3986fd2982` |
| **Provenance** | **CURRENT_MATCH** (promoted after #370) |
| **UI chip** | `3.14+msyurbz9` · `244b7a41` |
| **Google Drive file** | [CIO_AND_ADVISORY_LIVING_STATUS.md](https://drive.google.com/file/d/1scL90dCZa7uOK9_sojX-MNBWHfrViWMi/view) |
| **Drive folder** | [docs / investment-office](https://drive.google.com/drive/folders/1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8) |

> Operator confirmation sheet. **Not marketing.** Every status below is from a 2026-08-18T15:58–16:02Z live probe plus the applied closed-loop reconcile.  
> Do not treat R1–R3 as current evidence.

**Prior program:** `TRADE_AI_CLOSED_LOOP_AUTONOMOUS_INTELLIGENCE_FINAL_RESULT`  
**Result:** **EXECUTED IN RECONCILIATION MODE (this revision).** The Cursor prompt never returned a packet. This run shipped `IntelligenceLineage@v1`, an append-only Hermes drain, a 7-day EXPIRED observer (no invented P&L), GET `/api/v3/intelligence`, and a CC Closed Loop tab. Lineage IDs below are **real**, rebuilt from live CIO evidence.

---

## 1. One-screen truth (live)

| Surface | Status | Live evidence |
|---|---|---|
| Command Center SPA | **WORKING** | `/v3/*` 200 HTML; chip `3.14+msyurbz9` |
| Release / CURRENT vs main | **WORKING** | CURRENT = origin/main `244b7a41` after exact-main promote |
| `/api/v3/cio` | **WORKING_DEGRADED** | 200, thesis v5; snapshot missing **reconciliation**; delegation **pending=108** |
| `/api/v3/advisory` | **WORKING_DEGRADED** | 200, 58 rows, **OPINION_FRESHNESS=EXPIRED**, health DEGRADED |
| `/api/v3/intelligence` | **WORKING** | 200, 13 lineages, pending 108, latest `lin_cebe7bbaba9921e9aeb6` |
| Agent maturity | **WORKING_DEGRADED** | fail-soft repo path from #364/#365 |
| Memory | **SHADOW** | DurableJsonl, 2 records (1 ADMITTED, 1 EXPIRED), influence flag ACTIVE_ADVISORY, **MBI=0** |
| Learning | **WORKING_DEGRADED** | 204 cases, **201 OPEN / 3 AWAITING / 0 matured / 0 scored**, 7 RATIFIED_CONTEXT, 0 ADVISORY_ACTIVE |
| Closed-loop lineage store | **WORKING** (data plane) | `intelligence_lineages.json` 13 lineages @ 15:58:30Z |
| Hermes challenge queue | **WORKING_DEGRADED** | **313 events** (history kept); **108 pending** after drain; 210 ENQUEUED rows still in history |
| Hermes research worker | **BROKEN** | `hermes-autonomous-loop` + `hermes-deep-research-local` still **failed** (Ollama timeout MU/STLD) |
| System Telegram daily | **PROVEN_LIVE** | `message_id=47831` at 2026-08-18T12:34:55Z |
| System Telegram canary | **PROVEN_LIVE** | `message_id=47832` |
| CIO financial Telegram auto-send | **OFF_BY_POLICY** | 0 financial sends; silence explained |
| Authority | **PROVEN_LIVE** | READ_ONLY_ADVISORY, MBI=0, 0 broker/order/stop/risk/2FA mutations |

---

## 2. Source / release (fetched, not assumed)

| Item | Exact value |
|---|---|
| CURRENT SHA | `244b7a41b0c9e973e2ea874c8e0b2c3986fd2982` |
| CURRENT path | `/home/johnclaw/trade-ai-releases/portfolio-server/244b7a41-main-exact-phase2-20260818-120315` |
| Shared CIO dir | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio` (CURRENT `data/cio` symlink) |
| Classification | **CURRENT_MATCH** |
| Recent merges | **#370** closed-loop P0, #369 R3 docs, #368 living R2, #367 guard ledger, #365/#364 CC gaps |
| This packet | #370 `244b7a41` |

Do **not** treat committed `docs/investment-office/RELEASE_MANIFEST.md` (still pins `aa037b73`) as CURRENT.

---

## 3. Intelligence closed loop (required links)

| Link | Status | Last success | Today | Persist | Runtime owner | CC surface | Known gap |
|---|---|---|---|---|---|---|---|
| SECTOR / INDUSTRY / ASSET DISCOVERY | **ARMED_NOT_PROVEN** | last hermes loop **failed** 2026-08-17T21:13 EDT | 0 proven | Hermes/DB | `hermes-autonomous-loop` **failed** | none dedicated | Ollama gemma3:12b timeout on MU then STLD |
| RESEARCH REQUEST | **WORKING_DEGRADED** | enqueue still happens | drain applied | `hermes_challenge_queue.jsonl` | CIO material-scan | Closed Loop + CIO delegation | 108 still pending; completing worker down |
| RESEARCH EXECUTION | **BROKEN** | loop failed | 0 proven this run | Hermes | same failed unit | Hermes hub | requests do not complete |
| MEMORY ADMISSION | **WORKING** | mem_d00f5067… SCHD | admissions 0 today | `aif_memory.jsonl` | DurableJsonl | `/api/v3/maturity/memory` | not auto-bridged from completed research |
| AUTOMATIC MEMORY RETRIEVAL | **SHADOW** | 7 earlier today | retrieval receipts exist | same | memory provider | maturity memory | not proven to change advice |
| MEMORY ADVISORY USE | **SHADOW** | eligible_runs=0 | 0 | influence store | influence gate | influence API | do not read ACTIVE_ADVISORY as product |
| OUTCOME OBSERVER | **WIRED / NOT_YET_DUE** | observer ran 15:58:30Z | **0 expired** | `cio_production_cases.jsonl` | outcome-scorer 18:30 + this CLI | Closed Loop / learning | all 204 cases younger than 7d |
| SCORING | **WIRED / NOT_YET_DUE** | Darwin only after EXPIRED/POSITIVE/NEGATIVE/FLAT | **0 scored** | same | same timer | same | nothing matured |
| REFLECTION | **WORKING** | 2026-08-18T01:50:00Z | 1 | CIO reflect | 21:50 timer | maturity learning | does not consume scored outcomes |
| LESSON RATIFICATION | **WORKING** | 7 RATIFIED_CONTEXT + 5 RETIRED | 0 new | lessons store | prior | same | not all linked |
| LESSON REUSE | **NOT_PROVEN** | 0 | 0 | influence | gate | influence API | no reuse_decision_id |

---

## 4. Closed-loop lineage proof

**IntelligenceLineage@v1:** **PRESENT** at `data/cio/intelligence_lineages.json` (generated 2026-08-18T15:58:30.207511+00:00).  
13 lineages. Status mix: 8 ADVISORY_USED · 5 OUTCOME_PENDING.  
IDs are rebuilt from live symbols / streams / memory / cases. **No invented POSITIVE/NEGATIVE.**

### Latest LIVE_FORWARD lineage (SCHD — richest real chain)

| Field | Value |
|---|---|
| lineage_id | `lin_be74ab5d25c949dd980c` |
| discovery_id | `disc_1cc5e00216ad1726bcd4` |
| research_request_ids | 55 real ids; first `hermes-challenge-4f77d3cad269`, `res_0c233a1b58c3`, … |
| research_result_ids | **empty** (no RESOLVED research completion events) |
| memory_ids | `mem_d00f5067563bf5e77d95b3849ce0d426` |
| memory_retrieval_ids | `case_1bd29537f129159417d4:retrieval` |
| cio_case_id | `case_1bd29537f129159417d4` |
| decision_id | `dec_b0376fefcb010302` |
| advisory_use | not set on this row (status OUTCOME_PENDING) |
| outcome_id | **MISSING** (case still young) |
| score_id | **MISSING** |
| reflection_id | **MISSING** |
| lesson_id | **MISSING** |
| reuse_decision_id | **MISSING** |

### Other real lineage_ids (this rebuild)

`lin_cebe7bbaba9921e9aeb6` · `lin_749e193d568f81f99b5f` · `lin_27d3fc8faf50bcfc007c` (JEPI) · `lin_123dd4eb1d0350a7b313` · `lin_08fa032d58b5aeb3595d` · `lin_355e722320d4e8351638` · `lin_3f66c0b8f4195755049e` · `lin_3c3396d00d5ad22104a3` · `lin_22aab6421808f1ed2881` (REENTRY) · `lin_f798f6b6fa335720010f` (CASH) · `lin_352c8f1a3c10bad76664` (BOOK) · `lin_ba3c073169c3a2ddd41c` (OFFICE)

Do not treat CIO notification `lineage_count=9` as IntelligenceLineage.

---

## 5. Daily operating proof — 2026-08-18 (reconcile @ 15:58:30Z)

| Metric | Count / value |
|---|---|
| research requested (history ENQUEUED) | **210** events (unchanged; never deleted) |
| research pending (latest-per-stream) | **108** after drain |
| drain applied | test/fixture cancel **27** · duplicate expire **74** · stale>7d **1** · applied_n **102** · after_events **313** |
| research completed today | **NOT_PROVEN** (Hermes loop failed 2026-08-17) |
| cases | **204** (201 OPEN, 3 AWAITING) |
| outcomes matured / scored | **0 / 0** (horizon 7d; all cases young; 1 unknown timestamp skipped) |
| invented POSITIVE/NEGATIVE | **0** |
| lineages | **13** |
| memory admissions today | **0** (lifetime ADMITTED 1, EXPIRED 1) |
| Telegram system heartbeat | **1** (`message_id=47831`) |
| Telegram financial sends | **0** |
| MBI / broker writes | **0 / NONE** |

---

## 6. Operator product (Command Center)

| Route | Purpose | Page/API | After this packet | Empty / stale |
|---|---|---|---|---|
| `/v3/advisory` | Opinion table | **WORKING_DEGRADED** | unchanged | opinions EXPIRED |
| `/v3/cio` | Thesis / plans / books | **WORKING_DEGRADED** | delegation pending-count **after promote** | reconciliation missing |
| `/v3/intelligence?tab=closed-loop` | Lineage table | **WORKING** | Closed Loop tab + `/api/v3/intelligence` 200 | 13 rows; 0 outcomes |
| `/v3/closed-loop` | alias | **WORKING** | redirects to intelligence tab | live on CURRENT |
| `/v3/health?tab=daily-intelligence` | Daily proof | **WORKING** | unchanged | DEGRADED components |
| Memory / Learning | maturity APIs | **SHADOW / DEGRADED** | observer will expire at 7d | 0 matured |

---

## 7. Telegram truth

Unchanged from R3. SYSTEM daily **47831**, canary **47832**. CIO financial auto-send **off** (0 sends, silence explained). Conversational CIO bot running. `CIO_TELEGRAM_INTERDICT=0` effective via drop-in **25**.

---

## 8. Configuration truth (effective)

Unchanged from R3 on flags. **Do not describe ACTIVE_ADVISORY as “learning is changing advice.”** Metrics: eligible_runs=0, advisory_changes=0, MBI=0.

New runtime hooks:

| Hook | Behavior |
|---|---|
| `scripts/closed_loop_reconcile.py` | dry-run default; `--apply` appends drain + observe + rebuild |
| `scripts/advisory_outcome_scorer.py --once` | existing 18:30 timer now also observes overdue cases + rebuilds lineage |
| `GET /api/v3/intelligence` | GET-only lineage / challenges / closed-loop |

---

## 9. CIO / Advisory live numbers

**CIO:** thesis `desk@v5`. Snapshot still missing reconciliation. Plans ~30 (mostly draft). Actions 15 OPEN. **CURRENT delegation** reports challenges **pending=108** (EXPIRED 75 · CANCELLED 27 · ENQUEUED 108). History still has 210 ENQUEUED rows (313 events).

**Advisory:** 58 rows. Health DEGRADED (Flash/Pro opinions EXPIRED). FACT_FRESHNESS=CURRENT on desk build; **do not call holdings CURRENT** (underlying snapshot still 2026-08-14). SCHD taxable lots ≈406.54 / IRA ≈6155.25.

---

## 10. Runtime topology

Persistent: `portfolio-server` CURRENT `244b7a41`, `cio-governed-bridge`, `tradeai-cio-telegram`, heartbeat-receiver.

**Failed units (still):** `hermes-autonomous-loop.service` (TimeoutStart / Ollama 300s on MU, then killed at 10m), `hermes-deep-research-local.service`.

Outcome scorer timer **18:30 EDT** now owns the durable observer (runs from CURRENT after promote).

---

## 11. FINAL_MATURITY_GAP_REGISTER@v1

| gap_id | domain | severity | current | notes |
|---|---|---|---|---|
| G-PRIOR-01 | program | **closed** | packet executed in RECONCILIATION mode | this revision |
| G-REL-01 | release | **closed** | CURRENT = origin/main `244b7a41` | exact-main promote after #370 |
| G-LOOP-01 | lineage | **closed** | store + live GET 200 + 13 real IDs | SCHD `lin_be74ab5d25c949dd980c` |
| G-RES-01 | research | **partial** | drain 210→108 pending; worker still failed | completing worker **not** claimed |
| G-OUT-01 | outcomes | **partial** | observer wired; 0 due | will expire only after 7d |
| G-CC-01 | CC | **closed** | Closed Loop tab + `/v3/closed-loop` live | 13 rows; no fake outcomes |
| G-REC-01 | CIO | **P1** | reconciliation domain missing | unchanged |
| G-ACT-01 | CIO | **P1** | 12 system-backfill OPEN | unchanged |
| G-PLN-01 | CIO | **P1** | mostly draft plans | unchanged |
| G-OPN-01 | Advisory | **P1** | Flash/Pro EXPIRED | unchanged |
| G-HLD-01 | Advisory | **P1** | desk CURRENT vs as_of 2026-08-14 | unchanged |
| G-INF-01 | influence | **P1** | ACTIVE_ADVISORY flags, runs=0 | unchanged |
| G-HER-01 | Hermes | **P2** | failed loop remains | drain did **not** delete history |
| G-MAN-01 | docs | **P1** | RELEASE_MANIFEST pins aa037b73 | unchanged |
| G-DOC-01 | docs | **closed** | living sheet on this revision | Drive replace in place |

Acceptance: G-RES-01 is **not** fully closed until a Hermes run completes real research. G-OUT-01 is **not** fully closed until a case actually matures.

---

## 12. Operator confirmation (R4)

Hard-reload `/v3/` now.

- [ ] Chip `3.14+msyurbz9` · SHA `244b7a41`
- [ ] `/api/v3/intelligence` 200, `lineage_count=13`, `pending_challenges=108`
- [ ] `/v3/intelligence?tab=closed-loop` shows SCHD `lin_be74ab5d25c949dd980c`
- [ ] `/api/v3/cio/delegation` challenges.pending = **108** (not 210)
- [ ] Hermes queue file still has **210 ENQUEUED** historical rows
- [ ] Learning still 0 matured (honest)
- [ ] SYSTEM Telegram today: message **47831**
- [ ] Drive header says **R4 — 2026-08-18T16:04Z**
- [ ] MBI still 0; no broker writes

---

## 13. How we update

Same filename. Next rewrite is **R5** if a later promote or drain changes the numbers. Replace Drive file `1scL90dCZa7uOK9_sojX-MNBWHfrViWMi` in place.

---

## 14. Revision log

| Rev | UTC | What changed |
|---|---|---|
| R1 | 2026-08-18T15:15Z | First sheet after #364/#365. Pre-closed-loop. |
| R2 | 2026-08-18T15:40Z | Post-closed-loop reconciliation. Prior program did not run. |
| R3 | 2026-08-18T15:42Z | Exact-main promote `66c733a4`. Loop still not proven. |
| **R4** | **2026-08-18T16:04Z** | Unrun packet executed and promoted `244b7a41`. Live `/api/v3/intelligence` 200, 13 IDs, pending 108. Hermes worker still failed. 0 matured cases. |

*End of R4. GitHub + Drive + CURRENT tell this same story.*
