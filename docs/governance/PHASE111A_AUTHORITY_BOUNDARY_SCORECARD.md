# Phase 111A — Authority Boundary Scorecard

**Date:** 2026-06-01

## TradeAI vs Hermes Authority Comparison

| Dimension | TradeAI | Hermes | Gap |
|-----------|---------|--------|-----|
| Evidence quality | Native pipeline data | Source-backed + LLM analysis | Hermes may be richer |
| Source traceability | Internal pipelines | External URLs + internal views | Hermes has better provenance |
| Schema validation | Established fields | Newer, still evolving | TradeAI ahead |
| Rollback readiness | Established flows | Advisory rollback exists, execution rollback untested | TradeAI ahead |
| Audit completeness | Event logs, proposal lifecycle | Promotion audit, advisory events | Comparable |
| Downstream impact | Known pathways | New pathways, less tested | TradeAI ahead |
| Operator review | Embedded in ATM workflow | Dashboard + review lanes | Comparable |
| False-positive risk | Low (established rules) | Low for advisory, untested for execution | Untested |
| Blast radius | Known | Unknown for execution writes | TradeAI ahead |
| Current maturity | Level 6 execution authority | Level 6 advisory authority | Different domains |

## Per-Surface Assessment

| Surface | TradeAI Score | Hermes Score | Gap | Required Before Hermes Write |
|---------|:---:|:---:|-----|---|
| Proposal draft recommendation | 9/10 | 7/10 | Schema + lifecycle | Isolated staging table |
| Proposal mutation | 9/10 | 3/10 | Full lifecycle | Level 7 governance |
| Journal annotation (append) | 8/10 | 6/10 | Append-only proof | Schema + audit |
| Journal mutation (rewrite) | 8/10 | 2/10 | Historical integrity | PROHIBITED |
| Holdings discrepancy detect | 9/10 | 5/10 | Reconciliation proof | Recommendation only |
| Holdings mutation | 10/10 | 1/10 | Broker source of truth | PROHIBITED |

## Key Insight

TradeAI's advantage is not research quality — it's **control maturity**. Hermes must earn authority through proven control quality, not just intelligence quality.
