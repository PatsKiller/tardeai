"""One write module per store (AGENTS.md §7A, One Source of Truth phase 9).

Each module under this package owns the INSERT/UPDATE SQL for exactly one
store. Producers import the module and call it; they never carry their own SQL
for that table. `scripts/check_data_source_authority.py` counts the files that
write each table and fails when the count rises above the baseline.
"""
