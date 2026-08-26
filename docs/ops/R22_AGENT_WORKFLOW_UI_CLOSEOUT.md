# R22 Agent Office and Workflow Trace

**Status:** DESIGN_BASELINE_ONLY  
**Evidence class:** SOURCE_ONLY  
**Authority:** READ_ONLY_ADVISORY

The planned Agent Office and Workflow Trace must consume the R21 typed control-plane
contracts. They must show runtime state and immutable lineage, not infer status in React.
Initial delivery remains side-by-side under `/control-plane/agents` and
`/control-plane/workflows`; existing live routes are not replaced.

Required lineage: source event -> entity -> materiality -> research gap -> free-first
research -> specialist artifact -> council -> CIO product -> notification -> checkpoint
-> outcome -> learning. Each edge carries an ID, timestamp, source SHA, and evidence class.

No implementation or live proof is claimed in this baseline.
