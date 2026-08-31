# Financial Senses — read-only financial intelligence providers

Status:      ACTIVE
as_of:       2026-08-17T11:10:54-04:00
Measured at: efcc51365 / not measured

Parallel, isolated branch (`feature/financial-senses-parallel-v1`) that builds
provider-side financial "senses" for Trade AI. This branch is the **financial
senses** lane; the separate `feature/agent-intelligence-foundation` branch owns
the agent-intelligence plumbing (central MCP gateway, ContextEnvelope,
AgentRunTrace, memory). The two lanes are deliberately isolated and integrate
only after both are stable.

## What this branch builds

| Provider | Capabilities | Source |
|---|---|---|
| `sec_edgar` | `sec.resolve_cik`, `sec.get_recent_filings`, `sec.get_form4_context`, `sec.get_13f_context`, `sec.get_company_facts`, `sec.get_filing_metadata`, `sec.compare_filing_facts`, `sec.get_decision_evidence` | existing SEC pipeline + read-only EDGAR extension |
| `macro` | `macro.get_series`, `macro.get_series_snapshot`, `macro.get_latest_observation`, `macro.get_vintage_dates`, `macro.get_vintage`, `macro.compare_vintages`, `macro.get_decision_time_snapshot`, `macro.regime_inputs` | FRED / ALFRED (vintage-aware) |
| `identity` | `identity.resolve` | OpenFIGI (fail-closed) |
| `stress` | `risk.stress_portfolio` | deterministic scenarios |
| `factor` | `factor.overlap` | sourced factor loadings |
| `evidence` | `evidence.build_graph` | claim/evidence graph |
| `critic` | `critic.review` | shadow-only adversarial review |

## What this branch does NOT build

- A second SEC ingestion pipeline or scheduler
- A second MCP gateway
- A memory layer, ContextEnvelope, or AgentRunTrace
- Production deployment, systemd, cron, or Telegram changes
- Any broker / order / stop authority

## Architecture

```
Existing SEC ingestion / SEC DB          (canonical, unchanged)
        │
        ▼
SecEdgarProviderAdapter (read-only)      scripts/lib/financial_senses/sec_provider.py
        │
        ▼
Future governed MCP gateway              (built by the AIF branch — not here)
        │
        ▼
Alex / Maria / etc.
```

Authority is fixed to `READ_ONLY_ADVISORY`. Every provider result carries
provenance, `as_of`, quality, and a fixed authority field. No source may emit an
unqualified fact without provenance.

## Namespace

All new work lives under a dedicated namespace to avoid colliding with the other
agent:

```
scripts/lib/financial_senses/     implementation
tests/financial_senses/           tests
docs/financial-senses/            documentation
config/financial_senses/          config (macro series catalog)
```

## Tests

```bash
python3 -m pytest tests/financial_senses/ -q
```

The suite is fully offline (no network, no live DB). See
`TEST_AND_DRY_RUN_PLAN.md` for the complete testing matrix and
`ACCEPTANCE.md` for the 30 acceptance gates.

## Status

This branch is **parallel and isolated**; it is not deployed and not merged.
See `DEPLOYMENT_NOT_AUTHORIZED.md` and `PARALLEL_WORKTREE_AND_MERGE_STRATEGY.md`.
