# Portfolio Generation Propagation Dry Run

This contract-level acceptance suite verifies that one CIO operator product is
projected to Telegram, Morning, EOD, and Command Center without regenerating a
channel-specific decision. Every projection retains `generation_id`,
`product_id`, `workflow_id`, and `portfolio_snapshot_id`.

The suite also distinguishes explicit `CASH_DEPLOYMENT` from `REBALANCE`.
Both may use the same portfolio snapshot; a non-zero cash balance alone must
not relabel a rebalance or authorize deployment.

Evidence class: `DRY_RUN`. No provider, Telegram, broker, or production store
is accessed.
