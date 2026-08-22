# Research coverage snapshot — 2026-08-22 10:24 ET

**Authority:** READ_ONLY_ADVISORY  
**Financial action:** none  
**CURRENT pin:** `5e91225a` (not promoted for this). Live research crontab is still `$PROJ=` rebuild.  
**This note did not exist until now.** Friday–Saturday work documented oversight (#445) and Drive; it did **not** write this coverage picture. Parse errors were **not** fixed until this PR.

Flags unchanged: `RESEARCH_SKIP_GATE` unset/0 · `MEMORY_BEHAVIOR_INFLUENCE` unset/0 · `RESEARCH_ALLOW_LOCAL_LLM` unset/0.

## Are all LLM lanes working?

| Lane | Working? | Last 24h (as of snapshot) | Why |
|---|---|---|---|
| ChatGPT OAuth `:8646` | **yes** | 89/89 ok | `llm_lane.available('chatgpt')=True` |
| Grok OAuth `:8645` | **yes, not clean** | 67/96 ok | Lane up; some calls fail |
| DeepSeek Flash | **no, as scheduler `deepseek`** | 1/275 ok | See below |
| Claude | manual | 0 | `available('claude')=False` — expected |
| Overnight-deep | **no** | 0 | Last rows **2026-08-20 19:36 ET** `deepseek-v4-flash`. Alarm `zero_non_error_24h`. Policy is US overnight ChatGPT OAuth; live timer is still China-night gemma |
| Local gemma | Ollama up | not a research lane | Policy: math-only. `holdings_llm_refresh` still calls it (below) |

`llm_lane.available('deepseek')` is **False** on purpose — alias is ambiguous (`_AMBIGUOUS_DEEPSEEK`). Real model id is `deepseek-flash` (available True). Scheduler still auto-dispatches lane name **`deepseek`**.

### DeepSeek — two stacked failures, not “not scheduled”

RAW `hermes_external_research` last 36h (ET hours):

| When | Class | n |
|---|---|---|
| Fri 08:00–16:00 | `[ERROR] No module named 'lib.llm_lane'` | 223 |
| Fri 18:40 | **ok** SCHD (P0 #440 proof) | 1 |
| Fri 18:00 + 20:00 | `COST_CONFIGURATION_INVALID: global daily USD cap required` | 51 |
| Sat | nothing | weekday cron `1-5` |

Import errors stopped after #440. Then cron Python loaded rebuild `.env` which **had no** `LLM_GLOBAL_DAILY_USD_CAP` (systemd units have `0.50`; `.env` did not). `llm_consumption.py` fail-closes metered calls without that env. Restored on the live rebuild `.env` as `0.50` (not a raise — match systemd). Do not raise the cap.

## Holdings / reentry / watch — analyzed?

Three different books. Do not collapse them.

### 1. External research (`hermes_external_research`) — 22 held equity tickers

Denominator: `held_equity_tickers()` = AMANX ARKX BAH BND CSWC DIV DIVI DXCM JEPI LDOS NOC PFLT QCOM RTX SCHD SCHG SPCX SRNE V XAR XLB XLI. CASH + 3 CUSIPs out.

| Lane | Ever non-error | Last 24h | Last 14d chatgpt+grok |
|---|---|---|---|
| ChatGPT | **22/22** | 21/22 | all 22 |
| Grok | **22/22** | 17/22 | all 22 |
| DeepSeek | **1/22** (SCHD Fri 18:40) | 1 | — |

SRNE last ok **2026-08-13** (still inside 14d). Worthless/revoked; not a gap in the 14d window.

**Who writes ChatGPT/Grok holdings?** Not `research_scheduler` T0 lanes. Scheduler comment: grok/chatgpt are **not auto-dispatched**. T0-HOLD lanes = `local-gemma` (gated off) + `internal-deep` (gated off) + **`deepseek`**. ChatGPT/Grok holdings rows are `trigger_reason=holdings` from **H-enh position** (`hermes_subject_enhance.py --type position --lanes grok,chatgpt` every 2h). That job is why the held book looks covered on OAuth while DeepSeek does not.

### 2. Living CIO thesis (`HeldBookThesisCoverage@v1`) — **not** the LLM row

Artifact `data/cio/held_thesis_coverage_latest.json` as_of 2026-08-21 11:20 ET:

- 3/22 CURRENT (**13.6%**), SLA 80% **not met**
- CURRENT: DIV, DIVI, JEPI
- 19 `RESEARCH_REQUIRED` — missing a living symbol thesis (role / why owned / invalidation), not “no ChatGPT paragraph”

This is a different store. External research ≠ thesis. `RESEARCH_SKIP_GATE` still 0, so the skip index is not the reason theses are missing.

### 3. Reentry READY/NEAR — **in universe, not freshly researched**

25 names join T1-WATCH (no new tier). Scheduler `--mode watchlist` only auto-dispatches **`deepseek`** (plus local-gemma, which is off). DeepSeek is dead → T1/reentry starve.

Never a non-error external row: **FSPTX, LGPS, MOGU, WLDS, XCUR**.

Others last ran June–early August (TSLA 7/01, CACI 8/03, CSCO 8/12). None this week. **Do not auto-backfill.**

### 4. T1-WATCH

332 symbols. Any-lane ok in 14d: **153**. Miss: **179**. Same cause: T1 rotates one DeepSeek call; OAuth is not on that lane list; local LLM off.

## `holdings_llm_refresh` parse_error — not fixed until this PR

Fri 2026-08-21 07:15 ET cron (`rebuild`, gemma3:4b):

- 26 holdings, 19 refreshed, **Errors: 0** (bug: `parse_error` was not counted)
- `parse_error`: LDOS, V, DXCM, BND, JEPI, QCOM, DIVI (V later succeeded on a retry in the same run)
- Cause: `LOCAL_LLM_NUM_PREDICT` default **300**. Schema + G1–G10 preamble does not fit; gemma hits 300 tokens (`Ollama OK — gemma3:4b … 300 tokens`) and `extract_json_object` returns None because the JSON never closes
- Job still uses **local gemma for judgment**, against “unless math, no local LLM”. Freeze: **do not** reroute this job to ChatGPT until after 8/27 (that would change stored health/action). This PR only: process-local `NUM_PREDICT=900`, salvage health/action from truncated JSON, log `raw[:400]`, count parse_error as Errors

## What this PR does / does not

| Does | Does not |
|---|---|
| Write this snapshot | Promote CURRENT |
| Salvage + log parse_error; raise this job’s token cap | Auto-research the 5 never-touched reentry names |
| Restore missing `.env` `LLM_GLOBAL_DAILY_USD_CAP=0.50` on live rebuild (ops, not git) | Flip `RESEARCH_SKIP_GATE` / local-LLM / overnight timer |
| | Reroute holdings_llm_refresh off gemma |

## Metric

- Lane health: `scripts/research_lane_health.py` (deepseek + overnight-deep still the expected reds until Monday cap-bearing DeepSeek runs)
- Thesis: `data/cio/held_thesis_coverage_latest.json` `held_current_pct`
- Parse: next `holdings_llm_refresh` log — parse_error should drop; Errors must include remaining parse_error
- Tests: `tests/test_holdings_health_parse.py`

## MATURITY_IMPACT

Coverage was unmeasured-as-ops-doc (operator asked; answer lived only in chat). Parse_error was a silent 7/26 miss on the holdings health cron. Live path: snapshot file + salvage/token-cap. DeepSeek still needs the cap env on Monday’s weekday scheduler — restored on rebuild `.env`.
