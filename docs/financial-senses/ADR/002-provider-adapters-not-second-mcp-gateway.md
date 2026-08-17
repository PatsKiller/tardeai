# ADR-002 — Provider adapters, not a second MCP gateway

**Status:** Accepted

## Context

The Agent Intelligence Foundation branch owns the central MCP gateway. Building
a second gateway here would create two competing transports.

## Decision

This branch ships provider contracts (`FinancialSenseProvider`,
`FinancialSenseResult@v1`) plus a registration manifest. No MCP server, no
transport, no gateway.

## Consequences

- Providers work standalone with no MCP dependency.
- The future gateway imports/registers them via the manifest.
- Final wiring deferred to a post-merge integration PR.
