# Ticker Prospectus — backend

```
Status:      DRAFT
as_of:       2026-10-26T17:00:00Z
Measured at: branch feat/prospectus-backend off origin/main 99c44ac87 (not live)
```

Operator 2026-10-26: "Opus for all, Fable for top. [3: $25/day for 3 days] Build everything now. … fully colored
with graphs and everything. PDFs and Word documents besides the HTML version." The binding contract is
`persistent-state/data/coordination/handoffs/prospectus-20261026/CONTRACT.md`. A deviation is recorded next to it in `CONTRACT_CHANGES.md`.

## What it is

One sourced research document per held or watched symbol, versioned. Each version is rendered three ways:

- HTML: self-contained, dark and light, inline SVG charts.
- PDF: WeasyPrint, with matplotlib PNG charts.
- DOCX: python-docx, with the same PNGs.

The model writes the prose sections only. Charts are built from the same house series the facts came from.

A sentence is dropped, and logged in `guard_log`, when either of these is true:

- It carries a number that no supplied fact gives (`cio_ask_research.ungrounded_numbers`).
- It sizes, orders, stops or weights (`strip_behavior_text`). This enforces MBI_BEHAVIOR=0.

## Models and credit

| Process | Model | Credit tier | Per-call hold cap | Daily process cap |
|---|---|---|---|---|
| `prospectus_writer` | `claude-opus-5-5`, effort high, adaptive thinking | `long_form` | $2.00 | $22 |
| `prospectus_writer_premium` | `claude-fable-5-1`, effort high, thinking param omitted | `premium` | $4.00 | $12 |

- **Governed path.** Both processes run only through `llm_consumption.gate_and_generate`. That path uses the DB reservation, the process caps and the promotional credit book.
- **Anthropic only.** Both appear in `anthropic_only_processes`. `configured_plan` skips every other provider. `gate_and_generate` refuses the legacy lane with `ANTHROPIC_CREDIT_UNAVAILABLE` when the credit is not usable. The job then stays queued.
- **Premium fallback.** A premium refusal or invalid output falls back to Opus once. A credit refusal never falls back; it queues.
- **Fable restriction.** Fable is admitted only for `premium_tier_processes`. The transport refuses any other caller with `MODEL_DISABLED`.
- **Credit policy changes** (`config/anthropic_credit_policy.json`):
  - `daily_cap_overrides`: $25 per UTC day from 2026-10-26 up to, but not including, 2026-10-29. After that the $10 base applies again.
  - `renewal`: `one_time` by default. In `monthly` mode each UTC month starts a fresh `monthly_allowance_usd` period. The journal keeps every period.
  - `admin_cost_verification`: presence of `ANTHROPIC_ADMIN_API_KEY` is checked by name only. When the key exists, run `scripts/anthropic_cost_verify.py --apply` to compare the Usage & Cost report with the ledger.
  - All three show on LLM Spend through `anthropic_monitoring.snapshot()["credit_config"]`.
- **Pricing.**
  - Fable 5.1 is $10 input, $12.50 5-minute cache write, $20 1-hour cache write, $0.25 cache read and $50 output per MTok. These values are in all three price configs.
  - Sonnet 5.5 cache read stays at $0.10, which is the official page as fetched 2026-10-26. See `CONTRACT_CHANGES.md`.

## Inputs (house stores only)

Inputs are read from these stores:

| Data | Source |
|---|---|
| Company description, sector, industry, next earnings date | `symbol_profiles` |
| Fundamentals, growth, valuation | Finviz enrichment cache |
| Industry cohort medians for "vs peers" | Same cache, same industry, at least 3 peers |
| One year of daily closes | `daily_bars` |
| Analyst targets | `analyst_detail` |
| Catalysts and news | `catalyst_record` |
| CIO stance, stage and conviction | `cio_prospect` |
| Position | `positions_context`, which reads the position store through `lib.portfolio_positions` |
| Stop levels | `cio_truth.stop_for`, over persisted observations and `stops.json`. This makes no broker call. |

- Accounts appear by **name only**, through `account_display.account_label`.
- Derived numbers are supplied to the model as facts: upside to the mean target, 1-year change, distance to stop, and P/L %.
- Fresh web context comes through the governed `search_router` as caller `prospectus_writer`, class `research`. It is used for holdings only, at 2 searches per holding.
- The job has its own allowance of at most 40 searches per UTC day, tracked in `data/prospectus/search_budget.json`.
- The house has no revenue/EPS time series for charts and no peer list. `revenue_eps_trend` therefore charts the growth rates the house does hold, and "peers" means the industry cohort. The latest two periods of each SEC XBRL statement line (`sec_xbrl`: revenue, operating income, net income, diluted EPS and others) are supplied as cited facts.

## Accuracy rules (audit 2026-10-26)

- **Sessions only.** A price series holds NYSE sessions only (`blocks.is_session`). `ticker_prices` also stores
  Saturday, Sunday and holiday rows, which are quotes copied forward. Return windows are calendar spans: 1W is 7 days,
  1M is 30, 3M is 91, 1Y is 365 and 3Y is 1095. A window starts at the last session on or before that date.
