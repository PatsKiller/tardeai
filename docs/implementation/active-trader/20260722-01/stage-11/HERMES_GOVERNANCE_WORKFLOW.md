# Hermes Governance Workflow — Stage 11
States: DRAFT → EVIDENCE_PENDING → SIMULATION_PENDING → ARCHITECT_REVIEW_PENDING →
OPERATOR_REVIEW_PENDING → APPROVED_INACTIVE (terminal, INACTIVE — no auto-activation); any state can
go REJECTED/EXPIRED. Skipping review is illegal (HermesGovernanceError). Nothing auto-activates.
LLMs may summarize/draft/compare/cluster/explain; NEVER authorize/trade/change_risk/merge/deploy/
activate/place_order/unlock (hermes_llm_allowed enforced + tested).
