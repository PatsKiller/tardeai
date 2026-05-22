# System Facts — Latest

Generated: 2026-05-22T20:30:00Z (post ATM-SAFE-1)

## Runtime
- Hostname: ms01-openclaw
- Python: 3.13.7
- Portfolio: $1,201,120 / 47 positions

## Database
- Connected: True
- Tables: 376
- paper_trades: 5 open, 11 closed (30d)
- paper_trade_proposals: 5 pending, 111 total
- incubator_universe: 1,533 active
- strategy_registry: 23 active strategies
- atm_decision_log: 105 decisions today
- enrichment_log: active (new)
- audit_log: 45 entries (24h), schema fixed

## ATM State
- Mode: dry_run (frozen by ATM-SAFE-1 at 16:13:49 ET)
- Config hash: e0671b4e944f
- Classifier health threshold: 0.0 (temp cold-start bypass)
- B-1 observation: active, expires 2026-05-25
- Auto-enrichment: active (*/5 cron, non-blocking AI review)
- Strategies with health baseline: 0 of 23

## Execution Safety
- ALPACA_MODE: paper
- LLM_DISABLE_LIVE_EXECUTION: true
- Quote fail-closed: enforced (blocks if no price source)
- Audit logging: fixed (event_type column)
- Risk gate on promoter: active
- Enrichment pre-check on ATM: active

## Codebase
- Cron jobs: 142
- API endpoints: 217
- Dashboard pages: 80
- Screeners: 18 active
- Orchestrator windows: 0900, 1000, 1200, 1400, 1600, 1730

## Paper Trading Performance (30d)
- Closed: 11 trades (5W / 4L / 2 broker-review)
- Win rate: 45.5%
- Total P&L: $379.45
- Avg R: 0.13R
- Open: 5 positions (NWG, NVDA, AGNC, CMCSA, ASPN)

## Maturity (post-STOP-V2)
- Overall: 7.0 / 10.0
- Execution safety: 8.5
- Paper governance: 7.5
- Stop protection: 8.5 (NEW)
- Auditability: 7.0
- Quote readiness: 7.0
- Strategy proof: 3.5
- Live readiness: 2.0
- Operational: 7.5
