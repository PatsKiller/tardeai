# Integration with the Agent Intelligence Foundation

The other branch owns the central MCP gateway. This branch provides the
provider contracts and a registration manifest for later consumption. No AIF
code is imported; the integration is deferred until both branches are stable.

## Registration contract

The manifest (`scripts/lib/financial_senses/manifest.py`,
`render_registration_manifest()`) describes each tool:

```yaml
providers:
  sec_edgar:
    tools:
      - sec.resolve_cik
      - sec.get_recent_filings
      - sec.get_company_facts
      - sec.compare_filing_facts
      - sec.get_form4_context
      - sec.get_13f_context
      - sec.get_filing_metadata
      - sec.get_decision_evidence
  macro:
    tools:
      - macro.get_series_snapshot
      - macro.get_decision_time_snapshot
      - macro.get_vintage
      - macro.compare_vintages
      - macro.get_latest_observation
      - macro.get_release_dates
      - macro.get_series
      - macro.regime_inputs
  identity:
    tools: [identity.resolve]
  stress:
    tools: [risk.stress_portfolio]
  evidence:
    tools: [evidence.build_graph]
```

For each tool: `READ_ONLY`, input schema, output schema, source policy, timeout,
rate limit, and expected trace metadata (`request_id`, `provider`, `capability`,
`as_of`, `observed_at`).

## Deferred integration files

- Central MCP gateway registration (AIF owns it).
- `ContextEnvelope` / `AgentRunTrace` / memory hooks (AIF owns them).
- Wiring providers → gateway (post-merge PR).

## Boundary

This branch does not touch `docs/agent-intelligence/**`, `scripts/lib/agent_*.py`,
`tests/test_agent_*.py`, or the central gateway.
