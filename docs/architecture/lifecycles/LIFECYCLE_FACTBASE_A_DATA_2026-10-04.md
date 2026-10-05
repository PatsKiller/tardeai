# Trade AI — Family A: Data and Source Lifecycles (re-measured)

Status: ACTIVE
as_of: 2026-10-04T20:41-04:00 (measurement window 20:41–21:25 EDT, Sunday; markets closed since Fri 10-02 16:00)
Measured at: 4f932b88a (dev tree HEAD = CURRENT `4f932b88a-main-exact-phase2-20261004-202102`)
Baseline: `docs/architecture/lifecycles/LIFECYCLE_FACTBASE_A_DATA_2026-09-14.md` and the Family A chapters of `docs/architecture/TRADE_AI_AS_IS_LIFECYCLES_2026-09-14.md`

```
Method:   read-only. SQL wrapped in SET TRANSACTION READ ONLY (helper scratchpad lcA/q.sh); crontab -l;
          systemctl --user list-timers; file and log reads under persistent-state; GET :7777 only;
          git log --since=2026-09-14. No POST, no DB writes, no LLM calls, no broker calls, no secrets
          printed (env checks used grep -c on key NAMES only).
Labels:   MEASURED (command / file:line) · DOCUMENTED (commit message, doc or code comment, not observed
          at runtime) · INFERRED (reasoned from measured facts)
Clock:    Sunday night. Weekday-only producers (Finviz, Alpaca quotes, Schwab stream, moomoo probes)
          last ran Fri 10-02; that silence is expected and is not counted as a break.
Lifecycles: A1 data point · A2 data source (provider), including the per-provider data plane ·
          A3 identity · A4 material change · A5 served copy / persistent state (new chapter, split out
          from the A1 and F notes of 09-14)
Paths:    PS = ~/trade-ai-releases/persistent-state ; RT = PS/data/runtime ; CIO = PS/data/cio ;
          LOGS = PS/logs (CURRENT/logs → PS/logs)
```

---

## 0. Headline: what is true now vs 09-14

| # | Finding | Label / evidence |
|---|---|---|
| 1 | **The gap resolver is armed and has run 8,339 times. It has answered 4 times.** Of the receipts, 7,621 (91 %) are `budget_denied`. The 4 `answered` receipts are all `quote_price` for symbol S via yfinance on 09-23. `research_gaps` still has **0 resolved**: 118 OPEN plus 10 LLM_ELIGIBLE_NOT_AUTHORIZED, oldest 1,005 h. | MEASURED: `CIO/gap_resolution_receipts.jsonl` (python Counter on `outcome`); `RT/gap_resolution_last_run.json` (`receipts 8339`, `OPEN_NO_ATTEMPT 118`); `~/.config/tradeai/gap_resolver_live` mtime 2026-09-20 |
| 2 | **The 09-04/09-11 corrupt closes were rewritten in place, not quarantined.** NOC 09-11 now reads 518.80 (it was 120.25). `ticker_prices_quarantine` max is still 2026-08-27 (92 rows). The repricer has written no >50 % jump since 09-15. | MEASURED SQL on `ticker_prices` and `ticker_prices_quarantine` |
| 3 | **Three provider outages are visible but unrepaired.** Finviz elite export has returned 0 rows since 10-02 06:25 (last success 10-01 18:25, about 74 h ago). Alpha Vantage last succeeded 09-21; `fundamental_data` is 13 days old against a 192 h window. YouTube API is in `error` (HTTP 429, 20:02 tonight) and the cookie check is RED, with the alert suppressed to P1_DIGEST. | MEASURED `data_source_health`; `RT/data_source_health_last_run.json` (`off 3: alpha_vantage, finviz, youtube_api`); `LOGS/finviz_health_check.log`; `LOGS/youtube_cookie_health.log` |
| 4 | **The Schwab NASDAQ_BOOK stream misses every other regular session.** There are 0 book rows between 10:00 and 16:00 on 09-29 and 10-01. The daemon runs about 24 h, so the next 09:31 cron start loses the flock, and the old process then exits at about 09:31. | MEASURED SQL on `schwab_stream_book`, grouped by day and hour; crontab line 506 (`flock -n /tmp/schwab_stream.lock`) |
| 5 | **The CIO event bus hash chain is intact after the re-chain.** 13,394 records, 8,310 carry `rechain{}`, 0 `prev_hash` link breaks. The archive sha256 verifies. | MEASURED: python prev_hash walk over `CIO/cio_events.jsonl`; `sha256sum -c` in `archive/cio_event_bus_fork_20261004` |
| 6 | **Retirement is still incomplete, and the moomoo registry row has drifted further.** The 4 retired keys are still rendered into the tmpfs env. moomoo is still `service_down` with scope "positions" while live OpenD is `ok:true` and is now used for L2 quotes. | MEASURED `grep -c '^FINNHUB_API_KEY='` etc. on `/run/user/1000/tradeai/env` → 1 each; `config/data_source_authority.json` providers.moomoo |

---

## A1 · The market / reference data point

### (a) Purpose, actors, stores
- **Purpose** (unchanged). Every value carries `as_of`, age and stale/gap state from one declared store and one writer. When a value is stale or missing, a budgeted chain of resolution steps should fetch it.
- **Actors.**
  - Cron producers (478 active crontab lines, 1,071 total). MEASURED `crontab -l | grep -cv '^#'`.
  - `report_source` hooks.
  - Writers in `scripts/lib/writers/*`.
  - Validation timers: `tradeai-data-plausibility` 06:20, `tradeai-source-litmus` Tue–Sat 07:45, `tradeai-eod-consolidated-close` 17:15, `tradeai-finviz-view-contracts` 06:05, `tradeai-data-source-health` `*:27`, `tradeai-gap-resolution` `*:07,37`. MEASURED `systemctl --user list-timers`.
  - Resolver paths: `data_gap_resolver.py` cron (lines 140, 155, 174) now wired into `gap_resolver.resolve` (commit 5f6568f08, DOCUMENTED), and the desk resolver.
