# Research provider routing — when Brave should be used

**Status:** current as of 2026-09-05. Every number here was measured on this box;
where something was not measured it says so.

## The short answer

**Brave is the exception, not the default.** A self-hosted SearXNG instance is
already running and answering queries for free. Brave is a paid, per-query API
that should be spent only where the free lane demonstrably cannot do the job.

## The lanes, and which are real

| lane | cost | state on 2026-09-05 | evidence |
|---|---|---|---|
| **SearXNG** | free (self-hosted) | **LIVE** — container up 2 weeks, `HTTP 200` on `127.0.0.1:18888`, returns JSON results | probed directly; `hermes_observation_check.py:78-83` health-checks it |
| **DDG** | free | **IN USE** by 4 callers | `hermes_browse_proxy.py`, `hermes_momentum_catalyst_researcher.py`, `web_news_fetcher.py`, `topic_ingestion.py` |
| **Brave** | **paid, per query** | **IN USE** — 60 calls in Sept, ~12/day | `data/runtime/search_budget.json` |
| **Tavily** | paid | **DEAD CONFIG** — a budget entry with zero callers | only reference is `lib/search_budget.py:59` |

SearXNG records **no traffic in the shared ledger** — only Brave does. It is free,
so it is not budgeted, but that also means its usage is currently invisible. That
is a gap, not a defect: it costs nothing to exceed.

## When to use Brave

Use Brave when the query needs something the free lanes measurably do not give:

- **Freshness that matters to a decision** — a catalyst, a filing, a halt, an
  announcement inside the last few hours, where a stale or thin result changes
  what the system concludes.
- **An on-demand question someone is waiting for** — operator queries and
  interactive `web_research`. These draw on a protected reserve (below).
- **Result quality on a narrow entity** — where SearXNG returned nothing useful
  and the answer is load-bearing. *Try the free lane first and fall back;* do not
  route to Brave speculatively.

## When NOT to use Brave

- **Anything answerable from our own database** — prices, holdings, history,
  positions. These are already in Postgres.
- **Scheduled bulk enumeration** — sweeps, backfills, discovery crawls. Route to
  SearXNG.
- **Anything a cached result covers.** `brave_search.py` caches 60 min for news,
  5 min for web.
- **Weekends, for scheduled jobs.** `SKIP_WEEKENDS` already enforces this and
  correctly exempts on-demand callers.

## The ceilings, and what they are for

Set in `lib/search_budget.py: DEFAULT_LIMITS["brave"]`, which is the **binding**
ceiling — the shared check runs before `brave_search.py`'s own. Overridable by
`SEARCH_BUDGET_BRAVE_DAILY` / `_MONTHLY`.

| | value | job |
|---|---|---|
| daily | **120** | anti-runaway breaker. Bounds a *loop bug*, not spend. |
| monthly | **1500** | the cost bound. This is the number that maps to money. |
| reserve | **200** (capped at ⅕ of the budget) | held back from scheduled callers so cron cannot starve an interactive query |

**Why they were raised from 25/850 on 2026-09-05.** The two ceilings previously
encoded the same constraint — 25/day × 30 = 750, against a monthly of 850 — so
the daily cap bound first on every burst. Measured 2026-08-31: **25 calls made,
3 denied, with August's monthly counter at 25 of 850.** The lane was refused
research with 97% of the month unspent. A denial is not a downgrade: `_check_budget`
returns `False` and the research is simply lost, because no fallback provider is
wired behind a refusal.

**What the provider actually imposes.** Observed from Brave's own response headers
on 2026-09-05: `x-ratelimit-limit: 50, 0`, `policy: 50;w=1, 0;w=2592000`, HTTP 200.
That is **50 requests/second and no metered monthly window.** Brave imposes no
monthly ceiling on this key. The 1500 is entirely our cost choice.

The long-standing claim that Brave gives "1,000/month free tier" was never observed
from Brave — it was an assumption written into a code comment and inherited as
fact. It has been removed. See `lib/research_provider_truth.py`.

## Cost

At ~360 queries/month (the current run-rate) or even at the full 1500 ceiling,
this is low single-digit dollars a month at any normal per-1,000-query rate.
**The exact rate is not recorded here because this system has not measured it** —
rate-limit headers state limits, not prices. Read the plan and per-1k rate off the
Brave dashboard and multiply: 1500 queries is 1.5 units of a thousand.

One inference worth noting: **50 req/sec is not a free-tier rate** — free tiers are
throttled far harder. This key is very likely on a paid plan, which is consistent
with a card being on file, and inconsistent with the "free tier" comment that was
in the code.

## Known open item

Two budget ledgers exist:

- `data/runtime/search_budget.json` — **live**, `SearchBudget@v1`, canonical.
- `data/portfolios/state/brave_search_budget.json` — **frozen at 2026-08-10**, the
  legacy ledger `brave_search.py` reads for its own second-layer check.

`lib/search_budget.py` documents the split at its docstring and exists because of
it: four callers once held their own Brave client and never imported the budgeted
one, so the ledger read 150/month while the provider dashboard read ~1,000. The
divergence is **reported, not merged** — reconciling two copies of an authoritative
store is an operator decision (AGENTS.md §0 rule 5).
