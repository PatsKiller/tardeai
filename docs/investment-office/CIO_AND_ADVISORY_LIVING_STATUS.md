# CIO + Advisory — Living Operator Status

| Field | Value |
|---|---|
| **Document name** | `CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Repo path** | `docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md` |
| **Revision** | **R6.4 — 2026-08-18T22:12Z** (overnight Flash now-test; **not R7**) |
| **Status** | **PARTIAL_WITH_EXPLICIT_GAPS** — both overnight jobs **ran now** on DeepSeek Flash and committed. Overlay/desk-consumer gaps remain. |
| **Authority** | `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0` · `broker_write=NONE` |
| **Owner** | Alex desk · operator: John |
| **Live CURRENT** | `575477dc-main-exact-phase2-20260818-175137` |
| **CURRENT SHA** | `575477dc779c25111250a82b2e56d9c08a962950` |
| **origin/main** | `8f8a3acb` (R6.4 now-test docs, PR #383; last code `38cd2320` PR #382) |
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

Ollama was **not** used as primary. Tonight’s 21:01 / 02:30 timers will hit the same Flash-primary path.

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
- [ ] Drive header **R6.4 — 2026-08-18T22:12Z**
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

*End of R6.4. Not R7.*
