# Lane Quality Bake-Off — 2026-08-21

**Authority:** READ_ONLY_ADVISORY. Measurement only. **No routing flags flipped.**

**Closeout 2026-08-21 18:46 ET:** #440 (import+alarm), #437, #438, #439 **merged**. CURRENT **`a7f30d89`**. Scheduler-path proof `hermes_external_research` id=45900 `status=sent`. RAW-store alarm live. `RESEARCH_SKIP_GATE` still 0. `$0.42/14d` spend is void (crash loop) — 7-day re-baseline pending.
**Window:** Track A ran 17:31–18:06 ET (DeepSeek **off-peak**).
**Sandbox (volatile, rescued):** originally `/tmp/tradeai-bakeoff-20260821/`. **Fill:** [`LANE_QUALITY_BAKEOFF_OPERATOR_BLIND_2026-08-21.md`](LANE_QUALITY_BAKEOFF_OPERATOR_BLIND_2026-08-21.md). Keys: `bakeoff-2026-08-21/DO_NOT_OPEN_UNTIL_SCORED/`. Durable copy also under `data/bakeoff/2026-08-21/` (gitignored). No writes to `hermes_external_research`, no Telegram, no cards.

Claude was **not** the judge. Blind ranking sheet is unscored — do not change routing from Track A crash-rates.

---

## 1. Q0 — 90-day production store `[VERIFIED]`

`hermes_external_research` (`recommendation LIKE '[%'` = error, as the scheduler already treats it):

| Lane | volume | distinct_symbols | error_prefix | empty | **error_rate** | empty_rate | success median len | last_success |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| grok | 27,679 | 1,535 | 11,998 | 604 | **43.3%** | 2.2% | 60 | 2026-08-21 16:43 |
| chatgpt | 15,891 | 1,436 | 510 | 2,929 | 3.2% | **18.4%** | 452 | 2026-08-21 16:43 |
| deepseek | 2,137 | 132 | 2,137 | 0 | **100.0%** | 0% | — | **never** |
| claude | 113 | 52 | 0 | 0 | 0.0% | 0% | 205 | 2026-08-01 (manual) |

**Local-gemma is not in this table.** Scheduler “local-gemma” enqueues `watchlist_agent_jobs` (maria/full_chain). Stored gemma prose lives in `hermes_research_intelligence`.

### Local stored outputs (intelligence, 90d)

| model | n | `[` prefix | empty | last |
|---|---:|---:|---:|---|
| gemma3:4b | 3,899 | **0** | **0** | 2026-08-21 |
| gemma3:12b | 1,658 | **0** | **0** | 2026-08-21 |
| gemma3:27b | 21 | **0** | **0** | 2026-08-19 |

Ticker-thesis 12b: 1,639 rows / 319 symbols / median length 484 / **0 cross-symbol duplicate groups**.

### Local *jobs* (not output quality)

`watchlist_agent_jobs` 90d: maria **28.5% failed** (11,414/40,016), 57.8% completed, 951 still queued. `maria_research` **91.7% failed**. This is queue/infra choking, not a 40% `[` garbage rate on stored gemma text.

### DeepSeek scheduler lane is a **bug**, not a model

Every `lane=deepseek` row is:

```
[ERROR] No module named 'lib.llm_lane'
```

`scripts/hermes_external_researcher.py` does `from lib.llm_lane import generate`. The module is **`scripts/llm_lane.py`** (`import llm_lane`). There is no `scripts/lib/llm_lane.py` in CURRENT, rebuild, or #437. **2,137 holdings/priority dispatches since 2026-08-13 produced zero successful DeepSeek opinions in the research store.** The governed bridge (`:8766`) and `ticker_research_agent` Flash path still work — different import.

This is the single most important Q0 finding. It is not a quality prior about V4-Flash.

### Duplicate outputs (success rows, 90d)

- chatgpt: 0%
- grok: 1.1% (43 groups)
- gemma ticker_thesis: 0%

### Grok 403 clusters (not a quality model)

