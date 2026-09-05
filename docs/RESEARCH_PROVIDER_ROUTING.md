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

## Known open item — two ledgers, and a reconciliation only you can make

There are two budget layers, and until 2026-09-05 the lower one had **a copy per
source tree**:

| layer | path | role |
|---|---|---|
| **L3** | `production_state_root()/data/runtime/search_budget.json` (`SearchBudget@v1`) | **canonical and binding.** Checked first. Flocked, atomic, UTC. |
| **L2** | `production_state_root()/data/portfolios/state/brave_search_budget.json` | secondary per-caller cap (`CALLER_CAPS`), which L3 has no equivalent of |

**A correction worth recording.** The Phase 1 inventory reported the
`persistent-state` copy of L2 as "an orphan nothing reads". That is wrong, and
the check that shows it is the one AGENTS.md §7 already prescribes — *"a root that
symlinks to the same destination is not a control; vary the destination and
confirm different inodes"*. The **serving release symlinks
`data/portfolios/state` → `persistent-state/data/portfolios/state`**, so the
server process resolves to precisely that file (inode 4390787). It is not an
orphan; it is what production reads. Deleting it, as first proposed, would have
removed a file the live server resolves — and because `_load_budget()` rebuilds a
fresh zero counter on a missing file, that is a **fail-open**: unbudgeted calls.

The real defect was that `_BUDGET_FILE` was `Path(__file__).parent.parent / …`,
i.e. relative to whichever tree imported it. Eight copies of that basename exist
on this host; the server resolved one (frozen 2026-08-10, no September) and cron
running from the dev tree resolved another (September = 54). Each enforced the
ceiling against a fraction of the traffic. **Fixed** by resolving through the same
canonical state root L3 uses, so every caller now shares one L2 counter. The
scattered copies are thereby made inert *without deleting any of them* — nothing
resolves to them, and they remain readable as history.

**What is still open, and is an operator decision (AGENTS.md §0 rule 5).** The two
L2 copies disagree about September: the now-canonical file has no September entry,
the dev-tree copy has 54. L3 — the binding ceiling — has 60 and is unaffected, so
nothing is over-spending. But the L2 September count now starts from the canonical
file's view, not from 54. **Neither number was merged into the other.** The
reconciliation question — is September 54, 60, or the provider-billed figure? — is
yours to settle against the Brave dashboard.

**A second live defect, reported not fixed.** The operator spend alarm
(`alert_dispatcher_unified.py:89-111`, cron 08:30/16:30) reads **L2**, the
under-counted layer, not L3. That is the "working alarm on an unrepresentative
sensor" failure that created `lib/search_budget.py`, reproduced one layer up. The
correct sensor already exists and is already scheduled: `lib/search_health.py:127`
reads L3.

## A dormant bypasser

`phase2b_analyst.py:276-352` holds its own key and its own `urllib` call to
`api.search.brave.com`, touching neither ledger and passing no gate. It is
**dormant** — no cron entry, no systemd unit, no importer but itself, last touched
2026-04-18 — so it is a loaded gun rather than a live leak. It still carries the
comment `# Limit to top 5 to stay within 2000/mo free tier`: a third invented
provider limit, and a different number again. Its twin at
`scripts/portfolio_weekly_report.py:449` was neutered by the F2 sweep; this copy
was missed because it sits at the repo root, and the guard test at
`tests/test_overnight_f1_f2_search_bound.py:138-139` points only at the `scripts/`
path.
