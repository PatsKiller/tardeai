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
| `overnight-deep` | `hermes_research_intelligence` `research_type=deep_research_local` | yes | ChatGPT overnight **after** overlay; today this is empty gemma |

## Import fix

`hermes_external_researcher.py` now imports `llm_lane` (`scripts/llm_lane.py`).
Do not import `lib.llm_lane` — `scripts/lib` is the `lib` package and has no `llm_lane.py`.

Prove on the **scheduler path** (this file), not `:8766`.

## Overnight identity `[VERIFIED]` 2026-08-21

| Source | Claim |
|---|---|
| Live timer `hermes-deep-research-local.timer` | China-night `gemma3:27b`, US-day dry-run → empty `RESULT: {}` |
| #437 (unmerged) | US overnight = ChatGPT OAuth, not gemma |
| `RESEARCH_PRIORITIZATION` on main | still gemma3:27b overnight |

**Live is gemma3:27b attempted, not producing.** Policy in #437 is ChatGPT. Do not overlay the #437 timer until this alarm is installed — ChatGPT carrying deep synthesis needs this alarm more than Flash.

## Un-researched Aug 13–21 (do not auto-reacquire)

DeepSeek scheduler path: **132 symbols, 2,137 rows, 0 non-error**. All 22 held tickers were in that set (plus CASH — `isalpha` leak, fixed in #437).

Grok/ChatGPT still produced successes for **38** of those 132 (including all 22 held except SRNE last-ok 2026-08-13). **94 symbols** had no non-error external row in the window.

Reacquire cost (Flash ~$0.001/call, off-peak): **~$0.13** for 132 one-shots, **~$0.02** for held-only. **Do not auto-run.** Operator-approved backfill after this alarm is live.

## Cron

```
*/15 * * * * cd $PROJ && flock -n /tmp/research_lane_health.lock $PY scripts/research_lane_health.py --alert >> logs/research_lane_health.log 2>&1
```

Or systemd user timer `tradeai-research-lane-health.timer` (install after CURRENT promote).

## 27b

Measured **100% CPU** on Arc Pro B50 (15.13 GiB). Recommend **retire as a GPU deep-synthesis lane**. Keep the blob on disk if wanted; do not cron it; do not call it “deep multi-agent synthesis.”

## TSLA canary `mem_5989433c2194182282b6e49bedb19cde`

Admitted 2026-08-18 as `ACTIVE` `OPERATOR_EXPLICIT_PREFERENCE` because:

- `source_kind=operator_feedback` + `governed_admission`
- `is_forbidden_authoritative` only matches canonical-truth **field names** (“order state”), not “place an order”
- `admit_status` scanned **subject** (“Untrusted injection canary”), not jailbreak **content**
- `MEMORY_ADVERSARIAL_SCAN` defaulted **0**, so the match was `shadow_reject`, not reject

Live snapshot 2026-08-21: **RETRACTED** `p0_adversarial_quarantine_2026-08-21`. Search does not return it. `MEMORY_ADVERSARIAL_SCAN=1` on portfolio-server. Influence 0.
