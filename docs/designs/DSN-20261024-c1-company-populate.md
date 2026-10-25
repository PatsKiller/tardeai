---
id: DSN-20261024-c1-company-populate
title: 'WP-29 confirmed-security company facts in shared CIO memory'
owner: cio; codex-c1-populate-20261024 source worker
status: IN_PROGRESS
approval: 'Source implementation requested in coordinator-batch21-20261024/c1-populate-request.md; migration, contract admission and runtime activation require operator decisions.'
phases:
  - id: DSN-20261024-c1-company-populate-P1
    title: Fact-only facade, production-copy proof and native apply packet
    status: IN_PROGRESS
    goal: Populate identity and company evidence without inventing CIO judgments or a parallel store.
    entry_criteria: C1 population request and exclusive backend/config claim; immutable authorized source capture.
    acceptance:
      - Same GUID facts through existing apply_prospect/upsert_prospect, no judgment or promotion.
      - Exact before/after copy coverage, every gap, source clocks and idempotency proof.
      - Real FATN/ANET component fixtures, hidden-PG tests and required source gates.
      - Inactive native apply workflow with honest DRAFT health and operator packet.
    gates:
      - Coordinator owns publication and release; no worker push, DB backfill or scheduler activation.
      - Explicit migration grant if PG enabled, actual owner contract review and existing framework admission.
    tasks:
      - id: DSN-20261024-c1-company-populate-P1-T1
        title: Implement fact-only population and prepare reviewed runtime handoff
        status: IN_PROGRESS
        areas:
          - scripts/lib/cio_instrument_record.py
          - scripts/lib/cio_company_population.py
          - scripts/cio_company_facts_populate.py
          - docs/ops/packets/c1-company-population-20261024
  - id: DSN-20261024-c1-company-populate-P2
    title: Operator admission, backfill and native runtime acceptance
    status: HELD
    goal: Apply accepted source under existing authority and demonstrate exact consumer readback.
    entry_criteria: Source merged/released; operator approves migration if needed and actual contract review.
    acceptance:
      - Exact-CURRENT backfill receipt, canonical same-GUID facts and consumer readback.
      - Native workflow admitted/imported inactive, framework activation gate passed, exact approved activation.
      - Expected trigger through output, reader and notification proof; every gap retained.
    gates:
      - OPERATOR-only DB/schema/state/config/service/workflow authority as applicable.
      - No invented review provenance, identity minting or silent divergent-store repair.
    tasks:
      - id: DSN-20261024-c1-company-populate-P2-T1
        title: Review and execute the operator packet after release
        status: HELD
        areas:
          - operator-only/c1-company-population
---

# Shared CIO company facts population

See [delivery and measured gaps](../ops/C1_COMPANY_FACTS_POPULATION_20261024.md) and the
[operator runbook](../ops/packets/c1-company-population-20261024/RUNBOOK.md).
No runtime completion is claimed by this source task.
