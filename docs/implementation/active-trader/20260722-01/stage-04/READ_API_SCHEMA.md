# Read API Schema — Stage 4

## Success envelope (every 200)
```yaml
api_version: v3
service: active-trader-read
environment: SHADOW | SIMULATION      # LIVE is unrepresentable in this process
request_id: <uuid, echoed in x-request-id header>
generated_at: <iso>
data_as_of: <max source observed_at | null>
source_sha: <git sha of serving code>
sources:                              # ≤10
  - source_name: lab:<table> | <snapshot filename>
    source_type: LAB_DATABASE | SNAPSHOT
    observed_at: <iso|null>
    expires_at: <iso|null>
    freshness_state: FRESH | AGING | STALE | UNAVAILABLE
    evidence_ref: <ref|null>
warnings:                             # ≤20; categories:
  # STALE UNAVAILABLE PARTIAL CONFLICT NOT_INSTALLED NOT_CONFIGURED UNVERIFIED REDACTED
data: <route payload>
```

## Error envelope (every non-200)
```yaml
api_version: v3
service: active-trader-read
request_id:
generated_at:
error: {code, message, retryable, operator_action}
warnings: []
```
Statuses: 400 invalid query/symbol · 401 unauthenticated · 403 environment/CORS
forbidden · 404 not found · 405 non-GET · 409 unresolvable conflict (reserved; none
served in Stage 4 fixtures) · 422 invalid filter/pagination · 429 rate limit ·
500 internal (message is exactly "internal error" — no traceback/SQL/DSN/token) ·
503 required test source unavailable.

## Unavailability discipline
Values that do not exist are served as explicit `null` / `"UNAVAILABLE"` / `"UNKNOWN"` /
`"NOT_INSTALLED"` per the typed contract — never fabricated from unrelated fields
(tested: TESTB candidate, symbol microstructure, position marks/P&L).

## Sensitive-value policy
Account identifiers only as `masked_account_id` (`***<tail>`); authorization hash only
as a ≤12-char short hash; rejections stored AND served redacted; journal returns replay
references only. Response bodies are tested to exclude DSN/token/credential markers.
