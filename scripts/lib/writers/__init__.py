"""One write module per store (AGENTS.md §7A, Phase 9).

Each module here owns the INSERT/UPDATE SQL for exactly one table: column list,
conflict rule, coercions, plausibility rails, provenance and identity. Producers
import and call; none carries its own SQL for the store.
"""
