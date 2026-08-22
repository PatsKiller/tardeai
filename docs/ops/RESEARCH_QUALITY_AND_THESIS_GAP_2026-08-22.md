# Research quality, thesis mint gap, alarms — 2026-08-22

**Authority:** READ_ONLY_ADVISORY  
**Freeze:** no live thesis store writes, no CURRENT promote, no card wiring. Q2 apply after 8/27.  
**Proof artifacts:** `data/cio/research_quality_sample_2026-08-22.json`, `data/cio/thesis_mint_dryrun_2026-08-22.json`  
**Session index:** `docs/ops/SESSION_CLOSEOUT_2026-08-22.md`

## The number

539 DeepSeek calls. **$0.168934**. Thesis CURRENT **3/22 (13.6%)** — DIV, DIVI, JEPI — **unchanged**. 19 still `RESEARCH_REQUIRED`.

Plumbing is green. The brain did not learn. Research writes `hermes_external_research`. **Nothing mints `symbol_<ticker>` into `cio_theses.jsonl`.**

## Q1 — Are today's rows good?

Deterministic sample n=40 (20 T1, 10 T0-HOLD, 10 reentry). Heuristic, not a human grade. Blind sheet remains sealed.

| Metric | Result |
|---|---|
| Median length | **320 chars** |
| % under 300 chars | **45%** |
| % symbol-specific keyword (earnings/filing/catalyst/…) | **60%** |
| % generic-prose (HOLD/WATCH, insufficient evidence, …) | **15%** (threshold 40% — **not** a clone farm) |
| % numeric restatement suspect | **15%** |
| Cross-symbol near-duplicate (5-gram Jaccard ≥0.45) | **0%** |
| % that would survive as a thesis without human editing | **27.5%** |

Verdict: the lane is **not** repeating the same paragraph across tickers. It is also **not** producing mint-grade theses. Median 320 chars, 45% under 300, 27.5% survivable. Error-prefix health is a crash detector; this is the content half.

## Q2 — Mint path dry-run (no live store)

`scripts/thesis_mint_from_research.py --apply-staging`

Sources: existing `hermes_external_research` + Hermes rank + portfolio role. **No new LLM.** Staging only: `data/cio/staging/symbol_thesis_mint_dryrun.jsonl`.

| Book | Live CURRENT | Would mint from disk |
|---|---|---|
| T0-HOLD 22 | 3 | **22/22** |
| Of the 19 RESEARCH_REQUIRED | 0 | **19/19** |
| Reentry 25 | (not in held SLA) | **25/25** |

**Coverage was never a research problem.** It was a wiring problem. Every T1 dollar bought data the thesis store does not read. Apply mint after 8/27; do not publish to live `cio_theses.jsonl` during the window.

CURRENT bar **was** `summary >= 40` chars on `symbol_<ticker>`. That is the fake-green. M1 splits it.

## M1 — Quality gate (THIN ≠ CURRENT). Three published numbers.

`CURRENT` is now PASS-grade (Q1 survivable): ≥400 chars, ticker, symbol-specific fact, non-generic, numeric fidelity, survive-needle (invalidation / role / why own / catalyst / stop). Grade B/C mint as **`THIN`**. THIN counts toward `coverage_pct` and `fresh_pct`. It does **not** count toward `substantive_pct`. `sla_met` requires coverage 100 **and** fresh ≥90 **and** substantive ≥70.

Live held book after the classifier (no live mint):

| | n | % |
|---|---:|---:|
| coverage (CURRENT\|THIN) | 3/22 | 13.64 |
| fresh | 3/22 | 13.64 |
| **substantive (PASS)** | **0/22** | **0.0** |
| THIN (DIV, DIVI, JEPI re-graded) | 3 | — |
| RESEARCH_REQUIRED | 19 | — |

The three names that were "CURRENT" were paragraphs, not theses. `substantive_pct=0` is the honest number.

