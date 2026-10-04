# Active Trader — Phase 1: Level 2–confirmed scalp alerts

Status:      ACTIVE
as_of:       2026-10-04T12:30:00-04:00
Measured at: c08323704 (Phase 1 shadow) → this PR (live Telegram delivery + Alerts tab)

Operator intent (2026-10-04): the scanner and momentum scout find candidates; for names close to
meeting criteria, moomoo Level 2 and tape confirm, and the desk alerts the operator that it is time
to buy, so not every ticker has to be on screen. **Phase 1 is alerts only. No order path exists.**
Phase 2 (automated entry/exit) and Phase 3 (Schwab) are proposals, not builds.

## What fires

| | ARMED (heads-up) | TRIGGERED (time to buy?) |
|---|---|---|
| Source | entry-trigger state machine `ARMED` (or IGN lane `IGN_75` / `IGN_ACCEL`) | trigger fire ≤ 6 min old |
| Quote | moomoo snapshot, exchange time ≤ 30 s | same |
| Level 2 (moomoo, top 10 levels) | bid depth / ask depth ≥ 1.0×, spread ≤ 80 bps, book ≤ 15 s | bid/ask ≥ **1.2×**, spread ≤ 80 bps |
| Tape (moomoo) | — | ≥ 15 prints, ≤ 60 s old, buy volume ≥ 55 % of the last 50 prints |
| Stop | — | entry and stop refs present, R > 0 |

- **Fail closed.** A missing or stale quote, book or tape is a **VETO**, journaled with its reasons
  (`QUOTE_STALE`, `BOOK_STALE`, `SPREAD_WIDE`, `L2_ASK_HEAVY`, `TAPE_SELLERS`, …). It is never an alert.
- **Throttle.** 15-minute cooldown per symbol and kind; 12 alerts per hour; at most 8 candidates per
  pass (equal to the moomoo L2 subscription budget).
- **Deterministic.** No LLM anywhere in the path.

Why the trigger state machine and not the IGN score: from 2026-09-04 to 09-17 no row reached IGN_75 or
IGN_ACCEL. The trigger state machine produced 30 TRIGGER fires, about 3 a day.

## Data sources (measured 2026-10-04)

- **moomoo (primary).** OpenD quote context only: `FutuTransport.get_order_book`, `get_ticker`
  (TICKER subscription) and `get_snapshot_time`. A read-only probe returned **60 bid / 60 ask levels**
  for AAPL, TSLA, SPY and SOUN. Subscription quota is 100; alerts use 2 per armed symbol.
  - **Known limit:** OpenD returned an empty server receive time for the book on the weekend. When
    that happens, book age falls back to the fetch time and is journaled as `ts_source: fetch`.
    TRIGGERED alerts still require an exchange-stamped quote and tape.
- **Schwab (comparison only).** The latest `schwab_stream_book` row (NASDAQ_BOOK, 12 symbols, 5 levels
  through our `BOOK_TOP_N`) is journaled beside each decision. It never decides an alert.

## Where it runs

`scripts/scalp_shadow_logger.py` (cron `*/5 6-11 * * 1-5`, live work 09:30–11:55 ET, dev tree) calls
`active_trader.momentum_alert_pass.run_from_logger` after scoring and the trigger engine. Replay runs
never alert, and a logger `--dry-run` writes and sends nothing.

| Module | Role |
|---|---|
| `scripts/active_trader/momentum_alerts.py` | evidence, decision, throttle, message, journal, `telegram_send` |
| `scripts/active_trader/momentum_alert_sources.py` | moomoo quote-context reads; Schwab book and float (SELECT) |
| `scripts/active_trader/momentum_alert_pass.py` | builds candidates from a logger pass; writes the heartbeat |
| `scripts/active_trader/momentum_alert_scoring.py` | MFE/MAE at 1, 5 and 15 min ($, %, R) for alerts **and** vetoes |
| `scripts/active_trader/momentum_alerts_api.py` | `GET /api/v3/active-trader/alerts` |

## State (persistent, append-only)

`~/trade-ai-releases/persistent-state/data/active_trader/`:
- `momentum_alerts.jsonl`: every decision (contract `active-trader-momentum-alert-v1`)
- `momentum_alerts_scored.jsonl`: scores
- `momentum_alerts_throttle.json`: cooldown and hourly state
- `momentum_alerts_heartbeat.json`: the last engine pass, even when nothing qualified

The directory is pinned to persistent state so the writer (cron, dev tree) and the reader (API,
CURRENT) can't split the way the motion journal did on 2026-10-04.

## Delivery

- `active_trader_alerts.mode` in `config/scalp_signal_engine.yaml`:
  - `shadow`: journal only. This was the default and code fallback for the first deploy (c08323704).
  - `send`: Telegram. Operator decision 2026-10-04: **live from Monday 2026-10-05 open**.
- Sending goes through `telegram_alert.send_telegram(..., bypass_router=True,
  message_class="active_trader_scalp_alert")`. Bypassing the router means a digest never delays an
  intraday alert; cooldown and the hourly cap are enforced by `Throttle`.
- **Comms editor.** Your 09-23 rule holds any bullish message on a ticker with no CIO decision, and
  scalp tickers almost never have one. On 2026-10-04 you exempted **only** this alert class, and
  **only** from that missing-decision hold (`comms_editor.is_active_trader_scalp_alert`, matched on
  the fixed first line `ACTIVE TRADER · SCALP ALERT` plus `ADVISORY ONLY — NOT AN ORDER`).
  - A CIO **disagreement** on the ticker still rewrites or holds the alert.
  - Ordinary bullish messages are still held.
  - A forged header without the not-an-order line is still held.
- Each alert carries:
  - symbol, last, entry, stop, R, float, RVOL and setup;
  - the L2 and tape numbers that fired it;
  - the age of each data input;
  - a link to `/v3/active-trader?tab=Alerts`.

## Command Center

`/v3/active-trader` opens on the **Alerts** tab (`ActiveTraderAlertsTab.tsx`). It shows:
- the Telegram/shadow mode;
- the engine heartbeat;
- today's counts: time-to-buy, heads-up, sent and vetoed;
- 5-minute precision;
- the decision feed with L2, tape and score per row (filterable by all, alerts or vetoes);
- why signals were blocked;
- the track record at 1, 5 and 15 minutes (alerts vs vetoed triggers);
- the rules in force.

It is read-only, with no order controls. The Review, Configuration and Setups tabs are unchanged.

## Safety (asserted by tests)

- `tests/test_active_trader_momentum_alerts_20261004.py`: decisions, vetoes, throttle and journal; a
  replay on 30 recorded TRIGGER fires; and an AST check that the new modules can't reach
  `place_order` / `modify` / `cancel` / `unlock_trade` / any TradeContext / 2FA / TradingSessionGrant.
- `tests/test_active_trader_live_alerts_20261004.py`: the comms editor exemption and its limits; the
  Telegram path; shadow never sends; the heartbeat; the API; and the repo config in send mode.
- `apps/command-center-v3/e2e/active-trader-alerts.spec.ts`: landing tab, LIVE badge, feed, filter,
  empty state, and no overflow at 390 px.

## Turning it off

Set `active_trader_alerts.mode: shadow` (a config-write grant), or create the engine kill file
`~/.tradeai/SCALP_ENGINE_DISABLED`, which stops the whole ignition engine.
