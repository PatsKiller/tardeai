---
id: DSN-20261024-doc-index-pr-flow
title: 'WP-02: remove generated-index sibling PR contention with verified CI projection and batch regeneration'
owner: Operator; codex-doc-index-pr-flow-20261024 prepares the proposal
status: PROPOSED
approval: 'Proposal requested; replacement policy/gates and activation require reviewed approval'
source: 'Coordinator item 1, 2026-10-24; AGENTS.md sections 14.1, 20, 28.3b'
summary: 'Correct GitHub merge-driver claims now; propose clean source-only PRs with exact-tree index artifacts and a single committed index refresh per integration batch.'
phases:
  - id: DSN-20261024-doc-index-pr-flow-P1
    title: Correct comments and prove the proposed flow in fixtures
    status: IN_PROGRESS
    goal: Correct the mergeability claim and deliver an offline verified replacement without changing active policy or gates.
    entry_criteria: New task and exclusive source claims on freshly fetched main.
    acceptance:
      - Existing attributes preserved; false GitHub union claims corrected.
      - Source-only sibling merge and batch index pass with union disabled.
      - Strict coverage, malformed-row, identity, clean-source and artifact negatives pass with psycopg2 unavailable.
    gates:
      - No protected policy, hook, workflow, grant or active gate changes in this phase.
    tasks:
      - id: DSN-20261024-doc-index-pr-flow-P1-T1
        title: Correct merge comments and prepare reviewed projection package
        status: IN_PROGRESS
        areas:
          - .gitattributes
          - tests/test_generated_file_merge_driver.py
          - docs/ops/packets/doc-index-pr-flow-20261024
          - docs/ops/DOC_INDEX_PR_FLOW_20261024.md
          - docs/INDEX.md
  - id: DSN-20261024-doc-index-pr-flow-P2
    title: Review policy and implement the approved CI and batch integration
    status: PROPOSED
    goal: Change every consumer together so agent PRs may omit index changes without losing any integrity gate.
    entry_criteria: Operator/coordinator accepts the replacement clauses and exact consumer matrix in the packet.
    acceptance:
      - PR jobs emit and revalidate exact head/base projection artifacts; required gate names stay unchanged.
      - All current committed-index test/tail invocations have a reviewed PR-versus-batch contract.
      - Coordinator refreshes and commits INDEX before full exact-head batch checks; no automated remote write is added.
      - Two distinct real PRs demonstrate GitHub mergeability and green required checks after rollout.
    gates:
      - Protected policy edits made only through the operator-reviewed policy process.
      - Workflow edits and train integration reviewed by their owners; no agent merge/release authority added.
    tasks:
      - id: DSN-20261024-doc-index-pr-flow-P2-T1
        title: Approve and apply the replacement documentation-index policy
        status: PROPOSED
        areas:
          - design-approval/doc-index-pr-flow/policy
      - id: DSN-20261024-doc-index-pr-flow-P2-T2
        title: Implement every approved CI consumer and batch regeneration integration
        status: PROPOSED
        areas:
          - design-approval/doc-index-pr-flow/ci-batch
  - id: DSN-20261024-doc-index-pr-flow-P3
    title: Verify real sibling PRs and document the effective process
    status: PROPOSED
    goal: Measure GitHub behavior and retain exact-tree evidence rather than infer activation from fixture success.
    entry_criteria: P2 approved, merged, and all required workflows using the new contract.
    acceptance:
      - Real PR required checks and mergeability receipts attached; batch committed index passes unchanged checker.
      - Plan, contributor instructions and board shared-path guidance updated to the effective process.
    gates:
      - Coordinator owns merge and publication; source proof is distinct from runtime claims.
    tasks:
      - id: DSN-20261024-doc-index-pr-flow-P3-T1
        title: Attest the approved sibling PR and integration-batch proof
        status: PROPOSED
        areas:
          - design-approval/doc-index-pr-flow/rollout-proof
---

Status: PROPOSED
as_of: 2026-10-24

The [assessment](../ops/DOC_INDEX_PR_FLOW_20261024.md) and
[review packet](../ops/packets/doc-index-pr-flow-20261024/REVIEW.md) define the replacement.
The packet is executable offline evidence, not an active CI mode. Existing branch index
requirements still apply, including to this proposal's own PR. No policy approval,
GitHub CI result, merge, release or served-runtime acceptance is inferred from local tests.