**Projected split of the 19 RESEARCH_REQUIRED (today's disk, no new LLM):**

| Input | CURRENT (PASS) | THIN | SKIP |
|---|---:|---:|---:|
| rec-only (`recommendation` column) | **2** | 15 | 2 |
| joined (rec + dissent + evidence) | **12** | 7 | 0 |

**2/19 rec-only, 12/19 joined.** That is the number to remember, not 19/19. 19/19 is coverage after a join. Joined mint would land ~15/22 holdings CURRENT (68%) — shy of the 70% substantive target. Staging only: `data/cio/staging/symbol_thesis_mint_dryrun.jsonl`. Live `cio_theses.jsonl` untouched.

### Q1 — the other 5 of 19 (there is no unlabeled remainder)

The 2 CURRENT / 12 THIN mix came from stacking rec-only CURRENT (2) with joined CURRENT (12). Those are two different grades of the same 19, not CURRENT+THIN. Rec-only (what the mint now uses — stored `recommendation`, not joined evidence):

| Bucket | n | Names |
|---|---:|---|
| CURRENT (A / PASS) | **2** | AMANX, BAH |
| THIN/B | 11 | ARKX, BND, CSWC, DXCM, LDOS, QCOM, SPCX, SRNE, XAR, XLB, XLI |
| THIN/C (sub-300 / missing needles) | 4 | RTX, SCHD, SCHG, V |
| **STUB/F** (ungradeable stored rec) | **2** | NOC 17 chars, PFLT 7 chars |

2+11+4+2 = 19. THIN total = 15. STUB = do not mint; stay `RESEARCH_REQUIRED`.

### Q2 — dashboard after mint is not 19/19 and not 5/22 grandfathered

Mint grade is rec-only. Quality gate still runs on read for **everyone**, including the existing 3 (DIV, DIVI, JEPI fail PASS → THIN). Grandfathering those 3 as CURRENT would hide the thing the gate caught.

After rec-only mint apply (still after 8/27):

| Tile | n | % |
|---|---:|---:|
| CURRENT (PASS) | 2/22 | **9.1** (AMANX, BAH) |
| THIN | 18/22 | 81.8 (15 minted + 3 existing) |
| RESEARCH_REQUIRED / STUB | 2/22 | 9.1 (NOC, PFLT) |
| coverage_pct (CURRENT\|THIN) | 20/22 | 90.9 |
| substantive_pct | 2/22 | 9.1 |

5/22 = 22.7% only if we counted the existing 3 as CURRENT. We will not. `sla_met` stays false. The 19/19 green tile cannot happen.

Coverage-stall now fires on **PASS count < 70% of held**, not row-exists. A 22/22 THIN mint with 5 PASS still fires.

## M2 — 320 chars is the stored field, not Flash.

Config actually sent:

| Knob | Value |
|---|---|
| Process `max_output_tokens` | **1024** (`hermes_external_research`) |
| Caller default | 1500 → gate `min` → **1024** |
| Flash model ceiling | **384000** |
| Parser | `recommendation[:500]` |
| Prompt brevity | none explicit; JSON contract + "Give a clear recommendation…" |

Today's `llm_consumption_log` (n=546, $0.168934):

| | p50 | p90 | notes |
|---|---:|---:|---|
| tokens_in | 576 | 831 | input dominates |
| tokens_out | **824** | 1022 | not 80 tokens |
| response_chars | **3513** | 4316 | model already writes |
| % at 1024 cap | | | **11.4% (62)** |

Stored `recommendation` today (n=545): **p50=230 chars**, 61.7% <300, 16% at/over 500 (parser cluster). Q1's 320 was a 40-row sample of the same truncated column.

You already pay for ~825 output tokens and keep 500 characters. There is no cost argument for thin **stored** recs. Proposed, **not applied**: parser `[:500]→[:4000]`; prompt requires the recommendation string to *be* the thesis; ceiling 1024→4096. Dollar caps unchanged.

Sandbox 20 (`HERMES_SANDBOX_OUTPUT_CEILING=1`, `--no-store`, prompt-file, 4096, trigger `holdings`, 20/20 sent):

| Grade on | PASS |
|---|---:|
| stored rec (still `[:500]`) | **40%** |
| joined rec+dissent+evidence | **90%** |
| raw model text | **100%** |

The ceiling+prompt package makes the **model** thesis-survivable. The parser still throws the thesis away. Production cap stays 1024. Cron does not pass the flags. Highest-leverage unapplied patch is `recommendation[:500]→[:4000]`.

## M3 — Drive 404s

Hourly sweep ≠ targeted gog replace. Failures were `docs/_archive`, dated session-dump dirs, `_findings` / `ui_review` screenshot trees. Sweep now excludes those, purges dead cache lines, and **does not fall back to the Drive root on mkdir fail**.

Proved on the **same sweep path** cron uses (`CURRENT/scripts/sync-docs-to-drive.sh` overlay): **uploaded=26, skipped=2069, failed=0, exit_code=0** at 2026-08-22T21:09:15Z. Alarm can go green on the next lane-health tick.

## M4 — Freeze / payload clock

`git diff` vs #453 on DecisionPayload producers: **empty**. Traces CURRENT `agent_run_traces.jsonl`:

| UTC | v1 | reentry | material_scan | freeform | watch | holdings | advisory | opportunity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8/21 | 268 | 165 | 102 | 1 | 0 | 0 | 0 | 0 |
| 8/22 | 3500 | 3125 | 375 | 0 | 0 | 0 | 0 | 0 |

Reentry and material_scan **accrued**. freeform 1→0 is a one-off Telegram desk reply, not a daily producer — clock does **not** restart. watch/holdings/advisory/opportunity still 0 (pre-existing emit gap). CURRENT pin `5e91225a` lacks #451+ docs. **Noted. Not promoted.**

## Q3 — Alarm holes

- DeepSeek stays in `lanes[]` always. Telegram `--alert` now prints a **Watched: deepseek** line even when ok, so the outage alarm cannot "forget" the lane it was built for.
- **`main()` exits 0** when the check ran. Exit 1 = collect crashed. Exit 2 = Telegram send failed. Alarm state is JSON `ok`/`firing` + Telegram. systemd `failed` no longer means "found problems."
- New lane **`coverage-stall`**: DeepSeek ok_24h ≥ 20 and held **PASS/CURRENT < 70%** while research is not falling. THIN rows do not quiet it. **Today would fire.**

## Q4 — Overnight-deep: fix. Autonomous-loop: disable.

China-night timer (18:00–08:35 Asia/Shanghai) is **US daytime**. That is why the unit dry-runs at hour=9–12 ET with `targets=[]`. Last `deep_overnight_llm_results` row **2026-05-24**. Policy is ChatGPT 22:00–06:00 ET.

- **Fix:** `hermes-deep-research-local.timer` → `America/New_York` 22,23,00,01,02,03,04,05:35. Service `--model chatgpt` (script already remaps on US overnight).
- **Kill:** `hermes-autonomous-loop.timer` disabled. Script **refuses `--apply`** when model is gemma and `RESEARCH_ALLOW_LOCAL_LLM=0` (the 12:10 AJG/AMAT 503 path).

## Q5 — T3 SLA

Published 1×/14d × 2537 names = **181/day**. Production was **20/day → 127-day cycle**. At $0.000313/call the 14-day cycle is **$0.057/day** inside $0.50. Blocker was the **120-call process cap**, not dollars (today 34% of $0.50).

Change: `hermes_external_research` **daily_soft_cap 120 → 600**. Dollar caps stay **process $0.30 / global $0.50**. Cold-floor cron **budget 20 → 180**. 180×14 ≈ 2520. SLA is now physically possible.
