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

| mode | Momentum Scalp (scanner) | Active Trader | unified ledger |
| --- | --- | --- | --- |
| `off` | today's alert, byte for byte | today's alert | nothing written |
| `shadow` (default) | today's alert **plus** the unified message logged beside it (`SHADOW_LOGGED`, `legacy_alert` names the old one) | today's alert; replay CLI builds its shadow rows | shadow rows |
| `live` | unified message **instead**. The old alert is sent only if the unified send was not accepted | **unchanged until the grant below** | live rows with message ids |

Env `UNIFIED_MOMENTUM_ALERT_MODE` overrides the mode for one process. An unknown value resolves to `shadow`,
never to `live`.

## What is held, and why

`scripts/active_trader/**` is the broker execution file set. It is editable only under an operator
`execution-engineering` grant naming the files (AGENTS.md §0 rule 2, §2B, §24.10;
`config/agents_guard_hook_rules.json` rule `broker.execution_code_edit`, action deny). No grant was active on
2026-10-22, so this change does **not** touch it. Held for that grant:

1. **The Active Trader live hook.** `momentum_alerts.py` would call `unified_momentum_alert.emit(event_from_at_row(row))`
   where it sends today, suppressing its own alert in `live`. AGENTS.md §9.1 already lists the file's
   `bypass_router=True` site as awaiting this grant. Until then, `live` replaces only the scanner side.
2. **`microstructure_signals.SignalConfig` and the served AT payload** carrying `spread_bps` / imbalance
   signals. The computation and priors are in place (below), and the AT alert row already carries the inputs
   (`l2.best_bid/best_ask/bid_depth/ask_depth`).

Until then, the Active Trader side runs in shadow by replay, which reads its journal, a store, read-only:

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

The v1 priors are in `config/scalp_signal_engine.yaml` `l2_book_signals`:

| prior | value | basis |
| --- | --- | --- |
| `spread_bps_max` | 50 | the existing `config/scalp_confirmations.yaml` bound |
| `imbalance_min` | 1.5 | |
| `ask_heavy_max` | 0.67 | |
| `levels` | 5 | |

Changes are operator-ratified only; `signal_calibration` proposes. A missing, one-sided or crossed book gives
`NO_BOOK` with `on: None`, never a lit signal. Inputs are either a recorder snapshot (data-broker
`active_trader_microstructure`) or an AT row's `l2` block.

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
