# Research quality, thesis mint gap, alarms — 2026-08-22

**Authority:** READ_ONLY_ADVISORY  
**Freeze:** no live thesis store writes, no CURRENT promote, no card wiring. Q2 apply after 8/27.  
**Proof artifacts:** `data/cio/research_quality_sample_2026-08-22.json`, `data/cio/thesis_mint_dryrun_2026-08-22.json`

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

CURRENT bar is `summary >= 40` chars on `symbol_<ticker>`. Today's DeepSeek recs clear that bar. Quality (Q1) says they are thin — minting them would turn 13.6% into ~100% **coverage**, not ~100% **quality**.

## Q3 — Alarm holes

- DeepSeek stays in `lanes[]` always. Telegram `--alert` now prints a **Watched: deepseek** line even when ok, so the outage alarm cannot "forget" the lane it was built for.
- **`main()` exits 0** when the check ran. Exit 1 = collect crashed. Exit 2 = Telegram send failed. Alarm state is JSON `ok`/`firing` + Telegram. systemd `failed` no longer means "found problems."
- New lane **`coverage-stall`**: DeepSeek ok_24h ≥ 20 and held CURRENT < 80% SLA while research is not falling. **Today would fire.**

## Q4 — Overnight-deep: fix. Autonomous-loop: disable.

China-night timer (18:00–08:35 Asia/Shanghai) is **US daytime**. That is why the unit dry-runs at hour=9–12 ET with `targets=[]`. Last `deep_overnight_llm_results` row **2026-05-24**. Policy is ChatGPT 22:00–06:00 ET.

- **Fix:** `hermes-deep-research-local.timer` → `America/New_York` 22,23,00,01,02,03,04,05:35. Service `--model chatgpt` (script already remaps on US overnight).
- **Kill:** `hermes-autonomous-loop.timer` disabled. Script **refuses `--apply`** when model is gemma and `RESEARCH_ALLOW_LOCAL_LLM=0` (the 12:10 AJG/AMAT 503 path).

## Q5 — T3 SLA

Published 1×/14d × 2537 names = **181/day**. Production was **20/day → 127-day cycle**. At $0.000313/call the 14-day cycle is **$0.057/day** inside $0.50. Blocker was the **120-call process cap**, not dollars (today 34% of $0.50).

Change: `hermes_external_research` **daily_soft_cap 120 → 600**. Dollar caps stay **process $0.30 / global $0.50**. Cold-floor cron **budget 20 → 180**. 180×14 ≈ 2520. SLA is now physically possible.