Jul 28–30: **0 successful grok rows** (1,074 / 1,121 / 1,006 all 403). Then recovered. Last 30d otherwise mostly ok.

### ChatGPT 12-day lapse `[VERIFIED]`

Zero-ok gaps in the last 90d: **13 days (2026-07-03 → 07-15)** and 11 days (06-13 → 06-23). Docs’ “12-day ChatGPT lapse” is real.

`oauth_lane_keepalive.py` cron `*/30` was added **2026-08-02** — *after* that lapse. Keepalive currently green. It pings `import llm_lane` (the working module), **not** `hermes_external_researcher`. A green keepalive does not prove the research writer is healthy (DeepSeek store is the proof).

---

## 2. Q1 — What is actually running `[VERIFIED]`

### Inventory

| Claim | Verdict |
|---|---|
| SKILL.md `qwen3:1.7b` | **Not installed** |
| Live default | **gemma3:4b** (loaded 100% GPU before bake-off) |
| Disk | gemma3:4b 3.3GB, 12b 8.1GB, 27b 17GB, gemma3-overnight 17GB, qwen3:8b, embeddings |

`ollama ps` at start: `gemma3:4b` 4.4GB **100% GPU**.

### Hardware

- **Intel Arc Pro B50** `[8086:e212]`, driver `xe`, Vulkan `OLLAMA_VULKAN=1`
- OpenCL global memory **15.13 GiB** (16,241,180,672 bytes) — not a clean 16GB
- Also iGPU: Alder Lake Iris Xe `[8086:46a6]`
- System RAM 64 GB
- `OLLAMA_NUM_PARALLEL=1`
- **`OLLAMA_MAX_LOADED_MODELS=3` live** (not 1). Drop-ins disagree (2 vs 3); systemd `Environment=` shows **3**.

### gemma3:27b VRAM verdict

| Test | Processor | Size | Latency (3 output tokens) |
|---|---|---|---|
| 27b while 4b+embed on GPU | **100% CPU** | 19 GB | 22s load+eval |
| 27b after `ollama stop` left GPU empty | **100% CPU** | 19 GB | 13s |

**27b does not fit the B50 and Ollama is not partial-offloading layers.** It is a 19GB CPU process. “Deep overnight GPU synthesis” is a label on a slow CPU job. Cron even **skips** 27b in the fleet health ping: `LLM_HEALTH_SKIP_MODELS="gemma3-overnight,gemma3:27b"`.

MAX_LOADED=3: 4b was **not** evicted when 27b loaded; both stayed resident (4b GPU + 27b CPU). The schedule that assumes one slot is wrong — but 27b never took the GPU slot anyway.

---

## 3. Q2 Track A — machine scorecard

**Task:** identical JSON prompt, planted GROUND_TRUTH prices/RSI/support (numeric fidelity = echo, the disqualifier). 30 symbols (10 T0 / 10 T1 / 10 T2-T3 incl. catalysts BULL/BTCT/BIVI/BEEM/AVAV/SMCI and illiquids MOGU/WLDS/GXAI).

**27b capped at n=3** (~85s each on CPU; 30× would be ~40 minutes of CPU thrash).

DeepSeek Flash/Pro via governed bridge with **different callers** so the server actually selects those models (`advisory_desk` → Flash, `alex`+`cio_synthesis` → Pro). Vision-exp **direct API** (`reasoning_effort=high`) because the bridge **ignores client `model`**.

| Lane | n | parse | numeric exact | accept | p50 s | p95 s | empty/fail | notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| chatgpt `:8646` gpt-5.4-mini | 30 | 100 | **100** | 100 | 5.97 | ~7 | 0 | |
| grok `:8645` grok-3-mini | 30 | 100 | **100** | 100 | 9.77 | 31.2 | 0 | |
| deepseek-v4-pro | 30 | 100 | **100** | 100 | 2.08 | 3.5 | 0 | returned `deepseek-v4-pro` |
| deepseek-v4-flash-vision-exp **text CONTROL** | 30 | 100 | **100** | 100 | 2.01 | 3.3 | 0 | returned **vision-exp** (direct API) |
| deepseek-v4-flash | 30 | 90 | 90 | 90 | **1.41** | 8.2 | 10 | 3× HTTP 500 on bridge at symbols 28–30 |
| local-gemma-4b | 30 | 100 | **100** | 100 | 8.75 | 87.4 | 0 | one 87s outlier (DFSC) |
| local-gemma-12b | 30 | 100 | **100** | 100 | 24.16 | 25.3 | 0 | rock-stable ~24s |
| internal-deep-27b | 3 | 100 | **100** | 100 | 84.7 | 86 | 0 | 27 skipped on purpose |

