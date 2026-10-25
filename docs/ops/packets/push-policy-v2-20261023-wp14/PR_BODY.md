# WP-14 operator-only push-policy proposal

Status: DRAFT
as_of: 2026-10-24T02:33:00Z
Measured at: package base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5`

The flat two-push limit conflicts with continuity drafts. This operator-applied proposal adds
class-based accounting and a live-claim reason while remaining PROPOSED: v1 still decides,
v2 shadow verdicts are logged, and operator ratification is required for enforcement.

The train class is deliberately fail closed with TRAIN_AUTHORITY_UNPROVEN until a verified
host-service capability-reservation bridge is separately reviewed. Env identifiers and a guard
override cannot supply that proof. No real push, merge, release or live flag is performed.

The package contains the new policy tests and their canonical CI gate; DESIGN.md and the
worker report describe the isolated none/proposed/ratified verification and limitations.

Design-Task: DSN-20261023-handoff-v3-P3-T14

WIP requires a proven draft; unknown/API-failed/absent PR state refuses it. Enforce budget
decision and durable reservation share one cross-worktree lock. Five concurrent hooks with
one remaining review slot yield exactly one reservation; refusals and failed writes spend
no budget. Ledger rows reserve pre-upload budget and do not assert remote acceptance.
