# v3 Open Trades — Actionable Position Intelligence (2026-06-05)

Status:      HISTORICAL
as_of:       2026-06-05T17:27:45-04:00
Measured at: efcc51365 / not measured

Read-only refactor of Trading → Open Trades from a paper-only Alpaca card list into an all-account
position command surface with filter/sort, technicals, news/Hermes research, sector-relative perf,
and inline protection. NO writes anywhere.

## Backend (read-only)
- `scripts/open_trades_intelligence.py` → `build_intelligence()`: one normalized object per open
  position (all accounts, from `trades` where status=open). Batched (no N+1), NaN/Decimal-safe,
  broker-normalized, graceful fallbacks.
- Endpoint `GET /api/v2/open-trades/intelligence` (api_v2 `_open_trades_intelligence`). Existing
  `/api/v2/open-trades` untouched.
- Data sources (READ-ONLY): **positions = holdings.json (real accts) + paper_trades (alpaca paper)**; stale `trades.status=open` rows excluded to `excluded_items` (e.g. sold-out AXTI); live price/P&L/today/RVOL `market_quotes` (fallback
  `price_cache`); technicals `ticker_snapshot_daily` (RSI/SMA/perf) + `indicator_confluence_cache`
  (ATR/ADX/tier); news `news_articles`; Hermes `hermes_research_intelligence` + `hermes_alerts` +
  `hermes_validation_findings`; sector best-effort `aegis_symbol_snapshot_nightly`/`intelligence_entities`
  → static sector→ETF map vs SPY; protection `protection_adjustment_proposals`.
- Response: `{summary, filters, positions[]}` — each position has technical/sector_relative/news[]/
  hermes/protection/action_state. 152 positions, 4 accounts, live price 140/152.

## Frontend (`apps/command-center-v3/src/components/OpenTradesIntelligence.tsx`)
Mounted in TradingHub "Open Trades" tab (replaces inline paper-only cards; ProtectionPanel now a
collapsible `<details>` below). Summary header (visible/total, uPnL, near-stop, TP-missing,
below-entry, big-gain-unprotected, Hermes-findings, account breakdown, source timestamps). Filter
toolbar (account/broker/strategy/sector/RSI/protection/P&L) + sort (risk/P&L/R/RSI/news/symbol),
client-side over the aggregated payload. Cards: header (symbol/account/broker/env/strategy/shares/age),
P&L (uPnL$/%, today, R), plan (entry/now/stop/tgt), technical+protection chips (RSI bucket colored,
trend, TP-missing, below-entry, stop-near, trailing-candidate, Hermes alert/disagree), action label,
"more intelligence" expander → News & Research (source-badged, clickable URLs, age) + sector-relative
+ SMA/RVOL/Hermes. Empty states for missing news/technicals/sector.

## Safety (read-only intelligence + UX)
NO broker writes · NO order/stop mutation · NO GO/WAIT · NO strategy mutation · NO live endpoint · NO
Level 7 · Phase 205/timers untouched · Hermes read-only. Verified: module 0 writes, component 0 write
calls, strictly-valid JSON (no bare NaN), 6/6 edge cases graceful.

## Ownership
UI: OpenTradesIntelligence.tsx (TradingHub Open Trades tab). API: api_v2._open_trades_intelligence →
open_trades_intelligence.build_intelligence. Reads: trades, market_quotes, price_cache,
ticker_snapshot_daily, indicator_confluence_cache, news_articles, hermes_* , aegis_symbol_snapshot_nightly,
protection_adjustment_proposals. Writes: NONE.

## Remaining (data-unavailable / follow-up)
Sector coverage low (most symbols lack a sector source → "unavailable"); 1d perf + ATR% + support/
resistance + fib not yet wired; company_name null; RSI direction (rising/falling) needs prior snapshot;
many Schwab holdings are funds/CUSIPs with no technicals/news (shown as missing). Follow-up: server-side
filter params, sector ETF perf table, company-name join, RSI-direction from 2-day snapshot.


## 2026-06-05 false-positive fix
Base universe corrected from `trades.status='open'` (stale phantom lots incl AXTI, 149 zero-share) to current holdings + paper positions. See `docs/project/OPEN_TRADES_FALSE_POSITIVE_ROOT_CAUSE_20260605.md`. Regression: `scripts/validate_open_trades_intelligence.py`. 152→47 positions.


## 2026-06-05 basis validation
Schwab/Fidelity cards now label the cost basis as **avg cost** (not 'entry'; paper still shows entry). Broker-imported `cost_basis` is sometimes partial/wrong (a few Schwab lots implied avg cost a fraction of price → impossible +1000s%). Added basis validation: positions with missing cost_basis (`no_cost_basis`) or implausible basis (`basis_unverified`: avg_cost <10% of price, or gain% >400 / <-99) are flagged (`basis_reliable=false`, `basis_warning`), their derived P&L is **suppressed** (card shows market value + 'basis unverified'), and they're excluded from `total_unrealized_pnl`. Summary `basis_unverified_count`. This dropped a fabricated ~$337k total to the honest reliable-only figure.


## 2026-06-05 June-5 CSV basis + income repair
Cost basis for real holdings comes from latest broker transaction CSVs (latest-file discovery), explicit transfer-basis overrides (cost_basis_overrides.json), and approved source mappings (Fidelity Positions PDF). Reinvested shares add to basis; dividends/interest are recorded separately in income_ledger.json. Unknown transfer basis is flagged (basis_needs_transfer_mapping / partial_transfer_in), never fabricated. Open Trades trusts explicit cost_basis_source (no false 'unverified' on legit large gains like V +613%); badges: 'basis: owner provided', 'basis needs transfer mapping'. See COST_BASIS_JUNE5_CSV_REPAIR_20260605.md.
