# Research tiers, watchlist, and when each gets an LLM

**Date:** 2026-08-22  
**Authority:** READ_ONLY_ADVISORY  
**Code:** `scripts/research_scheduler.py` (`TIER_SLA`, `load_universe`, `--mode`)  
**Live crontab:** `$PROJ=` rebuild, weekday unless noted.

There is **one watchlist research tier: T1-WATCH**. There are **five universe tiers** total. Reentry READY/NEAR is **not** a sixth tier — those names **join T1-WATCH**.

Hermes **S0–S3** is a different ladder (scope governor on `watchlist_items.scope_tier`). S3-archived names are dropped from T1/T2 into T3-COLD. T0 (capital) is never downgraded. Do not treat S0–S3 as extra watchlist LLM tiers.

Live counts 2026-08-22: T0-HOLD **22** · T0-PROP **30** · T1-WATCH **331** · T2-INCUB **141** · T3-COLD **2537**. T1 includes Hermes rank ≤ `TOP_RANK_N` (default **200**) + active watch directives + reentry READY/NEAR (**25** today).

---

## The five universe tiers

Highest membership wins (`load_universe`).

| Tier | Who | How you get in | Scheduler LLM (auto) | SLA | Cron `--mode` | When |
|---|---|---|---|---|---|---|
| **T0-HOLD** | Open book (held equity tickers, not CASH/CUSIP) | `holdings.json` | **DeepSeek** every holdings run. Local gemma / internal-deep listed but **off** (`RESEARCH_ALLOW_LOCAL_LLM=0`) | **3× / 1 day** | `holdings` budget 70 | **M–F 08:00, 12:30, 16:30 ET** |
| **T0-PROP** | Active paper proposals | `paper_trade_proposals` PENDING/APPROVED | **DeepSeek** when the name is due in `priority` (T0 always candidate) | **2× / 1 day** | `priority` budget 40 | **M–F hourly 10:00–16:00 ET** |
| **T1-WATCH** | **The watchlist hot set** | Hermes rank ≤ 200 **or** active ticker directive **or** reentry READY/NEAR | **DeepSeek**, **one** external per refresh (rotation is a no-op while DeepSeek is the only auto lane) | **4× / 7 days** | `watchlist` budget 50; also `priority` if due/catalyst | **M–F 20:30 ET** watchlist sweep; **M–F 10–16** priority if due |
| **T2-INCUB** | Incubator / proposed in last 21d | `incubator_universe` active + recent proposals | **DeepSeek only if catalyst**; else no external | **1× / 7 days** | `incubator` budget 30 | **Sunday 19:00 ET** |
| **T3-COLD** | Rest of `symbol_profiles` | leftover after higher tiers | **No DeepSeek** unless catalyst. Local gemma listed, **off** | **1× / 14 days** | `cold-floor` budget 20 (rotating slice) | **Daily 10:00 ET** (off-peak wrap) |

SLA “due” ≠ execute. Lifecycle skip (`RESEARCH_SKIP_GATE`, default **0**) is still off, so due symbols are called. Cap: process `hermes_external_research` **120 calls / $0.30**/day in registry (DB soft_cap 120). Cron budgets are per-run, not per-day.

---

## Watchlist: there is not a T1/T2/T3 *inside* watchlist

People hear “T1-WATCH” and ask how many watchlist tiers. Answer:

1. **T1-WATCH** — the only tier that *is* the research watchlist (rank + directives + reentry READY/NEAR).
2. **T2-INCUB** — not “watchlist tier 2.” Incubator / recently proposed. LLM only on catalyst except the Sunday sweep’s local (off) + catalyst DeepSeek.
3. **T3-COLD** — not “watchlist tier 3.” The long tail. No auto DeepSeek without catalyst; cold-floor is a 20-name rotate, and with local LLM off that run is mostly a no-op unless catalyst.

Reentry READY/NEAR (**25** live) → `load_reentry_ready_near_symbols()` → **add as T1-WATCH**. Same DeepSeek cadence as the rest of T1. They do **not** get the T0 holdings 3×/day pass.

---

## Which LLM actually fires

| Lane | Auto on these tiers? | Frequency | Notes |
|---|---|---|---|
| **DeepSeek Flash** | T0-HOLD, T0-PROP (via priority), T1-WATCH, T2/T3 **catalyst only** | Cron table above | Scheduler `--lane deepseek`. Writer `hermes_external_researcher.py`. |
| **ChatGPT / Grok OAuth** | **Not** scheduler auto | Every **2h** `hermes_top20_external_intel.py` | Top-20 + directives. Held names tagged `trigger=holdings`. Separate family. |
| **Local gemma** | Listed on all five SLAs | **Off** | `RESEARCH_ALLOW_LOCAL_LLM=0`. Rebuild scheduler still *would* enqueue if you `--apply` it; CURRENT filters queue lanes. |
| **Claude** | never auto | manual `--apply-paid` | Paid. |
| **Overnight-deep** | policy ChatGPT 22:00–06:00 ET | live timer still China-night gemma | Not a universe tier. |

---

## Cron (copy of live lines)

```
0 8 * * 1-5      --mode holdings   --budget 70   # T0-HOLD DeepSeek
30 12,16 * * 1-5  --mode holdings   --budget 70
0 10-16 * * 1-5  --mode priority   --budget 40   # T0 + due T1 + catalyst
30 20 * * 1-5     --mode watchlist  --budget 50   # T1-WATCH only
0 10 * * *       --mode cold-floor --budget 20   # T3 slice
0 19 * * 0       --mode incubator  --budget 30   # T2 Sunday
```

Saturday/Sunday: **no** holdings / priority / watchlist DeepSeek unless someone runs it. That is why 2026-08-22 morning holdings were a **manual** test, not cron.

---

## Confirm-run (2026-08-22, ignore standing $0.50 in-process)

| Bucket | Intended | Result |
|---|---|---|
| T0-HOLD | all 22 | **22/22** DeepSeek sent ids 46013–46034 · **$0.00795** |
| T1 reentry READY/NEAR | all 25 | **25/25** ids 46035–46059 (in-flight test) |
| T1-WATCH remainder | all 331 | cron only does **50**/run; full remainder run after this doc |
| T0-PROP | all 30 | not cron on Saturday — run with remainder |
| T2-INCUB | production = catalyst only | confirm with a DeepSeek pass (note vs production gate) |
| T3-COLD | production = no DeepSeek unless catalyst; cold-floor 20 | confirm **20** slice, not 2537 |

Standing `.env` cap stays **0.50**. Test process uses `LLM_GLOBAL_DAILY_USD_CAP=25`. Process request cap 120/day is the other limiter unless raised for the confirm-run.

See also: `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md` (two LLM families) · `docs/RESEARCH_PRIORITIZATION.md` (policy SLA).
