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
4. The panel reads the GET-only `/api/v3/cio/decision/<id>/lineage`
   (`CIODecisionLineage@v1`) and shows each stage's state, `state_reason`,
   producer, `source_ref` and `source_as_of`.

Deep links (all router-relative inside the app; BrowserRouter owns `/v3`):

- `/v3/cio?tab=decisions&decision=<id>` opens and scrolls to that exact
  decision's lineage at the top of the Decisions tab (**Clear focus** removes it).
- `/v3/cio?tab=research&decision=<id>[&artifact=<aid>]` filters the research
  evidence groups to that decision and shows the focus banner; `research=<rid>`
  from Research Intelligence is shown in the same banner.
- Tab switches keep `decision=`; there is never a symbol fallback.

## Stage honesty

States are derived on the backend (`scripts/lib/cio_decision_lineage_projection.py`);
the panel renders them verbatim with their `state_reason`.

- `LIVE` — a durable row matched to THIS decision carries the stage value, a
  parseable `source_as_of` and a `source_ref`.
- `PARTIAL` — a matched row exists but lacks a required field (no clock, no
  ref, or only a request id without a result).
- `PENDING` — an outcome checkpoint whose horizon has not matured (or a
  producer-recorded PENDING).
- `NOT_RUN` — the producer explicitly recorded skip / not-yet-created
  (`stage_status`, `cognition_refs.skipped`).
- `NOT_APPLICABLE` — the producer recorded not-required, or the checkpoint
  resolved as not price-resolvable.
- `UNWIRED` — the stage has no producer contract in this system; declared per
  stage with a reason in `UNWIRED_STAGES` (today: `canon_frameworks`,
  `specialist_disagreement`).
- `UNAVAILABLE` — the stage's source store is missing or unreadable.
- `UNKNOWN` — none of the above could be established.

`False`, `0` and `""` are never evidence. `source_ref`, `run_id`, `trace_id`
and `source_as_of` are null unless a row matched; a row without its own
`source_ref` is cited as `<store>:<row id>`. The UI never fills a missing node
from a neighboring field and never presents composition time as source time.

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
