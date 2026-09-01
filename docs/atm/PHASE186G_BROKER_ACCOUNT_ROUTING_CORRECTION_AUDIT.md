# Phase 186G: Broker/Account Routing Correction Audit

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Correct Model

- **Broker**: Alpaca
- **Account mode**: paper
- **Account label**: alpaca_paper
- **Live account**: BLOCKED (RuntimeError in adapter)

## Database Schema (Correct)

The `accounts` table correctly separates broker from mode:
```sql
INSERT INTO accounts (account_label, broker, mode, ...)
VALUES ('alpaca_paper', 'alpaca', 'paper', ...);
```
- `broker TEXT NOT NULL` → 'alpaca'
- `mode TEXT NOT NULL CHECK (mode IN ('paper', 'live'))` → 'paper'

## Field Usage Audit

### `paper_trades.broker` DEFAULT 'alpaca_paper'
- **Assessment**: This is an account label, not a broker name. The label `alpaca_paper` encodes both broker (alpaca) and mode (paper). While semantically imprecise, it's used consistently as a routing key that maps to the `accounts` table where `broker='alpaca'` and `mode='paper'` are stored separately.
- **Breaking change risk**: HIGH — renaming this default would break all existing records and queries.
- **Recommendation**: Leave as-is. The `accounts` table is the authoritative source of truth for broker/mode separation. The `broker` column in `paper_trades` stores the account label, not the broker name.

### `atm_config.yaml` key `alpaca_paper`
- **Assessment**: Correct. This is the account label, matching the `accounts` table.
- **No change needed**.

### `proposed_account` DEFAULT 'TOS_PAPER' (legacy)
- **Assessment**: STALE. Legacy from ThinkOrSwim era. Current proposals use 'alpaca_paper'.
- **Impact**: Low — the default is rarely hit since proposal generation sets the account explicitly.
- **Fix**: Non-breaking — change default in future migration.

### `ALPACA_MODE=paper` env var
- **Assessment**: Correct. This is the account mode, not the broker.
- **No change needed**.

### Hardcoded 'paper' as broker
- **Found**: `report_phase8_lifecycle_linkage.py:54` queries `WHERE broker='alpaca_paper'`
- **Assessment**: This uses the account label correctly (matching the column default).
- **Recommendation**: Document that `paper_trades.broker` stores account labels, not broker names.

## Summary

| Check | Result |
|-------|--------|
| Broker is Alpaca | YES (accounts.broker='alpaca') |
| Account mode is paper | YES (accounts.mode='paper', ALPACA_MODE=paper) |
| Hard-coded "paper as broker" | NO — 'alpaca_paper' is an account label, not a broker name |
| Live Alpaca endpoint reachable | NO — blocked by RuntimeError in adapter |
| Paper Alpaca endpoint used | YES — paper-api.alpaca.markets |

## Recommendation

No code changes needed. The terminology is consistent: `alpaca_paper` is an account label that maps to `broker=alpaca, mode=paper` in the `accounts` table. Renaming would break existing data with no functional benefit.
