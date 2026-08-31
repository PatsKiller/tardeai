# Root Cause Analysis

Status:      ACTIVE
as_of:       2026-05-21T15:13:01-04:00
Measured at: efcc51365 / not measured

## Root Cause 1: DB credentials not available in cron

**Mechanism:** `db_adapter.py` reads `DB_PASSWORD` from `os.getenv()`. In interactive shells, `.env` is sourced. In cron, only `PROJ` and `PY` are set as crontab variables. Without `DB_PASSWORD`, `_db_enabled()` returns False and `_get_conn()` returns None.

**Why it was silent:** `_get_conn()` prints a warning to stdout and returns None. Scripts that get None from DB queries simply process 0 candidates and exit with no log output. Cron sees exit code 0.

**Why it worked for some jobs:** `trade_ai_orchestrator.py` imports `dotenv` and calls `load_dotenv()` at module level. The proposal alerter cron entry explicitly runs `set -a && source .env && set +a`. Other jobs had no such mechanism.

**Additional factor:** `.pgpass` had `127.0.0.1:5432:trade_ai:trade_ai:PASSWORD` but `db_adapter` connects via `host='localhost'`. psycopg2 `.pgpass` matching is exact — `localhost` does not match `127.0.0.1`.

## Root Cause 2: RealDictRow integer indexing

**Mechanism:** The promoter uses `cursor_factory=psycopg2.extras.RealDictCursor`, which returns `RealDictRow` (dict-like) instead of tuples. Line 652 had:
```python
if _sa_row and _sa_row[0] is not None:
```
`RealDictRow[0]` raises `KeyError(0)` because integer keys don't exist in the dict. This was caught by `except Exception: pass`, leaving `_scan_age_hours = None`.

**Result:** Every symbol hit `quote_never_checked` blocker in the pre-promotion gate, even those with fresh quotes in `market_quote_snapshots` and `trade_ai_scans`.

**Additional gap:** The promoter only checked `trade_ai_scans` for quote age, not `market_quote_snapshots`. Symbols refreshed via proactive quote refresh (Q-1) had no scan entry, so even with correct parsing, they could still be blocked.

## Fixes Applied

1. `db_adapter.py:_load_dotenv_if_needed()` — reads DB_* vars from `.env` file when not in environment. Only loads `DB_*` prefixed keys. Runs at module import time.

2. `.pgpass` — added `localhost:5432:trade_ai:trade_ai:PASSWORD` entry (local machine change, not committed).

3. `incubator_proposal_promoter.py` — replaced `_sa_row[0]` with `_sa_row.get('age_h')` for RealDictRow compatibility. Added `market_quote_snapshots` query as secondary quote source. Added transaction recovery on query failure.
