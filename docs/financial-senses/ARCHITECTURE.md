# Architecture

Status:      ACTIVE
as_of:       2026-08-16T22:32:42-04:00
Measured at: efcc51365 / not measured

## Layering

```
                          ┌───────────────────────────────┐
                          │  Future governed MCP gateway  │  (AIF branch — NOT here)
                          └───────────────▲───────────────┘
                                          │ registers via manifest
┌───────────────────────┐   ┌─────────────┴─────────────────────────────┐
│  FinancialSenseResult │◄──│  Provider contracts (read-only)            │
│  @v1 envelope         │   │  sec_edgar / macro / identity / stress /   │
└───────────────────────┘   │  factor / evidence / critic               │
                          └─────────────▲───────────────────────────────┘
                                        │
┌───────────────────────┐   ┌───────────┴─────────────┐
│  sec_companyfacts_    │   │  Existing SEC pipeline   │
│  reader (read-only    │   │  sec_data_ingest.py +    │
│  EDGAR extension)     │   │  trade_ai DB (canonical) │
└───────────────────────┘   └─────────────────────────┘
```

## Envelope

`FinancialSenseResult@v1` (`result.py`) is the single normalized envelope every
provider returns. Key invariants:

- `authority` is fixed to `READ_ONLY_ADVISORY`.
- Every `Fact` requires `source_type` + (`observed_at` or `as_of`).
- Every `Claim` requires a `source_type` (or is explicitly `UNSUPPORTED`).
- `status` is one of `OK / PARTIAL / NOT_CONFIGURED / UNAVAILABLE /
  INVALID_REQUEST / STALE / CONFLICT`.
- Missing data uses distinct states (`DATA_UNAVAILABLE`, `NOT_INGESTED`,
  `NOT_APPLICABLE`) — never silently zero.

## Provider protocol

```python
class FinancialSenseProvider(Protocol):
    name: str
    version: str
    def health(self) -> ProviderHealth: ...
    def capabilities(self) -> list[Capability]: ...
    def query(self, capability: str, request: dict) -> FinancialSenseResult: ...
```

`BaseProvider` provides fail-soft `query()` (exceptions become `UNAVAILABLE`
results with a warning), result builders that enforce provenance, and
`NOT_CONFIGURED` handling. Providers work standalone with no MCP dependency.

## Source governance

`source_governance.py` defines source classes (`PRIMARY_REGULATORY`,
`PRIMARY_GOVERNMENT`, `CANONICAL_INTERNAL`, `APPROVED_MARKET_DATA`,
`SECONDARY_RESEARCH`, `MEMORY_CONTEXT`, `MODEL_INFERENCE`) and quality ordering
keyed by claim type. `MODEL_INFERENCE` and `MEMORY_CONTEXT` can never back a
`FACT` node.

## Data flow for each provider

- **SEC**: reads canonical `sec_form4` / `sec_13f` tables via `db_adapter`, and
  reads company facts / submissions through a bounded read-only EDGAR extension.
  No production writes, no second scheduler.
- **Macro**: FRED/ALFRED with vintage-aware historical reads.
- **Identity**: OpenFIGI mapping, fail-closed on ambiguity.
- **Stress**: deterministic three-tier scenario P&L, unmodeled value explicit.
- **Factor**: sourced loadings + transparent overlap components.
- **Evidence**: FACT → CLAIM → DECISION graph with provenance invariants.
- **Critic**: shadow-only deterministic adversarial review.
