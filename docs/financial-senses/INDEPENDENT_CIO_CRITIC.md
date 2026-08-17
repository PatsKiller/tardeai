# Independent CIO critic (shadow-only)

Internal adversarial review, not a visible persona.

## Contract

Input: evidence packet + proposed material action + sizing objective +
portfolio constraints. Output: `CriticReview@v1`.

## CriticReview fields

`critic_review_id`, `decision_id`, `input_digest`, `evidence_digest`,
`proposed_action`, `objections`, `missing_evidence`, `counterevidence`,
`portfolio_effects`, `identity_risks`, `freshness_risks`, `result`,
`recommended_next_step`, `created_at`.

## Results

`NO_MATERIAL_OBJECTION`, `MATERIAL_OBJECTION`, `DATA_UNAVAILABLE`.

## Portfolio coverage semantics

`coverage_pct` is MODELED coverage: unmodeled = `100 - coverage_pct`.
`unmodeled_coverage_pct` is already the UNMODELED fraction and is used as-is
(not subtracted from 100 again). Both must be within `[0, 100]`; a missing,
non-numeric, or out-of-range value is `DATA_UNAVAILABLE` and never silently
passes.

## Shadow flags

`CRITIC_SHADOW = 1`, `CRITIC_BEHAVIOR_INFLUENCE = 0`. No live decision changes,
no Telegram. Golden cases: concentration trim with stale data, no-objective
trim, cash deployment with unfunded demand, re-entry without candidate-specific
authority, identity ambiguity, SEC filing contradiction, macro vintage leak.
