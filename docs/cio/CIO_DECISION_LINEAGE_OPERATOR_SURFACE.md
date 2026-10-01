# CIO Decision Lineage — Operator Surface

Status: IMPLEMENTED LOCALLY · READ_ONLY_ADVISORY
Measured against: `origin/main` at `f73d8c6bb4bffd61a0c42b8a978a8fbe62402242`

## Purpose

The CIO desk answers the investment-office question: “What does the CIO think,
why, and what needs my response?” Decision lineage is connected to that surface
without replacing it with the Control Plane. Control Plane pages remain the
diagnostic/engineering view.

## Operator path

1. Open `/v3/cio?tab=decisions`.
2. On a material decision with a canonical `decision_id`, select **View CIO
   decision lineage**.
3. The desk opens `/v3/cio?tab=evidence-comms&sub=decision-lineage&decision=<id>`.
4. The panel reads the GET-only IntelligenceLineage API and shows the selected
   record, producer, entity, status, timestamps, and lifecycle stages.

## Stage honesty

The panel renders a stage as `LIVE` only when the selected lineage record
contains evidence for that stage. Missing stages are explicit:

- `UNAVAILABLE` — the record does not expose the required evidence.
- `UNWIRED` — the stage is a known capability edge without a runtime artifact.
- `NOT_RUN` — the stage has not run for this record.
- `NOT_APPLICABLE` — the record is not far enough through the lifecycle.
- `OUTCOME_PENDING` — no settled outcome or derived lesson exists yet.

The UI never fills a missing node from a neighboring field and never presents
composition time as source time.

## Authority boundary

This is a read-only advisory projection. It does not place or cancel orders,
modify stops, alter risk or policy, request 2FA, send Telegram decisions, or
promote learned rules. Operator disposition remains a separate governed action.

## Validation record

Local validation for checkpoint `bac72d352`:

- frontend design, contrast, standards, TypeScript, and Vite build: PASS
- targeted CIO/operator tests: 63 passed
- selected CIO hardening gates: PASS
- served-CURRENT browser validation: PENDING
- natural-cycle/live Telegram proof: PENDING
- remote sync/deployment: governed action pending

Do not label the feature LIVE until the served CURRENT bundle and a natural
runtime observation prove it.
