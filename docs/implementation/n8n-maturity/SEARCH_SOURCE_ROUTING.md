# Search source routing — which source answers what, and what it may spend

Status:      DRAFT (engine built and tested; inert until `SEARCH_ROUTING_ENGINE=1` is set for a lane)
as_of:       2026-10-10T19:30:00-04:00
Measured at: branch `n8nmat/search-routing-engine` on top of `e8a4a6815` (+ local `n8nmat/quickwins-20261010`); live state read-only on ms01-openclaw

Owner: Agent V. The engine owns routing and the Brave budget. Agent Q's scalp hot tier (`n8nmat/scalp-hot-tier`) calls it.
Agent U's Alpha Vantage owner (`n8nmat/av-newsapi`) writes the AV news store that the engine reads.

**Link from:** `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` (branch `n8nmat/w0-siem-followups`, PR #1666).
That branch was not edited here. When #1666 merges, add one row under its provider/egress section:
"Web search: `config/search_routing_policy.json` → this document."

**Operator, 2026-10-10 ~18:03 ET (verbatim):** "implement your plan. I have $20 maximum a month on Brave already, trying
not to use it all, and we need to prioritize the search for scalps that are about to fire and make sense. And we
have the free lane, we just need to make sure that we have a mature engine and rules about which source to use for
what so we're conserving the spend."

---

## 1. The rule, in one line

Every routed question goes through the same steps, and stops at the first one that gives a good enough answer:

1. **Cache.**
2. **Free sources.**
3. **Paid Brave.** Only when the question's class allows it, the free answer fails a measurable quality rule, and the
   dollar budget has room.
4. **A declared "no coverage" answer.** It is never filled from the wrong source.

| Piece | Path |
|---|---|
| Policy (data) | `config/search_routing_policy.json` (`SearchRoutingPolicy@v1`), declared on `domains[web_search].routing_policy` in `config/data_source_authority.json` |
| Validator | `scripts/lib/search_routing_policy.py`. `scripts/check_data_source_authority.py` fails with `ROUTING_POLICY_INVALID` |
| Engine (the only entry point) | `scripts/lib/search_router.py`: `route()`, `route_query()`, `route_search()`. Alias: `scripts/lib/search_routing_engine.py` |
| Quality rule | `scripts/lib/search_quality.py` |
| Dollar budget | `scripts/lib/search_spend.py`. It is enforced inside the ledger lock through `search_budget.try_consume(gate=…)` |
| Scalp priority | `scripts/lib/scalp_priority.py` |
| Ledger, receipts | `data/runtime/search_budget.json`, `data/runtime/search_routing_receipts.jsonl`. Both are written only by `scripts/lib/search_budget.py` |
| Cache | `data/runtime/search_routing_cache.json` (`SearchRoutingCache@v1`) |
| Spend report and health | `scripts/search_spend_report.py` writes `data/runtime/search_spend_last.json`. The incident fan-in reads it as source `search_spend` (P2) |
| Tests | `tests/test_search_routing_engine_20261010.py` (67 tests, gate `search_routing_engine_20261010`) |

## 2. Classes and their tiers

Callers name themselves, and the policy's `callers` map assigns each one a class. A caller that is not in the map is
refused with `UNKNOWN_CALLER`. There is no default class, so a new caller cannot spend by accident.

| Class | Callers | Tier 0 cache TTL | Tier 1 free (in order) | Tier 2 paid Brave | Pool | Quality bar (results / trusted / relevant / fresh) | No coverage |
|---|---|---|---|---|---|---|---|
| `scalp_priority` | promoted by the classifier (§4); `scalp_hot_tier` | 20 min | internal news → SearXNG news → AV news store | news, `pd`, 5 results, when free is insufficient | **scalp** (first claim) | 2 / 1 / 1 / 1 within 24 h | say_so |
| `catalyst_confirmation` | `hermes_momentum_catalyst` (L708), `hermes_scalp_catalyst`, `catalyst_momentum_engine` (L379), `catalyst_intelligence` | 2 h | internal news → SearXNG news → AV news store | news, `pw`, when free is insufficient | catalyst | 2 / 1 / 1 / 1 within 72 h | say_so |
| `operator` | `web_research`, `intel_query`, `operator`, `manual` | 30 min | SearXNG web | web (+ Goggle once hosted), when free is insufficient | **operator** (reserve) | 3 / 1 / 2 / – | say_so |
| `research` | `governed_research_producer`, `hermes_cio_research` | 6 h | SearXNG web | web, 3 results, when free is insufficient | other | 3 / 1 / 2 / – | say_so |
| `gap_fill` | `gap_resolver` | 6 h | SearXNG | **never** | other | 1 / 0 / 1 / – | declared_gap |
| `quality_escalation` | `research_quality_escalate` | 6 h | SearXNG web | **never** | other | 1 / 0 / 1 / – | say_so |
| `social_discovery` | `aegis_social_sentiment` (only with `AEGIS_BRAVE_ENABLED=1`) | 6 h | SearXNG web | **never** | other | 1 / 0 / 1 / – | say_so |
| `transcript_discovery` | `aegis_transcript_discovery` (only with `AEGIS_BRAVE_ENABLED=1`) | 6 h | SearXNG web | **never** | other | 1 / 0 / 1 / – | say_so |

**The free sources**

- **`internal_news`.** A read-only broker projection, `catalyst_record.get_symbol_news` (`news_articles`, domain
  `catalyst_news`). It is symbol-tagged, so its rows count as relevant.
- **`searxng`.** The self-hosted instance. The engine names its engines explicitly (§6). It never sends a bare
  `categories=general` request.
- **`alpha_vantage_news`.** Reads the AV owner's rolling `data/runtime/alpha_vantage/news_sentiment_latest.json`
  (`NewsSentimentIndex@v1`, keyed by `by_ticker`, or `articles[].ticker_sentiment`). It never sends an Alpha Vantage
  request: the owner is the only AV caller, and it spends the 25 requests a day. The source is skipped with
  `NOT_GRANTED` until `providers.alpha_vantage.supplies` includes `news_sentiment` or `catalyst_news`. That is the
  operator's grant (§17), proposed on `n8nmat/av-newsapi`. The source is skipped with `NO_STORE` until the owner
  writes the index.

**The quality rule.** A free answer is sufficient when every count meets the class minimum:

- results that have a URL;
- results whose host is a trusted financial domain or a subdomain of one (34 domains, in the policy);
- results that mention the symbol as a whole word, or at least half the query's key terms;
- when the class sets a freshness window, results whose publish time is **known** and inside the window. An undated
  result does not count as fresh.

A cached free answer that was insufficient never blocks escalation for a class that is allowed to pay.

## 3. Budget, in dollars

The price is $0.005 per request (Brave Search plan, $5 per 1,000), with a $5 credit each month.

Every dollar line below is compared to **gross** spend, before the credit, which is the conservative reading. The
report shows gross, credit and net billed. The ledger counts requests, the engine multiplies them by the price, and
the decision runs **inside the ledger's flock**. That way "is there money?" and "spend it" are one atomic step across
cron processes.

| Line | Value | Who it stops |
|---|---|---|
| Account cap (Brave dashboard) | $20 | not used locally; the local lines stay under it |
| Local ceiling | **$18** | everyone, the operator included |
| Working target | **$15** | the scalp pool |
| Non-priority stop | **$12** | catalyst and other |
| Alert | 80% of $15 = **$12** | P2 through the incident fan-in. The notifier decides the send; the engine sends nothing |

| Pool | Share of $15 | Rule |
|---|---|---|
| scalp | 50% ($7.50) | First claim. May run to $15. May use any background allowance the day leaves unspent |
| operator | 20% ($3.00) | Reserve. Skips daily pacing. May run to $18. Background pools can never use it |
| catalyst | 20% ($3.00) | Its own share of the month and of the day; stops at $12 |
| other | 10% ($1.50) | Its own share of the month and of the day; stops at $12 |

**Daily pacing**

- base = $15 ÷ NYSE trading days in the month. October 2026 has 22 trading days, so base = $0.682 a day,
  about 136 requests.
- Unspent pace carries forward, capped at one day's base.
- Overspent pace is repaid from the next day, but the allowance never drops below 25% of base.
- A non-trading day gets 25% of base.
- Ledger days and months are **UTC**, the same keys the ledger itself uses.

The decision returns the first refusal that applies, checked in this order:
`LOCAL_CEILING`, `MONTH_LINE:<line>`, `POOL_MONTH_SHARE`, `DAILY_PACE`, `POOL_DAY_SHARE`.

**The request ceiling also still binds.** `providers.brave.budget` in the registry allows 120 requests a day and 1,500
a month, with 200 held back for on-demand callers. That is the anti-runaway breaker, and it was **not raised**. Until
the operator raises it, routed non-operator pools stop at 1,300 requests a month, which is **$6.50 gross**. Reaching
the $15 target needs a monthly budget of at least 3,000 (3,600 matches $18) and a daily budget of at least 140. That
is an operator decision (§17, funding a data plan).

**Per-caller hardcoded caps** (`CALLER_DAILY_CAPS`: 25 a day by default, `hermes_cio_research` 10) do not apply to
routed callers. Routed callers are named `route.<pool>`, and the pools govern them. The legacy map stays for callers
that are still unrouted.

### Expected monthly spend at current volumes

`[MEASURED]` from the ledger, read-only, 2026-10-10:

- Brave requests: 579 in September ($2.90 gross). October 1–10: 250 ($1.25 gross). October run-rate: $3.93 gross,
  **$0 net** (inside the $5 credit).
- All 250 October requests came from `governed_research_producer`, which asks Brave **first** today.
- SearXNG units in October 1–10: 1,923. Of those, `hermes_cio_research` used 1,347.

`[ESTIMATE]`, with the engine on for every caller:

- **research** moves to free-first, with Brave only on an insufficient answer. It is capped at $1.50 a month.
- **catalyst** is capped at $3.00 a month.
- **scalp_priority** is at most 5 names per cycle, each re-asked no more than every 30 minutes, 04:00–16:00 ET. The
  worst case is about 120 paid requests a day, which hits the 120-a-day breaker. If 20–40 a day go paid, that is
  about $2–4 a month.
- **Expected total: $3–7 gross ($0–2 net) a month.** The registry breaker bounds it at $6.50 gross until it is raised;
  after that, the policy bounds it at $18.

## 4. "About to fire": the scalp-priority definition

`scripts/lib/scalp_priority.py` is deterministic and read-only. A candidate gets first claim when **every** rule holds:

1. **Session.** It is an NYSE trading day, inside premarket (04:00–09:30 ET) or regular hours (09:30–16:00 ET).
2. **On the current list.** One of:
   - `data/trade_ai/scalp_universe_latest.json` (the L1050 lane's `TradeAIScalpUniverse@v1`) is no older than 15 min;
   - the calling lane handed the row in this cycle (L379's premarket candidates, Q's hot tier).
3. **Makes sense.** The decision is `GO`, `MANUAL_REVIEW` or `WAIT`, never `AVOID`.
4. **About to fire.** One of:
   - score ≥ GO line − 5, where the GO line is `assets/weights.yaml` `decision_rules.GO.min_score` = 40, so 35+;
   - momentum: RVOL ≥ 3 with a gap ≥ 5% or a move ≥ 10%, used only when the row carries those fields.
5. **Needs research.** The name was not researched (an answered `scalp_priority` receipt) in the last 30 minutes.
6. **Ranked.** Only the top 5 by score each cycle; the rest get `OVER_CYCLE_CAP`.

A name that fails any rule is routed as its caller's own class, `catalyst_confirmation`. The cache usually answers it.

**Q's hint** (`route_search(request_class="scalp_priority")`) is honoured only inside a session and outside the
30-minute recency window. The hint is recorded as `source: caller_hint`.

## 5. Callers rerouted (flag-gated; the legacy path is unchanged with the flag off)

| Caller | Lane | Before | With `SEARCH_ROUTING_ENGINE=1` |
|---|---|---|---|
| `governed_research_producer` | wake research | Brave **first**, SearXNG only on `CALLER_DAILY_CAP` | class `research`: free first, Brave only if insufficient |
| `hermes_web_research.gather` (`hermes_cio_research`) | CIO options research | SearXNG `categories=general`, Brave on zero hits | class `research`, one routed call per planned query |
| `gap_resolver._v_governed_search` | data gaps | Brave when armed, else SearXNG | class `gap_fill`, free only |
| `research_quality_escalate` | thin-answer climb | SearXNG | class `quality_escalation`, free only |
| `hermes_momentum_catalyst_researcher.search_catalyst` | **L708** (and L379 through it) | bespoke SearXNG call (google/bing/ddg news) | `route_search`, `catalyst_confirmation`, promotable to `scalp_priority`, cache keyed on (symbol, intent) |
| `catalyst_momentum_engine` | **L379** `*/30 4-9` premarket scalp | `search_catalyst(sym, suffix)` | the same call plus the candidate row (score, decision, rvol, gap_pct) so the classifier can promote it. Its 04:00–06:00 searches route through the engine |
| `aegis_social_sentiment` / `aegis_transcript_discovery` | Aegis | Brave router (off by default) | class `social_discovery` / `transcript_discovery`, free only; still gated by `AEGIS_BRAVE_ENABLED` |

**Untouched**

- The scalp-live L1050 runner.
- The L323 paper path (`auto_proposal_generator`).
- Every order, size and stop path.

L379's proposal gating reads the same row shape (`title`, `url`, `content`, `engine`, `published`).

**Agent Q's call shape**

```
route_search(query, *, request_class, caller, subject, intent, time_range="day", categories="news",
             limit=3, cache_ttl_s=1200, dry_run=False)
  -> {ok, results:[{title,url,content,engine,published}], provider, cache_hit, as_of, decision, denied_reason}
```

- It is importable as `lib.search_routing_engine`, `lib.search_router` and `scripts.lib.search_router`.
- `request_class` is either `scalp_priority` or `scalp_research`.
- The cache is keyed on (subject, intent), so L708 and L379 share entries. The TTL is min(`cache_ttl_s`, class TTL).
- `dry_run=True` reaches no provider and writes nothing. It works with the flag off.
- `decision` is the engine's reason string (for example `FREE_SUFFICIENT`, `PAID_OK`, `DRY_RUN`); `route` carries
  the class, pool, tier, cost and priority detail.
- Live calls need `SEARCH_ROUTING_ENGINE=1` **or** Q's `SCALP_HOT_TIER=1`, which is the operator's opt-in for the hot
  tier and enables only `route_search`.
- After the merge with #1671, `search_catalyst` picks one of three paths, in order:
  - with the hot tier on, Q's `scalp_research_route` calls `route_search`;
  - otherwise, with `SEARCH_ROUTING_ENGINE=1`, the engine path, with the candidate row attached;
  - otherwise, with both flags off, the legacy SearXNG call, byte for byte.

## 6. Finding: the "free" lane named a paid engine

`[VERIFIED]` 2026-10-10, local SearXNG `/config` endpoint and `docker logs searxng`, read-only.

- `braveapi`, the **paid** Brave API, is enabled in SearXNG's `general` category. `scripts/install_searxng_config.sh`
  keys it.
- Every `categories=general` query, which is what `free_search` and the spill adapter send, therefore also asks
  api.search.brave.com. `lib/search_budget` never counts those requests.
- SearXNG logged **2,357 braveapi requests from 2026-10-01 to 10-10, every one `422 Unprocessable Entity`** (per
  day: 73, 249, 176, 163, 268, 274, 233, 359, 377, 186).
- Whether Brave bills a 422 is **UNKNOWN**. Successful braveapi calls are not logged, so their count is unknown too.
  The Brave dashboard's October request count, compared with the ledger's 250, will answer both.

**Fix in this branch.** `searxng_client.searx_search(engines=…)` sends an explicit engine list and **drops
`categories`**. SearXNG takes the union of a category's engines and the `engines` list, so sending both re-admits
braveapi. This was measured: `categories=news` together with `engines=` also returned `wikinews`, while `engines=`
alone returned only the named engines.

The free lane's lists are policy data:

- web: bing, seznam, yandex, yep, wikipedia;
- news: bing news, duckduckgo news, reuters, yahoo news, google news, wikinews.

The validator refuses any list that names `braveapi`, `brave` or `brave.news`. `free_search` applies the list to
**every** caller, legacy callers included. A fallback copy is pinned equal to the policy by a test.

**Not done; the operator decides.** Disabling `braveapi` in the SearXNG pool itself is a host configuration change
through `install_searxng_config.sh`.

## 7. Receipts, metrics, health

**Per call.** Each call writes one `SearchRoutingReceipt@v1` line with these fields: `ts`, `caller`, `class`, `pool`,
`tier`, `source`, `reason`, `answered`, `cost_usd`, `cache_hit`, `units_paid`, `units_free`, `latency_ms`, `quality`,
`attempts`, `paid_reason`, `spend_decision`, `priority`, `symbol`, `query_hash`. The query text is never stored, only
its hash.

**Daily report.** `scripts/search_spend_report.py` is a dry run by default; `--write` writes the receipt and a history
line. It reports:

- month gross, net and the percentage of target, against every line;
- per-pool month and day spend, and today's pace;
- today's routed questions by class and tier;
- **the free-lane share** (answered with no paid request);
- the cache hit rate;
- **scalp-priority research latency**, p50 and p95;
- **ledger keys dated in the future**.

**Health contract.** This is the entry to add to `config/n8n_health_contracts.json` once #1666 merges, kind
`host_monitor`, id `search-spend`:

- purpose: keep Brave spend under the operator's $20 a month and answer scalps about to fire first;
- connects_to:
  - `data/runtime/search_budget.json` (read);
  - `data/runtime/search_routing_receipts.jsonl` (read);
  - `config/search_routing_policy.json` (read);
  - `data/runtime/search_spend_last.json` (write);
  - incident fan-in source `search_spend` (read by the fan-in);
- healthy: gross spend under 80% of $15 and the ledger readable;
- degraded: at or above $12 (80% of target), raised as P2;
- failed: at or above $18, or the ledger unreadable;
- baseline: `OPERATOR_SLO` (the operator's $20, $15 and $12 lines);
- measures: gross against the lines, `free_lane_share`, `scalp_priority_latency_ms`.

**Dry-run quote** (production state, read-only, 2026-10-10 ~19:10 ET; ledger md5 unchanged before and after):

```
ok ok dry True
{'month': '2026-10', 'month_requests': 250, 'gross_usd': 1.25, 'net_billed_usd': 0.0, 'pct_of_target': 8.3, 'run_rate_month_usd': 3.9286}
pace {'allowance': 0.170455, 'base': 0.681818, 'carry': 0.0, 'elapsed_trading_days': 7, 'trading_day': False, 'trading_days': 22}
future {'brave': ['caller_daily:2026-10-11', ..., 'monthly:2026-11', 'monthly:2026-12', ...], 'searxng': [... 'monthly:2026-11', 'monthly:2026-12']}
```

## 8. Finding: test fixture wrote into the production ledger (RC1 class)

`tests/test_research_heartbeat_20260914.py` runs `BridgeHermesResearchBackend.run`. That calls
`hermes_web_research.gather`, and because `options_desk_settings.web_research.enabled_reasons = ['*']`, the gather
really runs. It made **live SearXNG requests** and wrote `hermes_cio_research` rows into the production
`search_budget.json`. Some of those rows carry future dates: 10-11, 10-13, 10-14, 11-02 and 12-25, with searxng counts
of 2–4 and Brave refunds on the same days.

This was reproduced against a temp state root: the test wrote a ledger there.

**Fix.** An autouse fixture gives that file a temp state root and stubs the web gather offline, and a regression test
pins it.

**The existing future-dated rows were not cleaned** (§0 rule 5: never auto-remediate). `monthly:2026-11` and
`2026-12` hold 0 Brave requests and 2 searxng units, so they pre-spend nothing material. Archiving them is an
operator-approved ledger edit.

## 9. What turns it on, and the approvals it needs

Everything below is the operator's to grant. None of it was done here.

1. **Deploy** this branch: A3, an exact-SHA grant.
2. Set `SEARCH_ROUTING_ENGINE=1` in the environment of each lane to reroute: L708, L379, the governed research
   producer, the CIO research worker, the gap resolver, and the quality escalation host flag. Each is a cron, systemd
   or n8n entry change, so it is §17. Shadow first: `SEARCH_ROUTING_DRY_RUN=1` plans every decision with no call and
   no write.
3. **The paid tier also needs `BRAVE_ROUTER_LIVE=1`** on that lane. Without it the engine answers free-only and
   records `PAID_NOT_ARMED`.
4. Optional:
   - raise `providers.brave.budget` (monthly ≥ 3,000, daily ≥ 140) so the dollar policy, not the request breaker,
     binds;
   - grant `alpha_vantage` scope `news_sentiment` (Agent U's proposal);
   - host a financial Goggle and set `goggles.financial`;
   - disable `braveapi` in the SearXNG pool;
   - schedule `search_spend_report.py --write` (for example hourly) so the P2 alert has a receipt to read.
5. Archive the future-dated ledger keys (§8).
