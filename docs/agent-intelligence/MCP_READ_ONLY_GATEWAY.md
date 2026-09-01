# MCP Read-Only Gateway

Status:      ACTIVE
as_of:       2026-08-16T23:13:39-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY` · Phase 3

The MCP read-only gateway is the single chokepoint between an agent and any
Model Context Protocol style tool. It replaces direct agent→MCP connections
with a governed, internally-enforced, read-only path.

## Why an internal gateway (not the upstream `mcp` SDK)

The `mcp` SDK is not installed in this environment, and more importantly an
agent must never be able to reach a provider directly. The gateway is a small,
local, dependency-free module that:

- enforces an exact-tool allowlist **before** any provider is touched,
- enforces a substring denylist on top of the allowlist (defense in depth),
- validates request schemas, SSRF, and path traversal **locally**,
- routes only to registered, in-memory provider adapters,
- redacts secrets and bounds response size before returning anything,
- records a full receipt for every call.

There is no generic proxy and no arbitrary-URL fetch. A tool that is not in the
allowlist, or that contains a denied substring, is rejected without ever
reaching a provider.

## Data flow

```
Agent
  └─ call_mcp_tool(...)                      # the one chokepoint
       ├─ 1. wake_id / trace_id present      # missing => DENIED
       ├─ 2. allowlist + deny substring      # classify_tool_allowed()
       ├─ 3. request schema                  # dict + known fields only
       ├─ 4. SSRF guard                      # _is_safe_host()
       ├─ 5. path-traversal guard            # _is_safe_doc_path()
       ├─ 6. provider lookup                 # provider_registry[tool]
       │      └─ missing/error/NOT_CONFIGURED => fail-soft ok=False
       ├─ 7. response size bound             # oversized => BOUNDED
       ├─ 8. secret redaction                # redact_secrets()
       └─ 9. receipt + return                # append_tool_call()
```

Every path in that flow is read-only. There is no write leg.

## Allowed capability classes

The allowlist maps exact tool names to read-only **domain** capability classes
(scopes, never verbs):

| Capability class | Tools |
|------------------|-------|
| `portfolio` | `portfolio.get_verified_snapshot`, `portfolio.get_cash_snapshot`, `portfolio.get_risk_snapshot` |
| `decisions` | `decisions.get`, `decisions.search_history` |
| `research` | `research.search`, `research.get_source` |
| `documents` | `documents.search`, `documents.get` |
| `calendar` | `calendar.search`, `calendar.get_event` |
| `goals` | `goals.list` |
| `plans` | `plans.get` |

No tool exposes a mutation verb. `classify_tool()` in the trace layer still
reports every one of these as `read`, and the gateway independently enforces
the same read-only boundary — two layers that must both agree.

## Explicit denylist

`DENIED_SUBSTRINGS` is a tuple of substrings that always deny, even if a name
also matched the allowlist. It covers:

- broker / order / stop / trade / place / cancel / submit / mutate / send
- email (send)
- calendar write: create / update / delete
- document write: create / edit / delete
- shell / exec
- filesystem write: write
- generic http fetch: http / fetch
- risk-policy write: risk_policy
- credential / auth / 2fa / token

The check is case-insensitive and runs **before** the allowlist, so the
denylist wins any tie.

## Server-side read-only enforcement

Read-only is enforced server-side (in this local module), not by trusting
client metadata:

1. **Allowlist** — only exact, enumerated read tools exist.
2. **Denylist** — write/mutation substrings cannot pass.
3. **No write methods** — provider adapters (`ReadOnlyProvider`) expose only
   `get`, `search`, and `health`. There is no `create`/`update`/`delete`.
4. **No network** — providers are in-memory; external backends are
   `NOT_CONFIGURED`.
5. **No credentials** — nothing in this module holds or forwards a secret.

## Why `readOnlyHint` metadata is NOT trusted

An MCP tool description may advertise `readOnlyHint: true`. That is a client
hint, not a security boundary. A hint can be wrong, stale, or malicious. The
gateway ignores it entirely and instead derives the boundary from the exact
tool name, the denylist, and the absence of any write method on the adapter.

## Fail-soft behavior

- Missing provider → `ok=False`, `status="ERROR"` (no exception).
- Provider raises → `ok=False`, `status="ERROR"` (exception captured).
- External backend without credentials → `ok=False`, `status="NOT_CONFIGURED"`.

The gateway never raises for a deny or provider path. Only a programming error
in the gateway itself would raise.

## Files

- `scripts/lib/mcp_read_only_gateway.py` — allowlist, denylist, guards, chokepoint.
- `scripts/lib/mcp_provider_adapters.py` — `ReadOnlyProvider` protocol + local providers + `NotConfiguredProvider`.