- **Dividends.** `ticker_dividend_data.annual_dividend_per_share` is withheld when it differs by more than 25% from
  what was actually paid in the trailing year. The reference is the fund profile's trailing 12 months, or else the
  `ticker_dividends` ex-dates (`domains.dividend_guard`).
- **Fundamentals.** `fundamental_data` rows carry `fetched_at` as their `as_of`. Rows older than 30 days are withheld,
  and the gap names them.
- **Technical snapshot.** The snapshot's own price is never offered, because the house close is the price of record.
  A zero `target` or `change_pct` is a placeholder and is dropped.
- **Stop fills.** A filled stop is dated by the matching journal sell. `stop_last_known.captured_at` is the time of the
  read snapshot, not the time of the fill.
- **Unmatched sells.** Sells that the round trips do not cover are named in `my_history.unmatched_sells` and in the
  gaps. These are typically lots that arrived by transfer and have no basis.
- **Macro calendar.** The reader takes `MacroCalendar@v1` (`dates.*.events` and `fomc_decisions`). The Fed funds rate
  is read from the house series `DFF`.
- **Fund block (2026-10-27).** The header uses the look-through fund name when the Finviz cache has no company
  name. The fund profile carries the asset class and last reconstitution, distribution growth (annualized, trailing
  year against 2 or 3 years earlier, from `ticker_dividends`) and `book_overlap`: the share of the fund's top-holding
  weight the book already owns, directly or through another held fund. AUM, index, issuer, inception, holdings count
  and premium/discount stay a named gap until the `yfinance_info_snapshot` domain has a producer.
- **Journal accounts.** The FIFO and the position store are matched by canonical account key. A trip counts as
  stopped out when the journal says so or a broker stop fill is dated on its exit.
- **Rewrite trigger.** `stop_event` rewrites a held name when its resting stop levels differ from the stored report,
  and `position_closed` rewrites one that is no longer held.

## Every registered source, and the institutional blocks

Operator 2026-10-26: "use ALL internal sources plus whatever external sources it needs" and "make sure we're not
missing any information".

**Registry coverage.** Every domain in `config/data_source_authority.json` appears in `config/prospectus.json` under
`registry_domains`. Each domain is handled in one of three ways:

- read by a reader in `scripts/lib/prospectus/domains.py`
- covered by a named house source
- excluded with a written reason

`tests/test_prospectus_domains_20261026.py` fails CI when a domain is added to the registry without being wired.

Each prospectus carries `source_coverage`:

- `domains`: every domain with its status — `used`, `stale` (with `as_of`), `empty`, `failed` (with a reason) or `not_applicable` (with a reason)
- `house_sources`
- `web_searches`
- `key_gaps`

A missing key source makes the status `partial` and names the gap. The key sources are price history, fundamentals, the profile and the CIO record, plus the position for holdings and the SPY benchmark.

On apply runs, a domain that is empty or stale and marked `refreshable` files one request in the governed data-gap queue (`data_broker.gap_hook`). The prospectus never waits for that refresh.

**Web context.** The model gets a bounded search loop through the governed path:

1. One plan turn names at most `web.max_uses` searches: 6 for holdings, 3 for watch-list names.
2. The searches run through `search_router` (cache, then the free tier, then paid Brave under its budget).
3. The writing turn follows.

Paid Brave calls count against the job's daily allowance of 40. When that allowance or Brave's own budget is exhausted, the prospectus is written from house data and the coverage says so. Every web fact carries its URL and date.

The transport refuses tool definitions, so the loop is two governed turns, not an API tool call.

**Blocks, computed in Python** (never model output). The JSON keys are listed in `CONTRACT_CHANGES.md`:

| Block | Contents |
|---|---|
| `relative_performance` | Rebased series against SPY, QQQ and the sector ETF; returns over 1W–3Y; excess return; industry rank; RS 0–99; sector and industry trend |
| `peer_comparison` | Five industry peers from the enrichment cache, plus the median |
| `estimates` | — |
| `ownership_flows` | — |
| `risk_technicals` | Beta, volatility, drawdown, correlation to the book, SMA50/200, RSI14, ATR20 |
| `macro_sensitivity` | FRED series, 3-month trend, rate beta to the 10-year yield, macro calendar |
| `sec_filings` | `sec_filings_feed` events, Form 4 counts and dollars over 90 days |
| `earnings_call` | — |
| `options_sentiment_dividends` | — |
| `fund_lookthrough` | Funds only |
| `scenarios` | Prices anchored on analyst target facts; the probabilities are the writer's stated judgment |

The writer adds short notes inside these blocks — macro effect on this name, earnings-call points, what changed in each filing. Those notes are guarded like the prose sections.

Values the house does not hold print as `n/a`, and the block names the gap.

The institutional ("Street") blocks are in `PROSPECTUS_INSTITUTIONAL.md` (2026-10-27): analyst coverage and the action
log, consensus / revisions / 8-quarter beat-miss, the catalyst calendar with the options-implied move, positioning,
valuation vs its own history, and SEC XBRL quarters. Citations stay in the JSON. The reader sees one validation line
instead of footnotes.

## Storage (private)

