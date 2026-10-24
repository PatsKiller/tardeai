---
id: DSN-20261024-ops-config-modals
title: 'WP-34 item 4: operations configuration through governed Controls modals'
owner: Operator; codex-wp34-20261024 prepares the P3 proposal
status: PROPOSED
approval: 'Design requested by WP-34 item 4; implementation and any authority expansion await explicit operator approval'
source: 'HANDOFF_v3_ORDERED_WORK.md WP-34 item 4; AGENTS.md sections 27, 28.3b'
summary: 'Inventory remaining hand-edited operations configuration, reuse existing writers, and propose typed preview-and-readback forms without a generic file editor.'
phases:
  - id: DSN-20261024-ops-config-modals-P1
    title: Source inventory and concrete P3 modal proposal
    status: IN_PROGRESS
    goal: Account for tracked configuration paths and map current writer/reader evidence, existing Controls coverage and proposed form boundaries.
    entry_criteria: Named WP-34 item-4 design task claimed; existing PR/design work checked.
    acceptance:
      - Source-pinned path census and family matrix, with missing runtime/ownership measurements explicit.
      - Concrete offline modal mockup and validation evidence; no runtime effects.
      - Reviewable documentation PR with the task id and exact operator publication command.
    gates:
      - Proposal only; no runtime configuration, policy, credentials or applier authority changes.
    tasks:
      - id: DSN-20261024-ops-config-modals-P1-T1
        title: Inventory manual operations configuration and propose modals
        status: IN_PROGRESS
        areas:
          - docs/designs/DSN-20261024-ops-config-modals.md
          - docs/ops/WP34_MANUAL_OPS_CONFIG_INVENTORY_20261024.md
          - docs/ops/packets/ops-config-modals-20261024-wp34
  - id: DSN-20261024-ops-config-modals-P2
    title: Attest owners and approve field-level catalogue before enabling forms
    status: PROPOSED
    goal: Resolve writer ownership and schema/reload/readback contracts for each selected configuration family.
    entry_criteria: Operator approves the P1 design and selects the first family; relevant owners and grants identified.
    acceptance:
      - Per-field owner, permitted writer, public read path, finite/type bounds, reload mechanism and verification receipt.
      - Unsupported or unowned paths remain read-only; source policies keep the reviewed PR/package route.
    gates:
      - Explicit operator design/phase approval; no permission derived from a proposed modal.
      - Financial, credential, model-choice and protected-policy boundaries retain their existing approvals.
    tasks:
      - id: DSN-20261024-ops-config-modals-P2-T1
        title: Attest one-writer and effective-value contracts for the operator-selected first family
        status: PROPOSED
        areas:
          - design-approval/ops-config-modals/catalogue
  - id: DSN-20261024-ops-config-modals-P3
    title: Implement approved typed modal adapters and prove effective readback
    status: PROPOSED
    goal: Reuse the existing Controls request flow and original writer for each separately approved family.
    entry_criteria: P2 field-level catalogue approved; implementation task and exact file/grant scope registered.
    acceptance:
      - Fixture proofs for preview, refusal, stale revision, duplicate requests, partial failure and consumer readback.
      - Required exact-head CI and coordinator release; runtime success distinguished from source proposal and stored-only override.
      - Operator can see the original observation time and effective revision, with no secret values or invented approvals.
    gates:
      - Separate implementation approval; no generic path, shell, JSON or service-name execution.
      - Existing passkey, phrase, fresh-assertion exceptions, capability and reviewer requirements preserved.
    tasks:
      - id: DSN-20261024-ops-config-modals-P3-T1
        title: Implement only the approved first-family adapter with no additional authority
        status: PROPOSED
        areas:
          - design-approval/ops-config-modals/first-adapter
---

Status: PROPOSED
as_of: 2026-10-24T03:12:54Z

This is the P3 design requested by WP-34 item 4. It extends the existing
`DSN-20261022-ops-controls` programme through a separate proposal, without reopening #1976,
changing that programme's existing approval, or taking WP-34 operator-only items 2 and 3.

The [technical assessment](../ops/WP34_MANUAL_OPS_CONFIG_INVENTORY_20261024.md) contains the
source-backed writer/reader/coverage/authority/validation/preview matrix. Its packet includes
the complete tracked-path census, a family inventory, an offline interactive modal mockup
and a static evidence validator. All runtime changes remain future, separately approved work.

The task remains claimed until the coordinator publishes and reconciles the proposal. Local
completion does not mean the proposed editor or any new authority is deployed.
