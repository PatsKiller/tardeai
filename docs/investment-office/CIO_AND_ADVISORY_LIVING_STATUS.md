# CIO + Advisory — Living Operator Status

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Revision** | **R6.2 — 2026-08-18T21:38Z** (producer repair + promoted + CURRENT-native VALID job) |
| **Status** | **PARTIAL_WITH_EXPLICIT_GAPS** — producers fixed, PR #377 merged, CURRENT `40934ca8`. VALID jobs + CANDIDATE memory retrieved. Overlay still 108. Hermes units still failed. |
| **Authority** | `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0` · `broker_write=NONE` |
| **Owner** | Alex desk · operator: John |
| **Live CURRENT** | `40934ca8-main-exact-phase2-20260818-173544` |
| **CURRENT SHA** | `40934ca809e3cff18f0aacb3d59e00d7a9b15421` |
| **origin/main at authoring** | `40934ca809e3cff18f0aacb3d59e00d7a9b15421` (PR #377) |
| **Provenance** | **CURRENT_MATCH** with origin/main after promote. |
| **UI chip** | `3.14+msz6mwp7` · `40934ca8` |
| **Google Drive file** | [CIO_AND_ADVISORY_LIVING_STATUS.md](https://drive.google.com/file/d/1scL90dCZa7uOK9_sojX-MNBWHfrViWMi/view) |
| **Drive folder** | [docs / investment-office](https://drive.google.com/drive/folders/1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8) |

> R6.1 documented the blocks and stopped. That was wrong. This revision names the producers, the patches, and the live IDs. No invented PnL.

---

## 0. Direct answer (why R6.1 did not fix)

R6.1 **was** written and Drive-replaced (file `1scL90dCZa7uOK9_sojX-MNBWHfrViWMi`, 21:08Z). It correctly said the SCHD canary was `INSUFFICIENT` and memory refused.

It did **not** patch the producers. Honest refusal is not completion. The canary already had answer text; critique never saw it.

| Block | Root cause | Fix this revision |
|---|---|---|
| Critique `empty_summary` + `no_sources` | Bridge sent only empty `context_snapshot`. Request already had `catalyst.events`. Model said “no events.” `stamp_result` left top-level `summary` blank. Critique only reads `summary` / `sources`. | Pass `compact_catalyst(request)` into the model. Synthesize `summary` from answers/findings. Ground `sources` from catalyst `event_id`s + citations. |
| `as_of=2025-07-11` | Model date copied to both `as_of` and `completed_ts`. Persist then overwrote `completed_ts` with `as_of`. | `coerce_as_of` rejects stamps older than 14d. `completed_ts` is worker-now. Persist no longer clobbers it. |
| Memory refused | (1) empty summary → INSUFFICIENT. (2) `source_kind=research_result` is not in `VALID_SOURCE_CLASSES`. (3) full summary contained the words `holdings`/`price` (gap language) and tripped `forbidden_authoritative_truth`. | Use allowed class `research_artifact`. Pick a memory-safe paragraph (findings first). Do **not** weaken the forbidden scanner. |
| Confidence fail on first retry | `validate_result` rejected `confidence=0`. | Allow 0; clamp out-of-range in the backend. |
| CURRENT hijack 16:57/17:08 EDT | Rebuild-tree `deploy_portfolio_server.sh` rsyncs a timestamped dir and `ln -sfn` CURRENT. That copy hardcodes `TRADEAI_CC_SOURCE_PR=296`. | Guard: refuse to overwrite a `SOURCE_COMMIT` pin unless `FORCE_OVERWRITE_EXACT_MAIN=1`. Applied in-repo **and** on the live rebuild-tree script. |

Admission gates were not loosened to get green.

---

## 1. One-screen truth (21:32Z)

| Surface | Status | Live evidence |
|---|---|---|
| Command Center SPA | **WORKING** | chip `3.14+msz6mwp7` |
| Release | **WORKING** | CURRENT `40934ca8` = origin/main (PR #377 promoted) |
| `/api/v3/cio` | **WORKING** | 200 (recon producer present) |
| `/api/v3/advisory` | **WORKING_DEGRADED** | HOLDINGS_SOURCE_FRESHNESS=STALE; OPINION_FRESHNESS=EXPIRED |
| `/api/v3/intelligence` | **WORKING** | 13 lineages |
| `/api/v3/intelligence/queue` | **WORKING** | **108 pending overlay** (structured jobs completed; overlay not auto-expired) |
| `/api/v3/intelligence/reconciliation` | **WORKING** | 200; `ok=false` while overlay backlog exists |
| Memory | **SHADOW** | 2 ACTIVE + 1 EXPIRED + **3 CANDIDATE** (`mem_12ab1b21…`, `mem_b91739ce…`, `mem_3ec086de…`). MBI=0. |
| Learning | **WORKING_DEGRADED** | observer **PROVEN_IDLE**; next_due **2026-08-22T14:23:21Z** |
| Hermes autonomous-loop | **BROKEN** | still failed (Aug 17 MU/STLD timeout) |
| Hermes deep-research-local | **BROKEN** | still failed (DB SSL after 27b) |
| CIO Hermes worker | **PROVEN live-bridge** | two jobs below; timer still catalyst/stub unless promoted |
| Authority | **PROVEN_LIVE** | READ_ONLY_ADVISORY; MBI=0; 0 broker/order/stop/risk/2FA |

---

## 2. Live jobs this run

Worker invoked from worktree `fix/hermes-quality-producer` against live `data/cio` (CURRENT cwd). Backend: `BridgeHermesResearchBackend` :8766.

### 2a. SCHD — `res_e14a2fdac29c` → `rr_2ce371c209dc`

| Field | Value |
|---|---|
| plan | `plan_d45c7c4af5a6` |
| first attempt | failed `confidence_out_of_range` (model 0) — then validator fixed and retried |
| backend | live bridge, latency **4137 ms** |
| critique | **VALID** · sources=`cat_schd_2026-08-18_analyst_upgrade_a05f99` |
| model used catalyst | yes — q2 cites the event_id; finding names the 2026-08-18 upgrade |
| persist as_of | `2026-08-18T15:20:15.993785+00:00` (model; same day; kept) |
| persist completed_ts | same (this job used the old persist clobber) |
| plan attach | **YES** — `hermes_research` + findings, `result_id=rr_2ce371c209dc` |
| memory | **CANDIDATE** `mem_12ab1b21ba5055a7aebfeb4365cf070e` — retrieved. Content is the finding, not the holdings-gap sentence. |
| Telegram | none |

### 2b. XLI — `res_3f11c4dad72e` → `rr_60d280b8b1b3`

| Field | Value |
|---|---|
| plan | `plan_ece5f6531254` |
| backend | live bridge, latency **5875 ms** |
| critique | **VALID** · sources=`cat_xli_2026-08-18_other_9c57b4` |
| completed_ts | **`2026-08-18T21:30:36.119340+00:00`** (worker-now; persist clobber fixed) |
| as_of | `2026-08-18T15:16:13.988036+00:00` (model, same day) |
| plan attach | **YES** |
| memory | **CANDIDATE** `mem_b91739ce0729a3944f090d613ba8718a` — retrieved |
| Telegram | none |

### 2c. SCHD on promoted CURRENT — `res_f83c5d619f49` → `rr_b841b1b28b38`

| Field | Value |
|---|---|
| path | `hermes_cio_worker.py` on CURRENT `40934ca8` (no worktree PYTHONPATH) |
| plan | `plan_d45c7c4af5a6` |
| backend | live bridge, latency **5932 ms** |
| critique | **VALID** · sources=`cat_schd_2026-08-18_analyst_upgrade_a05f99` |
| completed_ts | `2026-08-18T21:37:22.774552+00:00` (worker-now) |
| plan attach | **YES** |
| memory | **CANDIDATE** `mem_3ec086deb2513db0720c628b4e8f10ba` retrieved (admit via same bridge after the worker return; hook did not write its own receipt) |
| Telegram | none |

17:00 timer stub-completions (`res_29e5a85972c1` XLI, `res_48a84c661bc8` DIVI) and R6.1 canary `rr_3ac69ce392c0` (INSUFFICIENT, `as_of=2025-07-11`) remain historical. History not deleted.

---

## 3. Queue / closed loop

| Stage | Status |
|---|---|
| Research request | **WORKING** |
| Queue visibility | **WORKING** — overlay pending **108** |
| Research completion | **TWO live-bridge VALID jobs** this hour. Autonomous-loop / deep-research still failed. |
| Critique | **WORKING** — VALID on both new results; INSUFFICIENT on R6.1 canary (correct at the time) |
| Plan attach | **PROVEN** for `rr_2ce371c209dc`, `rr_60d280b8b1b3`, `rr_b841b1b28b38` |
| Research→memory | **PROVEN CANDIDATE** (retrieved). Not ACTIVE policy. MBI=0. |
| Automatic retrieval / advisory delta | **NOT_PROVEN** as a desk consumer path |
| Overlay expire-on-complete | **NOT_WIRED** — completing a `res_*` does not EXPIRE the challenge stream |
| Outcomes | **PROVEN_IDLE** · next_due 2026-08-22T14:23:21Z |
| Influence | flags ACTIVE_ADVISORY; **eligible_runs=0**; MBI=0 |

---

## 4. P1 register

| gap | status | note |
|---|---|---|
| G-HER-01 | **open** | autonomous-loop + deep-research still failed |
| G-RES-01 | **partial** | two structured jobs completed; overlay 108 remain |
| G-OUT-01 | **PROVEN_IDLE** | not an engineering fail |
| G-REC-01 | **partial** | domain present; `ok=false` while overlay backlog exists |
| G-ACT-01 / G-PLN-01 | **open** | recon flags draft/diagnostic |
| G-OPN-01 | **open** | Flash/Pro EXPIRED |
| G-HLD-01 | **open** | HOLDINGS_SOURCE_FRESHNESS=STALE |
| G-INF-01 | **open** | no eligible influence runs |
| G-MAN-01 | **open** | RELEASE_MANIFEST historical pin |
| CURRENT hijack | **guarded** | restore still e96; script now refuses overwrite |
| G-QLT-01 (new) | **closed in branch** | catalyst in prompt; summary/sources stamped; as_of coerced |
| G-MEM-01 (new) | **closed in branch** | `research_artifact` + memory-safe excerpt |

---

## 5. Operator confirmation (R6.2)

Hard-reload `/v3/` after promote.

- [ ] Chip `3.14+msz6mwp7` · SHA `40934ca8` (not e96 / not 244b7a41)
- [ ] Plan `plan_d45c7c4af5a6` evidence includes `rr_b841b1b28b38` (latest) and earlier `rr_2ce371c209dc`
- [ ] Plan `plan_ece5f6531254` evidence includes `rr_60d280b8b1b3`
- [ ] Memory CANDIDATE `mem_12ab1b21…` / `mem_b91739ce…` / `mem_3ec086de…`
- [ ] Drive header **R6.2 — 2026-08-18T21:38Z**
- [ ] MBI=0
- [ ] Do not treat overlay pending 108 as “research never completed”

---

## 6. How we update

Same Drive file `1scL90dCZa7uOK9_sojX-MNBWHfrViWMi`. Code is on CURRENT. Overlay expire-on-complete is still unwired. Hermes units still failed. **R7** waits on those plus a desk consumer retrieving the CANDIDATE without a manual admit replay. Do not invent that.

---

## 7. Revision log

| Rev | UTC | What changed |
|---|---|---|
| R4 | 2026-08-18T16:04Z | Lineage store + drain; CURRENT was `244b7a41`. |
| R5 | 2026-08-18T20:40Z | Closure v2 authored as deploy-pending. |
| R6 | 2026-08-18T20:53Z | Truth-sync to `e96ff36a`; leftover R4 numbers remained below the fold. |
| R6.1 | 2026-08-18T21:06Z | Corrected stale numbers. Live-bridge canary `rr_3ac69ce392c0`. Memory refused. **Documented blocks instead of fixing them.** |
| **R6.2** | **2026-08-18T21:38Z** | Fixed producers. PR #377 merged + promoted `40934ca8`. VALID `rr_2ce371c209dc` / `rr_60d280b8b1b3` / CURRENT-native `rr_b841b1b28b38`. Memory CANDIDATE retrieved. Overlay 108. Units still failed. |

*End of R6.2. Not R7 — overlay still 108; Hermes units still failed; worker hook did not write its own memory receipt.*