- **Stores.** The registry now declares **49 domains** (09-14: 26), 22 providers. MEASURED `check_data_source_authority.py` → `domains=49 providers=22 findings=0`. The 23 new domains are cognition/supervisor stores (cogx W1–W5), not market data. Market-data stores are unchanged: `market_quotes`, `ticker_prices`, `symbol_profiles`, `fundamental_data`, `fred_economic_series`, `options_iv_history`, … The order-book stores **`schwab_stream_book` / `schwab_stream_quotes` and moomoo L2 are not declared as domains**. MEASURED: no domain in the registry names them; `schwab_stream` appears only as a backup for `quote_price` (`config/data_source_authority.json:497`).

### (b) State machines
- **Health row** (B1): unchanged code. `report_source` is still UPDATE-only. MEASURED `scripts/lib/data_source_report.py:82,91`: UPDATE, no INSERT/ON CONFLICT. There are still 18 rows, with no row for alpaca, schwab, yfinance, moomoo, searxng or schwab_stream.
  - Stored values now: healthy 12 · error 4 (alpha_vantage, finnhub, polygon, youtube_api) · degraded 1 (finviz) · unknown 2 (fmp, newsapi). MEASURED `select * from data_source_health`.
  - Effective audit: checked 18, off 3 (`error:alpha_vantage`, `error:finviz`, `error:youtube_api`), decayed 1 (`research_discovery`). MEASURED `RT/data_source_health_last_run.json` 00:27Z. The audit excludes retired finnhub and polygon from "off" (09-14: they counted).
- **Envelope** (B2): unchanged. MEASURED `GET /api/v2/agents/summary` 200 in 56 ms: `watchlist_agent_results` stale:false, age 27.3 h; `agent_debate_log` stale:true, age 3,662 h, `gap.kind=no_producer`.
- **Plausibility result** (B3): the timer now fires daily. MEASURED `RT/data_plausibility_last_run.json` `ran_at 2026-10-04T10:21Z`. Results: checked 12, off 8 BLOCK (09-14 manual run: 7/11). It still has no transition to quarantine. MEASURED same 12 contracts in `config/data_plausibility_contracts.json`, **none on `ticker_prices` or `market_quotes`**.
- **Litmus** (new since 09-14): `SourceLitmusReport@v1`, BLOCK when >2 % of a source's closes are off by more than 10 %. Last run 10-03 11:46Z, session 10-02. MEASURED `RT/source_litmus_last_run.json`:

  | Source | Result |
  |---|---|
  | finviz | BLOCK, 1/40 badly off (2.5 %) |
  | market_quotes | 35/112 off >1 %, 1 badly off (0.9 %) |
  | portfolio_repricer | 19/20 within 1 % |
  | yfinance_eod | `not_independent` 40 |

  What a BLOCK does downstream is DOCUMENTED only: "BLOCK a source" in the As-Is 09-14 update. No consumer refusal was observed.
- **EOD consolidated close** (new): last run 10-02 21:17Z, mode apply. MEASURED `RT/eod_consolidated_close_sync_last_run.json`: stored 5,342, replaced 1,420, held back 9, no_reference 2,810, rejected 0.
- **Quarantine** (B4): unchanged, last 2026-08-27, 92 rows. MEASURED.
- **Gap queue** (B5): `gap_hook.enqueue_gap` still has **0 callers**, and `CIO/gap_queue.jsonl` is absent. MEASURED `grep -rn "enqueue_gap(" scripts` (definition only); `ls`.
- **Resolver attempt** (B6): **ARMED** through the host file `~/.config/tradeai/gap_resolver_live` (2026-09-20). MEASURED `ls -la`; code `scripts/lib/gap_resolver.py:149-152,259`.
  - Receipts: 8,339 from 09-14 to 10-04 12:00Z. Outcomes: budget_denied 7,621 · partial 407 · no_answer 255 · queued 28 · error 19 · dry_run 5 · **answered 4**. MEASURED.
  - Requester: `data_gap_resolver` 7,591 of the budget_denied.
  - Domains: catalyst_news 8,227 · research_thesis 78 · analyst_opinion 12 · quote_price 12 · technicals 6.
- **Research gap** (B7): 129 rows, 128 ids. OPEN 118 (`all_stale` 86, `unresolved_after_free` 32) · LLM_ELIGIBLE_NOT_AUTHORIZED 10 · **RESOLVED_* 0**. MEASURED `CIO/research_gaps.jsonl`, last write 10-02 14:14Z. The SearXNG guard is still present. MEASURED `scripts/lib/cio_intelligence_fabric.py:1116` `ff.get("used") != "SEARXNG"`.
- **DB gap registry** (B8): rows written again after 4 months idle. Since 09-01: detector `cio_operator_desk`, resolved 10 (`gap_resolver_v2`, all with `resolution_data`) and abandoned 3. Newest detection 10-03 17:38, newest resolution 10-04 08:00. Cycle time p50 2.2 h, p90 14.4 h (n=10). MEASURED SQL.

