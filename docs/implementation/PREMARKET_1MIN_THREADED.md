# Premarket 1-minute cadence, threaded lifecycle and the scalp focus list

```
Status:      ACTIVE (shadow) — built and tested; cadence_mode live and the crontab packet are the operator's
as_of:       2026-10-23T09:30:00-04:00
Measured at: base 53aa1b619 (origin/main, release batch 7 incl. #1971); live crontab read-only 2026-10-23
```

Operator decisions, 2026-10-23 (verbatim):

- "I agree for every minute, because on manually, I do a 1 minute candle check."
- "And this should just be critiqued at least the top 20 that's it. We don't need everything, but we should have a
  mechanism that's bringing stuff in and out of the top 20. Or the top 30 or whatever. We're not trying to do the
  whole universe."

**ADVISORY ONLY — never an order.** Nothing here sizes, orders, stops or reaches a broker (MBI_BEHAVIOR = 0). The
moomoo connection is the existing quote context; no trade context is opened.

## What changed, and why

Before: `premarket_watch.py` ran from cron every 5 minutes (`*/5 6-9`), sent one `PREMARKET_WATCH` heads-up per
symbol and then muted the symbol for 30 minutes. A scalp can change in 2 minutes. The recorder already captures
book and tape every 5 s, so the data was there; the evaluation was not.

Now, on every closed 1-minute candle:

1. **Focus list.** The scalp hot list's pool (~110 names) is ranked and the top N (default 20, max 30) form the
   focus list (`scripts/lib/scalp_focus.py`). Only focus names are evaluated each minute, alerted on and critiqued.
2. **Lifecycle.** Each focus name gets a state from the closed candle: `WATCH → APPROACHING → ARMED → TRIGGERED`,
   then `EXTENDED`, `PULLBACK_ZONE` or `TRIGGER_CANCELLED`, and `STAND DOWN`. This reuses the #1971 vocabulary.
3. **Threading.** The first message opens the symbol's thread. Each state change posts in the thread at once. The
   same state is never sent twice. A hard cap limits messages per symbol per hour. This replaces the flat 30-minute
   throttle.
4. **Evidence.** Every message carries the shared "Driven by / Ready / Missing" block.

## Cadence (`--loop`)

- Cron starts `premarket_watch.py --apply --loop` on the existing `*/5 6-9` line, under the existing
  `flock -n /tmp/at_premarket.lock`.
- The loop sleeps until `settle_s` (6 s) after each minute boundary. It then evaluates the candle that just
  **closed**, the operator's manual method. The forming bar is never used.
- Bars come from the recorder store (`data_broker.microstructure.bars`), but only if that store was published after
  the boundary, so the candle is final. Otherwise they come from the quote context (`MoomooSource.bars_1m`,
  normalised to bar start). Book and tape come from the recorder's latest snapshot, with its age. For up to
  `direct_book_max` names that are APPROACHING or later and are not recorded, the book is read directly and
  labelled `moomoo_direct`.
- **Never overlapping:**
  - the loop is single-threaded;
  - a tick that overruns skips the minutes it missed (counted as `skipped_minutes`) and never queues them;
  - the process holds `premarket_watch.run.lock` (non-blocking), so a second `--apply` run prints
    `SKIPPED_ALREADY_RUNNING` and exits;
  - the cron flock stops a second loop.
- The loop exits at window end (after the 09:29 candle) or on the `PREMARKET_DISABLED` kill file. While the loop
  runs, each `*/5` relaunch finds the lock held and exits. If the loop dies, the next 5-minute slot restarts it.
- The legacy pass keeps its 5-minute grid inside the loop: minutes divisible by `legacy_grid_min`.
- Until the packet is installed, the one-shot `*/5` run does the legacy pass plus one tick of the new path. Shadow
  data therefore starts at 5-minute granularity the moment this PR is served.

## Lifecycle rules (v1 priors, `active_trader_premarket:` — operator-ratified)

All states are judged on the **closed** candle. `prior_high` is the PM high before that candle.

