# Question id contract — semantic, not positional (2026-08-29)

Status:      HISTORICAL
as_of:       2026-08-29T15:23:52-04:00
Measured at: efcc51365 / not measured

Found by the system critiquing itself. The one live Grok critique on SPCX
flagged that the artifact answered `q1/q2/q3` rather than the requested ids. A
scan of all 471 stored results showed the same shape book-wide:

    q1 337 · q2 191 · q3 191 · q_cat_1 134 · q_cat_2 134 · q_cat_3 134

Never a semantic id.

## The defect is not naming — it is that ids were positional

`cio_hermes_research` assigned `q{i+1}` when a question carried no explicit id.
So **`q2` meant "whatever was second in the list that day"**. Reorder the
questions, or drop one, and every carried-forward answer keyed on `q2` silently
attaches to a different question. Nothing errors. The mapping is just wrong.

That breaks the ladder's premise directly: Flash asks question_ids, Pro answers
*those* ids, OpenAI takes the residual, and the critique judges completeness
against them. If the ids move, the carry is fiction.

## Two vocabularies, one concept

Every question already carried a stable semantic field — but there were two:

    cio_hermes_research.default_questions_for_plan  ->  intent
    research_need_decision.decide                   ->  dim

Two names for one concept is how the earlier drift bugs in this codebase
started (two `total_cash` writers, two freshness laws). Both now resolve
through a single function, `cio_question_ids.question_id_for`, with `dim`
mapped into the `intent` vocabulary.

## The rule

    1. explicit question_id / id   — callers with a contract keep it
    2. intent, then dim           — the semantic anchor
    3. positional q{n}            — last resort, so a malformed question still
                                    gets an id instead of crashing the enqueue

Ids are **derived, never stored-and-diverged**: the same intent yields the same
id on every pass and every provider.

Duplicate intents get `_2`, `_3` suffixes rather than colliding — a collision
would let the second answer overwrite the first.

## Result

| situation | question ids |
|---|---|
| S6 concentration | `q_drift_attribution` `q_catalyst_map` `q_invalidation` |
| S1 lifecycle | `q_catalyst_map` `q_invalidation` `q_thesis_check` |
| S5 cash | `q_deployment_candidates` `q_regime` `q_liquidity` |
| S3 reentry | `q_thesis_check` |
| v1 gate | `q_structural_drivers` `q_bear_case` `q_priced_in` |

Wired at all three minting sites: `cio_hermes_research` (enqueue),
`hermes_research_backend` (normaliser), `research_need_decision` (v1 gate).
Each import is guarded so a failure degrades to the old behaviour rather than
breaking an enqueue.

## Nothing was backfilled

Historical results keep their positional ids. A backfill would rewrite evidence
to match a contract it was never produced under — the stored answers really
were keyed that way, and pretending otherwise loses the fact that the mismatch
happened. A test asserts the legacy ids are still present.

## Verification

22 contract tests, including the two that pin the property that actually broke:
ids do not move when questions are **reordered**, and do not renumber when one
is **dropped**.

269 green across the research surface. Four failures, all confirmed present in
the recorded `origin/main` baseline and unrelated to this change:
`test_run_apply_skip_gate_blocks_metered`, `test_non_policy_symbol_skips_gate`,
`test_apply_live_flag_exists_and_warns`, `test_notify_true_only_for_apply_live`.

Acceptance green.

## Not done

No re-run of the critique — that is a 3D hop and was not authorised here. No
backfill, no enqueue, no notify, no cap raise. MBI 0.
