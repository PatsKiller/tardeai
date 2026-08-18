# CIO + Advisory — Living Operator Status

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Revision** | **R6.7 — 2026-08-18T22:32Z** (China-night Flash cadence; **not R7**) |
| **Status** | **PARTIAL_WITH_EXPLICIT_GAPS** — Flash jobs fire **hourly on China night** (Beijing 18:00–09:00). Overlay/desk-consumer gaps remain. |
| **Authority** | `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0` · `broker_write=NONE` |
| **Owner** | Alex desk · operator: John |
| **Live CURRENT** | `575477dc-main-exact-phase2-20260818-175137` |
| **CURRENT SHA** | `575477dc779c25111250a82b2e56d9c08a962950` |
| **origin/main** | `a77d986b` (R6.6 daytime window #386; last overnight-code `38cd2320` PR #382) |
| **UI chip (live)** | `3.14+msz77bh2` · `575477dc` |
| **Google Drive file** | [CIO_AND_ADVISORY_LIVING_STATUS.md](https://drive.google.com/file/d/1scL90dCZa7uOK9_sojX-MNBWHfrViWMi/view) |
| **Drive folder** | [docs / investment-office](https://drive.google.com/drive/folders/1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8) |

> **Not R7.** Overlay is not empty. No desk consumer path. Overnight jobs were **not** left for tonight’s timer — they were run now.

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

## 1. One-screen truth (21:49Z)

| Surface | Status | Live evidence |
|---|---|---|
| Command Center SPA | **WORKING** | chip `3.14+msz77bh2` |
| Release | **WORKING** | CURRENT `575477dc` = origin/main (PR #379 promoted) |
| `/api/v3/intelligence` | **WORKING** | 200 |
| `/api/v3/intelligence/queue` | **WORKING** | overlay **94** after expire (was 108). 15 still `missing_symbol`. |
| Memory | **SHADOW** | Hook auto-admit **CANDIDATE** `mem_8bbacb882a761199a950eed65f15c5aa` on live store. MBI=0. |
| Hermes CIO worker timer | **ARMED live** | 21:45Z already wrote CANDIDATE `mem_2b0c1a65…` / `mem_8d9c6322…` |
| Hermes autonomous-loop | **PROVEN_NOW (Flash)** | 22:11:43–22:12:12Z apply 2/2 · CPRI `25365` · SH `25366` · `model_used=deepseek-v4-flash` · 29s · exit 0 |
| Hermes deep-research-local | **PROVEN_NOW (Flash)** | 22:12:12–22:12:32Z apply 3/3 · EKSO `25367` · AGMH `25368` · FUSE `25369` · Flash · 20s · exit 0 |
| Authority | **PROVEN_LIVE** | READ_ONLY_ADVISORY; MBI=0 |

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
| G-HLD-01 / G-OPN-01 / G-INF-01 | **open** | unchanged |
| CURRENT hijack | **guarded** | still in place |

---

## 4. Operator confirmation (R6.3)

- [ ] Chip `3.14+msz77bh2` · SHA `575477dc`
- [ ] Overnight now-test IDs `25365`–`25369` exist, `model_used=deepseek-v4-flash`
- [ ] Drive header **R6.7 — 2026-08-18T22:32Z**
- [ ] Timers are `Asia/Shanghai` 18:10–08:10 / 18:35–08:35
- [ ] Next fires still tonight (China morning): **18:35 / 19:10 ET**, then resume **06:10 ET** tomorrow
- [ ] Overlay pending **94** (or lower if the timer drained more)
- [ ] `mem_8bbacb882a761199a950eed65f15c5aa` present, status CANDIDATE
- [ ] Drive header **R6.3 — 2026-08-18T21:49Z**
- [ ] MBI=0
- [ ] Do **not** call this R7

---

## 5. How we update

Same Drive file `1scL90dCZa7uOK9_sojX-MNBWHfrViWMi`. **R7** only if: overlay expire keeps working on CURRENT, one overnight unit completes without systemd fail, and a desk consumer retrieves a CANDIDATE without a manual replay. None of those three are claimed here.

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

*End of R6.7. Not R7.*
