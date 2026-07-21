# Alpaca Live Accounts (Taxable + IRA) — Roadmap

**Canonical account keys (D1, 2026-07-21):**

| account_key | environment | credential_slot | Status |
|-------------|-------------|-----------------|--------|
| `tradeai_automated` | paper | `ALPACA_PAPER` | **LIVE Path A** |
| `alpaca_taxable_live` | live | `ALPACA_TAXABLE` | **DISABLED scaffold** (R4) |
| `alpaca_ira_live` | live | `ALPACA_IRA` | **DISABLED scaffold** (R4) |

**Supersedes:** `paca_personal` / `paca_ira` naming in earlier drafts (`paca-accounts.md` is a pointer stub).

## Data-layer arm guard (Alpaca-only)

`broker_accounts` CHECK `broker_accounts_alpaca_live_arm_chk` refuses
`broker='alpaca' AND environment='live' AND is_enabled` unless `live_arm_token` is
non-empty. **This guarantee is Alpaca-specific** — Schwab live rows use the separate
pilot-arm / `BROKER_LIVE_ENABLED` / Stage-2b stack and are **not** covered by this
CHECK (defensible; do not assume a general live-arm data rule).

## Live registry rows (verified 2026-07-21)

| account_key | environment | is_enabled | api_read | api_write | credential_slot | armed |
|-------------|-------------|------------|----------|-----------|-----------------|-------|
| tradeai_automated | paper | t | t | t | ALPACA_PAPER | f |
| alpaca_taxable_live | live | f | f | f | ALPACA_TAXABLE | f |
| alpaca_ira_live | live | f | f | f | ALPACA_IRA | f |

R4 insert is real: both live scaffolds exist as DISABLED rows. Interlock resolves
them as `environment=live` → REFUSE while `live_trading_allowed=false`.

## Read-only data path (built 2026-07-21)

| Piece | Path / endpoint |
|-------|-----------------|
| GET-only client | `scripts/brokers/alpaca_read_client.py` |
| Sync | `scripts/alpaca_live_read_sync.py` (cron: `install_alpaca_live_read_sync_cron.sh`) |
| Toggle | `POST /api/v2/broker-accounts/api-read-toggle` — **api_read only** |
| Probe | `POST /api/v2/broker-accounts/test-connection` — GET `/v2/account` |
| Admin UI | System → Admin → Alpaca Live — Read-Only Data |

With `api_read_enabled=false` (default), cron makes **zero** Alpaca API calls and never touches holdings.

## Not built

- Live submit adapter (`alpaca_factory` raises `NotImplementedError` for live)
- Live API key population (slots only in secrets modal)
- Enabling `api_read` / arm / write (operator-gated; left false this session)

## Activation prerequisites (future session)

1. Operator research on Alpaca IRA product constraints (external)
2. Fill `ALPACA_TAXABLE_*` / `ALPACA_IRA_*` via secrets modal
3. Enable `api_read_enabled` only (data) via admin panel when ready to pull positions
4. Set `live_arm_token` + `is_enabled` only after arm protocol (Alpaca-specific CHECK) — **execution path, not this session**
5. Build live adapter with ExecutionGuard parity to Schwab Path B
6. Mark `account_capabilities.verified=true` after portal confirmation

## See also

- `docs/brokers/trading-environments.md`
- `docs/brokers/tradingview-lanes.md`
- `docs/_findings/alpaca_taxonomy_audit_2026-07-21.md`
- Build session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`