### (c) Flow (deltas marked ●)
```
PROVIDER ─cron─▶ COLLECTOR ─report_source (UPDATE-only)─▶ data_source_health (18 rows; alpaca/schwab/moomoo none)
   │                                           └─hourly :27 decay ─▶ alert (● AV alert fired 10-04, DOCUMENTED 2bf2d458b)
   ▼
WRITER (repricer guard #1008 holds: 0 repricer >50 % jumps since 09-15 ●)
   ▼
STORE ──● litmus Tue–Sat 07:45 (BLOCK finviz 10-03) ── ● EOD close 17:15 (1,420 replaced 10-02)
   │   ──● plausibility 06:20 fires daily (8/12 BLOCK; no price contract) ✗✗▶ quarantine (last 08-27)
   ▼
ENVELOPE (177 hub direct reads, unchanged) ── enqueue_gap ✗✗ 0 callers
   │
   ├─ desk gap ─▶ gap_resolver (● armed) ─▶ receipts 8,339 ─▶ answered 4 / budget_denied 7,621
   ├─ data_gap_resolver cron 10-16 ─● chain resolve ─▶ data_gap_registry resolved 10 (v2)
   └─ cio_material_scan ─▶ research_gaps OPEN 118 ─ free-first ─✗ 0 RESOLVED
REFRESH ╌╌▶ refresh_producer vector: budget_denied 53 / no_answer 42 in 7 d; never answered
```

### (d) Iterations
| Loop | Closes now? | Evidence |
|---|---|---|
| Collector → store | YES for most domains. **NO** for fundamentals (AV) and Finviz elite views since 10-02; YouTube is partial | §A2 table |
| Health → decay → alert | YES, alert fires. Repair is manual (AV fixed same day in 2bf2d458b, unproven until Mon 10-05 08:00) | MEASURED `RT/data_source_health_last_run.json`; DOCUMENTED commit |
| Plausibility → quarantine | **NO.** The timer fires; nothing acts on 8 BLOCKs | MEASURED |
| Litmus / EOD → store | YES (EOD replaces >1 % off closes); litmus BLOCK has no observed consumer | MEASURED |
| Envelope stale → gap_hook | **NO**, 0 callers | MEASURED |
| Resolver chain → answer | **REPLAYS.** It runs every hour on weekdays; 91 % budget_denied; 0 answers since 09-23 | MEASURED receipts |
| Research gaps → RESOLVED_FREE | **NO.** 0 of 128; `unresolved_after_free` grew from 2 to 32 | MEASURED |
| data_gap_registry → resolve | YES, small: 10 resolved since 09-23 | MEASURED |

### (e) Questions (changes only)
- "Did this source succeed?": still dropped for unseeded providers (alpaca, schwab, moomoo). Now answered and alerted for AV, Finviz and YouTube. MEASURED.
- "Is this close plausible?": now asked daily by litmus and EOD against Yahoo, and at write time by the repricer guard. Still not asked of `market_quotes` at write time: 123 >50 % day-over-day jumps from market_quotes-sourced closes since 09-15. Most look like microcap and reverse-split moves (e.g. LGHL 0.41→4.10, SHFS 0.12→1.17), which is INFERRED; there is no split check. MEASURED SQL `lag()` over `ticker_prices`.
- "Can a cheaper vector answer this?": now asked about 400 times a day at peak (09-23/24), and answered 4 times. MEASURED.

### (f) Measurements
- **Throughput, last 7 calendar days** (MEASURED SQL):

  | Store | Weekday volume | Weekend volume |
  |---|---|---|
  | market_quotes | 92k–108k/day, 99 % alpaca (10-02: alpaca 96,909 / yfinance 605 / finviz 26) | 333–347 (Sat/Sun) |
  | ticker_prices | about 5.4k/day | — |

  09-14 recorded 1.1–1.3 M/day for market_quotes. The drop dates from 09-15 (09-22 was 1.02 M). The cause was not determined (BLOCKED: no writer-change commit found on `market_quotes_writer.py`; possibly retention).
- **Weekend-dated closes are still written.** `ticker_prices` holds finviz 61+61 rows dated Sat/Sun 09-26/27, and 63 rows dated Sun 10-04 created at 07:30–20:xx today. Three of the 10-04 rows jump more than 50 % (XCUR 1.15→1.78, ELAB 3.36→1.40, LGPS 0.73→1.19). The writer was not identified: `price_db_sync` is weekday-only (crontab:198). MEASURED SQL; writer BLOCKED.
- **Store freshness** (MEASURED SQL):

  | Store | Newest data |
  |---|---|
  | fred | 10-04 06:15 |
  | yahoo_analyst_targets_history | 10-04 20:38 |
  | symbol_profiles | 10-04 19:00 |
  | news_articles | 10-04 20:02 (15,408 in 7 d) |
  | hermes_research_intelligence | 10-04 18:10 (1,053 in 7 d) |
  | options_iv_history | 10-02 15:45 (111 in 7 d) |
  | sector_rs_daily | 10-02 |
  | market_regime | 10-02 16:05 |
  | dividends | 10-02 07:05 |
  | **fundamental_data** | **09-21 08:00** (13 d; window 192 h → stale) |
  | watch_candidate_events | 07-16 (dead) |
  | ai_reports | 08-02 (dead) |
  | agent_debate_log | 05-05 (dead) |
- **Coverage** (09-14 → now):
  - Health rows for primary providers: unchanged (alpaca, schwab, yfinance still absent).
  - Plausibility contracts on market-data stores: 0, unchanged.
  - Independent price check: 0 → 1 (litmus + EOD).
  - Hub direct reads: 177 → **177**. MEASURED gate output, `data_source_authority_baseline.json` `direct_reads: 177`.
  - Domains whose gap loop has closed at least once: 0 → 1 (quote_price: 4 answered on 09-23).
