---
id: DSN-20261024-site-system-tabs
title: System tab request admission and URL navigation
owner: codex-site-system-tabs-20261024
status: IN_PROGRESS
phases:
  - id: DSN-20261024-site-system-tabs-P1
    title: Admit requests for displayed System tabs and preserve URL state
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261024-site-system-tabs-P1-T1
        title: Implement and verify System request admission and bookmarkable navigation
        status: IN_PROGRESS
---

# System tab request admission

The operator's approved SITE specification says “System/Comms/Portfolio fetch per active tab only.” This package addresses the System portion of P1 finding 12 and its related URL-state finding. It preserves all panels, actions, business fields and the shared header request.

Entry: accepted main `e148e2a65303d8aa6e6c9437784ae83f9e2bebe8` (PR #2072). Task and source paths are registered on the claim board.

Acceptance: actual-component fixture proof at 1440/412 establishes initial request scope, cessation of inactive polling, URL context and Back/Forward behavior. Native build, hidden-driver source checks and repository guards must pass before the local publication packet is recorded. The coordinator/operator retains remote publication and runtime acceptance.

No backend endpoint, scheduler or execution authority changes. Endpoint size, portfolio-wide load and server RSS remain separate SITE work.
