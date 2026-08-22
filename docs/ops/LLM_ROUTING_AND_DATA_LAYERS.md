# How LLMs, Hermes, SearXNG, and ticker data actually work

**Date:** 2026-08-22  
**Authority:** READ_ONLY_ADVISORY  
**CURRENT:** do not promote for this (docs-only).  
**Live crontab:** still `$PROJ=` rebuild.

This is the map of **who calls which LLM, on which symbols, and why Telegram still says DATA_UNAVAILABLE** even though quotes, RSI, zones, Hermes scores, SearXNG, and OAuth research exist.

Related: `docs/RESEARCH_PRIORITIZATION.md` (policy) · `docs/ops/RESEARCH_LIFECYCLE_STANDARD.md` (skip/freshness) · `docs/ops/RESEARCH_COVERAGE_SNAPSHOT_2026-08-22.md` (measured 10:24 ET) · **`docs/ops/RESEARCH_TIER_LLM_CADENCE.md` (five universe tiers, watchlist is T1 only, cron + SLA)**.

---

## 1. Four layers — they do not auto-join

Nothing is “the research.” Four independent stores. Telegram reads **one card shape**. If that shape’s thesis field is empty, the card prints `DATA_UNAVAILABLE` even when the other three layers are full.

| Layer | What | Where | Joined into Telegram thesis block? |
|---|---|---|---|
| **Deterministic ticker** | Price, zone, RSI, invalidation, desk WAIT/NEAR/WATCH | reentry/opportunity desks, Finviz, quotes | **Yes** — “Technical setup” / “Why now” |
| **SearXNG** | Self-hosted metasearch `127.0.0.1:18888` (up) | think-tank, YouTube discovery, source dry-run, weak-evidence remediate | **No** |
| **Hermes** | Rank, composite score, RSI/trend on `watchlist_items` | scorer + top-N | Rank is in the *prompt* to OAuth, not the Telegram thesis |
| **LLM** | Prose opinion | `hermes_external_research` (+ local gemma on `holdings_llm_refresh`) | **No** — Telegram thesis is the **living symbol thesis**, not this table |

Living CIO thesis (`HeldBookThesisCoverage@v1`): **3/22 holdings CURRENT** (DIV, DIVI, JEPI). Watch/reentry names are almost all `RESEARCH_REQUIRED`. That is why the card says:

```
*Thesis*
DATA_UNAVAILABLE
State: RESEARCH_REQUIRED · Confidence: DATA_UNAVAILABLE

*Catalyst*
DATA_UNAVAILABLE
```

…while the same message already has price, zone, RSI, and desk state. **The data is not missing. The card is not reading it for those fields.** Product standard (`CIO_TELEGRAM_PRODUCT_STANDARD.md`) says keep the token `DATA_UNAVAILABLE` out of operator copy. Live cards still emit it.

Do not treat “Need data” on the keyboard as a missing quote. That button is a **disposition**. The red `DATA_UNAVAILABLE` under Thesis/Catalyst is the join bug.

---

## 2. Two LLM producer families (this is the holdings-vs-DeepSeek confusion)

Policy (`RESEARCH_PRIORITIZATION.md`): **one automated external skeptic = DeepSeek Flash**. Grok/ChatGPT OAuth are **not** scheduler auto-lanes (`LANES["grok"].auto = False`, `chatgpt` auto False). Claude is manual paid.

Live, a **second family** still calls ChatGPT/Grok every two hours.

### Family A — `research_scheduler.py` (DeepSeek)

| Cron | Mode | Who | Lane |
|---|---|---|---|
| 08:00 / 12:30 / 16:30 M–F | `--mode holdings` | T0-HOLD (22 tickers) | **deepseek** (local-gemma/internal-deep gated off) |
| hourly 10–16 M–F | `--mode priority` | T0 + T1 due + catalyst | **deepseek** (T1: one external per refresh) |
| 20:30 M–F | `--mode watchlist` | T1-WATCH (reentry READY/NEAR live here) | **deepseek** |
| 10:00 daily | `--mode cold-floor` | T3 slice | deepseek only on catalyst |
| Sun | `--mode incubator` | T2 | deepseek only on catalyst |

