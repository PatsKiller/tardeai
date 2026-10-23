# Unified momentum alert (Gate 4) and Level 2 book signals

```
Status:      ACTIVE (shadow) — built and tested; the live switch is the operator's
as_of:       2026-10-22T20:30:00-04:00
Measured at: base b9804fa57 (origin/main); AT journal and Hermes store under ~/trade-ai-releases/persistent-state, read-only
```

Operator-approved design, 2026-10-22 (mockup `Alert.dc.html`, "One alert, threaded"): **one alert per
symbol/event/day** replaces the separate Momentum Scalp alert (`social_scalp_scanner.send_scalp_alert`) and
Active Trader alert (`scripts/active_trader/momentum_alerts.py`). **ADVISORY ONLY — never an order.**

## Lifecycle and threading

`WATCH → APPROACHING → ARMED → TRIGGERED → STAND DOWN`, plus the engine's `EXTENDED`, `PULLBACK_ZONE` and
`TRIGGER_CANCELLED`. The Active Trader `PREMARKET_WATCH` kind maps to `WATCH`.

- Every **state change** is a new Telegram message sent as a **reply** to the thread's first message, so the
  phone still notifies. The first message id is stored **per chat**, per `day:SYMBOL:event` thread, in the ledger.
- The root is the first message that was actually **delivered** (it has a message id). A first message held for
  the quiet-window digest or deduped by the router has no id, so the next delivered one becomes the root.
- **Dedupe** (notify on transitions, AGENTS.md §9.1): the same state as the thread's last emitted state is not
  sent again (`DEDUPED_SAME_STATE`). A source row already in the thread is a replay (`DUPLICATE_ORIGIN`). The
  intent router's content dedupe window then applies on top (`dedupe_minutes`, default 30).
- A failed send is recorded (`SEND_FAILED`) and does not count as emitted, so the same state may be retried.
- Priority: APPROACHING, ARMED, TRIGGERED, EXTENDED and PULLBACK_ZONE are **P1** (never quiet-held). WATCH,
  TRIGGER_CANCELLED and STAND_DOWN are **P2**: held 22:00–07:00 ET for the digest, archived and never dropped.

Every message carries:

- the catalyst title;
- the grade;
- the AI verdict and confidence (Hermes scalp-catalyst research; `—` when there is none);
- float, volume and RVOL;
- which sources agree (scan / social / L2, `✓ ✗ —`);
- the L2 signals (`●` lit, `○` unlit, `⚠` ask-heavy);
- levels;
- the line `ADVISORY ONLY — NOT AN ORDER. Your decision, your broker.`

Absent values render `—`. They are never invented.

## Delivery path

Live sends go through the host communications gateway: one `send_telegram(text, priority, dedupe_minutes,
producer="unified_momentum_alert", reply_to_message_ids={chat: id})` notification intent per state change
(AGENTS.md §9.1, §24.1). It is routed by `telegram_alert_router.route_intent` and receipted. Time-critical sends
stay host-side and do not depend on n8n.

`reply_to_message_ids` is a new, optional `send_telegram` keyword. It follows the existing explicit-destination
legacy branch (like `thread_id`), and the transport puts `reply_to_message_id` on the first chunk to each chat
only. A class the comms gateway owns keeps its gateway path and is delivered unthreaded: a reply never routes
around the gateway. Omitting the keyword changes nothing.

## The flag — what the operator flips

`config/scalp_signal_engine.yaml`:

```yaml
unified_momentum_alert:
  mode: shadow        # off | shadow | live
  dedupe_minutes: 30
```

| mode | Momentum Scalp (scanner) | Active Trader engine | unified ledger |
| --- | --- | --- | --- |
| `off` | today's alert, byte for byte | today's alert, byte for byte | nothing written |
| `shadow` (default) | today's alert **plus** the unified message logged beside it (`SHADOW_LOGGED`, `legacy_alert` names the old one) | today's alert **plus** the unified message logged beside it (journal row `unified`) | shadow rows |
| `live` | unified message **instead**. The old alert is sent only if the unified send was not accepted | today's alert, unchanged; the hook **refuses** and records `LIVE_REFUSED` — "live replacement pending operator decision" | live rows (scanner only) |

Env `UNIFIED_MOMENTUM_ALERT_MODE` overrides the mode for one process. An unknown value resolves to `shadow`,
never to `live`.

## Active Trader side (execution-engineering grant e88bf21e, 2026-10-22)

