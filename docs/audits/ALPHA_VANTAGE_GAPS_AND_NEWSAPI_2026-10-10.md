# Alpha Vantage for the gaps, and the NewsAPI test

**Status:** ACTIVE (the owner code is on branch `n8nmat/av-newsapi`, committed locally, not pushed and not deployed). The registry rows are PROPOSED and need the operator's approval.
**as_of:** 2026-10-10 18:05 ET, host ms01-openclaw.
**Measured at:** `origin/main` e8a4a6815 plus `n8nmat/quickwins-20261010` (a2ba0a2e8, which removed the phantom Alpha Vantage spend). Database figures come from read-only `SELECT`s (`set_session(readonly=True)`) against the live `trade_ai` database.
**Operator asks (verbatim):** *"let's use Alpha Vantage for the gaps and prioritize which gaps that really make sense"* and *"on the news API, can you test it and fix it?"*

## 1 · Which gaps Alpha Vantage should fill, ranked

The free key allows 25 requests a day and 5 a minute. Three one-call, market-wide endpoints get the most coverage out of that budget. A per-symbol endpoint returns one ticker for each request spent.

| Rank | Gap | Evidence `[VERIFIED]` 2026-10-10 | Alpha Vantage call | Requests/day | Verdict |
|---|---|---|---|---|---|
| 1 | **Earnings date and timing** | `symbol_profiles` has `next_earnings_date` for **1,260 of 3,337** profiles (1,037 in the future). No store holds pre- or post-market timing; the only signal is Finviz's `earnings_before`/`earnings_after` mover lists (581 and 573 rows in 7 days). `earnings_date` has no backup, and its no_coverage rule is `UNKNOWN_blocks_options_gate`. | `EARNINGS_CALENDAR horizon=3month`: the whole US market in one call, with `reportDate`, `estimate` and `timeOfTheDay` (verified earlier today on the operator's brief). | 1 | **Fill.** One request covers the whole market. |
| 2 | **News sentiment for the scalp list and catalysts** | **0 of 7,492** `news_articles` rows written in the last 3 days have a `sentiment_score`. The scalp scanner's social inputs are 15–18 h old (CONSOLIDATION_PLAN L246). Hermes scalp catalyst averages 0.64 sources per ticker (L708). | `NEWS_SENTIMENT` with a time window and `limit=1000` and **no ticker filter**, because a multi-ticker query returns only articles that mention ALL the listed tickers (verified today: 27/27). Each article carries relevance and sentiment for every ticker it mentions. | 14 | **Fill.** A list of any size is covered at no extra request. |
| 3 | **Dead catalyst-news slots** | Finnhub (401 since 07-27, 9,554 failures), NewsAPI (never ran; see §3), and Polygon and FMP (paid only) were retired on 2026-09-13, leaving `catalyst_news` with finviz, yahoo and the search backups. | Same articles as rank 2 | 0 extra | **Fill as a by-product.** `catalyst_enrichment` already reads them through the projection when `ENABLE_ALPHA_VANTAGE_CATALYST=true`. Adding Alpha Vantage to the backup list is proposal B2. |
| 4 | **Fundamentals holes** | `fundamental_data` covers **21 symbols**, last fetched 2026-10-05 (weekly Monday lane, 5 per run). | `OVERVIEW`: one symbol per request. | ≤5 (+2 float) | **Keep as is, but budgeted.** This endpoint gives the least coverage per request. The weekly lane and the scalp-float lookup now draw from fixed allotments. |
| 5 | Top movers | Finviz already writes `market_movers` top_gainers (3,234 rows) and top_losers (3,288 rows) in 7 days. | `TOP_GAINERS_LOSERS`, verified today on the documented **demo** URL: 20 gainers, 20 losers and 20 most active, `last_updated 2026-10-09 16:15:57 US/Eastern` (end of day). | 0 | **Skip.** Finviz already covers it. |
| 6 | IPO calendar / listing status | Nothing in the system consumes either. Identity is already covered by SEC `company_tickers` and `identity_registry`. | `IPO_CALENDAR`: verified on the demo URL (CSV with `symbol,name,ipoDate,priceRangeLow,priceRangeHigh,currency,exchange`). `LISTING_STATUS`: the demo URL returned `{}`, so it is **unverified**. | 0 | **Skip.** No consumer exists. I did not spend a real request to verify LISTING_STATUS. |

