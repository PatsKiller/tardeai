# Proposal — broker market data for the Market Risk Engine (Schwab, moomoo)

```
Status:      PROPOSED — nothing in this document is built; each item needs the operator's approval first
as_of:       2026-10-31
Design:      DSN-20261031-market-risk-engine (P1 data)
Operator:    "We also have Charles Schwab and moomoo apis to use and finviz" (in session, 2026-10-31)
Rails:       AGENTS.md §0 rules 1-2, §7A, §22, §23.14, §24.10, §24.11, §26.6 — market data only; no account,
             position, order, stop or 2FA endpoint; no new credential handling; no agent ever calls a broker.
```

## Why a proposal and not code

Schwab and moomoo client code is broker-adjacent (§0 rule 2, §22): an agent may modify it only under an
`execution-engineering` grant naming the files, purpose and expiry, and no agent may call either API, even
read-only. Each item below therefore states the endpoint, the engine input it fills, the clause it falls under and
the exact approval text. Finviz items that use already-registered writers are built in the companion PR instead.

## What already exists (measured 2026-10-31, read-only)

| Source | Already integrated | Fresh? | Gap for the engine |
|---|---|---|---|
| Schwab option chains | `scripts/options_chain_snapshot.py` → `option_chain_snapshots` (put/call OI and volume, ATM IV, skew25, underlying) for 29 symbols incl. all 11 sector SPDRs, SPY, QQQ, held names; cron 10:00 and 17:35 ET | yes (10-30 17:35) | no per-strike data (dealer gamma); no look-through heavyweights (AAPL, MSFT, AMZN, GOOGL, META…); no implied move for names not in the list |
| Schwab quotes / price history / movers / market hours | token manager exists (auth AUTO, never touched by agents) | n/a | not used by the engine; extended-hours cross-check and sector-ETF daily history are not fetched from Schwab |
| moomoo OpenD | OpenD running (127.0.0.1:11111); `scripts/brokers/moomoo/`, `moomoo_live_read_sync.py` */15 09-16 (account read) | yes | §7A provider row says `service_down` (stale); no market-data use (pre/post quotes, capital distribution) |

## Items

### S1 — Schwab per-strike chain aggregates (dealer gamma / delta exposure)
- **Endpoint:** the chain call the snapshot lane already makes (`/marketdata/v1/chains`), keeping per-strike OI, gamma
  and delta that the lane currently discards.
- **Engine input:** options_flow (gamma flip / pin zones), deep brief "how the market is hedging".
- **Clause:** §0 rule 2 / §22 (edit to a Schwab-client caller) + §7A (new store `option_chain_strikes`, already
  proposed in PR #2333).
- **Approval needed:** `execution-engineering` grant — files `scripts/options_chain_snapshot.py`,
  `scripts/lib/writers/option_chain_strikes_writer.py` (new); purpose "persist per-strike aggregates from the existing
  chain response; market data only; no new endpoint"; expiry 24 h — plus grant of the `option_chain_strikes` row.
- **Risk:** larger rows per run (≈ strikes × 2); no new API call. **Scope:** market data only.

### S2 — Schwab chains for look-through heavyweights and held names not yet covered
- **Endpoint:** same chain endpoint, more symbols (top-15 index weights, held-ETF look-through heavyweights).
- **Engine input:** implied moves for the protection playbook and the event category (earnings implied move).
- **Clause:** config-only symbol-list change to a Schwab lane → treat as §0 rule 2 (execution-engineering) because
  it changes broker-API call volume.
- **Approval needed:** `execution-engineering` grant — file `config/` symbol list used by
  `options_chain_snapshot.py`; purpose "add N market-data symbols"; expiry 24 h.
- **Risk:** rate limit (one chain call per symbol, twice a day). **Scope:** market data only.

### S3 — Schwab price history for sector ETFs (XLC, XLRE, … daily bars)
- **Endpoint:** `/marketdata/v1/pricehistory`.
- **Engine input:** technical / breadth / sector attribution (XLC, XLRE, XLK… read UNKNOWN live today).
- **Clause:** §0 rule 2 + §7A (writer into `market_ohlcv_bars`, which has no registry row — flagged by PR #2348).
- **Alternative without a grant:** PR #2348's public-data refresh. The companion PR's provisional chain-snapshot
  close only exists when a chain snapshot lands in the 16:00–16:15 ET window; today's 10:00/17:35 schedule produces
  none, so it is not a substitute. **Recommendation: use #2348; S3 only if the public source proves unreliable.**

### S4 — Extended-hours cross-check (Schwab or moomoo pre/post quotes vs the Alpaca SIP feed)
- **Endpoint:** Schwab `/marketdata/v1/quotes` (extended fields) or moomoo `get_market_snapshot` (pre/after prices).
- **Engine input:** extended_hours category confidence (a second venue confirms an after-hours shock).
- **Clause:** §0 rule 2 + §7A (new domain `quote_extended_crosscheck`); moomoo additionally needs its provider row
  restored from `service_down` (§26.6).
- **Approval needed:** `execution-engineering` grant naming the new reader file + the domain row.
- **Risk:** a second broker call on the extended schedule. **Scope:** quotes only.

### M1 — moomoo capital distribution (institutional order-flow proxy, design §5.4)
- **Endpoint:** OpenD `get_capital_distribution` / `get_capital_flow` (large/medium/small order in-out) for SPY, QQQ,
  sector ETFs and look-through heavyweights.
- **Engine input:** institutional positioning (§5.4) — hedging/accumulation vs retail divergence.
- **Clause:** §0 rule 2 / §22 (moomoo client is broker code) + §7A (new domain `institutional_flow_daily`, proposed
  in PR #2333) + provider row status `service_down` → `active` (§26.6).
- **Approval needed:** `execution-engineering` grant — files `scripts/brokers/moomoo/` reader (new, quote context
  only, no trade context), `scripts/lib/writers/institutional_flow_writer.py`; purpose "market data only, quote
  context, no trade context, no unlock"; expiry 24 h — plus the domain row and the provider status change.
- **Risk:** OpenD quote quota; OpenD is a §24.10 unit (operator-only to operate). **Scope:** quote context only.

### R1 — Registry correction
- `providers.moomoo.status` reads `service_down` while OpenD is running and `moomoo_live_read_sync.py` runs */15.
  Correcting it is a §7A registry edit (operator approves the row).

## Built without a grant (companion PR)

`scripts/lib/market_risk/registered_sources.py`: implied moves (with IV data-quality flags) and provisional sector
closes (close window only) from the existing `option_chain_snapshots` rows, and positioning (institutional/insider
transaction %, short float, trend) from the Finviz enrichment cache file, knowable only when both `cached_at` and
`hot_cached_at` are at or before the evaluation time. No new fetch, no broker call.
