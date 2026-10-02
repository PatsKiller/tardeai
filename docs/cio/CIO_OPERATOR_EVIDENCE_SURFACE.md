# CIO Operator Evidence Surface

Status: IMPLEMENTED LOCALLY · `READ_ONLY_ADVISORY`

## Contract

`GET /api/v3/cio/operator-evidence` returns `CIOOperatorEvidence@v1`, a
read-only composition over existing CIO stores. It is not a second source of
truth and the React page does not infer capability state.

Every block carries:

- `source_as_of`
- `composition_as_of`
- `producer`
- `authority`

## Research provenance

Research artifacts are classified only from explicit canonical receipts:

- `USED_IN_JUDGMENT`: a positive use receipt from a closed allowlist. That is `True`, `"USED"`,
  `"USED_IN_JUDGMENT"`, a non-empty list of consuming decision ids (`consumed_by`,
  `consumed_by_decision_ids`), or an `intelligence_lineages.jsonl` row with status `ADVISORY_USED`
  that names exactly that one result id. `intelligence_lineage` writes that row only from the
  product-reassessment use receipt. Any other value (`"NOT_USED"`, `"no"`, `"0"`, `"rejected"`, a
  dict) proves nothing. For a single-decision lookup, a lineage receipt counts only when it names
  that decision.
- `REJECTED`: an explicit rejection field (`rejection_reason`, `reason_rejected`, ...), which is
  also the reason shown. A bare `status: REJECTED` with no reason is not a rejection.
- `RETRIEVED`: a retrieval fact (`retrieved_at`, `retrieved_ts`, `fetched_at`, `result_id`,
  `retrieval_receipt_id`, `fetched: true`) and no use or rejection receipt. Retrieval is not use.
- `UNKNOWN`: none of the above. The store a row came from is never a fact.

Each artifact exposes `artifact_id`, `source_type`, `publisher`, `source_url`, `source_ref`,
`source_store`, `publication_date`, `retrieved_at`, `source_as_of`, `symbol`/`affected_entities`,
`subject_guid`, `research_run_id`, `agent_model`, `provider`, `relevance`, `support_or_challenge`,
`status`, `status_basis`, `use_receipt_ref`, `reason_used_or_rejected`, `decision_id(s)`,
`trace_id` and `evidence_class`. A field the producer did not write is `null`; it is never
filled from a neighbouring field or the store name. The one exception is `retrieved_at` on a
Hermes result row: the row is itself the retrieval, so its `completed_ts` is used.

## Institutional cognition

The block separates the two kinds of information explicitly:

- `office_truth`: prices, holdings, cash, broker state, orders and risk limits.
  `sourced_from_memory: false` and `replaceable_by_cognition: false`. The block carries no office
  truth values. If a cognition row contains such a field, the field is withheld and listed in
  `office_truth_fields_withheld`.
- `institutional_cognition`: memory retrievals, memory contexts, research lineage, context-use
  receipts and `prior_operator_decision` items. The last group is the operator's prior REJECT and
  DEFER advice from `operator_ticker_feedback`, `decision_dispositions`, `cio_operator_learning`
  and `cio_defer_lineage`. Quarantined and synthetic defer lineages are excluded.

Each item reports:

- `availability`: `AVAILABLE` only when the row has a parseable clock that is not in the future;
  otherwise `UNKNOWN` with a reason.
- `state`: `UNKNOWN`, `AVAILABLE`, `RETRIEVED` (a retrieval basis is named) or `USED` (an
  allowlisted use receipt).
- `changed_question_or_view` and `contradictory` flags. Contradictory items are also listed in
  `contradictory_items` so they stay visible.
- `influence`: `PROVEN` only with an influence or use receipt (`influence_receipt_id`,
  `influence.changed_decision`, or a use receipt).

## Learning

- Outcome rows come from `advisory_outcomes_v1.jsonl` and `outcome_observations.jsonl`, read
  whole up to 32 MB. Belief ids of the form `adv:<source_row_id>:<N>d` resolve against
  `data/runtime/advisory_outcomes.jsonl`. An observation is settled when its horizon price is
  realised. Its verdict comes from the producer rule `outcome_to_lesson._direction`, so
  non-directional recommendations are settled with no verdict.
- `sample_size` and `successful_count` both count unique settled outcome ids that carry a
  verdict, so `success_rate` is always 1 or less. `settled_count` and
  `settled_without_verdict_count` are reported beside them.
- `evidence_state` on lessons, hypotheses and beliefs is:
  - `PROVEN`: every evidence id resolves to a settled outcome row.
  - `PENDING_OUTCOME`: the ids resolve only to unsettled rows.
  - `INSUFFICIENT_EVIDENCE`: otherwise. The unresolved ids are listed.
- `calibration` appears only when computed from settled outcomes, with the method stated
  (`CALIBRATION_METHOD`, grouped by population and horizon). Otherwise it is `null`, and
  `calibration_reason` says why. A belief's calibration shows only when its outcomes are PROVEN
  and its producer stated a `calibration_schema`.
- `review_ready` requires both a producer `REVIEW_READY` stage and `PROVEN` evidence.
  `producer_review_ready_unproven` counts the rows that claim the stage without the evidence.
- `link_graph` holds decision→outcome, outcome→belief, belief→lesson/hypothesis and
  lesson→source outcome/decision edges. Edges come only from ids carried by producer rows, never
  from a symbol join. Each edge records whether its target resolved.

## Capability coverage

Coverage is built server-side from producer modules, durable artifacts and observed rows. Each
capability has a producer predicate, so capabilities that share a store are told apart:

- `cio_workflow_lineage.jsonl`: `node_type` CIO_PRODUCT gives synthesis, CIO_GENERATION gives
  judgment, and the disagreement node types and relations give disagreement.
- `cio_instrument_records.jsonl`: `InstrumentRecord@v1` rows give InstrumentRecord, and belief
  entries `written_by: cio_belief_writer` give the belief writer.
- `security_research_spine.jsonl`: Hermes `research_result` contributions give external research.

Identity resolution cannot be told apart from spine publication, so it says so in `reason` and is
capped at `PARTIAL`.

| State | Rule |
|---|---|
| `DARK` | The producer store is missing, or no row matches the predicate in the window, and the producer module is declared. |
| `UNKNOWN` | Same, but no producer module exists in the repo. |
| `PARTIAL` | Producer rows exist, but no consumer row carries an explicit reference: an id from the producer rows, or the producer store named in `source_ref`/`producer`. |
| `LIVE` | Producer rows plus an explicit consumer reference. |
| `UNWIRED` | No declared consumer contract. |

`freshness` is a separate field (`FRESH`, `STALE` or `UNKNOWN`), set by `stale_after_seconds`
per capability against `composition_as_of`. Clocks in the future are ignored.

`known_dark_classification` exposes `config/cio_known_dark_classification.json`. Every
`KNOWN_DARK` entry is classified WIRE, RETAIN_WITH_REASON or RETIRE; see
`CIO_KNOWN_DARK_CLASSIFICATION.md`.

## Operator boundary

The surface cannot place trades, cancel orders, modify stops, alter risk or
policy, request 2FA, send a decision, or self-promote a lesson. Control Plane
pages remain the diagnostic/engineering view; this surface is the CIO
investment-office view.