```
<state>/data/prospectus/<SYMBOL>/<UTC-stamp>/{prospectus.json, .html, .pdf, .docx, charts/*.png}
<state>/data/prospectus/<SYMBOL>/versions.json
<state>/data/prospectus/{index.json, queue.json, universe.json, search_budget.json}
```

## API (portfolio server, `scripts/lib/prospectus_api.py`)

Routes are wired in `scripts/portfolio_server.py` ahead of the api_v2 dispatcher, so file responses can be streamed in chunks.

- `GET /api/v2/prospectus/index` returns `{items, totals, budget}`.
- `GET /api/v2/prospectus/<SYM>` returns the latest document plus `versions`.
- `GET /api/v2/prospectus/<SYM>/file/<html|pdf|docx>?version=` streams the file from disk with `Content-Disposition`.
- `POST /api/v2/prospectus/<SYM>/refresh` only queues a rewrite and answers 202.
  - It is restricted to the operator's tailnet identity on the serve proxy.
  - The handler re-checks CSRF, and `cc_auth.yaml` lists the route as hard route `prospectus_command`.

## CIO memory

Operator 2026-10-26: "I need to ensure that this is also in the CIO memory. Very important."

Every finished version (`ready` or `partial`) lands in the CIO-owned shared research memory, the
`SecurityResearchSpine` (`data/cio/security_research_spine.jsonl`). No new store is added.

- **Writer.** `scripts/lib/prospectus/cio_memory.py` `record_version` builds one `ProspectusMemory@v1` record and
  writes it through `security_research_spine.upsert_research_memory`. The call runs as `silo="cio"` with kind
  `prospectus_version` and tags `prospectus`, `llm_research` and `lifecycle`.
  - It requires a registry GUID. A security whose identity is unresolved is refused, as §26.1 requires.
  - It passes `thesis_patch=None`, so the writer's prose never replaces the house thesis tip.
  - The same payload goes to `research_write_path.submit` as lane `prospectus-writer`. That lane is SHADOW by
    default: it writes a receipt in `research_write_path_receipts.jsonl` and leaves the thesis stores untouched.
- **Record.** Each record holds:
  - symbol, version, `written_at`, model (`Opus` or `Fable`), status
  - verdict and the CIO conviction at writing (the `CIO conviction` fact)
  - a one-line summary, the summary section and a short excerpt of every section
  - scenarios (bear, base and bull price plus probability)
  - thesis breakers, key risks and data gaps
  - `source_coverage` counts
  - the house stop plan (level, method, distance and broker state; never dollars at risk)
  - a link to `/v3/prospectus/<SYM>`
- **Versions.** The spine tip holds the newest version in `latest_prospectus`, with `supersedes_version`. Every
  version keeps a compact row in `prospectus_history` (24 rows, newest first). A backfilled older version never
  replaces a newer tip.
- **Idempotent.** A record is keyed by (symbol, version). A version already on the spine is skipped.
- **When it runs.** `pipeline.run_queue` writes the record right after `store.write_version`. A memory failure is
  logged in the run summary (`cio_memory`) and never fails the prospectus.
- **Where it surfaces.**
  - **Ask the CIO.** Source `internal.prospectus` in `cio_ask_research.default_sources`. Its facts are cited to
    `security_research_spine.latest_prospectus` with the version and link. The headline fact reads like
    "Latest prospectus (Fable, Oct 26): ADD — … · CIO conviction 62/100 at writing". The other facts carry the
    summary, every section excerpt (so "what does the prospectus say about X" has an answer), the scenarios, the
    thesis breakers and key risks (as `risk` facts, which the answer lists), the data gaps and the stop plan. The
    stop plan fact is marked `local_only`.
  - **CIO desk.** `subject_dossier` shows a pill-tagged "Latest prospectus …" line with the thesis breakers,
    scenarios and link. The desk reads it with `_latest_prospectus`.
  - **Thesis readers** (Watch, options, desk). `overlay_thesis_fields_from_spine` adds a `latest_prospectus`
    reference to the thesis fields.
- **It is not a conviction input.** The prospectus is model-written. It never changes stance, conviction or the
  thesis tip; the CIO record stays the single source for those.

Backfill of existing versions (dry run by default; idempotent):

```
python3 scripts/prospectus_cio_memory.py                 # dry run: what would be written, refused (identity) or exists
python3 scripts/prospectus_cio_memory.py --apply         # write every stored version, oldest first per symbol
python3 scripts/prospectus_cio_memory.py --apply --latest-only --symbols AAA,BBB
```

## Running it

```
python3 scripts/prospectus_build.py --symbols <SYM> --show-prompt     # dry run (default): no writes, no model
python3 scripts/prospectus_build.py --apply --first-build --limit 40  # first build: premium top 5 → holdings → watch
python3 scripts/prospectus_build.py --apply --due --limit 12          # scheduled lane (n8n prospectus-build)
```

- The queue stops for the day when the credit reports `PAUSED_TODAY`, and resumes on the next run.
- Watch-list items run synchronously. The router's batch path supports only the `bulk` and `standard` tiers, with thinking off, so it cannot serve long-form high-effort work.
