# Research tiers, watchlist, and when each gets an LLM

**Date:** 2026-08-22 (confirm-run closed 12:43 ET; DB proof 12:50 ET)  
**Authority:** READ_ONLY_ADVISORY  
**Code:** `scripts/research_scheduler.py` (`TIER_SLA`, `load_universe`, `--mode`)  
**Live crontab:** `$PROJ=` rebuild, weekday unless noted.  
**Proof:** `data/cio/deepseek_all_tiers_confirm_2026-08-22.json` (rebuild tree, not git).

## Direct answer: how many watchlist tiers?

There is **one watchlist *research* tier: T1-WATCH**.

Three other ladders also use the word “tier.” They are **not** extra LLM watchlist queues. Mixing them is how “T1 watchlist / how many tiers?” gets confusing.

| Ladder | Values | What it controls | LLM? |
|---|---|---|---|
| **Universe (scheduler)** | **T0-HOLD, T0-PROP, T1-WATCH, T2-INCUB, T3-COLD** (five) | Who is a candidate for `research_scheduler` DeepSeek | **Yes — this is the LLM ladder** |
| **Hermes scope** | **S0, S1, S2, S3** (four) | `watchlist_items.scope_tier` scoring TTL. Scorer cron `*/15`, **zero LLM**. S3 names drop out of T1/T2 into T3-COLD. T0 never downgraded. | No |
| **Directive hygiene** | **1 malformed / 2 dead / 3 near-dup** (three) | Sunday `watch_directive_dedup.py`. Tiers 1–2 auto; tier-3 Telegram/UI one-tap merge. | No |
| **Watch lifecycle stages** | new / monitoring / watch / promoted / demoted / archived / blacklisted | Display + research *priority multiplier*, not membership | No extra jobs |

Reentry READY/NEAR is **not** a sixth universe tier. Those names **join T1-WATCH** (`load_reentry_ready_near_symbols`). Same DeepSeek cadence as the rest of T1. They do **not** get the T0 holdings 3×/day pass.

Live universe 2026-08-22: T0-HOLD **22** · T0-PROP **30** · T1-WATCH **331** (rank ≤ 200 **or** active ticker directive **or** reentry READY/NEAR **25**) · T2-INCUB **141** · T3-COLD **2537**. Highest membership wins.

---

## The five universe tiers — how / when / how often

Highest membership wins (`load_universe`). SLA “due” ≠ execute. `RESEARCH_SKIP_GATE` default **0**, so due symbols are called. Local gemma is listed on SLAs but **off** (`RESEARCH_ALLOW_LOCAL_LLM=0`).

| Tier | Who | How you get in | Scheduler LLM (auto) | SLA | Cron `--mode` | When | Confirm-run 2026-08-22 |
|---|---|---|---|---|---|---|---|
| **T0-HOLD** | Open book (held equity, not CASH/CUSIP) | `holdings.json` | **DeepSeek** every holdings run | **3× / 1 day** | `holdings` budget **70** | **M–F 08:00, 12:30, 16:30 ET** | **22/22** ids 46013–46034 · $0.00795 |
| **T0-PROP** | Active paper proposals | `paper_trade_proposals` PENDING/APPROVED | **DeepSeek** when due in `priority` (T0 always candidate) | **2× / 1 day** | `priority` budget **40** | **M–F hourly 10:00–16:00 ET** | **30/30** |
| **T1-WATCH** | **The watchlist hot set** | Hermes rank ≤ 200 **or** active ticker directive **or** reentry READY/NEAR | **DeepSeek**, **one** external per refresh | **4× / 7 days** | `watchlist` budget **50**; also `priority` if due/catalyst | **M–F 20:30 ET** sweep; **M–F 10–16** if due | **331/331** (incl. reentry **25/25** ids 46035–46059) |
| **T2-INCUB** | Incubator / proposed last 21d | `incubator_universe` + recent proposals | **DeepSeek only if catalyst** | **1× / 7 days** | `incubator` budget **30** | **Sunday 19:00 ET** | **141/141** confirm-run (production remains catalyst-only) |
| **T3-COLD** | Rest of `symbol_profiles` | leftover after higher tiers | **No DeepSeek** unless catalyst. Local listed, **off** | **1× / 14 days** | `cold-floor` budget **20** rotating | **Daily 10:00 ET** (`run_with_deepseek_offpeak.sh`) | **20/20 slice** (not 2537) |

Process cap: `hermes_external_research` **120 calls / $0.30**/day in `config/llm_process_registry.json`. Cron budgets are per-run. Standing global cap **$0.50** (not a raise). Bitwarden SM render at `/run/user/1000/tradeai/env` **omits** the cap and wipes appends on re-render. Live crontab now prefixes `env LLM_GLOBAL_DAILY_USD_CAP=0.50` on all six `research_scheduler` jobs so Monday cron does not fail-close `COST_CONFIGURATION_INVALID`. Sidecar `~/.config/tradeai/llm_global_daily_usd_cap.env` is the same 0.50.

