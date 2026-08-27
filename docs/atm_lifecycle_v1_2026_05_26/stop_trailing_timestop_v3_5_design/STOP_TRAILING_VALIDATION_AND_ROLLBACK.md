# Stop/Trailing Validation and Rollback

## API Tests
- GET /api/v2/atm/stop-trailing-control returns 3 open trades
- GET /api/v2/atm/stop-change-audit returns events (may be empty initially)
- No order placed, no stop modified

## UI Tests
- StopTrailingControlPanel renders in ATM Control Room
- StopChangeAuditPanel renders
- No action buttons modify trading state

## Rollback
git revert HEAD
