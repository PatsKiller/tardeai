# Catalyst lead time: root cause and fix plan (CC v3 audit, 2026-11-10)

Owner: cc-opus-1. Status: one code fix on branch `wt/cc-opus-1-noon` (finviz time zone). Schedule change
requested from the registry owner (cc-deepseek-7). The rest is designed below with dates.

## Metric

`catalyst_events.created_at - published_at` over the rows created in the last 24 h. It is measured by
`scripts/ops/ccv3_audit_remeasure.py`. Live on 2026-11-10 at 09:30 ET: 615 events, 0.8 % within 1 h,
18.5 % within 6 h, median 14.5 h.
The 11-09 audit's 14-day figures were 1.8 % within 1 h, 17.9 % within 6 h and 49.6 % within 24 h.

## Root cause: three independent causes

Every number below was measured read-only on 2026-11-10 (09:27 ET window). Catalysts were joined to their
source article through `raw_payload->>'news_article_id'`, and `news_articles.created_at` is used as "first
fetched".

1. **Old news is minted as a new catalyst. This dominates the median.** 223 of 591 joined rows (37.7 %)
   come from articles first fetched more than 24 h after publication. The 224 rows written outside the
   news-to-catalyst slots are 91.2 % stale: total lag median 658 h, publish-to-fetch median 154 h,
   fetch-to-catalyst 0 h. These are per-symbol back-catalogue pulls (yahoo_rss, google_news; the likely path
   is `watch_decision_refresh.py`, which runs `news_ingestion --symbol` and then `news_to_catalyst --symbol`).
   The selector in `scripts/news_to_catalyst.py` (the `LEFT JOIN catalyst_events ... ORDER BY published_at
   DESC LIMIT` query in `run()`) has no age floor. Any headline never seen before becomes a catalyst,
   whatever its age. Share of the 24 h `news_articles` inserts that were more than 24 h old on arrival:
   topic_google_news_rss 93 %, yahoo_rss 73 %, google_news 52 %.
2. **The news-to-catalyst schedule.** The lane runs `45 6,12,18 * * *` (3 runs a day, about 60 s each, with
   a 12 h overnight gap). The code comment in `run()` still assumes a "10-min cron". For the 368 fresh articles
   (fetched within 24 h of publication), publish-to-fetch median is 1.6 h, but fetch-to-catalyst median is
   4.9 h. Fetching is not the bottleneck; the 3-a-day conversion is. A replay of the same fresh articles at a
   15-minute cadence gives 32.6 % within 1 h and 72.8 % within 6 h (today: 0.8 % and 51.1 %).
3. **Wrong publish timestamps.**
   - finviz_news: Eastern wall-clock times were stored as UTC (`scripts/finviz_news.py`, the
     `replace(tzinfo=timezone.utc)` line). Every finviz row read 4-5 h late; the smallest lag per fetch batch
     was 5.02-5.23 h. Correcting finviz alone moves within 6 h from 19.3 % to 31.8 %.
     **FIXED on the branch**, with tests for winter, summer and ISO export formats, red on the old code.
   - sec_edgar: `published_at` is the filing date at midnight (`scripts/lib/sec_filing_events.py`, from
     `filingDate`). Its minimum lag is 21.5 h, which is artificial. EDGAR's `acceptanceDateTime` is the real
     instant.
   - UNVERIFIED: yahoo_premarket, google_news_rss and sec_edgar_premarket show exactly 0.0 h publish-to-fetch,
     which suggests `published_at` is filled with the fetch time. That would flatter the metric. Proof would be
     a sample of raw feed items compared against the stored `published_at`.

Deduplication is not a cause. The insert is `ON CONFLICT (symbol, headline) DO NOTHING`, so the first copy
wins and `created_at` is not pushed late.

## What ships when

| # | Change | Kind | Who | Date |
|---|---|---|---|---|
| 1 | finviz Eastern time zone (`scripts/finviz_news.py`) | code, on branch | cc-opus-1 → review → lead fold | review 11-10; fold at the lead's next window (not 09:30-16:15) |
| 2 | `news-to-catalyst` cadence `45 6,12,18 * * *` → `*/15 * * * *`, plus `CATALYST_LLM_BUDGET` 25 → 5 per run to keep the daily LLM load near today's 75 | schedule/config, through the -7 registry | REQUEST to cc-deepseek-7; dry run through n8n emulation; operator approval (scheduled-job change) | proposal 11-10; activate after 16:15 ET 11-10 if approved |
| 3 | Age floor: an article first fetched more than 24 h after `published_at` is recorded but does not mint a *new* catalyst. It is stored as `backfill` and excluded from the lead-time metric and from momentum consumers | code | cc-opus-1 | design review 11-11, code + tests 11-11, fold 11-12 |
| 4 | SEC `published_at` from `acceptanceDateTime` | code | cc-opus-1 | 11-11 |
| 5 | Scorecard split: lead time over fresh items only (article fetched within 24 h of publication), next to the all-rows figure | code (scorecard) | cc-opus-1 | 11-11 |
| 6 | Find the writer stamping `published_at` = fetch time (yahoo_premarket, google_news_rss, sec_edgar_premarket) | investigation | cc-opus-1 | 11-12 |
| 7 | Event-driven ingest (EDGAR full-text, press-wire polling ≤ 5 min), event-to-screen P95 ≤ 10 min | design (audit 60-90 day item) | unassigned | design by 11-20 |

Expected effect on the scorecard. These are estimates from the replay, not measurements:
- #1 + #2: within 6 h for fresh items rises from about 51 % to about 75 %; within 1 h rises from about 1 % to about 33 %.
- #3 removes about 38 % of rows from the long tail. The all-rows median should then drop to roughly the fresh-item median, a few hours.
- The 1 h ≥ 50 % threshold needs #7. A 15-minute conversion cadence cannot reach it while publish-to-fetch alone is 1.6 h median.

## Open questions

- UNVERIFIED: whether the slot-keyed effect claim (`fx:news-to-catalyst:<slot>`) accepts a sub-hourly slot.
  The n8n emulation dry run in #2 answers it.
- UNVERIFIED: whether `remediate_watchlist_news_guard.py` is a second back-catalogue writer. Its log timestamps
  around 14:50Z and 16:05Z (11-09) would settle it.
