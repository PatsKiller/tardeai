# Operator Command Surface
Generated: 2026-05-19T20:13:23.361494+00:00

## P0 — Immediate Attention (0 items)
- None

## P1 — Digest (0 items)
- None

## P2 — Dashboard Counts
- pending_proposals_count: 0
- open_trades_error: column "entry_date" does not exist
LINE 1: SELECT id, symbol, strategy_id, entry_date, entry_price FROM...
                                        ^
HINT:  Perhaps you meant to reference the column "paper_trades.entry_time".

- watchpool_error: current transaction is aborted, commands ignored until end of transaction block


## P3 — Log / Background
- system_health_status: unknown
- system_health_message: 
- log_file_count: 953

## Page Destinations
- pending_proposals -> `/v2/approvals`
- open_trades -> `/v2/paper-journal`
- watchpool_candidates -> `/v2/trade-ai`
- system_health -> `/v2/risk`