### Harness validation (vision-exp text vs Flash)

On the **27 symbols both OK**: exact-match **27/27 both**. **Delta = 0.** Control ties. The three Flash 500s are **bridge/process 500s in 0.005s**, not a Flash-vs-vision quality gap. Instrument is trustworthy for this task; do not treat Flash 90% as a model quality score.

### Flash-at-`max` vs Pro-at-`high` (n=5 T0)

Both **5/5 exact**. Flash-max p50 ~2.7s vs Pro-high ~2.1s on the main set. **More thinking on Flash did not beat Pro on this echo task; Pro did not beat Flash either.** No 3× quality gain observed here.

### Cost (off-peak card, cache-miss)

From returned usage:

| Lane | prompt tok | completion tok | est. USD (off-peak miss) |
|---|---:|---:|---:|
| Flash (27 OK) | 5,347 | 1,979 | **~$0.0025** |
| Pro (30) | 5,941 | 2,757 | **~$0.009** |
| vision-exp text (30) | 8,311 | 5,415 | **~$0.005** |
| Flash-max extra (5) | ~1.5k | ~1k | **~$0.001** |

**Bake-off DeepSeek total ≪ $0.05. Cap $0.50 not raised, not bound.**

`$ / accepted` on this task is **noise** (sub-cent). **Seconds per accepted** is the real ranking: Flash ~1.4s, Pro ~2.1s, ChatGPT ~6s, 4b ~9s, Grok ~10s, 12b ~24s, 27b ~85s.

### Blind human scoring

Sheet: `/tmp/tradeai-bakeoff-20260821/operator_blind.md` (30 triplets). **Not scored by an LLM.** Fill rank + usable; then decode with `operator_blind_key.json`.

---

## 4. Q3 — OAuth restore?

Stated deprecation reason (hourly Telegram research spam) **no longer applies** (§5 thesis-only Telegram).

| Question | Evidence |
|---|---|
| Are they good on echo-fidelity? | **Yes** — 30/30 exact today |
| Production reliability | Grok **43% 403** over 90d; multi-day 0-success clusters. ChatGPT **13-day zero-ok gap** |
| Rate limits | Not fully characterized; grok p95 31s once; otherwise ~10s. ChatGPT stable ~6s |
| Auth durability | Lapse was **missing data**, then keepalive was added. Keepalive ≠ researcher path |
| Re-noise | Thesis-only Telegram still closed. Restoring auto-dispatch to `hermes_external_researcher` would refill the **store**, not Telegram, unless some other consumer still fans out |

**Recommendation: `restore-as-fallback-only`.**

Do **not** make either the workhorse. Use as overflow when Flash is 500/capped. Keep keepalive. Add an alarm on `hermes_external_research` error_rate by lane (the store, not `/health`).

---

## 5. Q4 — Routing table (measured, not a prior)

**No flags flipped in this exercise.**

