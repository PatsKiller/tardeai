# Active Trader: ARMED quality, stand-down, Trade-AI verdict (2026-10-09)

Your report: "check active trader not working keeps giving this alert is it wired correctly for scalps along with
tradeai?" The alert was XNDU ARMED with "entry 4.05 · stop 4.01 · R 0.04 · RVOL 0.6x · setup n/a".

## Findings (read-only investigation)

- **The feeds work and the logger is clean.** XNDU's ARMED went out once today.
- **The ARMED tier was too loose.** All 19 ARMED alerts ever sent came from the trigger state machine alone (lane
  BELOW, no setup). That path has no RVOL, R or setup gate, and no time limit. Only 1 of the 19 was followed by a
  TRIGGERED. The other 18 went quiet, with no stand-down message.
- **The ARMED levels were not the setup.** "Entry" was the last price and the stop was last − 1·ATR. The real break
  is the state machine's prior-bar high.
- **Repeats keyed on price.** The dedupe key was `entry:{price}`, so a 1-cent move counted as a new alert.
- **"🟢 Trade-AI" is the house pill on every message, not a verdict.** The alert universe comes from
  `scalp_scan_results`. Trade-AI marked XNDU WAIT, not tradeable, today. `not_tradeable` is set on 27 of 30
  scalp-name verdicts (10-05 to 10-09), so it cannot be used as a gate.
- **The "🧭 Conviction … R:R 3.8x" line is the CIO's multi-week swing view**, printed next to the scalp's R.
- **The microstructure recorder keeps one DB connection for the whole window.** It dies with "connection already
  closed" in the tick consumer and the end-of-window replay.

## Changes

| Change | Where |
|---|---|
| A state-machine-only ARMED reaches Telegram only with RVOL ≥ 1.5×, R ≥ 1.5% of entry, and at most 15 minutes ARMED. Otherwise it is journaled as a VETO (`ARMED_LOW_RVOL` / `ARMED_R_TOO_SMALL` / `ARMED_STALE`) and stays visible on the Active Trader page. Ignition-lane ARMED is unchanged. | `momentum_alerts.decide`, `AlertConfig` |
| ARMED entry is the prior-bar high + entry_offset and the stop is the pullback low − stop_offset (the levels a fire would use). The headline reads "trigger above X, now Y". | `momentum_alert_pass.armed_levels`, `build_message` |
| ARMED dedupe is per setup leg (`leg:{leg_high}`), not per last price. | `level_key` |
| **STAND DOWN.** An ARMED sent in the last 90 minutes that goes stale (more than 15 minutes ARMED) or leaves ARMED without firing gets one closing message. No book or quote is fetched for it. | `stand_down_candidates`, kind `STAND_DOWN` |
| Every alert carries "Trade-AI today: DECISION HH:MM · not tradeable" or "no scan today". An explicit **AVOID** blocks the heads-up kinds (ARMED, APPROACHING) only. TRIGGERED is never gated by Trade-AI. | `trade_ai_today`, `trade_ai_line`, `trade_ai_block_headsup` |
| On scalp alerts the CIO line reads "🧭 CIO swing view (not this scalp): …". | `opportunity_alert.SWING_VIEW_CLASSES` |
| The recorder checks its connection with `SELECT 1` and reopens it when it has closed. | `microstructure_recorder.live_conn` |

**Replay.** Under the new floor, 18 of the 19 ARMED alerts actually sent would have been journaled, not sent; GRML
(RVOL 2.1×) still sends. The replay uses the old last − ATR stops, so it overstates `ARMED_R_TOO_SMALL`. With the
state machine's real levels, more setups will clear the R floor.

Gate: `active_trader_armed_quality_20261009`. Everything stays ALERTS ONLY: no order path, no broker write.
