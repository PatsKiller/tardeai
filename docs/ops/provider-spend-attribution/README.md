# Provider spend attribution

Status:      ACTIVE
as_of:       2026-08-17T18:17:51-04:00
Measured at: efcc51365 / not measured

READ_ONLY_ADVISORY. Observability / FinOps only.

## Three numbers (never mix)

- **CONSOLE_TOTAL** — vendor-billed USD for the period
- **LEDGER_ATTRIBUTED** — mapped to Trade AI ledger + OpenClaw + known bypass (excludes `test_*` and Claude Code)
- **LEDGER_GAP** = CONSOLE_TOTAL − LEDGER_ATTRIBUTED
- **HOST_ATTRIBUTED** — ledger + Claude Code / other host-local developer tools
- **HOST_GAP** = CONSOLE_TOTAL − HOST_ATTRIBUTED

## Period A/B (independently recomputed from fixture)

Supplied baseline LEDGER_GAP **$60.07** is preserved.

Independent fixture replay: CONSOLE $60.94, LEDGER $0.8673, LEDGER_GAP $60.0727, HOST $11.1673, HOST_GAP $49.7727, test-only $4.85, Claude Code $10.30, OpenClaw $0.2475.

Period A Trade AI billing-matched tokens at the **2026-08-03** schedule compute **$0.5338**, not the retroactive new-table $1.17.

Period B residual (~$12.59) is **UNATTRIBUTABLE_WITH_CURRENT_PROVIDER_DATA**: DeepSeek has no usage-by-key API; this host’s Claude JSONL is $0 in Period B; 114k tok/req mix is consistent with an off-host / other-key coding agent.

## Export-by-key

`python scripts/provider_cost_export.py --start … --end … --group-by key`

Returns `KEY_ATTRIBUTION_UNAVAILABLE` unless an operator console CSV with key columns is supplied.

## Daily job

`config/systemd/user/tradeai-provider-cost-reconcile.timer` at 06:40 local. No duplicate cron. Never auto-disables keys.