The demo URLs use Alpha Vantage's public `apikey=demo` key, so they spent none of our 25. No URL was printed.

## 2 · The owner: one Alpha Vantage caller, one budget

**Before:** five call sites hit `alphavantage.co` directly, and only one of them consulted any budget:

- `catalyst_enrichment` (NEWS_SENTIMENT per symbol)
- `external_market_data_ingest` (OVERVIEW and NEWS_SENTIMENT)
- `scalp_float_lookup` (OVERVIEW, every 5 minutes from 06:00 to 15:55, no budget)
- `credential_monitor` and `secret_validators` (GLOBAL_QUOTE on every key check)

**After:** `grep alphavantage.co scripts/` matches one file, `scripts/lib/alpha_vantage_owner.py`. A test enforces this.

| Piece | File |
|---|---|
| Gateway, budget, refusals, receipts | `scripts/lib/alpha_vantage_owner.py` |
| Scheduled jobs and publishers (dry run by default) | `scripts/alpha_vantage_owner.py` |
| Config (jobs, allotments, slots, draft health contracts) | `config/alpha_vantage_owner.json` |
| Projections (zero provider calls, read envelope) | `scripts/lib/data_broker/earnings_calendar.py`, `scripts/lib/data_broker/news_sentiment.py` |
| Registry proposal (operator approval needed) | `config/policy_proposals/data_source_authority_alpha_vantage_scope_20261010.json` |
| Tests (GATES `alpha_vantage_owner_20261010`) | `tests/test_alpha_vantage_owner_20261010.py` (47) |

### The budget

| Job | Function | Allotment/day | Class | Caller |
|---|---|---|---|---|
| `earnings_calendar` | EARNINGS_CALENDAR | 1 | scheduled 06:05 ET | owner |
| `news_sentiment_window` | NEWS_SENTIMENT | 14 | scheduled at 06:00, 07:00, 08:00, 09:00, 09:45, 10:30, 11:30, 12:30, 13:30, 14:30, 15:30, 16:30, 18:00 and 20:00 ET | owner |
| `fundamentals_overview` | OVERVIEW | 5 | scheduled lane | `external_market_data_ingest.py --fundamentals` (cron L162, Mon 08:00), still the single writer of `fundamental_data` |
| `scalp_float` | OVERVIEW | 2 | on-demand reserve | `scalp_float_lookup.py` |
| `key_check` | GLOBAL_QUOTE | 1 | on-demand reserve | `credential_monitor` and `secret_validators`, only when the owner has had no success in 36 h |
| `top_movers` | TOP_GAINERS_LOSERS | 0 | disabled | none |
| **Total** | | **23** | | hard cap = 25 − 2 margin |

**How the owner decides each request:**

- **Refusals are checked first, in this order, and are never counted:**
  1. unknown job, or a function that is not the job's own
  2. a disabled job
  3. **the registry has not granted the domain**: the owner reads `providers.alpha_vantage.supplies`, which grants `fundamentals` only today
  4. no key
  5. the provider has already sent its daily-limit notice today
  6. the job's allotment is spent
  7. the hard cap is spent
  8. the 12 s spacing slot is more than 30 s away
- **Counting:** a call counts against both the UTC day and the America/New_York day, and both must stay ≤ 23. Alpha Vantage does not document which midnight resets the 25, so double-counting is the safe choice.
- **Spending:** a call is counted before it is sent, so a timeout still spends.
- **Response handling:**
  - A daily-limit notice marks the day exhausted.
  - A notice on a CSV endpoint is detected. Today's demo response showed the header followed by `I,n,f,o,r,m,a`.
  - The key is scrubbed from every error string and never reaches the ledger or the receipts.
- **Records:**
  - Every decision writes one line to `data/runtime/alpha_vantage/receipts_YYYYMM.jsonl`.
  - Every real call reports `alpha_vantage` liveness to `data_source_health`. Lanes no longer report it themselves, because a budget refusal is not a provider failure.
- **When nothing is available:** each projection answers `gap.kind = no_coverage` with `declared_behaviour = say_so`. It never substitutes a value from another domain.

