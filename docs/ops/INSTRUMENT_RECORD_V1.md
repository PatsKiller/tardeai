# InstrumentRecord@v1

Status:      ACTIVE
as_of:       2026-08-29T23:50:42-04:00
Measured at: efcc51365 / not measured

`InstrumentRecord@v1` is the normalized operator projection for one instrument.
It is built from the existing `watchlist_items` row and linked canonical
identity, research, specialist, operator-turn, and lesson evidence. It is not
a second business-logic store.

The adapter lives in `scripts/lib/instrument_record.py` and is registered as
`instrument.records` in `CanonicalStoreRegistry@v1` (`POSTGRES`, table
`watchlist_items`). Ticker text is display-only; identity joins require a
canonical security or issuer identifier.

## Current implementation

The adapter normalizes thesis, Command Center narrative, event/price markers,
research and artifact IDs, operator turns, lessons, analyst/earnings timing,
research eligibility, notification priority, workflow identity, and data
quality. Missing identity or lineage is explicitly marked `LEGACY` or partial;
values are never inferred from ticker text.

## Remaining integration work

Existing writers still persist their evidence in their domain stores. Each
writer must call the adapter with the same `workflow_id`, and Command Center
sections must consume the normalized projection rather than independent table
queries. Notification threshold state and operator ack/defer updates also need
to be persisted against the same record. These are additive follow-up tasks;
historical evidence remains untouched.

<!-- moved from AGENTS.md 25.0.1 lines 3113-3144 -->
## Moved from AGENTS.md (25.0.1 lines 3113-3144)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

### `InstrumentRecord@v1` — the persistent unit

```
subject_key
thesis · cc_narrative              CC reads cc_narrative; writers rewrite it
last_event · last_price_hash
research[] · artifact_ids
operator_turns[]                   ack / defer / reject / question land HERE
lessons[]                          cognition only → next question, priority
analyst · earnings_next
next_eligible_at · notify_priority
last_outcome                       the research-gate ROUTE of the last cycle (flash|pro|reuse) — NOT a market outcome
beliefs[]                          SHIPPED 2026-09-24 (PR #1226) — `InstrumentBelief@v1`: per
                                   (subject_key | recommendation | horizon [| population])
                                   sample_size · successful · success_rate · outcome_ids ·
                                   lesson_ids (RATIFIED only) · belief_proposal_id · revision.
                                   Written ONLY by `cio_belief_writer` from SETTLED rows
                                   (advisory_outcomes, resolved checkpoints with a price change,
                                   CONFIRMED/REFUTED commitment outcomes) through `apply_belief`,
                                   a named rail entry beside `apply_cognition` that refuses any
                                   BEHAVIOR_FIELDS key anywhere in the block and any live_mutation.
                                   Read before authoring: the research gate (flash→pro,
                                   `prior_belief_weak_escalates`), the L3 question, and
                                   `default_decide` (BELIEF_REVIEW). Supersedes the former
                                   `priors` / `scored_lessons[]` SPECIFIED lines.
commitments[]                  SPECIFIED — AgentView staked; no producer ON THE RECORD (governed
                                   commitments live in the wake store, keyed by subject_guid)
```

Loaded by `load-by-subject` on every wake. `plan_id` on every wake. An operator ack or defer writes
back onto **this** record. Outcome checkpoints bind to it by `subject_key` (stamped at mint since
PR #1226) and by registry `subject_guid` — never by a tag GUID.

<!-- moved from AGENTS.md 25.0.1 lines 3146-3182 -->
## Moved from AGENTS.md (25.0.1 lines 3146-3182)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

### Pipeline stages — extend these; do not build alongside them

```
S0_OPERATOR_CONVERSE      the operator is an event; a Telegram reply is the next S0
CANONICAL ENTITY          ticker ≠ CUSIP ≠ ETF-without-CIK; dust residual ≠ a position
MATERIALITY               S1–S7, persist fairness → notify_priority
GRAPH IMPACT              1-hop, held non-dust only
RESEARCH GAP              gap vs THIS record, not a blank page
FREE-FIRST RESEARCH       persistent cognition · Hermes/RAG/FRED · librarian grading
                          then residual web, gated, ≤1 hop per subject_key per day, budget N=3
                          then LLM only if unresolved AND materially useful
SPECIALIST DISPATCHER     thin; no second harness; same workflow_id
CIOCouncilSynthesis@v1    deterministic; DISPUTED stands
WRITE BACK                cc_narrative · next_research_question · next_eligible_at · notify_priority
CIOOperatorProduct@v1     DETERMINISTIC_PRODUCT · $0.00 — CC sections BIND to the record
NOTIFICATION POLICY       fires only if notify_priority crossed a bar
                          IMMEDIATE · DIGEST · COMMAND_CENTER_ONLY · SUPPRESSED
DELIVERY RECEIPT/DEDUPE   sent or would_send, stamped
OutcomeCheckpoint@v1      plan_id or plan_binding reason, bound at creation
OUTCOME → LESSON          support-only, cognition apply
REVIEW_READY              next wake loads the record
```

### Artifact types

```
SpecialistArtifact@v1-lite   specialist output; same workflow_id; writers update THE SAME record
CIOCouncilSynthesis@v1       deterministic synthesis
CIOOperatorProduct@v1        the operator-facing product
OutcomeCheckpoint@v1         a checkpoint bound to a plan at creation
AgentView@v1                 an agent-formed view — claim, reasoning, confidence, falsifier.
                             Provenance class A. Marked as opinion everywhere it is displayed.
AGENT_COMMITMENT@v1          subject_key · claim · confidence · horizon · falsifier · checkpoint_id
                             A view with no falsifier is not a commitment — it is a sentence,
                             and it does not enter the store.
                             MBI_BEHAVIOR stays 0: a commitment is a belief, never an order.
```
