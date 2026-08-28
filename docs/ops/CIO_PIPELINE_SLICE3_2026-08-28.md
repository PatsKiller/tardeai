# CIO Pipeline Slice 3 — label the two reentry books

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MEMORY_BEHAVIOR_INFLUENCE: 0
Branch: `feat/cio-pipeline-slice3-reentry-book-labels`

## What this slice did

P9.3 / #584: two `build_reentry_book` functions answer different questions with the same voice. This slice **labels** them. It does **not** merge them and does **not** pick a winner.

| Surface | Scope | Question | Producer |
|---|---|---|---|
| **A** | former holdings vs exit trigger | which former holdings are near their re-entry trigger? | `cio_investment_product.build_reentry_book` |
| **B** | candidates vs cash-stage R:R under desk thesis | which candidates have acceptable risk-reward at the current cash stage? | `cio_desk_depth.build_reentry_book` |

Labels (`surface`, `scope`, `question`, `precedence`, `not_this_book`) are stamped on both payloads. CioHub Investment Books and home Opportunities re-entry chips show Surface A. Desk-note / Telegram template states Surface B and that it is independent of A. Morning brief prefixes `Re-entry book A (former holdings vs exit trigger)`.

## What this slice did not do

- No merge of the two books
- No notify / no new Telegram producer
- No ThesisDecisionGate / MBI / ROTATE / stop-management change

## After promote (fill live)

| Metric | Value |
|---|---|
| SOURCE | *(filled)* |
| Surface A leading names | *(filled)* |
| Surface A scope | former holdings vs exit trigger |
| Surface B leading names | *(filled)* |
| Surface B scope | candidates vs cash-stage R:R under desk thesis |
