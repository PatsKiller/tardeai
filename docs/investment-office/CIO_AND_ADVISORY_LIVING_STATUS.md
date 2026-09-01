# CIO + Advisory — Living Operator Status

Status:      ACTIVE
as_of:       2026-08-18T21:19:02-04:00
Measured at: efcc51365 / not measured

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Revision** | **R6.9 — 2026-08-19T01:12Z** (closed-loop live + trust/signal code live; **not R7**) |
| **Status** | **CODE_FIXED_AWAITING_HOST_OBSERVATION** — CIO closed-loop is on CURRENT. Trust/signal patches are on CURRENT. Telegram quieting and two pipeline runs still need host time. |
| **Authority** | `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0` · `broker_write=NONE` |
| **Owner** | Alex desk · operator: John |
| **Live CURRENT** | `f17c36cf-main-exact-phase2-20260818-210255` |
| **CURRENT SHA** | `f17c36cf1793835807a05b58568aa4ad114865ea` |
| **origin/main** | `f17c36cf` (merge #391). **This docs revision must not re-promote CURRENT.** |
| **UI chip (live)** | `3.14+msze1bj2` · `f17c36cf` |
| **Google Drive file** | [CIO_AND_ADVISORY_LIVING_STATUS.md](https://drive.google.com/file/d/1scL90dCZa7uOK9_sojX-MNBWHfrViWMi/view) |
| **Drive folder** | [docs / investment-office](https://drive.google.com/drive/folders/1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8) |

> **Not R7.** R6.8 certified books. #389 closed research→reassessment. #391 made one Telegram message mean something. Host observation of the quiet Telegram path is still open. See §1e–§1f.

---

## 0. What was still broken after R6.2 — and what we fixed

| Block | Root cause | Fix |
|---|---|---|
| Overlay stayed 108 after structured completes | No expire-on-complete. Overlay `plan_id` lives in `payload.source` (`cio_plan:plan_…`), not metadata. | `expire_overlay_for_plan` + `expire_satisfied_overlays`. Hook expires matching streams. Backfill expired **11**. |
| Hook “admitted” but no live receipt | (1) `agent_memory_admission` imports `scripts.lib.*`; CLI `PYTHONPATH=scripts` → `ModuleNotFoundError: scripts`. (2) memory store resolved to the **worktree** via `__file__`, not cwd/`TRADEAI_CIO_DIR`. | Worker puts repo root on `sys.path`. `default_store_path` prefers `TRADEAI_CIO_DIR` then cwd `data/cio`. |
| Lineage/overlay read the wrong cio dir | `cio_dir()` used the imported file’s repo `data/cio`. | Prefer cwd `data/cio` (same as worker persist). |
| CIO timer wrote stubs | `HERMES_BACKEND=catalyst`. | Live unit + repo unit: `--backend live`, `TimeoutStartSec=600`. |
| Autonomous-loop unit red | 2×300s Ollama vs `TimeoutStartSec=600`; exit 1 if second row times out. Rebuild tree had no budget skip. | Budget skip + `deferred_budget` is not a unit fail. Live `TimeoutStartSec=900`. |
| Deep-research unit red | SSL dead after 27b; rebuild-tree script had **no** reconnect-before-write. | Reconnect + per-symbol retry on the **live** rebuild-tree script. |

Admission gates were not loosened.

---

## 1. One-screen truth (01:12Z)

| Surface | Status | Live evidence |
|---|---|---|
| Command Center SPA | **WORKING** | chip `3.14+msze1bj2` |
| Release | **WORKING** | CURRENT `f17c36cf` = origin/main (PR #391 promoted; APP_RUNTIME) |
| `/api/v3/intelligence` | **WORKING** | 200 |
| `/v3/cio` | **WORKING** | 200 after exact-main promote |
| Closed-loop CIO | **LIVE** | #389: research completion → parent reassessment → persist_product → what_changed → notify |
| Telegram trust | **CODE LIVE** | #391: industry bypass gone; Hermes/health state-transition; EOD sign fixed. Awaiting host quieting. |
| Holdings guard | **CODE LIVE** | $1M floor removed. $722,923 reconcile still **blocked** (partial vs last-good $1.28M). |
| Memory | **SHADOW** | #390 isolated test root. MBI=0. AIF-FS CI green on #391. |
| Authority | **PROVEN_LIVE** | READ_ONLY_ADVISORY; MBI=0; no broker/order/stop/2FA mutation |

---

## 1b. Overnight now-test (did not wait for timers)

Same command lines as the systemd units, run immediately. `HERMES_LLM_PRIMARY=bridge_flash`. Deep-research added `--allow-daytime` because local hour was 18 EDT.

| Unit | Command | Wall | Exit | Rows |
|---|---|---|---|---|
| autonomous-loop | `--loop ticker_challenger --apply --max-rows 2` | 29.3s | **0** | CPRI `25365` conf 0.65 · SH `25366` conf 0.70 · **deepseek-v4-flash** |
| deep-research-local | `--allow-daytime --apply --max-rows 3` | 20s | **0** | EKSO `25367` · AGMH `25368` · FUSE `25369` · log: `LLM bridge_flash deepseek-v4-flash` |

Prior same-hour Flash proofs (still in the table): STLD `25362`. Early LRCX/NUVL/IVF/SPRC/AXTI rows still show `gemma3:*` in `model_used` because Flash echoed that name before we forced the stamp.

Ollama was **not** used as primary.

## 1c. Why 21:01 / 02:30 — and the new schedule

Those two times were **once per day**, from the old Ollama overnight design:

| Job | Old calendar | Why it looked like 21:01 / 02:30 |
|---|---|---|
| autonomous-loop | `01:00 UTC` + `RandomizedDelaySec=300` | 01:00 UTC = **21:00 EDT**; jitter → ~21:01–21:05 |
| deep-research-local | `02:30` local + 300s jitter | ~02:30–02:35 EDT |

They were **not** DeepSeek off-peak. Official DeepSeek peak is **01:00–04:00 and 06:00–10:00 UTC** (Beijing 09:00–12:00 and 14:00–18:00). Half price outside those windows. [pricing](https://api-docs.deepseek.com/quick_start/pricing/)

In America/New_York (EDT, UTC−4):

| Local | UTC | Official DeepSeek |
|---|---|---|
| 21:00–00:00 | 01:00–04:00 | **PEAK** (old 21:01 timer sat here) |
| 00:00–02:00 | 04:00–06:00 | off-peak |
| 02:00–06:00 | 06:00–10:00 | **PEAK** (old 02:30 timer sat here) |
| 06:00–21:00 | 10:00–01:00 next | off-peak |

**Correction (R6.7):** cheapest DeepSeek is **China night**, not US night and not a 9am-ET start.

Official peak = Beijing business hours **09:00–12:00** and **14:00–18:00**. Half price the rest of the day. [pricing](https://api-docs.deepseek.com/quick_start/pricing/)

| Clock | China night (cheap) | China day (peak) |
|---|---|---|
| Beijing | **18:00–09:00** | 09:00–12:00 and 14:00–18:00 |
| UTC | 10:00–01:00 | 01:00–04:00 and 06:00–10:00 |
| ET now (EDT) | **06:00am–9:00pm** | 9pm–midnight and 2am–6am |
| ET winter (EST) | **05:00am–8:00pm** | 8pm–11pm and 1am–5am |

China lunch 12:00–14:00 Beijing is also cheap (US midnight). Not scheduled — that is not night.

**Live cadence: hourly on Asia/Shanghai, 15 fires each = 30 Flash jobs / day.**

| Beijing | ET (EDT) | Job |
|---|---|---|
| 18:10 … 08:10 every hour | 06:10am … 8:10pm | autonomous-loop (2 tickers) |
| 18:35 … 08:35 every hour | 06:35am … 8:35pm | deep-research (3 symbols) |

Timers use `Asia/Shanghai` so winter/summer stay on China night. Scripts still refuse Flash apply during official peak unless `--allow-peak`. `tradeai-hermes-cio-worker` still every 15m 24/7.

Not R7. CURRENT not promoted.

## 1d. CIO investment-product live certification (2026-08-18T22:45Z)

No new architecture. No CURRENT promote.

**SOURCE.** origin/main `08e768d08a0aed24511bc1156925dd70238b9f68`. CURRENT `575477dc-main-exact-phase2-20260818-175137` SOURCE=BUILD=GIT=`575477dc779c25111250a82b2e56d9c08a962950` stamped 2026-08-18T21:52:15Z. portfolio-server WorkingDirectory is that release on `:7777`. chip `3.14+msz77bh2`.

**main-ahead classification (575477dc..08e768d):** all **DOCS_ONLY**, **SCHEDULER_ONLY**, or **HOST_ALREADY_APPLIED** (Flash failover/primary + China-night timers). **runtime_required_ahead = 0.**

**INVESTMENT_PRODUCT** `GET /api/v3/cio/investment-product` **200**. schema `CIOInvestmentProduct@v1`. as_of **2026-08-18T20:55:17Z** (persisted snapshot, ~2h stale vs home 22:39Z). MBI=0. temperament RISK OFF — SELECTIVE RISK. reentry **61** (NEAR 25 / WAIT 32 / AVOID 4 / REENTER 0). opportunity **20** (all `source=reentry`). DO_NOW 0. RESEARCH_NEXT 8. what_changed **absent**. governed_verdicts **[]**.

**REENTRY.** SCHG = **currently held** (advisory HOLD; not a clean re-entry candidate). CSCO = **present NEAR**, exit/price **missing**, no governed RE_ENTER. ANET = same. NEAR ≠ RE_ENTER.

**OPPORTUNITIES.** ranked 20; top ADBE… all former-holding watches. cash not a ranked row. empty **new-name** pipeline: watchlist 12 all WAIT; rotation exists on `/home` only; opportunity_book does not ingest watch/rotation/defense.

**TEMPERAMENT.** regime risk-off as-of 16:05 EDT. FS receipts=4 unused (fs_mode OFF). 7 ratified lessons unused (lesson_mode OFF). No breadth/VIX/sector leadership block. **product-quality gap.**

**DAILY_CIO.** Last four-book persist 20:55Z (`cio_investment_brief.json`). Live named memo `cio_desk_note_latest.md` 22:30Z — HOLD/STAGE cash, HOLD SCHD (operator defer), SPCX awareness. **PASS** as named HOLD CASH / WAIT. persist_product lives on `cio_wake_dispatch_entrypoint` which is **not** the live reactive timer (`cio_reactive_cycle` dispatched=0, no persist).

**RESEARCH_LOOP.** lineages 13 (MEMORY_ADMITTED 2 DIVI/XLI, RESEARCH_COMPLETED 1 JEPI, REQUESTED 5, OUTCOME_PENDING 5). pending challenges 88. queue pending 88 (73 legitimate, 15 missing_symbol). DIVI: res_* → rr_* → mem_8bbacb88… admitted. **advisory_use=None. memory_retrieval_ids=[]. CIO product not rebuilt.** Flash rows 25365–25391 not consumed by books.

**HERMES.** China-night timers live Asia/Shanghai. last deep 18:35 ET APAM/BRO/BWEN Flash `25389–25391` exit 0. next 19:10 / 19:35 ET. Flash used. Quality: summaries exist; **no CIO consumption.**

**ADVISORY.** desk_freshness CURRENT. HOLDINGS_SOURCE_FRESHNESS **STALE**. OPINION_FRESHNESS **EXPIRED** (synthesis 2026-08-13, label PRIOR SYNTHESIS). watch CURRENT. reentry CURRENT. DATA_CONFLICT banner 17 rows. MBI=0. Financial Senses on rows DATA_UNAVAILABLE.

**TELEGRAM.** last financial-class scan 22:35Z: digest=0 immediate=0 suppressed_unchanged=3 (cash / reentry / SCHD DATA_CONFLICT). last Telegram IDs: heartbeat 47831, autonomy_RECOVERED 48061. **no daily investment digest sent.**

**COMMAND_CENTER.** `/v3/cio` reads live `/api/v3/cio/home` + `/investment-product`. `/v3/advisory` live. `/v3/closed-loop` → intelligence live. Not fixtures. Operator Qs: 1–3 yes; 4 partial; 5–6 partial; 7 no; 8 no; 9 suppressed.

**PROMOTION (R6.8).** **no.** 08e768d was docs/scheduler/host-already-applied.

**P0 then.** persist_product not on live reactive path; GET serves stale brief; research/memory does not reassess books. Closed by **#389** (see §1e).

## 1e. Closed-loop product (PR #389 → then live on CURRENT)

`on_hermes_completed` now reassesses the parent book even without `plan_id`, persists `CIOInvestmentProduct@v1`, writes `what_changed`, and uses Signal-over-Spam (`IMMEDIATE` / `DIGEST` / `SUPPRESSED` / `COMMAND_CENTER_ONLY`). Duplicate replay is SUPPRESSED.

Natural CIO worker later reassessed evening names (SPACEX_TEST / SPCX / SCHD) with `material=false` → SUPPRESSED. That is the router working.

#390 was memory-API test hygiene only. It moved `origin/main` to `22220efc` and was **not** the reason CURRENT moved.

## 1f. Trust, Telegram signal, data integrity (PR #391 — APP_RUNTIME — **this CURRENT**)

The system was over-reporting, not failing to wake. Industry Momentum was **not** a Signal-over-Spam failure. A legacy Defense publisher called `send_telegram(..., bypass_router=True)`. Health-inspector remediations ran `finviz_industry_groups.py --close` about every two minutes; same-day persist made debounce re-confirm the same transition.

| Defect | Source truth | Fix on `f17c36cf` |
|---|---|---|
| Identical INDUSTRY MOMENTUM every ~2 min | health-inspect `--close` + `bypass_router=True` + today-row reconfirm | remediations no `--close`; prior-session confirm; semantic from→to; governed send; close flock |
| 1,555 `hermes_rank_surge` | `status='active'` treated as daily-priority; UID `hermes_rank_<sym>_<timestamp>` | scoring-priority + rank bands; durable condition state |
| 401 staleness / 73–85 system_health | new event each cycle | FRESH→STALE / STALE→RECOVERED |
| EOD CVS/KMB look like gains | `abs(pnl)` + `sign()` omits minus | signed money/pct/R; missing stop/target; option label |
| holdings write BLOCKED 722,923 vs $1M | static floor assumed ~$1.24M book | coverage + cash + 50% drop; **keep block** — payload incomplete vs last-good **$1,279,682** |
| finviz `connection already closed` | raw conn held across HTTP | `ensure_conn` + refresh after fetch |
| Aegis evening overflow | OpenClaw job, no isolated session, unbounded dumps | bounded packet + isolated contract; live gateway `sessionTarget` still host-pending |

**Do not write the $722,923 snapshot.** Last-good is complete at $1.28M (34 positions, $578k cash, 5 accounts). Recurring `holdings_reconcile --apply` at ~16:10 is the partial producer.

**This docs commit is DOCS_ONLY. Do not exact-main promote it.**

## 2. Validation this hour (not R7)

| Job | Result | Critique | Overlay | Memory |
|---|---|---|---|---|
| `res_fc591e9aa2b2` JEPI | `rr_2b29e36a610a` | VALID | expired 1 | hook error `scripts` (before path fix) |
| `res_fb8f3cc992f9` XLI | `rr_e7324ad87582` | VALID | expired 1 | admitted to **worktree** store (before cwd path fix) |
| `res_f992e780343d` DIVI | `rr_ceeb1274b8ad` | VALID | expired **1** | **live hook CANDIDATE** `mem_8bbacb882a761199a950eed65f15c5aa` retrieved |

Backfill: `expire-satisfied` `before=108` `expired=11` `skipped_open=97` `deleted=0`. Then two more expires → **94**.

Remaining 94 overlays are plans with **no** completed structured result. Not deleted. Worker timer drains 2 live jobs / 15m.

---

## 3. P1 register

| gap | status | note |
|---|---|---|
| G-HER-01 | **closed as now-test** | both overnight jobs apply-committed on Flash this hour |
| G-RES-01 | **partial** | overlay 94; structured drain continues |
| G-QLT-01 | **closed** | R6.2 catalyst/summary/sources |
| G-MEM-01 | **closed** | hook auto-admit on live store |
| G-OVL-01 | **closed as producer** | expire-on-complete + backfill |
| G-OUT-01 | **PROVEN_IDLE** | next_due 2026-08-22T14:23:21Z |
| G-HLD-01 / G-OPN-01 / G-INF-01 | **open** | holdings last-good $1.28M; opinion still can expire |
| G-TG-01 industry bypass | **closed in source** | #391; host remediations patched; observe next close |
| G-TG-02 Hermes cardinality | **closed in source** | scoring-priority + band UID |
| G-EOD-01 sign | **closed** | CVS/KMB fixture `-$5.72` / `-$163.24` |
| G-HLD-02 $1M floor | **closed** | static floor removed; 722k still blocked as incomplete |
| CURRENT hijack | **guarded** | still in place |

---

## 4. Operator confirmation (R6.9)

- [ ] Chip `3.14+msze1bj2` · SHA `f17c36cf`
- [ ] CURRENT `f17c36cf-main-exact-phase2-20260818-210255` (rollback: `08ec3a3d-…-190351`)
- [ ] Drive header **R6.9 — 2026-08-19T01:12Z**
- [ ] Industry remediations no longer pass `--close` (cron 12:30 / 16:18 unchanged)
- [ ] Next EOD print shows minus on losses
- [ ] Do **not** lower the holdings floor to $700k
- [ ] Do **not** promote this docs PR
- [ ] MBI=0
- [ ] Do **not** call this R7

---

## 5. How we update

Same Drive file `1scL90dCZa7uOK9_sojX-MNBWHfrViWMi`. In-place `--replace`. **R7** only if: overlay expire keeps working on CURRENT, one overnight unit completes without systemd fail, a desk consumer retrieves a CANDIDATE without a manual replay, **and** Telegram is quiet enough that one message means something. None of those are claimed here.

---

## 6. Revision log

| Rev | UTC | What changed |
|---|---|---|
| R6.1 | 2026-08-18T21:06Z | Documented INSUFFICIENT. Did not fix producers. |
| R6.2 | 2026-08-18T21:38Z | Catalyst/summary/sources. PR #377 promoted `40934ca8`. VALID jobs. |
| **R6.3** | **2026-08-18T21:49Z** | Overlay expire + hook path/store fix. 108→94. Live auto-admit `mem_8bbacb88…`. Not R7. |
| **R6.4** | **2026-08-18T22:12Z** | Did not wait for timers. Overnight jobs run now on Flash: 2/2 + 3/3 committed. Not R7. |
| **R6.5** | **2026-08-18T22:25Z** | Official DeepSeek off-peak cadence. 21:01/02:30 were peak. Now 5×2 in 00–02 and 06–09 ET. Not R7. |
| **R6.6** | **2026-08-18T22:28Z** | Cheap window is 09:00–20:59 ET, not overnight. Hourly 12×2. Not R7. |
| **R6.7** | **2026-08-18T22:32Z** | China night is the cheap block. Timers on Asia/Shanghai 18:00–09:00. Hourly 15×2. Not R7. |
| **R6.8** | **2026-08-18T22:45Z** | Certified CURRENT `575477dc` books live but incomplete. Do not promote `08e768d`. Not R7. |
| **R6.9** | **2026-08-19T01:12Z** | Header pin to live `f17c36cf` (#389 closed-loop + #391 trust/signal on CURRENT). Docs-only; do not re-promote. Not R7. |

*End of R6.9. Not R7.*
