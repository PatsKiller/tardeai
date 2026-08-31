# Schwab Trader API → Trade AI v12 — Capability Map (design, no code)

Status:      ACTIVE
as_of:       2026-06-09T23:18:22-04:00
Measured at: efcc51365 / not measured

**Prepared:** 2026-06-10 · **Type:** design/capability mapping (documentation only — no implementation)
**Source of truth for the API surface:** the operator's mid-2026 Schwab Trader API (Individual / Production)
capability inventory (reproduced inline below). **Source of truth for our system state:** the live cred-in
build — see [`SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](SCHWAB_API_PHASE1_READONLY_FOUNDATION.md).

This document maps **every** Schwab API capability to where it does / would / must NOT plug into Trade AI v12.
It is the planning artifact: it surfaces capabilities that are wire-able but not yet wired, and the ones
that stay fenced. **No code is added here.**

## Status legend
| Tag | Meaning |
|---|---|
| ✅ **BUILT** | live + proven in our system today |
| 🟡 **READY** | API-capable + we have the transport, but NOT yet wired (a documented gap to build later) |
| ⛔ **FENCED** | API-capable but deliberately unreachable — Stage 2, `api_write_enabled=false`, `NotProvenWrite` |
| 🚫 **N/A** | not exposed by the Schwab API (or not for our account type) — no path, don't fabricate |

---

## 1. Core Features

| Schwab capability | Status | System component / integration point | Notes |
|---|---|---|---|
| **Account details / balances / cash-for-trading / linked accounts** | ✅ BUILT | `schwab_transport.get_account` → `normalize_account`; `SchwabMonitor` | live; per-account hash resolved (`schwab_account_links`) |
| **Account numbers ↔ hash mapping** | ✅ BUILT | `resolve_account_hashes` (last-4 match, ambiguity-refused) | encrypted hash in `schwab_account_links` |
| **Positions (with P&L)** | ✅ BUILT | `get_positions` → `normalize_positions` | live; feeds the real-account view |
| **Transaction history (filter by date/symbol/type)** | ✅ BUILT | `get_transactions`; `schwab_transaction_ingest.py` → `trade_transactions` | API-authoritative ledger; ~11-mo window |
| **Order history & status (read)** | ✅ BUILT | `get_orders` → `normalize_orders` | read-only; used for same-day fill visibility |
| **User preferences** | 🟡 READY | `get_user_preferences` works (returns `accounts/streamerInfo/offers`) | only used today to confirm auth; `streamerInfo` is the streaming handle (see §4) |
| **Watchlists** | 🚫 N/A | — (see §5) | **confirmed 404 live** — not migrated from legacy TDA; ToS-export fallback BUILT |
| **Saved / conditional orders (multi-leg)** | ⛔ FENCED | would be `schwab_adapter` writes | write surface — Stage 2 only |
| **Instrument fundamentals / search** | 🟡 READY | schwab-py `get_instruments` / `search_instruments` (un-wrapped) | could enrich the watchpool / symbol master |

---

## 2. Market Data

| Schwab capability | Status | Integration point | Notes |
|---|---|---|---|
| **Real-time quote (single)** | ✅ BUILT | `get_quote` → `normalize_quote` | live |
| **Batch quotes** | 🟡 READY | schwab-py `get_quotes(symbols)` (un-wrapped) | would cut rate usage for watchlist refresh vs per-symbol |
| **Historical price (daily + intraday)** | 🟡 READY | schwab-py `get_price_history_*` (un-wrapped) | could feed backtester OHLC + entry-grade engine (currently other sources) |
| **Option chains (Greeks, IV)** | 🟡 READY | `get_option_chain` exists as a **passthrough stub** (not normalized/used) | needed for any options strategy; reconcile shape at wire-time |
| **Fundamentals / instruments** | 🟡 READY | schwab-py `get_instruments` | symbol master enrichment |
| **Market hours / calendar** | 🟡 READY | schwab-py `get_market_hours` (un-wrapped) | would replace/confirm our market-hours gating for the live path |

> **Rate limits:** Schwab ≈ **120/min market data, 60/min trading/account**. Our transport uses ONE shared
> conservative token bucket (`tm.RATE`) — **documented gap:** set it to the real per-bucket numbers at
> market-data wire-time, and ideally split market-data vs trading buckets.

---

## 3. Streaming (WebSocket) — deferred

| Capability | Status | Notes |
|---|---|---|
| Real-time quote stream | 🚫 N/A (deferred) | schwabdev/Level-II spike — **out of scope by policy** (entitlement-then-reliability proof first) |
| Order book / Level II (exchange-limited) | 🚫 N/A (deferred) | Rule-9 isolation: even if added, must NOT touch screeners/match-mins/GO-WAIT/ATM |
| Account activity stream (orders/fills/positions) | 🚫 N/A (deferred) | `streamerInfo` (from user-preferences) is the handle; revisit post-Stage-2 |

---

## 4. Watchlists — N/A via API → ToS fallback (BUILT)

The Schwab Trader API exposes **no watchlist endpoint** (confirmed live: all `…/watchlists` paths 404 while
control endpoints 200). Watchlists were not migrated from the legacy TD Ameritrade API. **Resolved route:**
- ✅ **BUILT** — `ingest_tos_watchlists.py`: thinkorswim exports dropped in `imports/tos_watchlists/` →
  `tos_watchlists` / `tos_watchlist_members` (add/remove **dates** tracked) / `tos_watchlist_events`
  (audit) → mirrored into `watchlist_items` (`source=tos_watchlist`). Manager UI (rename / match-strategy /
  notes / per-symbol note) via `/api/v2/tos-watchlists` + `…/manage`. Daily cron 18:45.

---

## 5. Trading — Order Types & Management (ALL ⛔ FENCED until Stage 2)

The API supports the full order suite below. In Trade AI v12 **every write path is fenced** today
(`api_write_enabled=false`, Schwab accounts `MANUAL_REVIEW`, `schwab_transport` order methods raise
`NotProvenWrite`, `validate_schwab_no_writes.py` 12/12). This section maps **where each would plug in** so
Stage 2 is a known quantity — it is **not** a license to build.

| Order capability | Status | Stage-2 integration point (when gated-open) |
|---|---|---|
| Market / Limit | ⛔ FENCED | `schwab_adapter.submit_entry` (currently NOT_PROVEN) |
| Stop / Stop-Limit | ⛔ FENCED | protection/stop path (mirrors paper stop v2) |
| Trailing Stop | ⛔ FENCED | trailing policy → adapter |
| Market/Limit-on-Close (MOC/LOC) | ⛔ FENCED | session/duration param on the order builder |
| **Bracket** (entry+stop+target) | ⛔ FENCED | the paper bracket flow has a proven shape (`proposal_paper_submitter`) to mirror |
| **OCO / OTO** | ⛔ FENCED | `orderStrategyType` on the adapter order builder |
| Multi-leg options (verticals, condors…) | ⛔ FENCED | `complexOrderStrategyType` + legs; needs option-chain (§2) first |
| Place / modify / replace / cancel | ⛔ FENCED | `schwab_adapter` (place/cancel/replace all NOT_PROVEN) |
| Order status / fills (read) | ✅ BUILT | `get_orders` (read side is live) |

**Hard preconditions before ANY of the above is built (Stage 2, separate gated prompt):** the live-trading
interlock + governance flag flipped, `broker_confirm_schwab.py` designed under the same gates, the 12/12
no-writes guard intentionally retired *per-capability*, and operator sign-off. None exist today.

---

## 6. Limitations — how our system already accounts for each

| Schwab limitation | Our handling |
|---|---|
| **No paper trading via API** (live only) | We never needed it — paper trading is Alpaca; Schwab stays read-only. The live-trading gate is **paper-only** and uncontaminated by real Schwab data. |
| **No/limited fractional trading** | Read side handles fractional shares fine (dividend-reinvest fills, e.g. V 6 sh). Trading is fenced anyway. |
| **Asset limits** (futures/forex/mutual-fund order entry mostly unavailable) | Read-only; mutual-fund **quotes/positions** flow through the ledger; no order entry attempted. |
| **No full ToS parity** (no ThinkScript, no native news) | News via existing pipelines; watchlists via the ToS-export route (§4); ThinkScript out of scope. |
| **Rate limits** (~120/60 per min) | Shared token bucket today; **gap:** set real numbers + split buckets at market-data wire-time (§2). |
| **OAuth** (access ~30 min, refresh ~7 days, manual re-auth) | **Gate A**: token manager owns expiry as first-class state, day-5/6 alerts, one-command re-auth, fail-closed; refresh persists through the manager. |
| **Market hours** (regular; extended restricted) | Paper path already market-hours-aware; live `get_market_hours` is a READY wire (§2). |

---

## 7. Gaps identified ("capable but not wired") — backlog, not built

1. **Batch quotes** (`get_quotes`) — cheaper watchlist refresh than per-symbol.
2. **Historical price history** — feed the backtester/entry-grade engine from the authoritative broker source.
3. **Option chains** — normalize the existing passthrough; prerequisite for any options work.
4. **Fundamentals / instrument search** — enrich `watchlist_symbol_master`.
5. **Market hours** endpoint — confirm/replace live-path gating.
6. **Real rate-limit numbers + split buckets** — replace the conservative shared default.
7. **`streamerInfo`-based streaming** — deferred (policy), but the handle is already in hand.

Each is a self-contained, read-only wire (no write surface). Prioritize at the operator's direction; none
change the fence.

## 8. Cross-references
- Foundation + live cred-in: [`SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](SCHWAB_API_PHASE1_READONLY_FOUNDATION.md)
- Real-account journal + basis correction: same doc, "Stage 1 LIVE" + CHANGELOG 2026-06-10
- Engineering hard rules: [`../ENGINEERING_HARD_RULES.md`](../ENGINEERING_HARD_RULES.md)

---

### Appendix A — operator's Schwab Trader API capability inventory (mid-2026, verbatim spine)
> Core: Account Management; Portfolio & Transactions; Market Data (quotes L1/L2, batch, historical daily+
> intraday, option chains w/ Greeks+IV, fundamentals/instruments, market hours/calendar); Streaming
> (WebSocket quotes, order book L2 exchange-limited, account updates); Watchlists (limited/partial legacy —
> no full CRUD/ToS sync; manage lists in your own DB); Other (saved multi-leg orders, fundamentals, some
> alerts; no built-in news). Trades: equities + options (single+multi-leg); Market, Limit, Stop, Stop-Limit,
> Trailing Stop, MOC, LOC; OCO, OTO, Bracket, complex multi-leg; place/modify/replace/cancel; status+fills;
> session/duration; extended hours (limited). Limitations: no paper via API; no fractional (mostly); futures/
> forex/mutual-fund order entry mostly unavailable; no full ToS parity; rate ~120/min data, ~60/min trading;
> OAuth access ~30 min / refresh ~7 days; regular hours primarily.