Trigger written: `research_scheduler`.  
Through Fri 2026-08-21: **912 error / 1 ok** (`lib.llm_lane` then `COST_CONFIGURATION_INVALID`). **2026-08-22 confirm-run (manual, Saturday):** T0-HOLD **22/22**, T0-PROP **30/30**, T1-WATCH **331/331** (reentry READY/NEAR **25/25**), T2 **141/141** (forced; production is catalyst-only), T3 **20/20** cold-floor slice. Spend `hermes_external_research` **$0.168934**. Full ladder: `docs/ops/RESEARCH_TIER_LLM_CADENCE.md`.

Intended order for a T0 holding on this family: DeepSeek first (metered, cheap, auto). OAuth is **not on this list**. Cron M–F only — Saturday coverage was the confirm-run, not crontab.

### Family B — OAuth enhancement fleet (ChatGPT `:8646` + Grok `:8645`)

These jobs **never go through scheduler lane tables**. They shell `hermes_external_researcher.py --lane chatgpt|grok`.

| Cron | Script | Trigger written | Who actually gets a call |
|---|---|---|---|
| `5 */2 * * *` | `hermes_top20_external_intel.py --lanes grok,chatgpt` | **`holdings`** if the name is in `holdings.json`; else `open_proposal` / `active_directive` / `high_rank_watchlist` | Hermes rank ≤20 **plus** every directive name. If that set includes a held ticker, the row is labeled `trigger=holdings` |
| `20 */2` | `hermes_subject_enhance.py --type position` | `enh_position` | Open **paper** positions (not the 22-name book) |
| `*/30` RTH | enhance scalp | `enh_scalp` | scalp subjects |
| RTH | enhance proposal / sector / closed_trade / report | `enh_*` | those subjects |

Last 3d ChatGPT: **105 `holdings`** + 25 `high_rank_watchlist` + 14 `enh_position` + …  
Same counts on Grok (paired).

**That is why holdings “get OAuth and not DeepSeek first.”**

1. Scheduler *would* DeepSeek the 22 holdings 3×/weekday. DeepSeek is dead (`COST_CONFIGURATION_INVALID` after the import fix; cap restored on rebuild `.env` 2026-08-22, next real run is Monday).
2. Independently, top-20 every 2h sees held names in `holdings.json`, tags the call `holdings`, and hits **ChatGPT+Grok**. That job is healthy. So the book *looks* OAuth-covered.
3. Reentry / most of T1 are **not** in that top-20-or-held shortcut. They only have Family A → DeepSeek → empty.

Policy said OAuth is “retained, not auto” to stop duplicate Telegram noise. Top-20 was never turned off. Two truths: **scheduler auto = DeepSeek**; **live holdings prose = OAuth top-20 overlay**.

```
                    holdings.json (22)
                           │
           ┌───────────────┴────────────────┐
           ▼                                ▼
 Family A scheduler                    Family B top-20
 T0-HOLD → deepseek                    if symbol in holdings
 3× weekday                            → chatgpt + grok every 2h
 LIVE: 1 ok / 912 err                  LIVE: 22/22 non-error
           │                                │
           └──────────┬─────────────────────┘
                      ▼
           hermes_external_research
                      │
                      ✕ not read by Telegram *Thesis* field
                      │
                      ▼
           living symbol thesis store  ← Telegram Thesis/Catalyst
           3/22 CURRENT, rest RESEARCH_REQUIRED
                      │
                      ▼
           Telegram: technicals filled, Thesis DATA_UNAVAILABLE
```

---

## 3. Lane cheat sheet (live)

