# Security and Redaction Report — Stage 4

## Attack-surface posture
- Loopback-only listener, manual start, default disabled, no unit/proxy/firewall change.
- GET-only; every non-GET returns 405; no handler mutates state; the notifications
  endpoint cannot ack/resolve/escalate; the features endpoint cannot flip flags
  (asserted in-handler: production effective modes are always OFF).
- Environment LIVE is unrepresentable: refused at App construction, refused by the dev
  server gate, and excluded from order/position SQL.

## Authentication and CORS
- Test identity is registered ONLY through the app factory; a bare
  `x-at-test-identity` header with an unregistered value → 401 (tested with a forged
  value). No production auth was invented.
- CORS disabled by default; test profile allows exactly one explicit localhost origin;
  wildcard `*` is refused at the factory (tested).

## Injection and input handling
- All SQL parameterized; filter/sort fields allowlisted; injection strings stay values
  (tested; table existence re-verified after attempts).
- Symbol input conservatively validated; traversal/control chars/overlong → 400.
- Cursors are opaque; invalid → 422. Date ranges capped at 92 days.

## Redaction guarantees (tested)
- Account identifiers only as `***tail` masked fields; no `account_number` field is
  ever served; authorization hash only as a ≤12-char short hash.
- Rejections stored redacted (Stage 3) and served as stored; journal returns
  `replay://` references only.
- 500 responses say exactly "internal error" — no traceback, SQL, psycopg2 text, DSN,
  token, or path (tested by forcing a handler exception).
- Response bodies tested to exclude: `postgresql://`, `SCHWAB_APP`, `refresh_token`,
  `Bearer `, `APCA-API`, `BWS_`, `authorization:`.
- Dev server suppresses the default access log; nothing logs identifiers, headers, or
  query values; only masked/aggregate metrics are kept.

## Resource protection
Rate limits 120/min general + 30/min heavy per identity (429 with retryable=true);
response ceiling 1.5 MB; ≤20 warnings; ≤10 sources; DB statement_timeout 5 s;
read-only DB session (writes fail before permissions are even consulted).

## Residual risks (accepted for a dev-only stage)
- Identity is a shared-secret-less header check suitable ONLY for loopback development;
  Stage 6+ must bind real dev auth before any non-loopback exposure is even proposed.
- The rate limiter is in-process (resets on restart) — acceptable for a manual dev tool.
