"""One write module per store (One Source of Truth, Phase 9; AGENTS.md §7A).

Plural PRODUCERS of a store are by design; plural WRITE PATHS are not. Each
inline INSERT carried its own column list, conflict rule and coercions, and
they drifted -- the Finviz column shift put ten-year performance in a 1-5
rating column for five months because two parsers each owned their own write.
Here the SQL for a store lives in exactly one function that also owns the
plausibility rails, provenance and identity resolution; every producer imports
and calls it and none carries its own SQL for the store.

``check_data_source_authority.count_writers`` counts the FILES whose text
contains ``INSERT INTO / UPDATE / COPY <table>``. A module in this package is
therefore the one file allowed to say so for its table; producers, and the
target modules that re-export these functions, must not repeat the phrase --
not even in a comment.

AUTHORITY: READ_ONLY_ADVISORY with respect to trading. Data stores only; no
orders, no policy, no broker calls.
"""
