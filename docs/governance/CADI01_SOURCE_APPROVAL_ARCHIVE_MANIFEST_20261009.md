# CADI-01 source approval archive manifest

Status: APPROVED REGISTRATION; PRODUCTION ACTIVATION NOT GRANTED
Owner: John (operator); CADI implementation agent (provenance); Agent A (review/merge/release)
as_of: 2026-10-09T11:42:14-04:00
Measured at: operator conversation and isolated CADI-01 clone, checkpoint `86eeb9ba021647ed6f6c4dab83087881378a3fb9`

## CADI01-SOURCE-APPROVAL-20261009

The operator's current reply was **"approved"**, immediately after this specific request:

> Approve CADI-01 stores `cross_asset_evaluation_history` and `cross_asset_decision_projection`, with sole writer `scripts/lib/cross_asset/decision_store.py`; no production activation.

This is a conversation approval of those two registrations under AGENTS.md sections 7A/17,
not an inferred approval from the earlier plan, generic push instruction or another agent's
grant. The recording timestamp above is observed locally; a message ID and an exact operator
message timestamp were not supplied and are not fabricated. This manifest is the retained
reference for both registry rows, not a claim of a Telegram approval or an already-approved PR.

| Domain | Store | Sole writer | Approved scope |
|---|---|---|---|
| `cross_asset_evaluation_history` | `cio/cross_asset_decisions.sqlite`, table `cross_asset_evaluation_history` | `scripts/lib/cross_asset/decision_store.py` | Immutable advisory evaluations and per-symbol error history; registration and fixture/local implementation only |
| `cross_asset_decision_projection` | Same SQLite file, table `cross_asset_decision_projection` | `scripts/lib/cross_asset/decision_store.py` | Rebuildable latest advisory decisions from that history; registration and fixture/local implementation only |

No production database is created, migrated or written by recording this approval. The separate
`TRADEAI_CADI_RECORDS_READ_ENABLED` activation control is not enabled by this change. No scheduler,
workflow import, model promotion, retention extension, broker or trading authority is granted.
The system remains READ_ONLY_ADVISORY, NO_PROVEN_WINNER and NOT READY for the full CADI program.

Before remote sync: rerun canonical local acceptance and inspect its actual exit and failures,
commit the completed candidate, obtain a separate exact-SHA git-push grant and use the normal hook.
Agent A reviews the PR and controls merge and release. No self-merge or deployment is authorized
by this source-registration approval.

Before state: both rows had null `approved_by`/`approved_on`, with two UNAPPROVED_SOURCE findings.
After state: both rows point here with `approved_by=operator`, `approved_on=2026-10-09` and their
unchanged single writer and no-production-activation scope. This manifest alone is not a passing
test receipt. Subsequent post-approval validation on `d8431c7eb4a3f3b724e5d8deefe146470bd97e59`:
seven targeted suites **155 passed / exit 0 / 409.67s**, including native authority clean-gate and
negative-control assertions. JUnit is retained at
`~/cadi-evidence/cadi01-approved-20261009-U2sUcP/approved-targeted.xml`, SHA256
`227f2fc862ba43d0f310f3c575ec4d6c1d9efc92594ce6708f08428110892962`.
Independent approval review found no blocking issues. Final integrated-tree full acceptance
remains NOT RUN; it awaits the peer docs-index lease handoff and is not waived by these results.
