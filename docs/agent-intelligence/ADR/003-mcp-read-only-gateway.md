# ADR-003 — Internal read-only MCP gateway

Status:      ACTIVE
as_of:       2026-08-16T23:13:39-04:00
Measured at: efcc51365 / not measured

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

Agents need read-only access to portfolio, decisions, research, documents,
calendar, goals, and plans. If agents connect to MCP providers directly, a
compromised or misbehaving agent could reach a write tool, an internal network
endpoint (SSRF), a file outside the allowed root (path traversal), or a secret
in a provider response. Upstream tool metadata (`readOnlyHint`) is a client
hint and cannot be treated as a boundary.

## Decision

Route every agent tool call through an **internal** gateway
(`scripts/lib/mcp_read_only_gateway.py`) instead of a direct agent→MCP
connection. The gateway:

1. enforces an exact-tool read-only allowlist plus a substring denylist,
2. validates request schema, SSRF, and path traversal locally,
3. resolves providers from a registry and fails soft on
   missing/error/NOT_CONFIGURED,
4. redacts secrets and bounds response size,
5. records a full receipt (trace/wake/agent/tool/provider/digests/timing).

Read-only is enforced **server-side** (in the gateway and adapters), not by
trusting client metadata: provider adapters expose only `get`/`search`/`health`
— no write methods, no network.

External providers (Google Calendar / Google Documents) are marked
`NOT_CONFIGURED` and return fail-soft (`ok=False`, `status="NOT_CONFIGURED"`)
until credentials exist. No credential is requested or fabricated.

## Consequences

- Agents can read only from the allowlisted, capability-classed tools.
- Any write/mutation attempt is denied before reaching a provider, and the
  denial is itself traced (auditable).
- SSRF and path traversal are structurally blocked; the only permitted egress
  is an explicit safe-host allowlist, and private/metadata hosts are always
  blocked.
- External calendar/documents reads are unavailable until credentials are
  configured — a deliberate, fail-soft gap rather than a silent success.
- The gateway is additive: it introduces new modules and does not alter
  existing scripts or tests.
