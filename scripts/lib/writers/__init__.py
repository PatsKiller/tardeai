"""One write module per store (One Source of Truth, Phase 9).

Each module here owns the INSERT/UPDATE SQL for exactly one table: the column
list, the conflict rule, type coercion, plausibility rails, provenance and
identity. Producers import and call; they never carry their own SQL for the
store. `scripts/check_data_source_authority.py` counts the files that write
each declared store and fails when the count rises above its baseline.
"""
