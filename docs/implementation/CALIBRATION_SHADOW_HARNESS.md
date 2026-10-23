# Calibration shadow harness

```
Status:      ACTIVE (n8n lane at stage shadow; contract DRAFT, owner review required)
as_of:       2026-10-22T20:30:00-04:00
Measured at: base b9804fa57 (origin/main); journals under ~/trade-ai-releases/persistent-state/data/active_trader/learning, read-only
```

Operator-approved design, 2026-10-22. `signal_calibration` already measures the journaled Active Trader
decisions and **proposes** threshold changes. This harness tests each proposal **forward** before the operator
decides. Approval stays with the operator; a one-click approval in Ops is a later step.

## What it does

`scripts/calibration_shadow_harness.py` (`CalibrationShadowReport@v1`) works in three steps.

1. **Opens trials.** Every `PROPOSED` threshold in `<AT dir>/learning/calibration_report.json` becomes a trial
   keyed by its knob.
   - The proposed value is **frozen** at first sight.
   - `first_seen_session` is the last session the proposal was fitted on.
   - A later proposal within `drift_tolerance` (10%) of the frozen value keeps the trial.
   - A proposal that drifts further supersedes the trial. One that disappears withdraws it. Both stay in
     `history`; nothing is deleted.
2. **Evaluates forward.** Over the next `sessions` (5) sessions after `first_seen_session`, it applies the
   current threshold and the frozen proposal to the same journaled decisions
   (`trade_learning.jsonl`, `type: decision` with an outcome). It reads only; no fitted session enters the
   forward window. For each side it counts:
   - decisions admitted;
   - WORKED, STOPPED and NO_TOUCH;
   - worked rate;
   - mean rule-exit %;
   - worked decisions dropped and stopped decisions avoided.

   An `in_sample` block over the fitted sessions is kept beside it, labelled IN_SAMPLE.
3. **Recommends.** Each trial gets one of:
   - `IN_PROGRESS`: fewer than N forward sessions so far;
   - `INSUFFICIENT_SAMPLE`: fewer than `min_sample` decisions admitted;
   - `RECOMMEND_ADOPT`: worked rate is at least `min_edge` better and the mean exit is not more than
     `max_exit_regression_pct` worse;
   - `RECOMMEND_REJECT`;
   - `NO_CLEAR_EDGE`.

   Each one carries "PROPOSED — operator ratifies; config is unchanged until then". The harness never writes
   config.

**Current value.**
- It comes from `config/scalp_signal_engine.yaml` at the knob path, else from `current_values` in
  `config/calibration_shadow_harness.json` (labelled *declared*).
- Otherwise it is **not computed**, and the baseline is "no threshold". The engine defaults
  (`AlertConfig`) live in the broker execution file set, which the harness does not read.
- `current_scale` converts config units to feature units.

## Fixed: proposal units

`min_stop.pct_of_price` is a fraction in config (`0.01` means 1%), but `signal_calibration` proposed it in percent
from feature `risk_pct` (`1.767` on 2026-10-22): ratified as written, a minimum stop of 176.7% of price. Under grant
`e88bf21e` `signal_calibration.KNOB_UNIT_SCALE` converts: `proposed_value` is now in knob units (`0.01767`) with
`proposed_feature_value` (`1.767`) and `knob_unit_scale` beside it. The harness freezes the feature-unit value (and
reads older reports' `proposed_value` as the feature value) and scales the current value by 100.

**Current values.** `config/calibration_shadow_harness.json` declares the `AlertConfig` defaults read under the
grant (`max_spread_bps` 80, `min_buy_ratio` 0.55, `min_depth_ratio_armed` 1.0); a test pins them equal to
`AlertConfig`, so the harness compares against the real baseline without importing the broker execution set.

## n8n lane `calibration-shadow-harness`

Registered in a stacked PR (registry row, allowlist entry, DRAFT health contract,
`tests/test_calibration_shadow_harness_lane_20261022.py`) so the harness PR stays green while the contract
waits for the owner's review.

| Item | Value |
| --- | --- |
| Registry row | `scheduler.kind n8n`, expression `dispatcher`, stage `shadow`, cadence `25 12 * * 1-5` ET (after `signal_calibration` at 12:10), class `report`, dispatch mode `dry_run` |
| Allowlist | `$PY scripts/calibration_shadow_harness.py`, `dry_run_arg ["--dry-run"]`, `live_arg null`, flock `/tmp/calibration_shadow_harness.lock` |
| Health contract | `config/n8n_health_contracts.json`, status **DRAFT** (AGENTS.md §23.19: only the operator reviews it) |
| Reach | no broker, no sender, no model call; the import closure is test-checked |

At shadow, a fire runs `--dry-run`. It evaluates, prints, emits `LANE_OUTPUT` and **writes nothing**.

At canary, a separate PR sets `live_arg []` and dispatch mode `live`. The lane then writes:

- `data/runtime/calibration_shadow_report.json`;
- `data/runtime/calibration_shadow_report.md`;
- the `LaneRunReceipt` `data/runtime/calibration-shadow-harness_last.json`.

Dry run on 2026-10-22 against the live journals (re-run after the grant work):

```
decisions_read 3615 · 3 trials, all IN_PROGRESS (0/5 forward sessions); current = AlertConfig defaults:
  active_trader_alerts.min_buy_ratio   current 0.55  proposed 0.434  in-sample worked rate 0.0699 -> 0.0743
  active_trader_alerts.max_spread_bps  current 80    proposed 57.75  in-sample worked rate 0.0909 -> 0.1084
  min_stop.pct_of_price                current 1 (0.01 x100)  proposed 1.767  in-sample 0.0711 -> 0.0697
LANE_OUTPUT produced_count 0, empty_reason dry_run; nothing written
```

## Tests

`tests/test_calibration_shadow_harness_20261022.py`, CI gate
`config/ci_gates/calibration_shadow_harness_20261022.json`. The tests cover:

- the trial lifecycle;
- the forward window;
- the recommendation rules;
- provenance and unit scale;
- dry run writes nothing;
- a live run writes the report and receipt;
- journals and config are never written;
- the registry, allowlist and contract shape;
- the import closure.
