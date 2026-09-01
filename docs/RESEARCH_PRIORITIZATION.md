# Research Prioritization & Refresh Methodology (all Hermes lanes, 24/7)

Status:      ACTIVE
as_of:       2026-08-22T13:20:44-04:00
Measured at: efcc51365 / not measured

How the always-on Hermes fleet decides **what gets researched, by which lane, in what order, and how
often** — so every tracked symbol is refreshed at least *X* times per *Y* days, exposure-weighted, with
event-awareness. This governs **all** research lanes (local gemma, overnight deep, external OAuth,
web/topic, catalyst, news), not just the external skeptics.

**Tiers / cron / LLM frequency:** `docs/ops/RESEARCH_TIER_LLM_CADENCE.md`.
There is **one** watchlist research tier (`T1-WATCH`). Reentry READY/NEAR joins it. T2/T3 are not watchlist sub-tiers.

**LIVE vs this policy (read first):** `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md`.
Scheduler auto-external is DeepSeek-only. Holdings still get ChatGPT/Grok from
`hermes_top20_external_intel.py` (trigger labeled `holdings`) every 2h — that is
**not** “DeepSeek first.” T1/reentry only have the scheduler path, so they starve
while DeepSeek is red. Telegram `DATA_UNAVAILABLE` is a **thesis-slot join**, not
missing quotes (technicals are already on the same card). SearXNG is up and not
wired into that slot.

**Lifecycle gate (canonical):** `docs/ops/RESEARCH_LIFECYCLE_STANDARD.md`. Research is incremental,
change-driven, and freshness-based. An SLA “due” symbol is a **candidate**. Execute only if the source
changed, freshness expired, or an operator/event trigger fired. Unchanged in-date work is reused
(`SKIP_UNCHANGED` / `SKIP_FRESH`), never re-analyzed.

Implemented by `scripts/research_scheduler.py` (symbol-level fan-out) + the existing topic/source/news
crons (subject-level), all keyed to the same tiers below.

## 0. The lanes (cheapest → scarcest)

| Lane | Engine | Cost | Breadth | Dispatch | Role |
|------|--------|------|---------|----------|------|
| **local-gemma** | gemma3:4b / 12b (local) | free | overflow / math-adjacent | enqueue `watchlist_agent_jobs` **only if** `RESEARCH_ALLOW_LOCAL_LLM=1` (default **0**, **recommendation-only until the operator-blind sheet is scored**) | bake-off proved **0% `[` error prefix** (no crashes), **not** output quality. Maria jobs 28.5% fail is infra, not a quality score. Do not auto-enable from bake-off crash-rate. |
| **internal-deep** | **Policy:** ChatGPT OAuth 22:00–06:00 ET. **Live timer:** China-night gemma3:27b (empty US-day). 27b is **100% CPU** on the B50 — not a GPU deep lane | ChatGPT free; 27b CPU | T0/T1 | policy `:8646`; live timer not retargeted | do not label 27b “deep multi-agent synthesis” |
| **deepseek** | DeepSeek V4 Flash via `scripts/llm_lane.py` | metered, cheap | T0/T1 + catalyst | `hermes_external_researcher` (`--trigger research_scheduler`) | **intended** auto external lane after #440 import fix. **Not the workhorse until a 5-day burn-in** reports error rate, latency, and spend. One call (id=45900) proves the import, not production. |
| **grok** | xAI OAuth proxy :8645 | free, **rate-limited** | *(retained, not auto)* | — | deprecated for auto-dispatch |
| **chatgpt** | codex OAuth proxy :8646 | free, **rate-limited** | US overnight judgment | `hermes_deep_research_local` (overnight) | default overnight LLM — not gemma |
| **claude** | Anthropic API | **metered $** | arbitration only | manual / on disagreement | tie-break, high-stakes only — **never auto** |
| **web/topic** | `topic_research_synthesizer`, `hermes_research_autonomy` | free (search) | topics + T0/T1 | own cron | grounded thesis research |
| **catalyst** | `hermes_momentum_catalyst_researcher`, social scalp | free | event-driven | own cron | detects new events → pulls symbols forward |
| **news** | `news_ingestion`, Finviz | free | broad, continuous | own cron | event feed feeding catalyst signal |

The governed DeepSeek Flash lane is the **intended** auto external writer (`llm_lane.py`, not `lib.llm_lane`).
It was **100% `[ERROR] lib.llm_lane`** for 8 days (2026-08-13..21) and has **one** proven scheduler-path success (`hermes_external_research` id=45900). That is not burn-in. **Do not call Flash the workhorse in policy until 5 days of RAW-store error rate + latency + spend are posted** (window start 2026-08-21 19:10 ET; due 2026-08-26). `$0.42/14d` was the crash loop — void.

