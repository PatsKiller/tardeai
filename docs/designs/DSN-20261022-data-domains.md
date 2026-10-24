---
id: DSN-20261022-data-domains
title: Data domain approvals (17 proposed domains)
status: PROPOSED
approval: awaiting operator (batches B-D); batch A approved (approval E)
source: docs/ops/DATA_DOMAIN_APPROVAL_READINESS_2026-10-22.md
summary: 58 domains APPROVED in config/data_source_authority.json; 17 proposed. Phases are the readiness report's batches.
  The operator approval list is board task T-20261023-240510.
phases:
- id: DSN-20261022-data-domains-P1
  title: Batch A — cio_prospect (approval E given; promotion pending)
  status: APPROVED
- id: DSN-20261022-data-domains-P2
  title: Batch B — security_identity, positions_store, broker_stops, fused_signals, cio_theses
  status: PROPOSED
  tasks:
  - id: DSN-20261022-data-domains-P2-T1
    title: 'OPERATOR: sign off batch B domains'
    status: PROPOSED
    areas:
    - operator/decisions/domains-b
    owner: OPERATOR
- id: DSN-20261022-data-domains-P3
  title: Batch C — transactions, catalyst_events, cio_decisions, options_ideas, scanner_results, comms_intents, alert_events,
    watchlist_membership (unconsolidated writers)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-data-domains-P3-T1
    title: 'OPERATOR: sign off batch C domains (writers consolidate first)'
    status: PROPOSED
    areas:
    - operator/decisions/domains-c
    owner: OPERATOR
- id: DSN-20261022-data-domains-P4
  title: Batch D — paper_proposals, paper_trades (needs an execution-engineering grant)
  status: PROPOSED
- id: DSN-20261022-data-domains-P5
  title: operator_settings — not ready, fix first
  status: HELD
- id: DSN-20261022-data-domains-P6
  title: Ops -> Controls Data approvals readiness view
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-data-domains-P6-T1
    title: 'Land #1976 Data approvals readiness (green, mergeable) in batch 10'
    status: PROPOSED
    areas:
    - apps/command-center-v3/src/lib/opsControlsData.ts
---

Seeded 2026-10-23 from the readiness report (§3, lines 92-141; verdicts lines 49-65).

Backfill 2026-10-23: the Ops view #1976 is green and mergeable (batch 10 candidate).
