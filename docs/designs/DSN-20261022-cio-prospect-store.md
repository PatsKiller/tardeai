---
id: DSN-20261022-cio-prospect-store
title: CIO prospect store (one record per security) + no-silos wiring
status: IN_PROGRESS
approval: 'approved (AGENTS.md 18.0.0 §26; approval E 2026-10-22: row, migration 6bac8924, reader batch); no-silos directive
  2026-10-23'
source: docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md
summary: 'One CIO-owned record per security_guid; every per-security fact lands in CIO memory (operator 2026-10-23: "We should
  have no silos.").'
phases:
- id: DSN-20261022-cio-prospect-store-P0
  title: Architecture, dictionary rows, CI checks, 18.0.0
  status: LIVE
- id: DSN-20261022-cio-prospect-store-P1
  title: Shadow — migration + dual-write + shadow builder + lane (built inert)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-cio-prospect-store-P1-T1
    title: Promote the cio_prospect row grant (approval E) in its own PR — investigated by T-20261023-9c7a5c
    status: IN_PROGRESS
    areas:
    - config/data_source_authority.json
    board_task: T-20261023-9c7a5c
  - id: DSN-20261022-cio-prospect-store-P1-T2
    title: 'Land #1953 cio-prospect-shadow lane at SHADOW (contract REVIEWED on branch, approval F)'
    status: PROPOSED
    areas:
    - config/n8n_health_contracts.json
- id: DSN-20261022-cio-prospect-store-P2
  title: Compare job
  status: PROPOSED
- id: DSN-20261022-cio-prospect-store-P3
  title: Switch readers in batches
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-cio-prospect-store-P3-T1
    title: 'Positions reader batch #1 (Watch held flag) — #1930'
    status: DONE
    areas:
    - history/cio-prospect/reader-1
    evidence: '#1930 merged 2026-10-22 16:48Z, LIVE batch 5 ee38621b1'
  - id: DSN-20261022-cio-prospect-store-P3-T2
    title: 'Positions reader batch #2 (+stop_health/positions_proof) — #1946/#1947'
    status: DONE
    areas:
    - history/cio-prospect/reader-2
    evidence: '#1946 + #1947 merged 2026-10-22 21:59Z, LIVE batch 5 ee38621b1'
  - id: DSN-20261022-cio-prospect-store-P3-T3
    title: 'Home reads positions through reader batch #3 (approval G) — #1978'
    status: DONE
    areas:
    - history/cio-prospect/reader-3
    evidence: '#1978 merged in batch 8 #2002, LIVE 80e93c99f'
  - id: DSN-20261022-cio-prospect-store-P3-T4
    title: 'OPERATOR: approve positions reader batch #4 (curator held flag) — phrase ''approve positions reader batch #4 (curator
      held flag)'''
    status: PROPOSED
    areas:
    - operator/decisions/reader-batch-4
    owner: OPERATOR
- id: DSN-20261022-cio-prospect-store-P4
  title: Retire old stores with a tripwire
  status: PROPOSED
- id: DSN-20261022-cio-prospect-store-P5
  title: 'No-silos wiring: 46 producers -> the CIO record (audit: 3 wired / 16 partial / 27 silo)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-cio-prospect-store-P5-T1
    title: 'Memory silo audit doc — #1995'
    status: DONE
    areas:
    - history/cio-prospect/silo-audit
    evidence: '#1995 merged in batch 8 #2002, LIVE 80e93c99f (docs/ops/CIO_MEMORY_SILO_AUDIT_2026-10-23.md)'
  - id: DSN-20261022-cio-prospect-store-P5-T2
    title: 'Batch #1996 / #2000 / #2001 (catalyst facts, held-after-sale guard, directives+proposals) — board task T-20261023-c72f3b'
    status: PROPOSED
    areas:
    - scripts/lib/cio_prospect
    board_task: T-20261023-c72f3b
  - id: DSN-20261022-cio-prospect-store-P5-T3
    title: 'OPERATOR: decide suppress_add_hold and HELD->EXIT'
    status: PROPOSED
    areas:
    - operator/decisions/suppress-add-hold
    owner: OPERATOR
  - id: DSN-20261022-cio-prospect-store-P5-T4
    title: 'OPERATOR: decide the SAIQ GUID split'
    status: PROPOSED
    areas:
    - operator/decisions/saiq-guid
    owner: OPERATOR
  - id: DSN-20261022-cio-prospect-store-P5-T5
    title: Broker-sync staleness guard (needs an execution-engineering grant naming the files)
    status: HELD
    areas:
    - scripts/brokers/broker_sync_staleness.py
  - id: DSN-20261022-cio-prospect-store-P5-T6
    title: 'CIO data quality: stop_lifecycle ordering + Hermes wrong-company catalysts — board task T-20261023-9a2754'
    status: PROPOSED
    areas:
    - scripts/lib/cio_prospect_builder.py
    board_task: T-20261023-9a2754
- id: DSN-20261022-cio-prospect-store-P6
  title: Trade journey (origin, stop path, exit cause, review, re-entry) — TradeInView
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-cio-prospect-store-P6-T1
    title: 'Rebase and land #1955 TradeInView journey (green, conflicting)'
    status: PROPOSED
    areas:
    - apps/command-center-v3/src/fixtures/tradeJourneys.fixture.ts
- id: DSN-20261022-cio-prospect-store-P7
  title: 'Watch hygiene approved 2026-10-22: enrichment-coverage scope + in_directive_watch at source'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261022-cio-prospect-store-P7-T1
    title: 'Land #1958 (enrichment-coverage audit) and #1960 (directive flag at source) in batch 10'
    status: PROPOSED
    areas:
    - config/ci_gates/enrichment_coverage_audit_20261022.json
    - scripts/directive_promotion.py
---

Seeded 2026-10-23. Evidence: CIO_PROSPECT_DATA_FOUNDATION.md:244-252 (phase table), :302 ("P0/P1 built, inert");
DATA_DOMAIN_APPROVAL_READINESS_2026-10-22.md:49.

Backfill 2026-10-23: #1929 (P0) and #1944 (P1 inert) LIVE since batch 5; approval E given 2026-10-22 but the store is
still shadow (T-20261023-9c7a5c finds why). Silo audit #1995 LIVE: 46 producers, 3 WIRED / 16 PARTIAL / 27 SILO.
Operator, verbatim, 2026-10-23: "Anything that's such as a security catalyst related to the security, anything for
the security . The CIO agent needs to have it in memory. We should have no silos."
