---
id: DSN-20261026-ask-hourly
title: Hourly Ask the CIO lifecycle
status: IN_PROGRESS
approval: "Operator 2026-10-26: Implement the plan. Checks need to run hourly, not once a day. Opus primary and independent critiques selected in session."
phases:
  - id: DSN-20261026-ask-hourly-P1
    title: Implement and verify the hourly research lifecycle
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261026-ask-hourly-P1-T1
        title: Durable checks, budgets, shared memory and lifecycle projection
        status: IN_PROGRESS
        areas: [scripts/lib/cio_ask_lifecycle.py, scripts/lib/cio_ask_store.py]
      - id: DSN-20261026-ask-hourly-P1-T2
        title: Governed Opus primary and independent provider critiques
        status: IN_PROGRESS
        areas: [scripts/lib/cio_ask_research.py]
      - id: DSN-20261026-ask-hourly-P1-T3
        title: Operator freshness and manual refresh on desktop and phone
        status: IN_PROGRESS
        areas: [apps/command-center-v3/src/pages/MyQuestions.tsx]
      - id: DSN-20261026-ask-hourly-P1-T4
        title: Native n8n schedules, admission and business health
        status: IN_PROGRESS
        areas: [scripts/lib/cio_ask_lifecycle_health.py]
---
# Hourly Ask lifecycle

One canonical Ask ledger records requests, checks, answer versions, shared-memory
acknowledgements and delivery status. Native n8n schedules an hourly pass on the
hour in America/New_York plus material-source polling every five minutes. Both
lanes share the executor lock; no host crontab is changed.

Checks and answer generation have different clocks. A successful unchanged check
advances last_checked_at without replacing the answer or inventing a new version.
Models run only for material evidence, a genuinely requested manual refresh or
recovery of an incomplete answer. Aggregate Ask budgets and uncertain holds are
serialized under the existing Ask ledger lock; process/global/provider caps still
bind. Scheduled work has its own process and never forges operator intent.

The primary analysis uses governed Opus. Reviewer routes are bound to independent
providers. Their actual receipts, missing reviews and source/search gaps remain
visible. Source facts and answer summaries use existing shared CIO memory writers.
Memory/delivery retries reuse the saved answer rather than invoking a model again.

Activation requires reviewed native contracts, required CI and exact release
readback. Dry-run receipts do not prove live business freshness. The source
implementation does not activate n8n, mutate broker behavior, expose credentials,
change AGENTS.md or perform a real model call.
