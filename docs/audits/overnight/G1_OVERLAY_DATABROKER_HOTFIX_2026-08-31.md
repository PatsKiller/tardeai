# G1 overlay hotfix — state/data_broker path

G1 added `state/data_broker` to `OVERLAY_RELS`. On GOOD_PERSISTENT_ROOT the durable
files live at `data/portfolios/state/data_broker`, so `overlay_is_safe` refused
exact-main prepare (`REFUSE_EMPTY_SOURCE_TREE_OVERLAY`).

Fix: `_resolve_overlay_source` falls back to the portfolios path when
`state/data_broker` is empty. Does not merge hub vs persistent forks.