| state | when |
|---|---|
| WATCH | today's PREMARKET_WATCH gates pass (price, float, gap, PM volume, rotation, above PM VWAP, fresh quote, book/tape) |
| APPROACHING | close within `approach_pct` (3 %) of the PM high |
| ARMED | within `arm_pct` (0.75 %), 1-min volume ≥ `arm_vol_mult` (1.2×) the session median, book not ask-heavy |
| TRIGGERED | green candle **closes** above `prior_high` on volume ≥ `trigger_vol_mult` (1.5×); break level recorded |
| EXTENDED | close ≥ break level + `extended_pct` (5 %): don't chase |
| PULLBACK_ZONE | after EXTENDED, back within `pullback_pct` (2 %) of the break, above VWAP |
| TRIGGER_CANCELLED | after TRIGGERED, a close back below the break level |
| STAND DOWN | from APPROACHING or later: `stand_down_vwap_bars` (2) closes below PM VWAP, or a hard gate fails (price band, gap, float, no bars). It then holds for `reopen_after_min` (10) before any new pre-trigger state |

- Pre-trigger states only escalate until a STAND DOWN, so a name hovering at a threshold does not chatter.
- A plain WATCH that fades is dropped **without** a message. A STAND DOWN message is only for a name that was
  getting close. A dropped WATCH that comes back is not re-sent (same state as the thread's last).
- A one-minute soft veto (for example a wide spread) holds the current state.
- The evidence gate is unchanged:
  - `downgrade`: the message says UNVALIDATED;
  - `hold`: journal only.

## Threading, caps and priority

Messages go through `scripts/lib/unified_momentum_alert.emit`, with origin `active_trader_premarket` and the
symbol's `momentum` thread.

- **Same state.** A state equal to the thread's last emitted one is `DEDUPED_SAME_STATE`.
- **Hourly cap.** `max_msgs_per_symbol_hour` (6) is enforced inside `emit` under the ledger lock. The next state
  change past the cap is recorded `CAPPED_PER_HOUR` and not sent. STAND DOWN and TRIGGER CANCELLED correct an alert
  already sent, so they are never capped (`momentum_alerts._INFO_KINDS`).
- **Priority.** Every premarket state is sent **P1**. 06:00–07:00 is inside the 22:00–07:00 quiet hold, and the
  operator asked for alerts from 06:00.
- **Live delivery.** In live mode the send goes through the host gateway (`send_telegram` notification intent,
  replies to the thread root per chat). A failed threaded send falls back to the legacy transport
  (`momentum_alerts.telegram_send`), so the operator is never left with nothing.

## The evidence block (`MomentumEvidenceBlock@v1`)

`scripts/lib/momentum_setup_evidence.evidence_block(evidence, extra_facts=…)` and `format_evidence_block(block)`
are the **single definition**. Inputs are:

- the five cached source facts (price, float, RVOL, gap, verified catalyst);
- the live facts measured on the candle, book and tape: gap, scan RVOL, 1-min volume vs median, above VWAP, book
  bid/ask with source and age, tape buys.

The three lines are:

- `Driven by:` the passed facts that move a name;
- `Ready:` every passed fact;
- `Missing:` every failed or unknown fact, with why.

Nothing is invented: absent data is `Missing … unknown`.

> **For the Trade AI ↔ Active Trader alignment work:** no shared evidence object existed on 2026-10-23 (no open PR
> or branch matching align / evidence carried one; `~/wt-at-align` had no changes). This is now the shared
> definition. Render it from here rather than re-deriving it.

## Focus list (`ScalpFocusList@v1`)

The focus list extends the hot list rather than duplicating it. The hot list
(`run_finviz_momentum_scalp_scan.py --hot-list-only`, lane `scalp-hot-list`) keeps Finviz membership fresh every
2 minutes. It has no rank and no size. The focus list ranks that pool each minute.

**Ranking.**

- **Pre-rank (whole pool).** One batched `get_market_snapshot` call (no subscription) gives change, PM volume vs
  float and scan RVOL.
- **Closed-candle rank (contenders).** The top `ceil(1.5 × N)` names and the current members are re-ranked on the
  closed candle. Components:

  | component | weight |
  |---|---|
  | RVOL | 0.25 |
  | % change | 0.20 |
  | volume vs float | 0.15 |
  | L2 bid/ask | 0.10 |
  | tape buys | 0.10 |
  | five-fact evidence count | 0.10 |
  | recency of the last new high | 0.10 |

  An unknown input counts 0.

**Membership with hysteresis.**

- **Entry.** A name enters at rank ≤ N while there is room.
- **Full list.** An entrant at rank ≤ N displaces the worst-ranked member only if it outranks that member by at
  least `ceil(0.5 × N)` places. Two names swapping at rank N/N+1 therefore never flap.
- **Leaving.** A member leaves after `exit_minutes` (5) consecutive minutes below rank `ceil(1.5 × N)`, or at once
  on stand-down or invalidation (float or price out of band).
- **Protection.** A member is **never** dropped or displaced while ARMED or TRIGGERED. A `HOLD` event records why
  it stayed.
- **Reasons.** Every entry and exit is recorded with a reason:
  - `entered: RVOL 14x, +22%, rank 6`
  - `left: faded below VWAP, rank 41 for 5 min`
  - `left: displaced by G (rank 1) at rank 7`

- **Cooling off.** A name that left on a stand-down cannot re-enter until `reopen_after_min` has passed.
- **Price band.** A current member keeps a 3 % price-band tolerance, so a name trading at the $1.00 edge does not flap
  in and out.

**Stores.** The single writer is `premarket_watch.py`:

- `<state>/data/runtime/scalp_focus_list.json` (atomic);
- `<state>/data/runtime/scalp_focus_events.jsonl` (append-only).

**Readers.** One source:

- `lib.data_broker.scalp_list.get_focus_list()` (Trade AI page);
- `GET /api/v3/active-trader/alerts` → `focus_list` (Active Trader page);
- the critique gate.

**Critique gate (`scalp_focus.critique_gate: focus`).** Hermes scalp catalyst research
(`hermes_momentum_catalyst_researcher.py --source scalp`) researches only focus names while the list is fresh
(`fresh_s` 180 s).

- With no fresh list (outside 06:00–09:29, legacy cadence, writer down) the selection is unchanged. This is
  fail-soft, never a silent stop.
- The Active Trader recorder's live symbols (your fills first, cap 8) are still added.
- The counts record `focus_gate_applied` and `focus_gate_skipped`.

**Not yet scoped.**

- The recorder (`microstructure_recorder.py`, outside this grant) still picks its own 10 symbols. Pointing it at
  the focus list is a follow-up that needs an execution-engineering grant naming that file.
- The focus list covers the premarket window. RTH (09:30–11:55) is the RTH engine's.

## Rollout — `active_trader_premarket.cadence_mode`

| mode | legacy 5-min heads-up | 1-min threaded lifecycle | focus list / critique gate |
|---|---|---|---|
| `legacy` | sent as today | not run | not written → critique unchanged |
| `shadow` (default) | **sent as today** (the only sender) | logged to the unified ledger as `SHADOW_LOGGED` + `momentum_alerts_premarket_1m.jsonl`; nothing sent | written each minute; critique limited to focus names |
| `live` | journaled, **not sent** | sent: one in-thread message per state change (legacy transport if the threaded send fails) | same |

Two things limit live mode:

- `unified_momentum_alert.mode: off` (the global kill switch) turns the new emit off, and the legacy path sends.
- `active_trader_premarket.mode: shadow` means nothing is sent by either path.

### Before switching to live — the comparison

```
python3 scripts/premarket_cadence_compare.py --day 2026-10-24          # per symbol: old first alert, new first
python3 scripts/premarket_cadence_compare.py --day 2026-10-24 --json   # message + state, latency gained, focus in/out
```

### Flip to live (operator)

In `config/scalp_signal_engine.yaml`:

```yaml
active_trader_premarket:
  cadence_mode: live
```

Serve that change before 06:00 ET. **Rollback:** set `cadence_mode: shadow` (or `legacy`) in the served config. The
loop re-reads `active_trader_premarket:` on every tick, so the change applies at the next closed candle with no
restart. The `PREMARKET_DISABLED` kill file still stops everything.

## Operator packet — cron (`docs/ops/packets/premarket-1min-20261023/`)

The packet makes two exact-text crontab edits:

- the premarket line becomes `--apply --loop` with timeout 13200;
- the Finviz scalp-scan line splits into:
  - `*/5 6-9 … --refresh-if-older-min 5`
  - `*/5 10-11 … --refresh-if-older-min 15`

The packet script:

- takes a backup;
- refuses inside 05:55–09:35 ET;
- reads the crontab back into a file before any grep (no SIGPIPE false-FAILED, #1965).

**Finding (2026-10-23, read-only).** The hot-list line (`*/2 6-9`) shares the Finviz refresh receipt and already
keeps it ≤ 2 minutes old from 06:00 to 09:58. The 5-minute threshold therefore acts only when the hot line fails.
It is a safety net, not a speed-up.

## Dry run — replay of 2026-10-23 (read-only)

`~/.cache/rtc/replay/replay_1m.py` is not committed. It drives `evaluate_1m` with:

- today's premarket recorder bars (14 names: the recorder's names that had a premarket row in the AT journal);
- prev close and float from those rows;
- a MemoryLedger, with every store redirected to `~/.cache`.

There was no book or tape, and no scan RVOL, so the gates are the candle's alone. Results:

- **First version:** 36 shadow messages, mostly WATCH ↔ STAND DOWN on names oscillating around PM VWAP.
- **After the quiet WATCH drop and the 10-minute reopen:** 15 messages over 209 ticks.
- **Focus list:** 11 names at 06:01. 9 in/out events over the session; each exit was a stand-down, each re-entry came
  after the cool-off.
- **SAIQ:** the old path's first alert was at 07:05. The new path opened the thread at 06:29 (WATCH) and moved to
  APPROACHING at 06:32.

## Stores and journals

| file | schema | writer |
|---|---|---|
| `data/runtime/scalp_focus_list.json` | ScalpFocusList@v1 | premarket_watch (via lib/scalp_focus.save) |
| `data/runtime/scalp_focus_events.jsonl` | ScalpFocusEvent@v1 | same |
| `data/active_trader/momentum_alerts_premarket_1m.jsonl` | PremarketCadence@v1 / PremarketCadenceTick@v1 | premarket_watch |
| `data/active_trader/momentum_alerts_premarket_lifecycle.json` | per-day state memory (state, break level) | premarket_watch |
| `data/runtime/unified_momentum_alerts.jsonl` | UnifiedMomentumAlert@v1 (origin `active_trader_premarket`) | lib/unified_momentum_alert |

The 1-minute journal is a separate file. Its rows never enter the AT alert journal, so the recorder's
"alerted today" pick and the AT page counts are unchanged.

## Tests

`tests/test_premarket_1min_threaded_20261023.py` (CI gate `premarket_1min_threaded_20261023`) covers:

- **Cadence and alignment:** 1-minute cadence; candle-close alignment, where the forming bar is never used; the
  legacy 5-minute grid.
- **No overlap and loop end:** an overrun skips minutes; the run lock; window end and kill file.
- **Lifecycle threading:** state changes with no repeats; the hourly cap, with STAND DOWN never capped; stand-down
  below VWAP.
- **Messages and delivery:** the evidence block on every message; shadow sends nothing new; live replies to the
  root; the legacy fallback; legacy, shadow and live wiring of the legacy send.
- **Focus list:** size cap and reasons; hysteresis without flapping; the exit rule; no eviction while ARMED or
  TRIGGERED; displacement margin.
- **Critique:** runs only for focus names (Hermes `_execute`).
- **Report, packet and registry:** the comparison report; the packet (preview, apply, idempotent, refuse on text
  drift, no pipe into an early-exit reader) against a fake crontab that dies on SIGPIPE; registry pending rows.

Grant: `execution-engineering` 423dbe39 (2026-10-23, A1/A2 only) names `premarket_watch.py`, `momentum_alerts.py`,
`microstructure_signals.py`, `momentum_alerts_api.py`, `read_api.py`, `signal_calibration.py` and `kill_switches.py`.
This PR edits `premarket_watch.py` and `momentum_alerts_api.py` only.
