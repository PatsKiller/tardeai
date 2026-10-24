# Conflict engine (W10 PR 1)

Status: IMPLEMENTED, LOCAL VALIDATION; rulebook PROPOSED

Design-Task: DSN-20261024-conflicts-P1-T1

`scripts/lib/conflicts/engine.py` is byte-identical to the coordinator's tested
2026-10-24 reference. It exports `Subject`, `Input`, `Finding`, `evaluate` and
`headline`, with the same function names and output fields. The reference test
source is retained byte-for-byte in `tests/fixtures/conflicts/reference_tests.py.txt`;
the test loader substitutes only the package import resolver. The SHA manifest
pins the original core, profiles and tests.

Profile thresholds and vocabularies live in `config/conflict_rulebook.json`.
Its status is PROPOSED, approval is null and live is disabled. The final exceptions
matrix, thresholds and never-auto list await operator ratification. No local test
or implementation approval grants runtime authority. No producer or page is switched
by this PR; AGENTS.md is unchanged.

`adapters.security_inputs_from_truth` consumes W1's `security_inputs_for` envelope:
canonical value/source/as_of/subject_id, context.held and persisted protection inputs.
Unknown holdings or missing confirmed identity produces DATA_ERROR. It never joins by
ticker or derives ownership from an opportunity label. `security_inputs` accepts
already joined Watch review, synthesis, Trade AI and re-entry rows. Producer clocks
are preserved. Invalid identity, missing/naive/future time, nonfinite numbers,
unknown roles and unknown vocabulary produce DATA_ERROR before reference evaluation.
Counts compare exactly; money uses the reference absolute dollar tolerance and zero
relative tolerance. A filled stop with a still-held canonical position is represented
as AWAITING_FILL for operator reconciliation; this changes no stop behavior.

Every consumer receives the same `findings_section`: `findings`, `headline`, `gap`.
A finding carries `schema`, `engine`, `kind`, `rule`, `summary`, `clears_when`,
`action`, `severity`, `sides` (source/value/as_of/account) and stable `key`.
AGREEMENT and SUPERSEDED never flag. UI owners W9/W7/W4 render these fields without
classifying disagreements. W8 owns the lane registry and scheduling.

## Evidence and limits

The original 24 reference cases remain intact. Adapter fixtures include 16 exact
opportunity rows selected from the persistent projection; their original path and
SHA are recorded in `opportunity_rows.json`. They contain no GUID. The tests prove
that they cannot bypass W1's identity join. Other adapter edge cases are explicitly
synthetic unit inputs. The design's 15-card expected result is reference evidence,
not a newly measured live-tree acceptance result. A full real-tree replay requires
the captured card inputs plus W1's confirmed identity/holdings snapshot.

PR 2 owns ledger, lifecycle, operator API authentication, CIO memory/context and
review-completion integration. W8 owns the separate inactive lane declaration;
W9/W7/W4 own 412/390 actual-tap fixture proofs. This backend PR changes no UI.
