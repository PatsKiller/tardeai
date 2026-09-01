# MCP Security Model

Status:      ACTIVE
as_of:       2026-08-16T23:13:39-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY` · Phase 3

Threat model for the read-only MCP gateway. The adversary is a misbehaving or
compromised agent attempting to (a) mutate broker/order/stop/2FA/risk-policy
state, (b) reach internal network services, or (c) exfiltrate credentials or
documents.

## SSRF

- Guard: `_is_safe_host(host)`.
- Always blocks localhost, `127.x`, `0.0.0.0`, `169.254.x` (link-local /
  metadata), `10.x`, `172.16-31.x`, `192.168.x`, `::1`, and any
  private/metadata host (via `ipaddress` plus hostname suffixes
  `.localhost` / `.local` / `.internal` / `.metadata`).
- Otherwise, the host must be in an explicit safe-host allowlist passed to
  `call_mcp_tool(safe_hosts=...)`. With no allowlist, every non-private host is
  denied too (fail closed).
- URLs are extracted from request keys named `url`/`uri`/`host`/`endpoint`/
  `base_url`/`source_url`/`webhook` etc., and from any `http(s)://` string in
  the request.

## Path traversal

- Guard: `_is_safe_doc_path(path)`.
- Rejects `..` path components, absolute paths (Unix `/`, Windows `\` and
  `C:`), and any path whose resolved form escapes the allowed root.
- Applies to request keys named `path`/`file_path`/`doc_path`/`source_path`.

## Rate limits

- Not yet applied at the gateway (Phase 3). The gateway is a per-call
  chokepoint; a rate limiter (per wake / per provider) can be inserted between
  steps 6 and 7 without changing the contract. Documented here as a deliberate
  gap to close before any external provider is activated.

## Timeouts

- Providers are synchronous in-memory calls today. Before an external provider
  is wired, each adapter must bound its call with an explicit timeout. The
  gateway records latency (`latency_ms`) on every receipt so a timeout/SLA
  policy can be enforced from traces even now.

## Response size limits

- Guard: `max_response_bytes` (default 65536) in `call_mcp_tool`.
- Oversized responses are bounded: the gateway returns `status="BOUNDED"` with
  `bounded=True` and a truncated payload rather than streaming unbounded data
  into the agent context.

## Network egress allowlist

- The gateway makes **no** network calls. The only hosts that can ever be
  considered are those in `safe_hosts`, and private/metadata hosts are blocked
  unconditionally. Egress is therefore zero unless an operator explicitly
  configures a safe-host allowlist and a real (non-local) adapter.

## Per-wake authorization

- `call_mcp_tool` requires a non-empty `wake_id` and `trace_id`. Every receipt
  binds `trace_id`, `wake_id`, `agent`, `tool`, and `provider`, so a tool call
  is always attributable to a specific wake/trace. Missing ids are denied.

## Secret redaction

- `redact_secrets()` runs on every response before it is returned and before
  the receipt digest is computed. Secret-shaped keys (`api_key`, `token`,
  `password`, `authorization`, `bearer`, …) and secret-shaped values
  (`sk-…`, `ghp_…`, `xox…`, `AKIA…`, long hex) become `[REDACTED]`.
- The receipt stores only `request_digest` / `response_digest`, never raw
  bodies.

## Threat table

| Threat | Control | Outcome |
|--------|---------|---------|
| Agent calls `broker.place_order` | Denylist substring `broker`/`order` | DENIED |
| Agent calls `calendar.create` | Denylist `create` | DENIED |
| Agent calls `shell.exec` | Denylist `shell`/`exec` | DENIED |
| Unknown tool not in allowlist | Exact-tool allowlist | DENIED (`unknown tool`) |
| SSRF to `169.254.169.254` | `_is_safe_host` metadata block | DENIED (`unsafe host`) |
| SSRF to `localhost` / RFC1918 | `_is_safe_host` private block | DENIED |
| Path traversal `../etc/passwd` | `_is_safe_doc_path` | DENIED (`unsafe path`) |
| Oversized provider response | `max_response_bytes` | BOUNDED |
| Provider raises | try/except fail-soft | `ok=False`, `ERROR` |
| External backend w/o creds | `NotConfiguredProvider.health()=False` | `NOT_CONFIGURED` |
| Secret in provider response | `redact_secrets` | `[REDACTED]` |
| Missing wake/trace id | step 1 | DENIED (`missing wake_id`/`trace_id`) |
| Malformed request | schema validation | DENIED (`invalid schema`) |

## Residual risk / open items

- Rate limiting and per-provider timeouts are stubbed pending external-provider
  activation (see above).
- The gateway is single-process and in-memory; it does not yet persist policy
  decisions beyond the append-only tool-call trace.
