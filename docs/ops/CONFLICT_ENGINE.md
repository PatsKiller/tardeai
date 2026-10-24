# Conflict engine (W10 PR 1)

Status: IMPLEMENTED, LOCAL VALIDATION; rulebook PROPOSED

Design-Task: DSN-20261024-conflicts-P1-T1

`scripts/lib/conflicts/engine.py` retains the coordinator reference's `Subject`,
`Input`, `Finding`, `evaluate` and `headline` interfaces. Binding ADDENDUM 2 and 3
and EXCEPTIONS_MATRIX supersede the original rule semantics. Original reference
core, profiles and all 24 test cases remain byte-for-byte in the fixture archive,
with SHA pins and a separately labelled historical baseline. Historical test
results do not establish current matrix acceptance.

Profile thresholds and vocabularies live in `config/conflict_rulebook.json`.
Its status is PROPOSED, approval is null and live is disabled. The matrix and R13
source instructions bind implementation; final rulebook ratification and live
activation remain operator acts. No local test
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
relative tolerance. A filled stop with a still-held canonical position freezes
stance evaluation as an ownership DATA_ERROR; this changes no stop behavior.

Every consumer receives the same `findings_section`: `findings`, `headline`, `gap`.
A finding carries `schema`, `engine`, `kind`, `rule`, `summary`, `clears_when`,
`action`, `severity`, `sides` (source/value/as_of/account), stable `key`, `owner`,
`next_run`, `tier` and `never_auto`.
AGREEMENT and SUPERSEDED never flag. UI owners W9/W7/W4 render these fields without
classifying disagreements. W8 owns the lane registry and scheduling.

## Evidence and limits

Binding tests cover E1–E22, T0/T1 precedence, R1 material-input/trading-session age,
R3 widened Trade AI gates, R7 missing stance, R8 unknown vocabulary, all-account
wash gates, instrument/paper/failed-output scope, N-way splits and R15 hysteresis.
R13 consumes W1's class-specific `concentration_policy` values; this engine owns no
IPS thresholds or instrument classification. Look-through accepts raw exposure and
W1 policy limits through `concentration_inputs`, never assuming missing coverage is zero.

The original 24 reference cases remain intact as historical evidence. Adapter fixtures include 16 exact
opportunity rows selected from the persistent projection; their original path and
SHA are recorded in `opportunity_rows.json`. They contain no GUID. The tests prove
that they cannot bypass W1's identity join. Other adapter edge cases are explicitly
synthetic unit inputs. The design's 15-card expected result is reference evidence,
not a newly measured live-tree acceptance result. A full real-tree replay requires
the captured card inputs plus W1's confirmed identity/holdings snapshot.

PR 2 owns ledger, lifecycle, operator API authentication, CIO memory/context and
review-completion integration. W8 owns the separate inactive lane declaration;
W9/W7/W4 own 412/390 actual-tap fixture proofs. This backend PR changes no UI.
