# Macro vintage policy

Historical evaluation must distinguish what was known at decision time from
what is known now.

## Invariant

For a historical case, never inject a later revision as though it was known at
the decision date.

## Implementation

- `macro.get_vintage(series_id, decision_date)` uses ALFRED
  `realtime_end = decision_date` and returns only observations dated
  `<= decision_date`.
- `macro.compare_vintages` returns `decision_time_value`, `latest_revised_value`,
  `revision_delta`, and `vintage_date`.
- `macro.get_decision_time_snapshot` snapshots multiple series as-of a date.

## Tests

`test_fred_alfred_provider.py` proves a later revision (5.9) does not leak into
a 2024 decision that only had 5.5.