- **Failure rates.**
  - Health off: 3/18 (17 %; 09-14: 22 %).
  - Plausibility BLOCK: 8/12 (67 %; 09-14: 64 %).
  - Resolver answered: 4/8,339 (0.05 %).
  - Research-gap closure: 0/128.

### (g) Failure paths now
1. The resolver spends its turns being refused. 91 % budget_denied, mostly `data_gap_resolver` on catalyst_news during 09-23–25. The refusal is recorded but does not change the next run's selection (INFERRED from repeated requester/domain counts).
2. A quarantine lane still does not exist. Corrupt rows were fixed by overwrite (INFERRED: EOD replace or repricer re-run), which leaves no audit trail of the bad value in the quarantine table.
3. No plausibility contract covers price stores. `market_quotes` microcap jumps and weekend-dated finviz rows enter `ticker_prices` unchecked.
4. The health ledger is still blind to alpaca, schwab, moomoo and Schwab-stream. The stream's alternating-day outage (§A2) raised no health signal.
5. `enqueue_gap` still has 0 callers. Stale envelopes never become gaps.

### (h) Maturity per stage
| Stage | 09-14 | Now | One-line evidence |
|---|---|---|---|
| Collect | L2 | **L2** | Declared cadences run; Finviz/AV outages persist ≥3 d (MEASURED health rows) |
| Liveness | L1 | **L2** | fred/yahoo/sec/brave/youtube hooks proven and reporting today; still UPDATE-only, unseeded providers blind (MEASURED) |
| Decay view | L3 | L3 | Hourly audit, off 3, decayed list (MEASURED `RT/data_source_health_last_run.json`) |
| Single writer | L2 | L2 | Gate `findings=0`, 49/49 grants (MEASURED) |
| Plausibility | L1→L3 (prices, after #1008) | **L3 prices / L1 contracts** | Litmus and EOD run and replace; 12 contracts, 8 BLOCK, no action (MEASURED) |
| Quarantine | L0 | **L0** | Max 08-27; corrupt rows overwritten, not archived (MEASURED) |
| Projection | L3 | L3 | Envelope live; 177 direct reads (MEASURED) |
| Gap detect | L2 | L2 | 118 OPEN_NO_ATTEMPT detected; hook unused (MEASURED) |
| Gap resolve | L0 | **L1** | Armed; 8,339 receipts with provenance; 4 answered (MEASURED) |
| Refresh | L0 | L0 | `refresh_producer` never answered (MEASURED receipts) |

### (i) Target / exit
The 09-14 exits remain valid. Progress against each:

| Exit | Status |
|---|---|
| `gap_resolution_receipts.jsonl` exists | **MET** |
| ≥1 answered receipt | **MET** (4) |
| Plausibility `LastTriggerUSec` non-empty | **MET** |
| `research_gaps` RESOLVED_FREE > 0 | open |
| Quarantine row within 24 h of a refusal | open |
| alpaca/schwab/yfinance health rows | open |
| DIRECT_READ 177 → 0 | open |

New exits:
- budget_denied share below 50 % over 7 days.
- A price contract on `ticker_prices.close_price` with a split check.
- No weekend-dated rows written after Sun 10-04.

---

## A2 · A data source (provider), including the data plane

### (a) Purpose, actors, stores
Unchanged: registry `config/data_source_authority.json` (`DataSourceAuthority@v2`), CI gate, `retired_providers.py`, health ledger, SM render to `/run/user/1000/tradeai/env`. The registry has had 17 commits since 09-14, all domain additions or approval citations (e.g. #1402, #1419, #1425). MEASURED `git log --since=2026-09-14 -- config/data_source_authority.json | wc -l`.

### (b) State machine — `providers[].status`
| Status | Count | Notes |
|---|---|---|
| active | 13 | |
| active_paid | 1 | brave |
| active_metered | 1 | deepseek |
| configured_unused | 1 | tavily |
| service_down | 1 | moomoo |
| no_api_manual | 1 | fidelity |
| retired | 4 | finnhub, fmp, newsapi, polygon |

MEASURED python over the registry. **Identical to 09-14.**

### (c) Flow
Unchanged from 09-14 except that the authority gate now passes with `domains=49/49` (MEASURED). The missing edges are still missing:
- degraded → registry: moomoo `service_down` vs live `ok:true`.
- retired → keys removed.
- the gate does not scan `config/`: `agent_discovery_config.json:43` still lists fmp/finnhub/polygon; `agents_data_sources.yaml:9,38,39,82` still lists finnhub and fmp. MEASURED grep.

### (c2) Data plane per provider (new table)
| Provider / feed | Registry | Health row | Last good | State now | Evidence |
|---|---|---|---|---|---|
| Alpaca quotes (`quote_price` primary) | active | **none** | 10-02 (96,909 rows) | OK for a weekend | MEASURED SQL by `source` |
| Finviz elite export (screens, movers) | active | degraded, fail_count 6, "cookie may be expired" | 10-01 18:25 | **DOWN.** 5 consecutive `DEGRADED: 0 rows` probes on 10-02. `finviz_market_movers` logged 44/44 runs with `most_active: 0 rows` while printing `snapshot: 10/10 signals` (false green) | MEASURED `LOGS/finviz_health_check.log`, `LOGS/finviz_market_movers.log` |
| Finviz screener runner / group perf | active | (shares finviz row) | 10-02 10:32; group perf 155 rows/day through 10-02 | Partial: the screener still returned rows on 10-02 (INFERRED: a different auth path) | MEASURED `LOGS/finviz_screener.log`, `finviz_group_performance` |
| Finviz view contracts | — | — | 10-02 06:06, block 0, warn "market_quotes not reachable" | The cross-check was skipped | MEASURED `RT/finviz_view_contracts_last_run.json` |
| Alpha Vantage (fundamentals, Mon 08:00) | active | error, burst-limit text | 09-21 08:00 | **Fix merged, unproven.** 2bf2d458b paces calls at 1.5 s with one 5 s back-off and excludes ETFs/funds; first run Mon 10-05 08:00. The 09-28 run refused BND/CSWC/DIV/JEPI/LDOS | MEASURED log `LOGS/market_data.log` lines 127-130; DOCUMENTED commit 2bf2d458b |
| YouTube Data API (`symbol_enrichment.py:421`) | — | error, HTTP 429, fail_count 10 | 10-04 20:01 | Flapping: success at 20:01, 429 at 20:02. A 429 cooldown file exists, `until` 2026-09-28 19:31 (expired) | MEASURED health row; `RT/youtube_429_cooldown.json` |
| YouTube transcripts (cookie path) | — | — | 10-02, 19 transcripts | Ingest healthy (11–30/day). **Cookie check RED** (0 auth cookies) on 5 of 8 logged runs; alert `Suppressed (P1_DIGEST)` | MEASURED `youtube_transcripts` SQL; `LOGS/youtube_cookie_health.log` |
| Schwab stream (L1 + NASDAQ_BOOK) | backup for quote_price only | **none** | 10-02 23:59 | 12 symbols, 5 levels confirmed. **Regular-session rows 0 on 09-29 and 10-01** (flock collision with a ~24 h run). Table retention begins 09-28 | MEASURED `schwab_stream_book` (`max(jsonb_array_length(bid_levels))=5`, `count(distinct symbol)=12`); crontab:506 |
| moomoo OpenD (quotes, L2) | **service_down**, scope "positions" | **none** (own JSON) | probe 10-02 21:55 `ok:true`, `snapshot ok` | Running. 60-level L2 depth "proven live 2026-10-04" is **DOCUMENTED only**: commit d7521b17d. No alert journal on disk yet (shadow mode, market closed) | MEASURED `RT/moomoo_opend_health.json`, `systemctl --user` unit active; DOCUMENTED d7521b17d |
| FRED | active | healthy 10-04 06:15 | today | OK (09-14: `unknown`; hook proven) | MEASURED |
| Yahoo / yfinance | active | yahoo_finance healthy 10-04 06:17; yfinance none | today | OK. Litmus reference worked 10-03 | MEASURED |
| SEC EDGAR | active | healthy 10-04 20:02 | today | New `sec_filing` material-change kind (8 rows) | MEASURED |
| Brave | active_paid | healthy 18:45 | today | OK | MEASURED |
| finnhub / polygon / fmp / newsapi | retired | error / error / unknown / unknown | — | Rows not retired. **Keys still rendered** (`grep -c` = 1 each in env; 2 each in manifest) | MEASURED |

### (d) Iterations / (e) Questions
- Health → alert → human fix: fires. The AV alert of 10-04 produced 2bf2d458b the same day (DOCUMENTED).
- Health → registry: still no loop (moomoo).
- "Should this key still exist?": still asked by nobody.
- New dropped question: **"Is this provider approved for what we now use it for?"** moomoo is scoped "may supply: positions" but now feeds L2 book and tape to Active Trader alerts. The gate checks the grant, not the scope (INFERRED from gate output `findings=0`).

### (f) Measurements
- Providers by status: identical to 09-14.
- Health off: 3/18.
- Retired-provider rows still present: 4.
- Retired keys rendered: 4/4.
- Days since retirement: 21.
- Outage age at measurement:

  | Feed | Hours without a good fetch |
  |---|---|
  | Finviz elite | ~74 |
  | Alpha Vantage | ~324 |
  | YouTube API | intermittent |

### (g) Failure paths
1. **Cookie-based feeds expire silently or semi-silently.** Finviz and YouTube are both cookie-gated. YouTube RED is suppressed to the digest. Finviz movers print success with 0 rows.
2. **The registry scope does not track the data-plane reality** (moomoo L2, Schwab book not declared).
3. **Retired keys remain live** (unchanged since 09-13).
4. **Health stays blind on the order-book feeds.** The alternating-day Schwab book gap went unalerted.

### (h) Maturity per stage
| Stage | 09-14 | Now | Evidence |
|---|---|---|---|
| Proposal + grant | L3 | L3 | 49/49 grants (MEASURED gate) |
| Registry / render | L3 | L3 | 17 commits, gate green |
| Gate | L3 | L3 | build-time; config not scanned (MEASURED grep) |
| Active health | L1–L2 | **L2** | 3 outages detected and alerted; order-book feeds unmonitored |
| Degraded → registry | L0 | L0 | moomoo drift unchanged |
| Retirement (code) | L2 | L2 | 0 retired call sites in scripts |
| Retirement (ledger, config, secrets) | L0 | L0 | keys rendered, rows present |

### (i) Target / exit
The 09-14 exits are all still open. Add:
- `finviz` healthy within 24 h of a cookie refresh, with movers failing loudly on 0 rows.
- An `alpha_vantage` success on Mon 10-05 08:00 and `fundamental_data` max ≥ 10-05.
- Schwab book regular-session rows > 0 every weekday.
- Registry domains for `order_book` (moomoo primary, schwab_stream comparison) and a moomoo scope update approved by the operator.

---

## A3 · Identity (mention → subject_guid)

### (a) Purpose, actors, stores
Unchanged actors. New since 09-14:
- A weekly CUSIP sweep: `sweep_schwab_instruments.py --apply`, Sat 03:30. MEASURED crontab:940; `RT/schwab_instrument_evidence.json` mtime 10-03 03:30.
- Company-name binding for operator text, "bind operator company names in any case" (b4495901b, DOCUMENTED).
- Identity stamping at the publish chokepoint (3e647b793, DOCUMENTED).
- Lineage causation ids (4f9c2fa88, DOCUMENTED).

Registry: `RT/identity_registry.json`, `updated_at` 2026-10-02T09:50Z.

### (b) State machine
Unchanged ranks and transitions.

Entities now: **10,903**. UNRESOLVED_WITH_REASON 5,589 (51.3 %) · CONFIRMED 5,292 (48.5 %) · CANDIDATE 22. Active 5,622. Superseded 5,281 (08-27: 5,002 · **09-21: 183 · 09-28: 96**). MEASURED python over the registry. `RT/identity_health_state.json` agrees: confirmed 5,292 / 10,903 at 00:39Z.

### (c) Flow
As 09-14, plus the weekly CUSIP sweep feeding mint and supersede. That supersede edge **now fires**: 279 supersedes after 08-27.

### (d) Iterations
| Loop | Closes? | Evidence |
|---|---|---|
| Row sweep (*/30) | **Replays.** Latest run: catalyst 1,073 · news 1,328 · research_insights 1,451 unresolved; rows_stamped 0–8 | MEASURED `LOGS/identity_sweep.log` tail |
| Registry mint (weekdays 05:50) | Adds +5 (10,898 → 10,903) | MEASURED `LOGS/mint_identity_registry.log` |
| CANDIDATE/UNRESOLVED → CONFIRMED via CUSIP | **YES, weekly.** CONFIRMED +278 since 09-14 | MEASURED |
| Mention role decision | NO. `document_mentions` role_source: deterministic 327,373; model 0; operator 0 | MEASURED SQL |
| Inbound quarantine replay | NO. 27 rows `inbound_persist_failed`, resolved=false, 09-08 17:07–18:32 | MEASURED SQL |

### (e) Questions
- "Which company is this?" (inbound): the name path exists now (DOCUMENTED b4495901b). Yet operator turns are mostly NULL identity: 492 of 676 operator turns overall, and **167 of 193 turns in the last 7 days** are NULL. MEASURED SQL on `operator_conversation_turns`. Whether NULL means "no subject in the turn" or "tag not computed" is not distinguishable from the row (INFERRED gap in honesty).
- Unresolved escalation: still asked of nobody.

### (f) Measurements
- `news_articles`: CONFIRMED 97,398 · UNRESOLVABLE 27,036 · UNRESOLVED_WITH_REASON 5,582 · NULL 0. MEASURED.
- `document_mentions`: 327k rows (09-14: 214k+).
- Inbound quarantine: 27, age 26 days.

### (g) Failure paths
1. The unresolved re-scan still burns cycles without back-off: about 3,900 symbols re-read every 30 min across tables, about 0 stamped.
2. No model or operator role decider exists.
3. The quarantine has no replay; age is now 26 d.
4. NULL identity on 87 % of recent operator turns.

### (h) Maturity per stage
| Stage | 09-14 | Now | Evidence |
|---|---|---|---|
| Tagging | L3 | L3 | Deterministic; chokepoint stamping added (DOCUMENTED) |
| Registry resolution | L2 | L2 | Mint +5/run (MEASURED) |
| Supersede chain | L2 | **L3** | Recurring weekly CUSIP sweep; supersedes on 09-21 and 09-28 (MEASURED) |
| Mention roles | L1 | L1 | model 0 (MEASURED) |
| Escalation of unresolved | L0 | L0 | No back-off or escalation (MEASURED log) |
| Inbound quarantine | L1 | L1 | 27 unresolved (MEASURED) |

### (i) Target / exit
**MET:** "CONFIRMED count and `superseded_at` max advance past 08-27" (max 09-28T09:50Z).

Still open:
- Unresolved per run falls.
- `role_source=model` > 0.
- 27 quarantine rows resolved.

New exit: operator turns carry an explicit `identity_status` (UNRESOLVED_WITH_REASON with a reason) instead of NULL.

---

## A4 · Material change

### (a) Purpose, actors, stores
Actors are the same, plus:
- Notice v2: "page only what you can act on, one daily digest" (13f35ffcd, DOCUMENTED). Digest cron is 16:15 daily (crontab:1050).
- SEC filings → `material_changes` kind `sec_filing` (241a2b980, DOCUMENTED).
- DDQ runs under the DeepSeek off-peak gate (`PEAK_SKIP` lines; crontab:1016).

The **selection feed now lives in persistent state**: `CURRENT/data/persistent_wake` → `~/trade-ai-state/persistent_wake`. MEASURED `readlink -f`. FEED_META `written_at_utc` 2026-10-05T00:55Z.

### (b) State machine
New terminal values: `DIGEST_SENT`, `DIGEST_NOT_DELIVERED`.

| notify_outcome (all rows) | Count |
|---|---|
| SENT | 544 |
| DIGEST_SENT | 284 |
| DIGEST_NOT_DELIVERED | 103 |
| UNCORROBORATED_CORRUPT_SOURCE | 6 |
| NULL | 4 |

MEASURED SQL. The "aged out" state is still unlabelled. 4 rows: PSQL, EIX (09-07), and SDST ×2 (created 09-17, observed 07-31). MEASURED.

### (c) Flow
```
detector */30 ─▶ corroborate ─(uncorroborated: ACII, DNP, IFBD — dropped ✗✗)─▶ material_changes (941)
   ─▶ notify 7-59/15: PAGE (rare) | DIGEST 16:15 ─▶ "Not shown: stale quote" ─▶ DIGEST_NOT_DELIVERED
   ─▶ DDQ */20 (off-peak only) ─▶ questioned 614/941
   ─▶ wake_selection_feed :55 ─▶ persistent_wake (● persistent) ─▶ wake
```

### (d) Iterations
| Loop | Closes? | Evidence |
|---|---|---|
| Detect | YES. 353 rows in 7 d; 9–72/day | MEASURED |
| Notify | YES, by design, through the digest. Created→notified p50 is now 3.5–20 h (news_burst p50 915 min), against 15 min on 09-14; this is the intended page→digest change | MEASURED percentile SQL |
| Not-delivered | **103/353 (29 %)** in 7 d are DIGEST_NOT_DELIVERED with `notified_at` NULL. The digest hides names whose quote is "too old". The quote age comes from `watchlist_items.last_enriched_at` (`notify_material_change.py:361-372`), not `market_quotes`. Example: TSLA digest "quote 9.2d old" while `market_quotes` TSLA was 10-02 16:30. 53/170 active watchlist items are older than 72 h | MEASURED SQL and code read |
| Corroboration → quarantine | NO. The refusal set changed (the 6 corrupt symbols cleared after the overwrite); the current refusals are still dropped | MEASURED log |
| Question | PARTIAL. 614/941 (65 %; 09-14: 87 %) | MEASURED |

### (e) Questions
New dropped question: **"Is the quote really old, or is our projection stale?"** The digest suppresses on a projection age and never checks the store of record.

### (f) Measurements
- Rows: 941 (09-14: 256).
- By kind: news_burst 568 · price_excursion 151 · sector_move 108 · catalyst_new 106 · sec_filing 8.
- Detection lag p50: catalyst 6.0 h · news 2.8 h · price 15.0 h · sector 15.0 h · sec_filing 531 h (backfill).
- Unlabelled aged rows: 4.

### (g) Failure paths
1. Projection staleness (`watchlist_items`) causes 29 % non-delivery.
2. Corroboration refusals are still discarded.
3. Aged-out rows are still unlabelled.
4. DDQ coverage fell (off-peak gating).

### (h) Maturity per stage
| Stage | 09-14 | Now | Evidence |
|---|---|---|---|
| Detect | L3 | L3 | Corroborated, new SEC kind (MEASURED) |
| Corroboration feedback | L0 | L0 | Refusals dropped (MEASURED log) |
| Notify | L4 fresh / L1 aged | **L3** | Digest delivers with honest NOT_DELIVERED labels, but 29 % are hidden on a stale projection (MEASURED) |
| Question | L2 | L2 | 65 % questioned (MEASURED) |
| Feed / wake | L2 | **L3** | Feed on persistent state, written hourly (MEASURED readlink and FEED_META) |

### (i) Target / exit
**MET:** feed under persistent state.

Still open:
- AGED_OUT label.
- Refusal → quarantine.

New exits:
- Digest quote age taken from `market_quotes` (or the envelope), so DIGEST_NOT_DELIVERED falls below 5 %.
- DDQ questioned share ≥ 85 %.

---

## A5 · Served copy / persistent state (new chapter)

### (a) Purpose, actors, stores
- **Purpose.** Every append-only or authoritative store has exactly one physical copy that both the dev tree (where cron runs) and CURRENT (what is served) resolve to.
- **Actors.**
  - `scripts/check_served_copy_split.py` (receipt `RT/served_copy_split_last_run.json`; archive tripwire).
  - Promote (links `served_from.linked_dirs`).
  - `scripts/repair_cio_event_bus_fork.py` (new, operator-approved, dry-run default).
- **Stores.** `PS/data/{runtime,cio,portfolios}`, `PS/logs`, `~/trade-ai-state/persistent_wake`, `CIO/cio_events.jsonl`.

### (b) State machine
- Per directory: `LINKED` | split.
- Event bus: `verify_integrity` pass/fail. The repair writes an archive (byte-for-byte + sha256) and then rechains in place.

### (c)–(f) Measurements
- **Split check:** last run 10-04 20:42 EDT, checked 7, split 0. MEASURED receipt.
- **Holdings:** `holdings.json` resolves to one inode (4375507) and one sha (474a4305…) from the dev tree, CURRENT and PS. MEASURED `stat` and `sha256sum`.
- **Logs:** CURRENT/logs → PS/logs. The dev tree `logs/` is a separate real directory, still written by a few jobs (`stale_lock_cleanup.log` newest) and holding stale family-A logs from 09-25. MEASURED `readlink` and `ls -t`. INFERRED risk: a reader of the dev-tree logs sees week-old state. This risk misled the first pass of this measurement.
- **CIO event bus:**
  - The fork at line 2447 (2026-08-26) was re-chained 2026-10-05 00:22Z.
  - The archive `trade-ai-releases/archive/cio_event_bus_fork_20261004/cio_events.pre-rechain-20261005T002229.jsonl` (8.3 MB) verifies against its sha256.
  - The live file has 13,394 records, 8,310 re-linked and **0 prev_hash breaks**. 30 events appended after the repair chain cleanly.
  - MEASURED python walk and `sha256sum -c`. Re-hash correctness (recomputing `event_hash`) was not re-verified: DOCUMENTED in 1939edcb8 as "verifies".
- **Holdings truth:**

  | Field / store | Value |
  |---|---|
  | `last_repriced` | 10-04 20:30 ET |
  | `positions_built_at` | 09-29 15:15 ET |
  | `data_as_of` | **2026-09-28** (account `moomoo_taxable_live`) |
  | `account_summaries.schwab_rollover_ira` as_of / last_sync | 2026-07-17 (metadata stale; value present) |
  | `schwab_positions_live` | 51 rows, max 10-02 16:33 |
  | `position_share_drift` | 1 open (10-02), 11 reconciled |

  MEASURED file fields and SQL.

### (g) Failure paths
1. Per-account freshness metadata in `holdings.json` is stale or contradictory: an account `data_as_of` of 6 days, and a 07-17 `last_sync` on the largest account. A consumer cannot tell which account is fresh.
2. The two log trees diverge.
3. The bus repair was a one-shot. A future fork is detected by the gate but not prevented (INFERRED; root cause of the 08-26 fork not stated in the commit).

### (h) Maturity per stage
| Stage | Level | Evidence |
|---|---|---|
| Single copy (linking) | L3 | 7/7 linked; gate with archive tripwire (MEASURED) |
| Divergence detection | L3 | Hourly-or-better receipt (MEASURED mtime 20:42) |
| Repair | L2 | Operator-approved tool, archive + sha, verified once (MEASURED/DOCUMENTED) |
| Freshness metadata (holdings) | L1 | Stale per-account stamps (MEASURED) |

### (i) Target / exit
- Dev-tree `logs/` linked to PS/logs, or archived with a tripwire.
- `account_summaries[*]` carry a truthful per-account `as_of`.
- The bus `verify_integrity` runs on a schedule with a receipt.

---

## Family A score

| Lifecycle | Mean stage level 09-14 (after #1008) | Mean now | Terminal / feedback stage |
|---|---|---|---|
| A1 Data point | 1.6 | **1.8** | quarantine L0 · refresh L0 |
| A2 Provider | 1.8 | **1.9** | degraded→registry L0 · key retire L0 |
| A3 Identity | 1.5 | **1.7** | escalation L0 |
| A4 Material change | 2.2 | **2.2** | corroboration feedback L0 |
| A5 Served copy | — (not scored) | 2.3 | — |
| **Family A (A1–A4)** | **≈1.8** | **≈1.9 / 5** | **Terminal-gated: L0 → L0.** Every lifecycle still has an L0 terminal or feedback stage |

INFERRED: the means are simple averages of the per-stage tables above. By the house rule ("a lifecycle is only as mature as its terminal stage"), family A is still **L0**, as on 09-14.

## Top 5 risks
1. **Corrupt or implausible prices have no quarantine and no price contract.** 123 market_quotes-sourced >50 % jumps and weekend-dated finviz rows (3 of them >50 % jumps on Sun 10-04) enter `ticker_prices`, which feeds technicals, RSI, stops and the detector baselines. MEASURED.
2. **Cookie-gated providers fail quietly.** Finviz elite has been down about 74 h, with movers printing "10/10 signals" on 0 rows. The YouTube cookie RED was suppressed to the digest. MEASURED.
3. **The order-book data plane is undeclared and unmonitored.** Schwab NASDAQ_BOOK missed 2 of 5 regular sessions last week. moomoo L2 is used outside its registry scope with no health row. Active Trader alerts depend on both. MEASURED.
4. **The resolver is armed but starved.** 91 % budget_denied, 0 answers in 11 days, 0 research gaps ever resolved. It creates the appearance of a working loop. MEASURED.
5. **Retired provider keys are still rendered into the runtime env** 21 days after retirement, in a repo with keys in git history. MEASURED.

## Top 5 recommendations
1. Add a `ticker_prices.close_price` plausibility contract with a split/reverse-split check and an independent-source check. Wire litmus BLOCK, plausibility BLOCK and detector `uncorroborated` into a scheduled `quarantine_price_spikes.py --apply`, and refuse weekend-dated writes at the writer. Exit: a quarantine row within 24 h of a refusal; 0 weekend-dated rows.
2. Make zero-row results fail loudly. Have `finviz_market_movers` exit non-zero on all-zero signals, un-suppress YouTube cookie RED, and add a cookie-age probe for Finviz. Exit: Finviz healthy within 24 h of a cookie refresh. Verify the AV fix on Mon 10-05 08:00 (`fundamental_data` max ≥ 10-05).
3. Declare `order_book` as a domain (moomoo primary, schwab_stream comparison); seed health rows for alpaca, schwab, schwab_stream and moomoo (make `report_source` an upsert); fix the Schwab stream flock collision (stop at 16:05 or use a systemd service). Exit: weekday regular-session book rows > 0 every day; moomoo registry scope and status match reality, with the operator approving the scope change.
4. Make the resolver budget-aware. Skip domains and vectors whose last N receipts were `budget_denied`, prefer free vectors, and accept SearXNG evidence for RESOLVED_FREE (or record why not). Exit: budget_denied < 50 % per 7 d; RESOLVED_FREE > 0.
5. Finish retirement and fix the digest's quote source. Remove the 4 retired keys from SM and the env (operator-only), extend the gate scan to `config/`, and take the digest quote age from `market_quotes` or the envelope. Exit: `grep -c` = 0 for the 4 keys; DIGEST_NOT_DELIVERED < 5 %.

---

## Measurement notes
- **BLOCKED:**
  - The writer of the Sun 10-04 finviz `ticker_prices` rows.
  - The cause of the market_quotes volume drop after 09-14.
  - The recomputation of event hashes on the re-chained bus (only links were checked).
  - The 60-level moomoo depth (no runtime artifact; commit message only).
- **Not re-measured** (carried from 09-14 as context only): document_mentions per-table role splits; Brave ledger details.
- The first log reads used the dev-tree `logs/` directory (stale since 09-25) before switching to `PS/logs`. All figures above come from `PS/logs`.
- Writes made during this measurement: scratchpad `lcA/q.sh`, `lcA/crontab.txt`, `lcA/agents.json`, `lcA/acct.json` (a 404 body), and this file. Nothing was written to the repo, DB, config, crontab or systemd.
