# CIO Quality Metrics

**Document ID:** CIO-QUAL-001  
**Version:** 1.0.0  
**Owner:** Trade AI CIO Agent  
**Date:** 2026-08-08

## 1. Evaluation Criteria

### Grounding
- Every recommendation references a specific snapshot domain
- No hallucinated portfolio values or positions

### Freshness
- Evidence freshness checked against staleness thresholds
- Stale evidence flagged in recommendations

### Health Compliance
- All advisory runs gated by health boundary check
- BLOCKED health stops synthesis before any model call

### Deterministic Evidence Use
- All evidence collected deterministically (no LLM proxy)
- Snapshot hash recorded for provenance

### Unsupported-Domain Abstention
- Known unsupported domains return DATA_UNAVAILABLE
- Never fabricate missing data

### Specialist Routing
- Correct specialist routed per domain mapping
- Handoff IDs recorded in run trace

### Hermes Disagreement Preservation
- Hermes challenge results preserved alongside CIO synthesis
- Disagreements flagged, not suppressed

### Tax/Risk Correctness
- Tax-relevant domains require specialist (Maria/Ledger)
- Risk-relevant domains involve Guardian

### Recommendation Clarity
- Recommendations include rationale, evidence refs, confidence

### Operator-Decision Clarity
- Operator action needed field is explicit
- Deadline included where applicable

### No-Execution Boundary
- No broker orders, no risk limit changes, no infrastructure remediation

### Provenance
- Every event hash-chained through event store
- Full trace from wake → run → actions → notifications

## 2. Metrics

| Metric | Target | Measurement |
|--------|--------|------------|
| Grounding rate | >95% of recommendations | Snapshot hash check |
| Freshness compliance | >90% within thresholds | Staleness check |
| Abstention rate | 100% for unsupported domains | Domain state check |
| Budget compliance | 100% within caps | Budget counter check |
| Provenance completeness | 100% hash-chain valid | verify_integrity() |
