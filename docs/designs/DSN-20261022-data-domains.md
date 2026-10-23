---
id: DSN-20261022-data-domains
title: Data domain approvals (17 proposed domains)
status: PROPOSED
approval: awaiting operator (batches B-D); batch A approved
source: docs/ops/DATA_DOMAIN_APPROVAL_READINESS_2026-10-22.md
summary: 58 domains APPROVED in config/data_source_authority.json; 17 proposed. Phases are the readiness report's batches.
phases:
  - id: DSN-20261022-data-domains-P1
    title: Batch A — cio_prospect (approval E given; promotion pending)
    status: APPROVED
  - id: DSN-20261022-data-domains-P2
    title: Batch B — security_identity, positions_store, broker_stops, fused_signals, cio_theses
    status: PROPOSED
  - id: DSN-20261022-data-domains-P3
    title: Batch C — transactions, catalyst_events, cio_decisions, options_ideas, scanner_results, comms_intents, alert_events, watchlist_membership (unconsolidated writers)
    status: PROPOSED
  - id: DSN-20261022-data-domains-P4
    title: Batch D — paper_proposals, paper_trades (needs an execution-engineering grant)
    status: PROPOSED
  - id: DSN-20261022-data-domains-P5
    title: operator_settings — not ready, fix first
    status: HELD
---

Seeded 2026-10-23 from the readiness report (§3, lines 92-141; verdicts lines 49-65).