Local gemma default-off (`RESEARCH_ALLOW_LOCAL_LLM=0`) is **recommendation-only until** `docs/ops/LANE_QUALITY_BAKEOFF_OPERATOR_BLIND_2026-08-21.md` is scored. Evidence that exists today: maria queue 28.5% fail (infra), 27b 100% CPU on the B50 (not a GPU deep lane), bake-off 0% error prefix (availability, not quality). **0% `[` ≠ usable judgment.** Flag stays 0; do not treat that as a quality routing decision.

Claude is metered arbitration-only. RAW-store health: `scripts/research_lane_health.py` (does **not** use `last_real`; also CURRENT-pin + Drive-sync 24h). Skip gate `RESEARCH_SKIP_GATE` defaults **off**.

## 1. Universe & tiers

Every tracked symbol gets the **highest tier it qualifies for**:

| Tier | Membership | Source |
|------|-----------|--------|
| **T0-HOLD** | open positions (real money) | `data/portfolios/state/holdings.json` |
| **T0-PROP** | active proposals (PENDING/APPROVED) | `paper_trade_proposals` |
| **T1-WATCH** | top-N Hermes-ranked + operator watch directives + reentry READY/NEAR | `hermes_score_history`, `watch_directives`, reentry desk |
| **T2-INCUB** | incubator / recently-proposed candidates | `paper_trade_proposals` (21d) |
| **T3-COLD** | rest of the profiled universe (~2500) | `symbol_profiles` |

**Scope-governor binding (Phase 1, 2026-07-02,** [`docs/design/HERMES_MATURITY_5_DESIGN.md`](design/HERMES_MATURITY_5_DESIGN.md)**):**
one governor owns research scope too — a symbol the scope governor archived
(`watchlist_items.scope_tier = 'S3'`) never holds a T1-WATCH / T2-INCUB slot; it drops to T3-COLD
(metadata-only under the budget guard) until an event or the governor reactivates it. T0 (capital
exposed) is never downgraded. Measured effect at cutover: T1-WATCH 469→256, T2-INCUB 390→122.
**External lane is DeepSeek-only (2026-08-13):** the single automated *external skeptic* is the governed
DeepSeek V4 Flash lane. Grok OAuth stays non-auto (hourly duplicate Telegram noise). ChatGPT OAuth is
the US-overnight judgment lane (`hermes_deep_research_local`, 22:00–06:00 ET) — not a scheduler skeptic.
Claude remains manual arbitration-only. T1's one-external-per-refresh pick still resolves to DeepSeek.

Live split (2026-08-22, `research_scheduler.load_universe()` after CASH excluded from T0):
**T0-HOLD = 22** · T0-PROP **30** · **T1-WATCH 331** (rank ≤200 + directives + reentry READY/NEAR 25) · T2-INCUB **141** · T3-COLD **2537**.
How/when each is LLM’d: `docs/ops/RESEARCH_TIER_LLM_CADENCE.md`.

Holdings.json has 34 rows / 26 unique symbols including 5 CASH account rows and 3 $0 CUSIPs. Coverage denominator is **22 tickers** (`holdings_universe.held_equity_tickers`). Do not count CASH as a thesis name.

## 2. Refresh SLA — "at least X times in Y days", per lane per tier

| Tier | Min × / window | local-gemma | internal-deep | deepseek |
|------|----------------|-------------|---------------|----------|
| **T0-HOLD** | **3× / 1 day** | ✓ each cycle | ✓ nightly | ✓ |
| **T0-PROP** | 2× / 1 day | ✓ | — | ✓ |
| **T1-WATCH** | 4× / 7 days | ✓ | — | ✓ (one external per refresh) |
| **T2-INCUB** | 1× / 7 days | ✓ | — | catalyst only |
| **T3-COLD** | **1× / 14 days** (was fiction at budget 20 = 127d). 2026-08-22: cold-floor **180**/day + process call cap **600**; dollar cap stays **$0.50** (~$0.056/day). | ✓ off (`RESEARCH_ALLOW_LOCAL_LLM=0`) | — | rotating DeepSeek floor |

**Holdings (T0-HOLD) are special** (operator requirement): researched **several times a day** across the
full lane fleet, and any **material change** is pushed to the symbol **card** and surfaced to the
**advisory desk** as external-research evidence (§5). Not just a refresh — a *diff-and-alert*. Telegram
is reserved for synthesized **thesis** changes only, not per-symbol research prose.

## 3. Priority score (ordering within a run)

```
priority = 100·tier_weight            # HOLD 1.0 · PROP 0.9 · WATCH 0.6 · INCUB 0.3 · COLD 0.1
         +  40·min(overdue_ratio,3)   # (now − last_real) / per-refresh-window ; >1 = past due
         +  25·catalyst_signal        # RVOL≥5 | |gap|≥10 | fresh news | score surge | social/meme
         +  15·rank_score             # inverse Hermes rank (top names first)
```

