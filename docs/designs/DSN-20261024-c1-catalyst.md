---
id: DSN-20261024-c1-catalyst
title: C1 stored catalyst population and registered company names
owner: codex-c1-catalyst-20261024
status: IN_PROGRESS
phases:
  - id: DSN-20261024-c1-catalyst-P1
    title: Source and production-COPY proof
    status: IN_PROGRESS
    goal: Populate eligible stored catalysts through existing CIO fact-only memory and reject paragraph company labels.
    entry_criteria: Own task/claim and fresh accepted-main worktree; read-only COPY authorized.
    acceptance:
      - Original catalyst source dates/refs and short registered-name source retained.
      - Fresh immutable COPY before/after, every gap, idempotent readback and no judgment writes.
      - Affected whole native suites, hidden PG, production barriers, build and ratchets.
      - One PUSH_NEEDED; no agent push, merge, release, live application or schedule change.
    tasks:
      - id: DSN-20261024-c1-catalyst-P1-T1
        title: Fix existing company population capture and registered-name validation
        status: IN_PROGRESS
        areas:
          - scripts/lib/cio_company_population.py
          - scripts/lib/cio_company_facts.py
          - scripts/lib/data_broker/catalyst_record_readonly.py
          - docs/ops/C1_COMPANY_CATALYST_FIX_20261024.md
  - id: DSN-20261024-c1-catalyst-P2
    title: Coordinator release and operator application
    status: HELD
    goal: Apply exact accepted source and verify same-GUID outputs across consumers.
    entry_criteria: Required remote checks green, coordinator release and exact operator write authority.
    acceptance:
      - Exact CURRENT/source identity, dry-run receipt and authorized apply readback.
      - Existing-lane runtime/scheduling/monitoring accepted independently.
    tasks:
      - id: DSN-20261024-c1-catalyst-P2-T1
        title: Release and apply source through existing operator-owned lane authority
        status: HELD
        areas:
          - coordinator-operator-only/c1-catalyst-application
---

# C1 catalyst and company-label correction

Use the existing CIO record and validated fact-only facade. No new store, provider, judgment authority or scheduler.
See [source and COPY report](../ops/C1_COMPANY_CATALYST_FIX_20261024.md).