| Lane | Cost | Scheduler auto? | What actually calls it | Status 2026-08-22 |
|---|---|---|---|---|
| ChatGPT OAuth | free, rate-limited | **no** | top-20, subject-enhance, overnight **policy** | **Working** (89/89 24h) |
| Grok OAuth | free, rate-limited | **no** | same top-20 / enhance | Working, 67/96 |
| DeepSeek Flash | metered, intended auto | **yes** (only auto external) | `research_scheduler` only | **Broken** until Monday cap-bearing runs; alias `deepseek` is not `available()` |
| Claude | paid | never | `--apply-paid` weekly / arbitration | manual |
| Local gemma | free GPU/CPU | queued only if `RESEARCH_ALLOW_LOCAL_LLM=1` (default 0) | `holdings_llm_refresh` **still calls it** 07:15 M–F | judgment against standing policy; parse_error salvage shipped #446 |
| SearXNG | free search | not an LLM | discovery/think-tank | **up** (`:18888`) — not on the Telegram thesis path |
| Overnight-deep | policy ChatGPT | timer | live China-night gemma3:27b | 0 rows in 24h |

US overnight judgment = ChatGPT OAuth **policy**. Live timer is still gemma. Do not retarget during the payload freeze.

---

## 4. Why “nothing should be missing”

Operator intent: deterministic + SearXNG + Hermes + LLMs ⇒ a ticker card should never be empty.

What is actually present on a typical reentry Telegram (UBER 2026-08-21):

| Field | Source | Present? |
|---|---|---|
| Price, zone, RSI, desk WAIT/NEAR | deterministic desk | **yes** |
| Hermes rank / LLM paragraph | Family B if in top-20; Family A DeepSeek otherwise | often **yes in DB**, **not on the card** |
| SearXNG hits | search layer | **yes as a service**, **not on the card** |
| Thesis / confidence / catalyst | living `symbol_thesis` | **no** → `DATA_UNAVAILABLE` + `RESEARCH_REQUIRED` |

So the noise is **not** “we lack data on every ticker.” It is:

1. **Join:** Telegram thesis/catalyst slots do not bind deterministic, Hermes, SearXNG, or `hermes_external_research`.
2. **Thesis SLA:** 19/22 holdings (and almost all watch/reentry) have no living thesis object. External LLM rows do not create one.
3. **DeepSeek hole:** Family A is the only auto path for names outside top-20/held. It is red. Reentry READY/NEAR 25 names sit in T1 and starve (5 never had a non-error external row: FSPTX, LGPS, MOGU, WLDS, XCUR).
4. **Label:** `DATA_UNAVAILABLE` is printed as prose. Standard says it should stay machine-side.

Fix after 8/27 (not this PR, freeze): bind those slots to existing stores (price already proves the ticker is not “unavailable”); mint living theses from current Hermes+OAuth+desk; do not auto-backfill 179 T1 names without an execute_set. DeepSeek Monday = first test of restored cap, not a workhorse until the 5-day Flash burn-in ends 2026-08-26.

---

## 5. Cadence (what runs, not what policy wished)

```
every 2h     top-20  → ChatGPT + Grok   (holdings in that set get trigger=holdings)
M–F 07:15    holdings_llm_refresh → local gemma3:4b  (health/action on watchlist_items)
M–F 08/12:30/16:30  scheduler holdings → DeepSeek
M–F 10–16 hourly    scheduler priority → DeepSeek T0/T1
M–F 20:30    scheduler watchlist → DeepSeek T1 (reentry lives here)
Fri 18:15    weekly oversight → ChatGPT OAuth auto; Claude only --apply-paid
:05 hourly   Drive docs sync from CURRENT pin (this doc lands on Drive via targeted push)
```

---

## MATURITY_IMPACT

Docs-only. Explains the two-family LLM split and the Telegram DATA_UNAVAILABLE join. No lane table change, no flag flip, no CURRENT promote. Metric: this file + operator Telegram still showing `*Thesis* DATA_UNAVAILABLE` while Technical setup is populated.