`scripts/active_trader/**` is the broker execution file set (AGENTS.md §0 rule 2, §2B, §24.10). The operator's
grant `e88bf21e` (approve-all item H, A1/A2: fixtures and replay only) names `momentum_alerts.py`,
`microstructure_signals.py`, `momentum_alerts_api.py`, `read_api.py` and `signal_calibration.py`.

- **Shadow-only hook.** `momentum_alerts.evaluate_pass` calls `unified_shadow(row)` after every ALERT row's
  legacy send. It never suppresses or replaces that send (test-pinned: the legacy call is identical in off, shadow
  and live). In `live` it refuses and records `{"action": "LIVE_REFUSED", "note": "live replacement pending
  operator decision"}`. Replacing the AT alert is the operator's decision. A first version that suppressed the
  legacy send in live mode was refused by the session's safety classifier and is not built.
- **No new router bypass.** The legacy `telegram_send` keeps its allowlisted `bypass_router=True`; the hook sends
  nothing.

The replay CLI stays for back-filling a day (idempotent with the live hook: same `origin_ref`):

```
python scripts/unified_momentum_alert_shadow.py --day YYYY-MM-DD --dry-run --show 5
python scripts/unified_momentum_alert_shadow.py --day YYYY-MM-DD          # append shadow rows
```

Dry run 2026-10-22 against the live journal: write-free, `MemoryLedger`.

```
{"actions": {"DEDUPED_SAME_STATE": 3, "SHADOW_LOGGED": 14}, "day": "2026-10-22", "dry_run": true,
 "journal_rows": 1758, "replayed": 17, "threads": 7}
```

The 17 alerts the operator was sent on 2026-10-22 collapse to 14 messages in 7 threads. For example, GIXI:
TRIGGER CANCELLED 09:43, then EXTENDED 09:56, PULLBACK ZONE 10:16 and TRIGGER CANCELLED 10:32, each
`↳ update to TRIGGER CANCELLED · GIXI 09:43`.

## Level 2 book signals

`scripts/lib/l2_book_signals.py` (`L2BookSignals@v1`) computes two signals and one warning:

- `tight_spread`: on when `spread_bps ≤ spread_bps_max`;
- `bid_ask_imbalance`: on when bid size / ask size over the top `levels` is at least `imbalance_min`;
- `ask_heavy` (warning): on when that ratio is at or below `ask_heavy_max`.

The v1 priors are in `config/scalp_signal_engine.yaml` `microstructure_signals` (the section
`SignalConfig` reads), one home for both readers:

| prior | value | basis |
| --- | --- | --- |
| `spread_bps_max` | 50 | the existing `config/scalp_confirmations.yaml` bound |
| `imbalance_min` | 1.5 | |
| `ask_heavy_max` | 0.67 | |
| `imbalance_levels` | 5 | |

Changes are operator-ratified only; `signal_calibration` proposes. A missing, one-sided or crossed book gives
`NO_BOOK` with `on: None`, never a lit signal. Inputs are either a recorder snapshot (data-broker
`active_trader_microstructure`) or an AT row's `l2` block.

Under the grant the engine computes them too: `SignalConfig` carries the four priors, `entry_signals()` adds
`tight_spread` and `bid_ask_imbalance` (evidence on the journal row; never a verdict), and `ask_heavy()` exists as
a helper but is **not** added to `exit_signals()`, whose `fired()` count drives `exit_watch`. The served payload
(`GET /api/v3/active-trader/alerts`, `momentum_alerts_api._compact`) carries `l2_book_signals` for every
decision, computed from the row's own `l2` block, and the row's `unified` summary.

## Store

`<state root>/data/runtime/unified_momentum_alerts.jsonl` (`UnifiedMomentumAlert@v1`):

- one writer, `scripts/lib/unified_momentum_alert.py`;
- append-only under an flock;
- proposed as a history copy of the `alert_events` domain (`config/data_source_authority.json`, AGENTS.md
  §26.2). It is proposed, not granted.

## Tests

`tests/test_unified_momentum_alert_gate4_20261022.py`, CI gate
`config/ci_gates/unified_momentum_alert_gate4_20261022.json`. The tests cover:

- reply ids per chat;
- root selection when the first message is held;
- dedupe and retry;
- flag off is byte-identical;
- shadow logs beside today's alert;
- live replaces it, with fallback;
- the transport puts the reply on the first chunk only;
- the AT adapter;
- replay idempotency and dry-run;
- no broker reach.
