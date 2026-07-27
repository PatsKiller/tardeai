# Read API Architecture — Stage 4

## Topology
```text
create App (factory)                       dev server (manual, gated)
  dsn = ACTIVE_TRADER_READ_API_DSN  ──►  python scripts/active_trader/read_api.py
  environment = SHADOW|SIMULATION           bind 127.0.0.1:8134 (loopback enforced)
  identities = injected test ids            default DISABLED; LIVE unrepresentable
  allowed_origin = None | one localhost
        │
        ▼
  App.request(method, path, query, headers)      ← transport-independent core
        │ 405 non-GET · 401 unknown identity · rate limits · envelopes
        ▼
  handlers (15 GET routes)
        │                         │
        ▼                         ▼
  ReadStore (read_queries.py)   snapshots/fixtures
   trade_ai_test via             stage-02 live_probe_result.json (committed evidence)
   trade_ai_lab_ro               SYNTHETIC candidates fixture
   (SELECT-only · read-only     (freshness computed; UNAVAILABLE explicit)
    session · 5s timeout)
```

## Framework decision (documented per ruling)
The repo's server stack is stdlib `http.server` (portfolio_server.py). No Flask/FastAPI
exists in requirements and adding one is prohibited — so the dev wrapper is a ~40-line
stdlib `ThreadingHTTPServer` handler delegating everything to `App.request`. Domain and
query logic never import the transport; Stage 6+/later mounting reuses `App` unchanged.

## Data flow guarantees
- ONLY trade_ai_test (guarded: explicit DSN required, no env fallback, production
  name/port refused) + committed snapshots/fixtures. No production DB, no live broker,
  no credential read, no token refresh, no Bitwarden-production call, no Moomoo.
- Separate identities: fixture loader uses trade_ai_lab (write); API runtime uses
  trade_ai_lab_ro (SELECT-only; INSERT/UPDATE/DELETE/DDL proven to fail; read-only
  session; statement_timeout 5s; application_name at-read-api).
- LIVE rows are excluded by SQL (`environment <> 'LIVE'`) AND the App cannot even be
  constructed with environment LIVE.

## Observability
In-memory metrics: per-endpoint request counts, status counts, latencies, warning
totals, rate-limit count. Dev server disables the default access log so no identifier
reaches stderr; every response carries x-request-id. Nothing logs query values, account
ids, DSNs, tokens, or headers.