| Role | Recommendation | Justification |
|---|---|---|
| **Workhorse (judgment)** | **DeepSeek V4-Flash** on the **working** path (`llm_lane.py` / bridge), **not** `from lib.llm_lane` | 1.4s, echo-exact, ~$0.03–0.17/day observed Flash spend; $0.50 cap never binds. Scheduler store is 100% dead only because of the import bug. |
| **Workhorse call cap** | Raising `RESEARCH_EXTERNAL_BUDGET_PER_RUN` while leaving **dollar** cap $0.50 is the right *policy* move **after** the import is fixed | 400 Flash calls/day × ~$0.001 ≈ **$0.40/day** worst-case full-due; holdings-only ~**$2/month**. User’s $2–3/month is holdings-scale. Full 974 without a skip gate can approach the dollar cap. **Fix skip gate + import first; then re-derive the call cap.** |
| **CIO / disagreement** | V4-Pro stays escalation | 3× price, **0× quality** on echo; no reason to pay 3× for the workhorse. Keep PRO for alex_cio. |
| **Local 4b** | **Keep** for structured/math-adjacent JSON and as free overflow | 30/30 exact, ~9s, $0. Stored 90d `[` rate **0%**. Job-queue 28% fail is infra, not model garbage. |
| **Local 12b** | **Keep** but not workhorse | 30/30 exact, **24s p50** (too slow for 974/day). Stored thesis-challenge looks healthy (med 484, 0 dups). |
| **Local 27b** | **Retire as GPU deep lane** | **100% CPU**, 19GB, ~85s. Does not fit 15.13 GiB B50; no layer offload. 21 stored rows in 90d. Health cron already skips it. |
| **qwen3:1.7b** | Strike from docs (already struck in #437) | Not installed. |
| **Grok / ChatGPT auto** | Fallback only | Good when up; 403 and 13-day lapse disqualify workhorse. |
| **Vision-exp** | **No production lane** | Experimental ID. Track B n=5 labeled charts: 4/5 parsed **exact**, 0 extra levels; 1 empty (`V`). n=5 is **not** the requested 30. Capability: labeled readout works. **Do not build a vision pipeline on this.** |
| **Math** | **Python, not any LLM** | Scheduler `QUESTION` is qualitative (sound / catalysts / what changes mind) — not arithmetic. Bake-off planted numbers were *copied*, not computed. Any card math (RSI, zones, `derive_intel_state`) stays in code. |

### Can Flash take the workhorse outright?

**Yes.** #440 landed the import. Proof: scheduler-path id=45900 `status=sent`. Re-baseline spend 7 days before touching the call cap. Do not raise `LLM_GLOBAL_DAILY_USD_CAP`.

### Is local worth keeping?

**Yes for 4b/12b.** Q0 stored `[` rate is 0%, not 40%. Q2 echo-fidelity 100%. They are slow vs Flash (9s / 24s vs 1.4s) and the **maria job queue** is choking (28.5% fail) — retire the *enqueue flood*, not the models. #438 already defaults `RESEARCH_ALLOW_LOCAL_LLM=0` for scheduler enqueue; that matches this measurement.

### Is the 27b lane real?

**No as a GPU deep-synthesis lane.** It is a CPU 19GB process. Do not plan overnight 27b “multi-agent synthesis” on this box.

---

## 6. Track B — vision pipeline?

| | |
|---|---|
| Model | `deepseek-v4-flash-vision-exp` (in `/v1/models` today) |
| n | **5** synthetic labeled charts (not 30; side quest) |
| Parsed JSON | 4/5 (`V` returned empty content) |
| Exact / 1% / 3% on parsed fields | **12/12 exact** |
| Extra/hallucinated levels | **0/4** |
| Production | **Do not wire.** Experimental ID. Flag default 0 if ever prototyped; Flash text fallback on 400. |

**Does Track B justify a vision pipeline? No.** Promising labeled-read on n=5 is not a pipeline. Chartography 64.3 is still a prior.

---

## 7. What we did *not* do

- No routing flag changes, no cap raise, no CURRENT promote, no merge of #437/#438
- Did not use Claude as judge
- Did not write production research rows
- Did not run 30×27b (CPU)
- Did not complete operator blind ranking (sheet ready)

---

## Artifacts

`/tmp/tradeai-bakeoff-20260821/`

- `outputs_keyed.jsonl` / `outputs_blind.jsonl` / `lane_key.json`
- `scorecard.json` / `flash_max_extra.json` / `track_b.json`
- `operator_blind.md` + `operator_blind_key.json`
- `run_track_a.py` (sandbox harness)
