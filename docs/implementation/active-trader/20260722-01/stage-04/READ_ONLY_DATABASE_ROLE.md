# Read-Only Database Role — Stage 4

Provisioning script (committed, idempotent, secret-free):
`scripts/active_trader/provision_read_api_role.sh` (`--rotate` regenerates the password
and updates the Bitwarden secret).

## Identity separation
| Purpose | Role | Rights |
|---|---|---|
| Migrations + fixture loading (test setup) | `trade_ai_lab` | owner of trade_ai_test objects; create/drop in test DB only; refused by prod cluster |
| API runtime | `trade_ai_lab_ro` | LOGIN only; CONNECT + USAGE + **SELECT-only** (incl. default privileges for future tables); NOSUPERUSER/NOCREATEDB/NOCREATEROLE |

## Session-level enforcement (role settings, proven by tests)
- `default_transaction_read_only = on` → INSERT/UPDATE/DELETE/DDL fail with
  "cannot execute ... in a read-only transaction" even before permission checks
- `statement_timeout = '5s'` (verified via SHOW in-session)
- `application_name = at-read-api` (in DSN)
- No migration rights; no table ownership; production cluster refuses the role
  (it does not exist there); the ReadStore guard additionally refuses any DSN naming
  `trade_ai` or targeting port 5432, requires an explicit DSN (no env fallback), and
  accepts only `trade_ai_test`.

## Secret handling
DSN stored ONLY as `ACTIVE_TRADER_READ_API_DSN` in Bitwarden project `trade-ai-lab`,
written via the lab machine-account token (`~/.openclaw/credentials/bws_lab_token`).
Value never printed, committed, uploaded, or emailed.

## Proof (test_api_identity_cannot_write, run 3×)
SELECT ✓ · INSERT ✗ · UPDATE ✗ · DELETE ✗ · CREATE TABLE ✗ · statement_timeout=5s ✓ ·
default_transaction_read_only=on ✓ · production DSN refused ✓
