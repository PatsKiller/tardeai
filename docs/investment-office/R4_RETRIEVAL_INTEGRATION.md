# R4 Retrieval + Decision-Use Audit

Status:      ACTIVE
as_of:       2026-08-15T08:06:05-04:00
Measured at: efcc51365 / not measured

Dry-testable integration (RGA-16). Authority: `READ_ONLY_ADVISORY`.

## What R4 is

- `InMemoryRetriever` implements the R1 `ResearchRetriever` protocol.
- `retrieve_for_decision` (adapter) maps Almanac + optional CIO compact facts
  into `ResearchEvidence` and **must** write a signed `DecisionUseRecord`.
- Live research use without that record fails RG-10.
- Live research use without a degradation decision fails RG-11.
- Degradation retires grade X / failed reproduction; degrades consumed-OOS facts.

## What R4 is not

- Not a rewrite of `rag_retrieval.py`, Hermes, or `kb_lessons`.
- Does not send Telegram, change reports, or open broker/order/stop paths.
- Does not change production default CIO behavior unless a caller uses the
  audited adapter.

Existing `cio_research_retriever.retrieve_research_context` remains the live
hook; R4 wraps it fail-soft when importable.