**News windows are contiguous.** Each pull asks for `time_from` = the previous pull's `time_to`. The first pull, or a pull after more than 24 h, starts at now − 24 h and records `cursor_gap: true`. A pull that returns 1,000 articles records `truncated: true`. The index keeps a rolling 72 h of articles. Each article is appended once to `news_sentiment_articles_YYYYMM.jsonl`. Per ticker, the index holds the relevance-weighted sentiment (relevance ≥ 0.3), counts and the top 5 headlines, labelled with Alpha Vantage's own bands.

**Rerouted callers:**

- **`catalyst_enrichment._fetch_alpha_vantage`** now reads the `news_sentiment` projection and never sends a request. It still respects `ENABLE_ALPHA_VANTAGE_CATALYST`, which defaults to off.
- **`external_market_data_ingest`:**
  - `_av_overview` goes through the owner.
  - `ingest_av_news_sentiment` copies from the owner's store, still through `news_articles_writer`.
- **`scalp_float_lookup`** now uses the owner's `scalp_float` job.
- **`credential_monitor.check_alpha_vantage` and `secret_validators._alphavantage`** use `validate_key_via_owner`. The owner's last success answers first, and a request is spent only when the status is unknown.
- **`api_budget`'s `alphavantage` cap** has no caller left.

### Health contracts

`config/alpha_vantage_owner.json` holds three draft `N8nHealthContract@v1` contracts: news sentiment, earnings calendar and budget. Each has healthy, degraded and failed checks. `config/n8n_health_contracts.json` exists only on the unmerged branch `n8nmat/w0-siem-followups`, so the contracts sit next to the owner for now. Copy them into that file when it lands.

### Dry-run proof: 0 requests and 0 writes `[VERIFIED]`

The dry run used the real state directory, `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/alpha_vantage`. The key was resolved by `resolve_secret` anchored at the main checkout and was never printed. The HTTP transport was replaced with one that raises.

```
state_dir … exists_before False
=== alpha_vantage_owner.py --job all
  earnings_calendar      outcome refused_scope_not_granted
  news_sentiment_window  outcome refused_scope_not_granted  time_from 20261009T2203 time_to 20261010T2203
  requests_sent 0   ledger_sha256_before null   ledger_sha256_after null   granted_domains ["fundamentals"]
=== alpha_vantage_owner.py --job all --preview-granted-scope
  earnings_calendar      outcome dry_run_would_call
  news_sentiment_window  outcome dry_run_would_call
  requests_sent 0   ledger_sha256_before null   ledger_sha256_after null
=== alpha_vantage_owner.py --job due
  earnings_calendar slot 2026-10-10 06:05 refused_scope_not_granted; news_sentiment_window slot 2026-10-10 18:00 refused_scope_not_granted
  requests_sent 0
state_dir exists_after False
key_in_dryrun_output: False
```

The dry run would have exited 3 if a request had been sent or the ledger had changed.

## 3 · NewsAPI: test, root cause, recommendation

**What "the news API" means.** `NEWSAPI_KEY` is NewsAPI.org. Its registry row is `newsapi` (status `retired` on 2026-09-13, reason "Never ran; health row never touched"), and it was slot 2 of the old six-slot catalyst chain. Two other things also carry the name, which makes the request **ambiguous**:

- the Finviz "News API" (`news_export.ashx`, slot 2 of today's chain). It is healthy: `finviz_news` last wrote on 10-09 at 15:30.
- the Brave news endpoint (`brave_router.BRAVE_NEWS_URL`, the `catalyst_news` search backup)

I tested NewsAPI.org because it is the only one called "never ran".

**Key:** `NEWSAPI_KEY` is present. I checked by name through `resolve_secret` from the main checkout. `NEWSAPI_API_KEY` is absent.

**Live test, 2 calls, 2026-10-10 21:44 UTC.** The key was sent in the `X-Api-Key` header and every output was scrubbed:

| Call | HTTP | status | totalResults | Newest article age |
|---|---|---|---|---|
| `/v2/top-headlines?country=us&pageSize=1` | 200 | ok | 36 | **25.14 h** |
| `/v2/everything?q=Apple&sortBy=publishedAt&pageSize=5` | 200 | ok | 18,295 | **24.01 h** |

No rate-limit headers were returned. The key is valid. The newest of 18,295 "Apple" articles, sorted by publish time, is exactly 24.01 h old. That matches the developer (free) plan's **24-hour delay**. The plan is also limited to 100 requests/day and to development use only `[DOC-CLAIM: newsapi.org/pricing, not fetched today]`.

**Why it "never ran".** The health row was never touched, and two silent paths explain that. Neither proves the provider never answered:

1. `catalyst_news_sources._fetch_newsapi` did call `report_source("newsapi")`. However, `report_source` opened its own DB connection without `DB_PASSWORD` when cron did not source `.env`. It failed inside a swallowed exception. The `alpha_vantage` row stayed `unknown` from 05-09 for the same reason. That was fixed on 2026-09-14, the day **after** NewsAPI was retired. The `newsapi` row is still `unknown`, with `updated_at` 2026-05-09.
2. `_get_json` logged every non-200 response at DEBUG, and `catalyst_enrichment._fetch_newsapi` swallowed every exception with no health report at all.

In addition, the `api_budget_ledger` `newsapi` counter is phantom. It holds 112,818 "calls" over 86 days, the same as finnhub, polygon and fmp, because `spend()` counted refusals (fixed in a2ba0a2e8). The only NewsAPI log line found anywhere is `[api-budget] newsapi daily budget exhausted (451/450)`. The cap was set for "500/day free", but the plan is 100/day.

**Fix.** NewsAPI has had zero call sites since 2026-09-13, so no live code path exists to repair. Both silent-failure causes are already fixed (health reporting 09-14, phantom spend a2ba0a2e8). The remaining defects were in the key validator, and both are fixed on this branch:

- `secret_validators._newsapi` put the key in the URL. It now sends it in the `X-Api-Key` header and reports the body's `code` (for example `apiKeyInvalid`, `rateLimited` or `upgradeRequired`).
- `secret_validators.validate()` returned `str(exception)`, which can contain a URL with a key. It now scrubs the key from that text, for every validator.

**Recommendation: do not un-retire NewsAPI.** `catalyst_news` goes stale after 18 h, so every article from a 24-hour-delayed plan is stale on arrival, and the plan's terms rule out production use. Fill the slot with Alpha Vantage NEWS_SENTIMENT instead (proposals A3 and B2), with the existing Brave and SearXNG search backup behind it. Un-retiring is an operator decision. Row N1 in the proposal file is prepared with an approval placeholder and marked NOT RECOMMENDED.

## 4 · Operator decisions (propose and stop)

1. **Approve A1, A2 and A3** in `config/policy_proposals/data_source_authority_alpha_vantage_scope_20261010.json`. They widen the `alpha_vantage` scope to add `earnings_calendar` and `news_sentiment` and add those two domains. A test shows the rows pass `check_data_source_authority.py` once the grant is filled in, and fail with `UNAPPROVED_SOURCE` without it.
2. **Schedule the owner.** This needs a cron or n8n grant (cron freeze 2026-10-09): one entry running `scripts/alpha_vantage_owner.py --job due --apply` at the 15 slot times.
3. Optionally approve **B1** (Alpha Vantage as the same-question backup for `earnings_date`; needs an `earnings_enrich` reader change) and **B2** (Alpha Vantage in the `catalyst_news` backups).
4. Optionally set `ENABLE_ALPHA_VANTAGE_CATALYST=true`. This now costs no requests.
5. **Decline N1**, the NewsAPI un-retire.

## 5 · Open items

- **Time zone of `time_published` is UNVERIFIED.** Alpha Vantage does not state it. The owner treats it as UTC, as `catalyst_enrichment` always has. The cursor windows use the same convention, so coverage stays contiguous, but ages could be off by the ET offset.
- **Unknown reporter.** `data_source_health.alpha_vantage` shows a success at 10-09 21:47 that no known caller explains (API_OVERLAP_CONSOLIDATION §5). Its source is not traced. The 2-request margin in the cap exists for that unknown caller.
- **Other callers of the key.** Any caller outside this repository, such as an n8n node, would bypass the owner. The `over_cap` health check names this risk.