T0 symbols are **candidates** every run regardless of score; anything past SLA gets a hard overdue boost.
Candidate ≠ execute. Apply the lifecycle hash/mtime/TTL gate before a metered lane call
(`docs/ops/RESEARCH_LIFECYCLE_STANDARD.md`).

## 4. Lane budget (never exhaust the free OAuth lanes)

- **local-gemma / internal-deep** — enqueued, no budget; the always-on `watchlist_agent_jobs` workers
  (cron */15 weekday, */5 overnight) drain them. Idempotent: won't double-queue an in-flight symbol.
- **deepseek** — the single automated external lane, capped per run by `RESEARCH_EXTERNAL_BUDGET_PER_RUN`
  (default **40**); each call ~10–30s, governed under the `hermes_external_research` LLM process cap
  (`deepseek_only`, FAST policy, daily soft cap 120 calls / $0.30). Over-budget symbols **roll to the
  next run by priority** (local still runs for them now). T1 takes **one** external per refresh; T0 takes
  deepseek each cycle.
- **claude** — `auto: False`. Only invoked for arbitration on lane disagreement, never in a sweep.

## 5. Event surfacing (holdings)

After each T0-HOLD refresh the scheduler **diffs** the new DeepSeek opinion vs the prior stored one via a
content fingerprint (recommendation + confidence hash, not first-letter). A **material change** =
recommendation flip · new/removed risk flag · confidence Δ ≥ 0.2 · fresh catalyst · score/rank move past
threshold. On material change → (1) refresh the symbol **card** intel, (2) the research row is stored in
`hermes_external_research` and surfaced by the Advisory Desk `external_research` evidence loader — **no
per-symbol Telegram**. The scheduler only fingerprints the change so downstream synthesis can decide when
a *thesis* materially changed; that thesis change is what triggers a Telegram (via `CIOThesisStore.publish`,
classified `thesis_update`). No-change refreshes store silently (audit), no alert → no noise.

## 6. The run loop (algorithm)

```
1. universe   = load all tracked symbols → assign highest tier + today's catalyst signals
2. last_real  = latest NON-error research per (symbol, lane)   # recommendation NOT LIKE '[%'
3. due        = T0 (always) ∪ { s : age(s) > tier per-refresh window } ∪ catalyst(s)
4. score      = priority(s) for s in due ; order desc
5. dispatch   = for s in order:
                   for lane in tier.local_lanes:  enqueue(s, lane)          # always, cheap
                   for lane in tier.external_lanes (auto):                  # budgeted
                       if budget_left and (tier∈{T0,T1} or catalyst(s)):
                           external(s, lane); budget_left −= 1              # deepseek only
6. surface    = for s in T0-HOLD with material change: card + desk evidence (no Telegram)
```

## 7. 24/7 cadence (symbol-level scheduler + subject-level fleet)

| When (M–F) | Run | Scope |
|------------|-----|-------|
| 08:00, 12:30, 16:30 | `research_scheduler --mode holdings --apply` | T0-HOLD, full fleet, diff→card+desk |
| hourly 10–16 | `research_scheduler --mode priority --apply` | T0/T1 due + catalyst, external-budgeted |
| 20:30 | `research_scheduler --mode watchlist --apply` | T1 refresh sweep |
| 10:00 | `research_scheduler --mode cold-floor --apply` | rotating T3 floor (retargeted off 02:00 Peak B; PEAK_SKIP wrapped) |
| Sun | `research_scheduler --mode incubator --apply` | T2 sweep |
| US overnight 22:00–06:00 ET | **policy:** deterministic + ChatGPT OAuth (`:8646`) | **live timer still China-night gemma3:27b** (empty `RESULT: {}`). Alarm lane `overnight-deep` covers both. |
| every 15 min | `research_lane_health.py --alert` | RAW `hermes_external_research` + overnight-deep; `[ERROR]` rows count |
| (existing) ATP2 cycles, topic synth, news/finviz, catalyst | subject-level lanes | topics/sources/events feeding the catalyst signal |

`--mode backfill` walks the **whole** universe by priority within the external budget — used to recover
from an outage (e.g. the 12-day ChatGPT lapse). All tier sizes, SLAs, budgets are env-tunable
(`RESEARCH_*`) so "X times in Y days" can be dialed per tier without code changes.

## 8. Guardrails

- Advisory only — research feeds the watchlist/card/desk evidence, never live execution (separately gated).
- External lanes are redaction-safe (`safe_context`: no $/account/positions/secrets).
- Local lanes idempotent (no double-queue); externals budgeted (no exhaustion); claude never auto (no
  metered spend in sweeps).
