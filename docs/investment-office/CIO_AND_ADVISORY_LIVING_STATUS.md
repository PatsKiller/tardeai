# CIO + Advisory — Living Operator Status

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Revision** | **R6.1 — 2026-08-18T21:06Z** (R6 correction + Hermes live canary) |
| **Status** | **PARTIAL_WITH_EXPLICIT_GAPS** — one real worker completion; memory correctly refused; Hermes units still failed |
| **Authority** | `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0` · `broker_write=NONE` |
| **Owner** | Alex desk · operator: John |
| **Live CURRENT** | `e96ff36a-main-exact-phase2-20260818-164906` |
| **CURRENT SHA** | `e96ff36a2b950deb3cac187e37819a0524da8ae0` |
| **origin/main at authoring** | `c74e511257ada1b05e6ce8e46bbb7e1f528c2c43` (PR #374 docs-only; first parent = CURRENT) |
| **Provenance** | **MAIN_AHEAD_DOCS_ONLY** vs CURRENT. Do not promote this docs commit. |
| **UI chip** | `3.14+msz4yxaj` · `e96ff36a` |
| **Google Drive file** | [CIO_AND_ADVISORY_LIVING_STATUS.md](https://drive.google.com/file/d/1scL90dCZa7uOK9_sojX-MNBWHfrViWMi/view) |
| **Drive folder** | [docs / investment-office](https://drive.google.com/drive/folders/1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8) |

> All numbers below are from the **2026-08-18T21:01–21:06Z** probe after restoring CURRENT to `e96ff36a` (it had been hijacked at 16:57 EDT by unstamped dir `20260818-165624` / PR 296).  
> This revision **replaces** leftover R4/R5 passages (108/204/244b7a41/“reconciliation missing”).

---

## 1. One-screen truth (21:06Z)

| Surface | Status | Live evidence |
|---|---|---|
| Command Center SPA | **WORKING** | chip `3.14+msz4yxaj` |
| Release | **WORKING** | CURRENT `e96ff36a` restored; main `c74e511` docs-only ahead |
| `/api/v3/cio` | **WORKING** | 200; snapshot **15/15 domains**, `health.ok=true` (recon producer present) |
| `/api/v3/advisory` | **WORKING_DEGRADED** | 58 rows; health **STALE**; FACT_FRESHNESS=CURRENT (desk cache); **HOLDINGS_SOURCE_FRESHNESS=STALE**; OPINION_FRESHNESS=EXPIRED |
| `/api/v3/intelligence` | **WORKING** | 13 lineages |
| `/api/v3/intelligence/queue` | **WORKING** | **108 pending** after canary overlay expire (was 109) |
| `/api/v3/intelligence/reconciliation` | **WORKING** | 200; `ok=false` because research still pending |
| Memory | **SHADOW** | 1 ADMITTED + 1 EXPIRED; **MBI=0**; canary **not** admitted |
| Learning | **WORKING_DEGRADED** | **279** cases; 0 matured / 0 scored; observer **PROVEN_IDLE**; next_due **2026-08-22T14:23:21Z** |
| Hermes autonomous-loop | **BROKEN** | still **failed** (Aug 17 MU/STLD timeout) |
| Hermes deep-research-local | **BROKEN** | still **failed** (DB SSL after 27b) |
| CIO Hermes worker timer | **ARMED** | enabled; 17:00 tick stub-completed 2 jobs; 21:04 live canary below |
| Authority | **PROVEN_LIVE** | READ_ONLY_ADVISORY; MBI=0; 0 broker/order/stop/risk/2FA |

---

## 2. Source / release

| Item | Value |
|---|---|
| origin/main | `c74e511257ada1b05e6ce8e46bbb7e1f528c2c43` (#374 R6 docs) |
| CURRENT SHA | `e96ff36a2b950deb3cac187e37819a0524da8ae0` |
| CURRENT path | `/home/johnclaw/trade-ai-releases/portfolio-server/e96ff36a-main-exact-phase2-20260818-164906` |
| Classification | **MAIN_AHEAD_DOCS_ONLY** |
| Incident | 16:57 EDT `deploy_portfolio_server.sh` (or sibling) pointed CURRENT at unstamped `20260818-165624` (no SOURCE_COMMIT, SHA pin 31458e9b / PR 296). `/api/v3/intelligence` 404 until restore 21:02Z. |
| RELEASE_MANIFEST.md | still pins `aa037b73` — **HISTORICAL_ACCEPTANCE_PIN**, not CURRENT |

---

## 3. Hermes live canary (this run)

| Field | Value |
|---|---|
| research_id | `res_db9536fabeba` |
| parent plan | `plan_20c650160254` (S6_CONCENTRATION_OR_DISPOSITION, SCHD, desk@v5) |
| challenge stream | `hermes-challenge-c1fbd261c88d` |
| queued_at | 2026-08-16T15:19:37Z |
| path | `hermes_cio_worker.py --research-id … --backend live` on CURRENT `e96ff36a` |
| claimed/started/completed | 2026-08-18T21:04:12Z wall (worker latency **2779 ms**) |
| backend | `BridgeHermesResearchBackend` (governed bridge :8766, not stub write) |
| result_id | `rr_3ac69ce392c0` |
| source_count | **0** |
| quality / critique | **INSUFFICIENT** (`empty_summary`, `no_sources`) |
| model as_of | `2025-07-11` (hallucinated / not event-time — **not** treated as truth) |
| final_state | structured request **completed**; overlay challenge **EXPIRED** reason `satisfied_by_structured_result:rr_3ac69ce392c0` |
| plan attach | **YES** — `cio_plans` PLAN_UPDATED 21:04:12Z; evidence `hermes_research` + findings, `result_id=rr_3ac69ce392c0`, status=completed |
| memory admit | **REJECTED** (critique_INSUFFICIENT) — admission not weakened |
| lineage snapshot | SCHD `lin_be74ab5d25c949dd980c` still OUTCOME_PENDING; CURRENT builder did not ingest results jsonl (fix in follow-through commit) |
| Telegram | none (CIO_TELEGRAM_INTERDICT=1 / no material change) |

17:00 timer tick (while CURRENT was hijacked) stub-completed `res_29e5a85972c1` (XLI, `rr_2e02f2329648`) and `res_48a84c661bc8` (DIVI, `rr_5c0dc398dfb9`) via catalyst/stub. Those are **worker-path** events, **not** live-bridge research.

---

## 4. Queue (after canary expire)

| Metric | Value |
|---|---|
| pending | **108** |
| events | 315 (314 + 1 EXPIRED) |
| unique streams | 211 |
| by_reason (CURRENT classifier) | 93 legitimate_current · 15 labeled missing_parent |
| missing_parent truth | those 15 have **empty symbols** but **do have plan_id** (most also have research_id). They are **missing_symbol**, not orphans. Recoverable. Not deleted. |
| oldest_age_hours | ~162 |
| history deleted | **0** |

---

## 5. Closed-loop stages (honest)

| Stage | Status |
|---|---|
| Research request | **WORKING** |
| Queue visibility | **WORKING** |
| Research completion | **ONE live-bridge job completed** (SCHD). Autonomous-loop / deep-research still failed. Quality INSUFFICIENT. |
| Critique | **WORKING** (INSUFFICIENT on canary) |
| Plan attach | **PROVEN** for `rr_3ac69ce392c0` |
| Research→memory | **hook refused canary** (correct). No new memory_id. |
| Automatic retrieval / advisory delta | **NOT_PROVEN** (nothing admitted) |
| Outcomes | **PROVEN_IDLE** · next_due 2026-08-22T14:23:21Z · 279 cases · 0 matured |
| Lesson reuse | **NOT_PROVEN** |
| Influence | flags ACTIVE_ADVISORY; **eligible_runs=0**; MBI=0 |

---

## 6. P1 register (this probe)

| gap | status | note |
|---|---|---|
| G-HER-01 | **open** | autonomous-loop + deep-research still failed |
| G-RES-01 | **partial** | worker can complete; 108 remain; overlay ≠ structured store |
| G-OUT-01 | **PROVEN_IDLE** | not an engineering fail |
| G-REC-01 | **partial** | domain present; `ok=false` while backlog exists |
| G-ACT-01 / G-PLN-01 | **open** | recon flags draft/diagnostic; not mass-mutated |
| G-OPN-01 | **open** | Flash/Pro EXPIRED — no timestamp bump |
| G-HLD-01 | **open** | HOLDINGS_SOURCE_FRESHNESS=STALE on desk |
| G-INF-01 | **open** | no eligible influence runs |
| G-MAN-01 | **open** | RELEASE_MANIFEST is historical pin, not CURRENT |
| CURRENT hijack | **closed this hour** | restored e96ff36a |

---

## 7. Operator confirmation (R6.1)

Hard-reload `/v3/`.

- [ ] Chip `3.14+msz4yxaj` · SHA `e96ff36a` (not 244b7a41)
- [ ] `/api/v3/intelligence/queue` pending **108**
- [ ] Plan `plan_20c650160254` evidence includes `rr_3ac69ce392c0`
- [ ] Memory still 2 records; canary **not** admitted
- [ ] Drive header **R6.1 — 2026-08-18T21:06Z**
- [ ] MBI=0

---

## 8. How we update

Same Drive file `1scL90dCZa7uOK9_sojX-MNBWHfrViWMi`. **R7** only after a completed result that is **VALID** (or PARTIAL with sources) **and** admitted/retrieved by a consumer. Do not promote docs-only commits.

---

## 9. Revision log

| Rev | UTC | What changed |
|---|---|---|
| R4 | 2026-08-18T16:04Z | Lineage store + drain; CURRENT was `244b7a41`. |
| R5 | 2026-08-18T20:40Z | Closure v2 authored as deploy-pending. |
| R6 | 2026-08-18T20:53Z | Truth-sync to `e96ff36a`; leftover R4 numbers remained below the fold. |
| **R6.1** | **2026-08-18T21:06Z** | Corrected stale 108/204/244b7a41/recon-missing. Restored hijacked CURRENT. Live-bridge canary `rr_3ac69ce392c0`. Memory refused. 108 pending. |

*End of R6.1. Not R7 — canary quality was INSUFFICIENT and memory was not admitted.*
