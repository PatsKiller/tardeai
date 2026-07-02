# Research Prioritization & Refresh Methodology (all Hermes lanes, 24/7)

How the always-on Hermes fleet decides **what gets researched, by which lane, in what order, and how
often** — so every tracked symbol is refreshed at least *X* times per *Y* days, exposure-weighted, with
event-awareness. This governs **all** research lanes (local gemma, overnight deep, external OAuth,
web/topic, catalyst, news), not just the external skeptics.

Implemented by `scripts/research_scheduler.py` (symbol-level fan-out) + the existing topic/source/news
crons (subject-level), all keyed to the same tiers below.

## 0. The lanes (cheapest → scarcest)

| Lane | Engine | Cost | Breadth | Dispatch | Role |
|------|--------|------|---------|----------|------|
| **local-gemma** | gemma3:12b/4b (local) | free, fast | **all tiers, broad** | enqueue `watchlist_agent_jobs` → drained by 24/7 workers | the workhorse — every due symbol |
| **internal-deep** | gemma3:27b (overnight window) | free, slow | T0/T1 deep dives | enqueue (full_chain) → overnight queue | deep multi-agent synthesis |
| **grok** | xAI OAuth proxy :8645 | free, **rate-limited** | T0/T1 + catalyst | `hermes_external_researcher` | external skeptic |
| **chatgpt** | codex OAuth proxy :8646 | free, **rate-limited** | T0/T1 + catalyst | `hermes_external_researcher` | external skeptic |
| **claude** | Anthropic API | **metered $** | arbitration only | manual / on disagreement | tie-break, high-stakes only — **never auto** |
| **web/topic** | `topic_research_synthesizer`, `hermes_research_autonomy` | free (search) | topics + T0/T1 | own cron | grounded thesis research |
| **catalyst** | `hermes_momentum_catalyst_researcher`, social scalp | free | event-driven | own cron | detects new events → pulls symbols forward |
| **news** | `news_ingestion`, Finviz | free | broad, continuous | own cron | event feed feeding catalyst signal |

Cheap/broad lanes (local-gemma) cover everything frequently; scarce lanes (grok/chatgpt) are reserved
for high tiers and live catalysts and **budgeted per run** so they never exhaust; claude is metered and
only used for arbitration when lanes disagree.

## 1. Universe & tiers

Every tracked symbol gets the **highest tier it qualifies for**:

| Tier | Membership | Source |
|------|-----------|--------|
| **T0-HOLD** | open positions (real money) | `data/portfolios/state/holdings.json` |
| **T0-PROP** | active proposals (PENDING/APPROVED) | `paper_trade_proposals` |
| **T1-WATCH** | top-N Hermes-ranked + operator watch directives | `hermes_score_history`, `watch_directives` |
| **T2-INCUB** | incubator / recently-proposed candidates | `paper_trade_proposals` (21d) |
| **T3-COLD** | rest of the profiled universe (~600) | `symbol_profiles` |

**Scope-governor binding (Phase 1, 2026-07-02,** [`docs/design/HERMES_MATURITY_5_DESIGN.md`](design/HERMES_MATURITY_5_DESIGN.md)**):**
one governor owns research scope too — a symbol the scope governor archived
(`watchlist_items.scope_tier = 'S3'`) never holds a T1-WATCH / T2-INCUB slot; it drops to T3-COLD
(metadata-only under the budget guard) until an event or the governor reactivates it. T0 (capital
exposed) is never downgraded. Measured effect at cutover: T1-WATCH 469→256, T2-INCUB 390→122.
**External lane rotation is outcome-weighted (Phase 3):** T1's one-external-per-refresh pick is
weighted by graded hit-rate from `hermes_lane_usefulness` (0.15 floor so no lane starves; uniform
until ≥30 external recs have ledger verdicts).

Current split: ~32 holdings · 1 proposal · ~83 watchlist · ~274 incubator · ~584 cold = **974 symbols**
*(pre-binding snapshot — see scope-governor note above for post-cutover tier sizes).*

## 2. Refresh SLA — "at least X times in Y days", per lane per tier

