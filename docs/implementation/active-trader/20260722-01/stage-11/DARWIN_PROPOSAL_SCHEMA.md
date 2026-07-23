# Darwin Proposal Schema — Stage 11
DarwinProposal (proposal-only; applies_directly() == False always). Kinds: feature, threshold, risk,
runner, broker_policy. REQUIRES: evidence_refs (non-empty), sample_size>0, period, cohort,
confounders (non-empty — 'none-identified' allowed), replay_or_simulation_ref, rollback_plan, expiry,
review_state. No direct change to production/weights/risk/flags/policy/authorization/guardrails.
Missing any required field raises. Tested.
