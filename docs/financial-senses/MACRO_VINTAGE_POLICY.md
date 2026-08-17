# Macro vintage policy

Historical evaluation must distinguish what was known at decision time from
what is known now.

## Invariant

For a historical case, never inject a later revision as though it was known at
the decision date.

## Implementation

- `macro.get_vintage(series_id, decision_date)` bounds the FRED/ALFRED real-time
  period on BOTH ends — `realtime_start = decision_date` and
  `realtime_end = decision_date` — because `series/observations` defaults both to
  today, and a one-sided `realtime_end` does not select the historical
  decision-time vintage. It also sets `observation_end = decision_date` so only
  observations dated `<= decision_date` are returned.
- `macro.compare_vintages` returns `decision_time_value`, `latest_revised_value`,
  `revision_delta`, and `vintage_date`. It compares the SAME observation date
  across the decision-time vintage and the latest vintage; the `revision_delta`
  fact is timestamped `as_of` the retrieval time, never the historical decision
  date.
- `macro.get_decision_time_snapshot` snapshots multiple series as-of a date.

## Tests

`test_fred_alfred_provider.py` proves a later revision (5.9) does not leak into
a 2024 decision that only had 5.5, and `test_latest_as_of_pins_realtime_period_both_ends`
captures the REAL `FredClient` URL and asserts `realtime_start`, `realtime_end`,
and `observation_end` are all pinned to the decision date.
