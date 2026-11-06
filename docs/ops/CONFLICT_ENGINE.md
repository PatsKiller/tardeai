# Conflict engine (W10 PR 1)

Status: IMPLEMENTED; rulebook APPROVED 2026-10-28 and live-enabled (see `config/conflict_rulebook.json`)

Design-Task: DSN-20261024-conflicts-P1-T1

`scripts/lib/conflicts/engine.py` retains the coordinator reference's `Subject`,
`Input`, `Finding`, `evaluate` and `headline` interfaces. Binding ADDENDUM 2 and 3
and EXCEPTIONS_MATRIX supersede the original rule semantics. Original reference
core, profiles and all 24 test cases remain byte-for-byte in the fixture archive,
with SHA pins and a separately labelled historical baseline. Historical test
results do not establish current matrix acceptance.

Profile thresholds and vocabularies live in `config/conflict_rulebook.json`.
Its status and approval are recorded in that file (APPROVED, 2026-10-28, operator
words quoted verbatim there); this document does not restate or extend them. The
matrix and R13 source instructions bind implementation, and a rulebook change is
still an operator act: no local test or implementation approval grants runtime
authority. No producer or page is switched by this PR; AGENTS.md is unchanged.

`adapters.security_inputs_from_truth` consumes W1's `security_inputs_for` envelope:
canonical value/source/as_of/subject_id, context.held and persisted protection inputs.
Unknown holdings or missing confirmed identity produces DATA_ERROR. It never joins by
ticker or derives ownership from an opportunity label. `security_inputs` accepts
already joined Watch review, synthesis, Trade AI and re-entry rows. Producer clocks
are preserved. Invalid identity, naive/unreadable/future time, nonfinite numbers,
unknown roles and unknown vocabulary produce DATA_ERROR. Missing material time
is stale and blocks positive stances. Numeric and schedule mismatches are T1
DATA_ERROR incidents for source repair, never owner judgments that choose a fact.
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

## Vocabulary: mapped, declared unmapped, or a data error

`security_stance.families` and `security_stance.unmapped_labels` in
`config/conflict_rulebook.json` are the whole vocabulary contract. A label that is in
neither produces a visible R8 DATA_ERROR — that is the correct outcome for a genuinely
unknown word, and the wrong outcome for a word the desk already emits.

Two rules keep that distinction honest:

- **Declared means decided.** A label that is deliberately unmapped is listed in
  `unmapped_labels`. `MISSING_MARKET`, `MISSING_PLAN` and `STALE` are declared unmapped
  because "we do not know" must not read as "no action". Absence from both lists is not a
  third state; it is an oversight waiting to become noise.
- **No silent drift.** `tests/test_conflict_rulebook.py::test_every_desk_state_is_mapped_or_declared_unmapped`
  scans the string states in `reentry_rules.derive_intel_state`. A new desk state that is
  neither mapped nor declared fails the suite, so the next label cannot quietly become
  another unmapped error.

Mapping a label does not make it a judgment: it only says which family the word belongs to.
The conflict still has to be real, and safety, protection, policy and ownership findings stay
`never_auto`.

**What vocabulary work cannot fix.** On 2026-11-02 the live ledger held 1013 active conflict
items: 535 U1 "holding state unknown", 457 T1 "Ownership is unknown", 18 GATE R16 and 3
NEEDS_OPERATOR — and **zero R8**. The non-actionable mass is an identity/ownership coverage
gap, cured by W1 data, not by this file. Cite the ledger before claiming a vocabulary change
reduced the count.

<!-- moved from AGENTS.md 25.0.1 lines 6185-6203 -->
## Moved from AGENTS.md (25.0.1 lines 6185-6203)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **One engine decides what is a conflict.** Any disagreement between two inputs about one subject (a security, a metric, a job, a
  position) is evaluated only by the conflict engine (`scripts/lib/conflicts`) under the operator-approved rulebook
  (`config/conflict_rulebook.json`). No page, endpoint, agent or sender computes or announces its own conflicts. *Cause (§20):
  2026-10-24, 15 Watch flags of which 9 were noise and none could ever clear; three portfolio totals; operator, "a durable conflict
  resolution engine … used in other parts of the site".*
- **Agreement and superseded inputs never flag.** Inputs that call for the same action under the subject's profile, or that are
  older than the canonical value by more than their source's limit, are shown as agreeing or superseded, never as conflicts.
  *Cause (§20): WATCH vs AVOID on names not held, and 52–79-day-old reviews, were shown as conflicts.*
- **Gates are not conflicts.** A hard check (Trade AI deterministic checks, wash-sale in taxable accounts, earnings blackout) is
  shown as "Blocked: <check>" and clears itself when the check passes. *Cause (§20): FATN/ANET/SMCI were flagged as conflicts.*
- **The owner decides real conflicts, with a recorded reason.** The CIO decides stance conflicts (its review writes a
  ConflictDecision and its new stance); the operator decides protection (stop awaiting fill, pending, none), policy breaches,
  money mismatches between pages, data errors and flapping conflicts. An agent never picks a side itself.
  *Cause (§20): the "Resolve conflict" button queued reviews whose completions never cleared anything.*
- **The CIO is always informed.** Every conflict state change about a security is written to CIO memory (one contribution per
  change), and open conflicts are inputs to the CIO's reviews, briefs, Ask answers and conviction steps. *Cause (§20): operator
  2026-10-24, "is the CIO notified … baked into this?"*
- **Safety, protection and policy findings are never resolved automatically.** Kill switch, AUTO BLOCKED, stop states and policy
  limits are only ever shown and routed to the operator. *Cause (§20): §0 rule 1 and the 2026-10-14 SPCX stop incident.*