| Tier | Min × / window | local-gemma | internal-deep | grok | chatgpt |
|------|----------------|-------------|---------------|------|---------|
| **T0-HOLD** | **3× / 1 day** | ✓ each cycle | ✓ nightly | ✓ | ✓ (both externals = cross-check) |
| **T0-PROP** | 2× / 1 day | ✓ | — | ✓ | ✓ |
| **T1-WATCH** | 4× / 7 days | ✓ | — | rotated (one external per refresh) | rotated |
| **T2-INCUB** | 1× / 7 days | ✓ | — | catalyst only | catalyst only |
| **T3-COLD** | 1× / 14 days | ✓ (rotating nightly batch) | — | catalyst only | catalyst only |

**Holdings (T0-HOLD) are special** (operator requirement): researched **several times a day** across the
full lane fleet, and any **material change** is pushed to the symbol **card** + **Telegram** (§5). Not
just a refresh — a *diff-and-alert*.

## 3. Priority score (ordering within a run)

```
priority = 100·tier_weight            # HOLD 1.0 · PROP 0.9 · WATCH 0.6 · INCUB 0.3 · COLD 0.1
         +  40·min(overdue_ratio,3)   # (now − last_real) / per-refresh-window ; >1 = past due
         +  25·catalyst_signal        # RVOL≥5 | |gap|≥10 | fresh news | score surge | social/meme
         +  15·rank_score             # inverse Hermes rank (top names first)
```

T0 symbols are candidates **every run** regardless of score; anything past SLA gets a hard overdue boost.

## 4. Lane budget (never exhaust the free OAuth lanes)

- **local-gemma / internal-deep** — enqueued, no budget; the always-on `watchlist_agent_jobs` workers
  (cron */15 weekday, */5 overnight) drain them. Idempotent: won't double-queue an in-flight symbol.
- **grok / chatgpt** — capped per run by `RESEARCH_EXTERNAL_BUDGET_PER_RUN` (default **40**); each call
  ~30–60s. Over-budget symbols **roll to the next run by priority** (local still runs for them now).
  T1 rotates **one** external per refresh; T0 gets **both**. `oauth_lane_keepalive` keeps tokens warm.
- **claude** — `auto: False`. Only invoked for arbitration on lane disagreement, never in a sweep.

## 5. Event surfacing (holdings)

After each T0-HOLD refresh the scheduler **diffs** the new opinion vs the prior stored one. A **material
change** = recommendation flip · new/removed risk flag · confidence Δ ≥ 0.2 · fresh catalyst · score/rank
move past threshold. On material change → (1) refresh the symbol **card** intel, (2) **Telegram** alert
to the holdings/proposals channel. No-change refreshes store silently (audit), no alert → no noise.

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
                           external(s, lane); budget_left −= 1              # T1 rotates, T0 both
6. surface    = for s in T0-HOLD with material change: card + Telegram
```

## 7. 24/7 cadence (symbol-level scheduler + subject-level fleet)

| When (M–F) | Run | Scope |
|------------|-----|-------|
| 08:00, 12:30, 16:30 | `research_scheduler --mode holdings --apply` | T0-HOLD, full fleet, diff→card+telegram |
| hourly 10–16 | `research_scheduler --mode priority --apply` | T0/T1 due + catalyst, external-budgeted |
| 20:30 | `research_scheduler --mode watchlist --apply` | T1 refresh sweep |
| 02:00 nightly | `research_scheduler --mode cold-floor --apply` | rotating 1/14th of T3 (holds the 14-day floor) |
| Sun | `research_scheduler --mode incubator --apply` | T2 sweep |
| (existing) overnight 00:30–05:00 | deep gemma3:27b queue | T0/T1 deep dives |
| (existing) ATP2 cycles, topic synth, news/finviz, catalyst | subject-level lanes | topics/sources/events feeding the catalyst signal |

`--mode backfill` walks the **whole** universe by priority within the external budget — used to recover
from an outage (e.g. the 12-day ChatGPT lapse). All tier sizes, SLAs, budgets are env-tunable
(`RESEARCH_*`) so "X times in Y days" can be dialed per tier without code changes.

## 8. Guardrails

- Advisory only — research feeds the watchlist/card/Telegram, never live execution (separately gated).
- External lanes are redaction-safe (`safe_context`: no $/account/positions/secrets).
- Local lanes idempotent (no double-queue); externals budgeted (no exhaustion); claude never auto (no
  metered spend in sweeps).
