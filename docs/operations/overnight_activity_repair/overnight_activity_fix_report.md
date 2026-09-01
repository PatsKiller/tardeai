# Fix Report

Status:      ACTIVE
as_of:       2026-05-21T15:13:01-04:00
Measured at: efcc51365 / not measured

## Changes

### 1. scripts/db_adapter.py
Added `_load_dotenv_if_needed()` function that runs at module import:
- Checks if `DB_PASSWORD` is already set in environment
- If not, reads `.env` file from project root
- Only loads keys prefixed with `DB_` to avoid side effects
- Skips keys already present in `os.environ`

### 2. scripts/incubator_proposal_promoter.py
Three changes in the pre-promotion readiness gate:

**a) Fixed RealDictRow parsing:**
- Before: `_sa_row[0]` → `KeyError(0)` on RealDictRow
- After: `_sa_row.get('age_h')` → correct dict access

**b) Added market_quote_snapshots as quote source:**
- New query checks `market_quote_snapshots` for quote age
- Passes `quote_age_hours` and `quote_checked_at` to readiness gate
- Symbols refreshed via Q-1 proactive quote refresh now clear the gate

**c) Added transaction recovery:**
- `except` blocks now call `conn.rollback()` to prevent transaction poisoning
- Logged warnings instead of silent `pass`

### 3. .pgpass (local machine only, not committed)
Added `localhost:5432:trade_ai:trade_ai:PASSWORD` to match db_adapter's `host='localhost'` connection.
