"""One write module per store (AGENTS.md §7A, One Source of Truth Phase 9).

Each module here owns the INSERT/UPDATE SQL for exactly one table. Producers
import and call it; they never carry their own SQL for the store.
"""
