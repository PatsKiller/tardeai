# Integration with the Agent Intelligence Foundation

Status:      ACTIVE
as_of:       2026-08-17T17:24:31-04:00
Measured at: efcc51365 / not measured

Both subsystems are now on main. Financial Senses still owns provider
contracts and the registration manifest. AIF owns the central MCP gateway.
The post-merge adapter (`scripts/lib/financial_senses_aif.py`) registers the
manifest tools on that **existing** gateway. No second MCP is created.

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
      - macro.get_vintage_dates
      - macro.get_series
      - macro.regime_inputs
  identity:
    tools: [identity.resolve]
  stress:
    tools: [risk.stress_portfolio]
  evidence:
    tools: [evidence.build_graph]
  factor:
    tools: [factor.overlap]
  critic:
    tools: [critic.review]
```

For each tool: `READ_ONLY`, input schema, output schema, source policy, timeout,
rate limit, and expected trace metadata (`request_id`, `provider`, `capability`,
`as_of`, `observed_at`).

## Integration files (this program)

- `scripts/lib/financial_senses_aif.py` — adapter / registry / envelope mapping
- `scripts/lib/aif_financial_senses_replay.py` — deterministic dry replay
- Gateway allowlist + provider registry registration (AIF owns the chokepoint)
- `specialist_context.financial_senses` on ContextEnvelope@v1
- Tool receipts on the existing AgentRunTrace / tool-trace ledger

## Boundary

This branch does not touch `docs/agent-intelligence/**`, `scripts/lib/agent_*.py`,
`tests/test_agent_*.py`, or the central gateway.
