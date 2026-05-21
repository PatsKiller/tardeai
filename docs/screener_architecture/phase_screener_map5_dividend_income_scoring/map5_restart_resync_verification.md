# MAP-5 Restart & Drive Resync Verification

**Date:** 2026-05-21

## Restart
- Command: `pkill -f portfolio_server.py; nohup .venv/bin/python scripts/portfolio_server.py &`
- Result: Server started successfully

## Health Checks
| Endpoint | Status |
|----------|--------|
| /api/v2/overview | 200 OK |
| /api/v2/paper-proposals | 200 OK |
| HTTPS (Tailscale) | 200 OK |

## Drive Sync
- Result: Uploaded successfully

## Safety After Restart
- ALPACA_MODE=paper: Verified
- LLM_DISABLE_LIVE_EXECUTION=true: Verified
- Holdings: $1,195,947 (47 holdings, guard PASS)
- Trades created: NO
- Orders submitted: NO
- Live trading: NO
- Strategy activation changed: NO
- YAML changed: NO
- Finviz criteria changed: NO
