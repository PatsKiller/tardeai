# ADR: Financial Senses integrates through the AIF governed read-only gateway

**Status:** Accepted  
**Date:** 2026-08-17  
**Authority:** READ_ONLY_ADVISORY

## Decision

Financial Senses integrates through the existing Agent Intelligence Foundation
read-only MCP gateway (`call_mcp_tool`). No second MCP gateway is created.

## Context

PR #341 shipped AIF (gateway, ContextEnvelope, AgentRunTrace, memory,
UNTRUSTED_DATA, rate/timeout). PR #340 shipped Financial Senses providers
and a registration manifest, explicitly deferring gateway wiring.

## Consequences

- One allowlist, one denylist, one SSRF/path/redaction/rate/timeout boundary.
- FS remains evidence/intelligence; AIF remains governance.
- Shadow-first: `AIF_FINANCIAL_SENSES_SHADOW` default 0; no behavior flag.
- OpenBB remains unexposed plumbing.

## Rejected alternatives

- `financial_senses_mcp_server` / `financial_senses_gateway_v2`
- Agents calling FS providers directly (bypasses receipts and rate limits)
- Promoting ModelEstimate to Fact inside AIF
- Memory as financial truth
