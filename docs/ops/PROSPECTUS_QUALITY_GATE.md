# Ticker Prospectus — data-quality gate

Operator-approved 2026-10-26 ("build this and execute it immediately"). Goal: never spend Opus or Fable on bad data.
Code: `scripts/lib/prospectus/quality_gate.py`. Wired into `generate.write()` (runs before the web-search planning
turn, which is the first paid call) and `pipeline.run_queue()`. READ_ONLY_ADVISORY (MBI_BEHAVIOR=0).

## Layers

| Layer | Cost | What it reads | Outcome |
|---|---|---|---|
| 1 deterministic | free | the assembled facts packet + the 1Y price series + the blocks | HARD_FAIL / SOFT_FAIL / pass |
| 2 AI sanity read | ~$0.001/ticker | the facts packet only (never prose) | high-severity anomaly → SOFT; one that confirms a layer-1 hit → HARD |
| 3 post-write | free | the written sections and the facts they cite | > `post_write_max_unmatched` unmatched numbers → `partial` + one rewrite queued |

### Layer 1 reason codes

| Code | Severity | Check |
|---|---|---|
| `no_price` | HARD | no price series and no last close |
| `no_position` | HARD | holding with no position record |
| `nonpositive_price` | HARD | a zero/negative close or $ price fact |
| `first_bar_outlier` | HARD | first bar > 3x / < 0.33x the next five bars' median (listing day, prior symbol) |
| `last_bar_outlier` | HARD | last bar > 3x / < 0.33x the prior five bars' median |
| `isolated_price_jump` | HARD | one bar > 3x its neighbour that reverts the next bar |
| `pre_listing_or_symbol_reuse` | HARD | persistent > 3x level break: bars before it belong to another listing |
| `stale_last_bar` | SOFT > 3 sessions, HARD > 10 | last bar age vs the packet date |
| `series_gap` | SOFT | consecutive bars > 10 calendar days apart |
| `short_series` | SOFT | < 20 bars: 1Y statistics not meaningful |
| `market_cap_units` | SOFT | "$B" value above $5T, or > 1000x off the peer median ($M recorded as $B) |
| `beta_out_of_range` | SOFT | beta outside [-3, 5] |
| `volatility_absurd` | SOFT | annualized volatility > 200% |
| `pe_absurd` | SOFT | P/E or forward P/E ≤ 0 or > 1000 |
| `cross_source_disagreement` | SOFT | house YTD / 1Y return vs Finviz beyond max(10 pp, 25%) |
| `alphabetical_peers`, `etf_cohort_peers`, `peer_industry_mismatch` | SOFT | peer junk (no caps + alphabetical, AA… symbols, ETF cohort, other industry) |
| `transcript_not_earnings_call` | SOFT | the "transcript" is not an earnings call for this issuer (e.g. a YouTube stock-picking video) |
| `filing_cik_mismatch` | SOFT | a filing under a different CIK than the issuer's |
| `no_stop_state` | SOFT | holding with no recorded stop state |
| `no_analyst_or_fund_profile` | SOFT | neither analyst coverage nor a fund profile |

Thresholds: `DEFAULTS` in the module, overridable by an optional `config/prospectus_quality_gate.json`. Where the
concurrent data-defect fixes exist (`blocks.series_quality`, `domains.transcript_rejection`) the gate calls them;
otherwise its own checks stand alone.

### Outcomes

- **HARD_FAIL** — `DataBlocked` is raised before any model call. The queue row is parked as `blocked_data`, the index
  carries `status: blocked_data`, `gate_status`, `gate_reasons`, and one data-gap queue row per repair domain is filed
  (`data_broker.gap_hook`, requester `prospectus_quality_gate`). Re-requesting the symbol (cadence, operator refresh,
  `--gate-only --apply`) re-queues it and the gate runs again.
- **SOFT_FAIL** — the report is written and marked `partial`; `partial_gaps` lists `data quality: <code>: <why>`. The
  affected facts carry `unreliable: <code>`; the writer's prompt shows them as `NOT RELIABLE (<code>) - do not cite`,
  the grounding guard refuses their numbers, and the blocks print `not reliable (<code>)` instead of the number (with
  `block.unreliable` naming the field).

## Layer 2 routing

`prospectus_fact_check`: Claude Haiku 5.5 (credit tier `bulk`, thinking disabled, effort low), Anthropic credit only
(`anthropic_only_processes`), max 1,200 output tokens, $0.50/day, 250 calls/day. When the credit is unavailable the
caller uses `prospectus_fact_check_oauth` (Grok OAuth only, $0.00). Never DeepSeek. A failed read is recorded in
`gate.layers.ai` and never blocks. Structured output: the transport does not yet pass `output_config.format`, so the
prompt asks for `{"anomalies": [{field, value, why, severity}]}` and the gate parses and validates it.

Estimate: ~5.5k input + ~0.6k output tokens ≈ $0.00085 per ticker at list price; ~$0.10 for 119 tickers.

## Stored reports: `--gate-only`

```
python3 scripts/prospectus_build.py --gate-only --all            # dry: layers 1 + 3, counts, writes nothing, no paid call
python3 scripts/prospectus_build.py --gate-only --all --ai       # dry + the Haiku read
python3 scripts/prospectus_build.py --gate-only --all --apply    # + Haiku read, index gate fields, enqueue rewrites,
                                                                 #   file data repairs for HARD rows
```

A report needs a rewrite for `bad_data` (HARD), `soft_data` (SOFT), `no_web` (no web results), `partial`, or
`post_write_unmatched`.

## API

`/api/v2/prospectus/index` items carry `gate_status`, `gate_reasons`, `gate_checked_at`; `totals` counts
`blocked_data`. `/api/v2/prospectus/{SYM}` returns the stored `gate` object plus `gate_status` / `gate_reasons`, and
`latest_attempt` when a newer attempt was blocked on data.
