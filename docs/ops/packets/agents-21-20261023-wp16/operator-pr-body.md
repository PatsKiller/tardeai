# WP-16 operator policy proposal

Status: DRAFT
as_of: 2026-10-24T02:20:00Z
Measured at: base 4acb33ada3eed278c5f7652fcdcd6cbda15e68e5; proposed package only

WP-16 proposes AGENTS 21.0.0 as a MAJOR amendment for one deterministic, advisory-only Ask-CIO size field. The new module stays inert until the exact policy is ratified; broker authority, behavior writes, proposals and execution remain unchanged. No Ask-CIO importer is wired by this proposal.

The package pins the existing rails and three quoted ratification clauses, adds the policy regression test with its CI gate, and updates older policy-test normalizers without changing their baseline digests. An exact operator PR/head token is required before ratification. The package's three-stage fixture receipt distinguishes synthetic validation from real authorization.

Design-Task: DSN-20261023-handoff-v3-P4-T16
