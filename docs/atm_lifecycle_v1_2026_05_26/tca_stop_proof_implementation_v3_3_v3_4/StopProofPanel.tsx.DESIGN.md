# StopProofPanel Design

## Data source: GET /api/v2/atm/stop-proof

## Per open trade show:
| Field | Source |
|-------|--------|
| Symbol | paper_trades.symbol |
| Account | paper_trades.account |
| DB Stop | paper_trades.stop_loss |
| Stop Order ID | paper_trades.stop_order_id |
| Verified At | paper_trades.stop_verified_at |
| Status | computed from verification |
| Broker Status | from Alpaca query if available |

## Statuses:
- VERIFIED — stop_order_id exists, broker confirms
- UNVERIFIED — stop_order_id exists, not yet checked
- MISSING_ORDER_ID — no stop_order_id stored
- NOT_APPLICABLE — no stop configured

## Actions (labels only):
- Review broker stop proof
- Open trade journal
- Open broker recon

## Blocked:
- Cancel stop, Replace stop, Submit new stop, Live order
