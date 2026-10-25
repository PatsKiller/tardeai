---
id: DSN-20261024-w8-writers
title: 'W8 monitored n8n writer restoration and registry ownership'
owner: codex-w8-writers-20261024
status: IN_PROGRESS
approval: 'Source work requested by the W8 row in coordinator-batch21-20261024/parallel-split-request.md. Normal existing claim handoff precedes registry edits. Operator/coordinator activates; worker never activates.'
phases:
  - id: DSN-20261024-w8-writers-P1
    title: Source ownership, scheduling and success-evidence preparation
    status: IN_PROGRESS
    goal: Restore monitored writer coverage without duplicating absorbed writers or changing execution authority.
    entry_criteria: W8 task and exclusive source-path claim; origin/main after 2072.
    acceptance:
      - Trace every requested writer, its actual schedule owner, durable success evidence and admission gaps.
      - Preserve earlier claims and request normal registry/allowlist/health scope handoff.
      - Hidden-Postgres fixtures, registry and reconciliation CHECK, ratchets, completeness and native build.
    gates:
      - Earlier registry claims must be released normally; no override or takeover.
      - No push, merge, release, host scheduler changes, live sends, broker/order/stop behavior or policy/guard edits.
      - New health drafts are nonoperative and never marked REVIEWED by the worker.
    tasks:
      - id: DSN-20261024-w8-writers-P1-T1
        title: Prepare source restoration and monitoring evidence; integrate after normal scope handoff
        status: IN_PROGRESS
        areas:
          - config/n8n_writer_restoration.json
          - scripts/lib/n8n_writer_restoration.py
          - scripts/n8n_writer_restoration.py
          - docs/ops/packets/w8-writers-20261024
  - id: DSN-20261024-w8-writers-P2
    title: Owner review and operator activation
    status: HELD
    goal: Admit only audited writers and prove exact-trigger output, consumers and independent missed-run alert delivery.
    entry_criteria: Normal claims handoff; producer contracts and health review; released accepted source.
    acceptance:
      - Registry, allowlist, native schedules, expected outputs and monitoring describe the same admitted lane.
      - Existing pipeline writers retain one schedule owner.
      - Exact business-run, consumer and alert-delivery proof after operator activation.
    gates:
      - Execution-adjacent lanes remain paused pending separately named operator authority.
      - Worker never performs activation or changes host schedules.
    tasks:
      - id: DSN-20261024-w8-writers-P2-T1
        title: Review and activate the admitted source package
        status: HELD
        areas:
          - operator-only/w8-writer-admission
---

# W8 monitored writer restoration

The [W8 evidence and handoff](../ops/W8_WRITERS_20261024.md) distinguish completed source preparation from blocked registry integration and runtime acceptance.