---

## Hermes S0–S3 (watchlist *scope*, not LLM)

`config/hermes_scope_governor.yaml`. Owner: `hermes_scope_governor.py`. Scorer: `hermes_watchlist_scorer.py` `*/15` (zero LLM).

| Scope | Meaning | Scored | LLM effect |
|---|---|---|---|
| **S0** | Capital exposed / operator-pinned | every scorer run | Stays T0 if held; never TTL-demoted |
| **S1** | Live trigger (cap 400, 14d TTL) | market hours | May sit in T1-WATCH |
| **S2** | Warm incubator / watchpool (cap 320, 30d TTL) | premarket daily | Often T2-INCUB |
| **S3** | Archived | on_event only | Forced to **T3-COLD**; no T1/T2 slot |

---

## Directive hygiene tiers 1–3 (Sunday, zero LLM)

`scripts/watch_directive_dedup.py`. Cron Sun 09:30 `watchlist_hygiene.py --telegram` is a different cleaner (low-confidence AI names). Dedup:

| Hygiene tier | Meaning | Apply |
|---|---|---|
| **1** | Malformed labels → relabel / merge | auto |
| **2** | Dead `claude_challenger` (0 hits) → archive | auto |
| **3** | Near-dup families → merge onto survivor | Telegram / UI one-tap (`plan([3])`) |

These are **directive-row** cleanup, not research-universe membership.

---

## Which LLM actually fires

| Lane | Auto on universe tiers? | Frequency | Notes |
|---|---|---|---|
| **DeepSeek Flash** | T0-HOLD, T0-PROP (via priority), T1-WATCH, T2/T3 **catalyst only** | Cron table | Family A. Writer `hermes_external_researcher.py`. |
| **ChatGPT / Grok OAuth** | **Not** scheduler auto | Every **2h** `hermes_top20_external_intel.py` | Family B. Top-20 + directives. Held names tagged `trigger=holdings`. Why holdings look OAuth-first. |
| **Local gemma** | Listed on all five SLAs | **Off** | Rebuild scheduler still *would* enqueue on `--apply`; CURRENT filters queue lanes. |
| **Claude** | never auto | manual `--apply-paid` | Paid. |
| **Overnight-deep** | policy ChatGPT 22:00–06:00 ET | live timer still China-night gemma | Not a universe tier. |

Saturday/Sunday: **no** holdings / priority / watchlist DeepSeek unless someone runs it. 2026-08-22 confirm-run was **manual** (Saturday).

```
0 8 * * 1-5      --mode holdings   --budget 70   # T0-HOLD DeepSeek
30 12,16 * * 1-5  --mode holdings   --budget 70
0 10-16 * * 1-5  --mode priority   --budget 40   # T0 + due T1 + catalyst
30 20 * * 1-5     --mode watchlist  --budget 50   # T1-WATCH only (≤50/run)
0 10 * * *       --mode cold-floor --budget 20   # T3 slice 20
0 19 * * 0       --mode incubator  --budget 30   # T2 Sunday
```

---

## Confirm-run closed (2026-08-22)

Ignored standing **$0.50** in-process (`LLM_GLOBAL_DAILY_USD_CAP=25`); process soft cap temporarily 2000 then **restored 120 / $0.30**. Standing systemd/sidecar cap stays **0.50**. Do not raise `.env` / SM.

| Bucket | Production cadence | Confirm-run | Result |
|---|---|---|---|
| T0-HOLD | 3×/day M–F, budget 70 | all 22 | **22/22** |
| T0-PROP | hourly priority M–F, budget 40 | all 30 | **30/30** |
| T1 reentry READY/NEAR | joins T1 watchlist sweep | all 25 | **25/25** |
| T1-WATCH | 20:30 M–F budget **50**/run | remainder of 331 | **331/331** |
| T2-INCUB | Sunday; DeepSeek **catalyst only** | all 141 (forced) | **141/141** — not production gate |
| T3-COLD | daily 20-name rotate; no auto DeepSeek | **20** slice | **20/20**. Did **not** run 2537 (~$0.75 would breach $0.50) |

DB proof 12:50 ET: DeepSeek ok ids **46012–46982** (n=545 symbols with nonempty rec) · `hermes_external_research` spend **$0.168934** / 546 rows · global today **$0.206309** / 677. T2/T3 DeepSeek here is **confirm only**.

See also: `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md` (two LLM families) · `docs/RESEARCH_PRIORITIZATION.md` (policy SLA) · `docs/ops/RESEARCH_COVERAGE_SNAPSHOT_2026-08-22.md` (10:24 ET snapshot; superseded for DeepSeek counts).
