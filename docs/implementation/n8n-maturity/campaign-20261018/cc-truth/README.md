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
