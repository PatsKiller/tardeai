---
id: DSN-20261022-cio-prospect-store
title: CIO prospect store (one record per security)
status: IN_PROGRESS
approval: approved (AGENTS.md 18.0.0 §26; row grant approval E 2026-10-22, promotion pending its own PR)
source: docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md
phases:
  - id: DSN-20261022-cio-prospect-store-P0
    title: Architecture, dictionary rows, CI checks, 18.0.0
    status: DONE
  - id: DSN-20261022-cio-prospect-store-P1
    title: Shadow — migration + dual-write + shadow builder + lane (built inert)
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261022-cio-prospect-store-P1-T1
        title: Promote the cio_prospect row grant (approval E) in its own PR
        status: PROPOSED
        areas: [config/data_source_authority.json]
  - id: DSN-20261022-cio-prospect-store-P2
    title: Compare job
    status: PROPOSED
  - id: DSN-20261022-cio-prospect-store-P3
    title: Switch readers in batches
    status: PROPOSED
  - id: DSN-20261022-cio-prospect-store-P4
    title: Retire old stores with a tripwire
    status: PROPOSED
---

Seeded 2026-10-23. Evidence: CIO_PROSPECT_DATA_FOUNDATION.md:244-252 (phase table), :302 ("P0/P1 built, inert");
DATA_DOMAIN_APPROVAL_READINESS_2026-10-22.md:49.
