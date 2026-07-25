# Maya Intelligence Read-Only Presentation Contract — 2026-07-25

## Endpoint shape

Any future Command Center endpoint exposing Maya intelligence must be read-only and return normalized evidence records. This document does not add an HTTP route.

```json
{
  "contract": "maya-intelligence-evidence-v1",
  "domain": "WATCH|PROPOSAL|DEFENSE|SECTOR|INDUSTRY",
  "subject": "symbol or research identifier",
  "as_of": "RFC3339 timestamp",
  "evidence": [
    {
      "field": "pe",
      "label": "Trailing P/E",
      "value": 18.4,
      "provider": "finviz",
      "as_of": "RFC3339 timestamp",
      "provenance_ref": "opaque source reference",
      "methodology_version": "source contract version",
      "state": "CURRENT|STALE|MISSING",
      "authority": "deterministic_input|contextual_input|display_only",
      "deterministic_usable": true,
      "may_override_gate": false
    }
  ],
  "news_quality": {
    "state": "RATED|INSUFFICIENT_EVIDENCE",
    "rating": 1,
    "dimensions": {
      "source_reliability": 1,
      "freshness": 1,
      "primary_source_proximity": 1,
      "corroboration": 1,
      "materiality": 1
    },
    "meaning": "news evidence quality only; not sentiment or trade authority"
  },
  "authority": {
    "read_only": true,
    "mutation_endpoint": false,
    "execution_endpoint": false,
    "analyst_or_model_override": false
  }
}
```

## Presentation requirements

- Show source and age next to each value.
- Separate missing from stale.
- Separate evidence quality from bullish/bearish sentiment.
- Label analyst consensus and actions as corroborative.
- Show which deterministic check consumed a value; otherwise label it context/display only.
- Preserve the parent Watch, Proposal, Defense, Sector, or Industry decision and its evidence hash.
- Never expose a generic `verified` badge when only one evidence family is current.
- Provide no mutation, refresh, review-run, approval, or execution control through this evidence endpoint.
