# Truthful CC observations — October 18, 2026

Local source implementation; not deployed or operationally proven. The source commits are
`15850afef45f54d5e81341928da518891ec3e96b` and `4aede76600da4621e758af4c0d9c3727de184664`.
The integrator independently reviewed production source and passed 45 backend tests plus all four affected
TypeScript suites. New tests are wired into the existing CIO gate and frontend build. Required exact-head
local acceptance, hosted CI and reviewed PR remain separate gates.

N8nToday@v2, N8nCoordinationProjection@v2, N8nCoordinationRunsProjection@v2 and
NotificationOutboxProjection@v2 separate source availability, sample details and complete aggregates.
Unavailable totals are null. Each view declares actual source/window/coverage; no full-window total is
computed from a bounded row sample. API errors and stale records retain the actual last good timestamp;
a current failed capture is never a last good observation. Exit0, a repair action and first live execution
are not business recovery or cutover receipts.

The frontend reads oldv1 conservatively; an old cachedv1frontend with a newv2writer is unsupported.
Canonical release must deploy the refreshed backend/frontend together. No source/API dispatcher, scheduler,
workflow, live mode, authorization, delivery or acknowledgement mutation is included.

The reviewer found an incorrect outbox baseline capture: both alleged red/green logs passed. They are
explicitly superseded in the author packet. Corrected evidence verifies the imported source bytes and exact
3af0a8b baseline: the identical three behavioral assertions fail, then pass on4aede. No collection error or
arbitrary nonzero result is counted as red-first proof.

Full native acceptance at61c41 failed six legacy fixture expectations across three existing suites. The
follow-up supplies actual RunReceipt mode/identity metadata for intentionally completed-run fixtures, adds
the real ledger store_key column to the notifier fixture, and changes three missing-source assertions to
v2 UNAVAILABLE. It preserves bearer/path/body-cap checks, migration phases with actual executed modes,
and operator-notification assertions. The separate unknown-effective-mode tests remain enforced; requested
live alone is never promoted to executed live. No production source changed in this fixture follow-up.

Ruff formatting of the four touched legacy test files is mechanical; their ASTs match before/after that
formatting step. The semantic fixture changes above are separate.66 non-HTTP adjacent tests pass; full
native acceptance will exercise the relay HTTP cases and the complete suite at the final head.
