# Alpaca Live Accounts (Taxable + IRA) — Roadmap

**Canonical account keys (D1, 2026-07-21):**

| account_key | environment | credential_slot | Status |
|-------------|-------------|-----------------|--------|
| `tradeai_automated` | paper | `ALPACA_PAPER` | **LIVE Path A** |
| `alpaca_taxable_live` | live | `ALPACA_TAXABLE` | **DISABLED scaffold** (R4) |
| `alpaca_ira_live` | live | `ALPACA_IRA` | **DISABLED scaffold** (R4) |

**Supersedes:** `paca_personal` / `paca_ira` naming in earlier drafts (`paca-accounts.md` is a pointer stub).

## Not built

- Live submit adapter (`alpaca_factory` raises `NotImplementedError` for live)
- Live API key population (slots only in secrets modal)
- Validation pings against `api.alpaca.markets`

## Activation prerequisites (future session)

1. Operator research on Alpaca IRA product constraints (external)
2. Fill `ALPACA_TAXABLE_*` / `ALPACA_IRA_*` via secrets modal
3. Set `live_arm_token` + `is_enabled` only after arm protocol (Alpaca-specific CHECK)
4. Build live adapter with ExecutionGuard parity to Schwab Path B
5. Mark `account_capabilities.verified=true` after portal confirmation

## See also

- `docs/brokers/trading-environments.md`
- `docs/brokers/tradingview-lanes.md`
- `docs/_findings/alpaca_taxonomy_audit_2026-07-21.md`
- Build session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`
