# Research lane health + P0 outage (2026-08-21)

**Authority:** READ_ONLY_ADVISORY  
**Flag:** none (alarm is observational). `MEMORY_BEHAVIOR_INFLUENCE` stays 0.

## Why last_real hid the outage

`research_scheduler.py` computes `last_real` with `recommendation NOT LIKE '[%'`.
Every DeepSeek row from 2026-08-13..21 was `[ERROR] No module named 'lib.llm_lane'`.
Filtered through last_real the lane looked empty — identical to “no new research yet.”

`scripts/research_lane_health.py` reads the **RAW** store.

Fires per lane on:

1. newest N rows all error/empty (`RESEARCH_LANE_ERROR_STREAK`, default 5)
2. zero non-error rows in 24h (`RESEARCH_LANE_SILENCE_HOURS`, default 24)

| Lane | Store | 24h silence | Notes |
|---|---|---|---|
| `deepseek` | `hermes_external_research` | yes | scheduler workhorse |
| `grok` | same | yes | OAuth |
| `chatgpt` | same | yes | OAuth; **covers the 12-day lapse class** |
| `claude` | same | **no** (manual) | streak only |
| `overnight-deep` | `hermes_research_intelligence` `research_type=deep_research_local` | yes | covers ChatGPT overnight **and** the live gemma China-night timer |

## Import fix `[VERIFIED]`

`hermes_external_researcher.py` imports `llm_lane` (`scripts/llm_lane.py`).
Do not import `lib.llm_lane` — `scripts/lib` is the `lib` package and has no `llm_lane.py`.

**Scheduler-path proof (not the bridge):** `--lane deepseek --trigger research_scheduler --apply` → `hermes_external_research` **id=45900** `status=sent` (SCHD).

Shipped in **#440** (merged). Live on crontab `PROJ=` rebuild **and** CURRENT `a7f30d89`.

## Overnight identity `[VERIFIED]` 2026-08-21 18:46 ET

| Source | State |
|---|---|
| Policy (`docs/RESEARCH_PRIORITIZATION.md`, #437 merged) | US overnight judgment = **ChatGPT OAuth** `:8646`, not gemma |
| Live `hermes-deep-research-local.timer` | still **China-night gemma3:27b** calendar (US-day dry-run → empty `RESULT: {}`) |
| Alarm | `chatgpt` (external store) **and** `overnight-deep` — installed |

**Live timer is gemma-attempted, not ChatGPT.** Policy is ChatGPT. Do not retarget the timer until you want that routing change; the alarm is already covering both paths.

## Closeout (merged + promoted)

| PR | What |
|---|---|
| #440 | import fix + RAW-store alarm |
| #437 | R0 holdings denominator + ChatGPT overnight *policy* |
| #438 | R1–R5 (skip gate / payloads / coverage / scorecard) **flags default 0** |
| #439 | bake-off report |

**CURRENT:** `a7f30d89` (2026-08-21). Alarm: systemd `tradeai-research-lane-health.timer` enabled + crontab `*/15`. `RESEARCH_SKIP_GATE` unset. `MEMORY_BEHAVIOR_INFLUENCE=0`.

## Un-researched Aug 13–21 (do not auto-reacquire)

DeepSeek scheduler path: **132 symbols, 2,137 rows, 0 non-error**. All 22 held tickers were in that set (plus CASH — `isalpha` leak, fixed in #437).

Grok/ChatGPT still produced successes for **38** of those 132 (including all 22 held except SRNE last-ok 2026-08-13). **94 symbols** had no non-error external row in the window.

Reacquire cost (Flash ~$0.001/call, off-peak): **~$0.13** for 132 one-shots, **~$0.02** for held-only. **Do not auto-run.** Operator-approved backfill after this alarm is live.

## Cron

```
*/15 * * * * cd $PROJ && flock -n /tmp/research_lane_health.lock $PY scripts/research_lane_health.py --alert >> logs/research_lane_health.log 2>&1
```

Or systemd user timer `tradeai-research-lane-health.timer` (**enabled** 2026-08-21).

## 27b

Measured **100% CPU** on Arc Pro B50 (15.13 GiB). **Retired as a GPU deep-synthesis lane** (label only — blob stays on disk, health cron already skips it). Do not cron it. Do not call it “deep multi-agent synthesis.”

## TSLA canary `mem_5989433c2194182282b6e49bedb19cde`

Admitted 2026-08-18 as `ACTIVE` `OPERATOR_EXPLICIT_PREFERENCE` because:

- `source_kind=operator_feedback` + `governed_admission`
- `is_forbidden_authoritative` only matches canonical-truth **field names** (“order state”), not “place an order”
- `admit_status` scanned **subject** (“Untrusted injection canary”), not jailbreak **content**
- `MEMORY_ADVERSARIAL_SCAN` defaulted **0**, so the match was `shadow_reject`, not reject

Live snapshot 2026-08-21: **RETRACTED** `p0_adversarial_quarantine_2026-08-21`. Search does not return it. `MEMORY_ADVERSARIAL_SCAN=1` on portfolio-server. Influence 0.
