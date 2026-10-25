---
id: DSN-20261024-w8-legacy-carryforward
title: 'WP-33 Worker A six-lane shadow carry-forward'
owner: codex-w8-legacy-carryforward-20261024
status: IN_PROGRESS
approval: 'Operator legacy-pr-carryforward.md 2026-10-24; archive health review authorized explicitly, activation separate.'
phases:
  - id: DSN-20261024-w8-legacy-carryforward-P1
    title: Rebuild and validate the combined shadow source package
    status: IN_PROGRESS
    goal: Preserve accepted main while carrying forward six scoped lane configurations and reviewed non-config source.
    entry_criteria: Separate fresh origin/main worktree and task; normal earlier-owner claim handoffs.
    acceptance:
      - Six scoped registry and health rows; five shadow dry-run allowlist entries; options quote refresh inert.
      - Both recent main rows and every other preexisting row/proposal preserved.
      - JSONL retention merges with accepted disk changes; archive health uses exact operator review provenance.
      - Full affected hidden-PG tests, ratchets, CHECK-only reconciliation, completeness and build.
    gates:
      - No override, foreign claim edit, push, merge, release, activation or broker behavior change.
      - Initial W8 source369de0121 remains frozen and separate.
    tasks:
      - id: DSN-20261024-w8-legacy-carryforward-P1-T1
        title: Integrate six-lane configuration with the normally handed-off source port
        status: IN_PROGRESS
        areas:
          - config/lane_registry.json
          - config/n8n_run_allowlist.json
          - config/n8n_health_contracts.json
          - docs/ops/packets/w8-legacy-carryforward-20261024
---

# Worker A six-lane carry-forward

See [the source scope and proof plan](../ops/W8_LEGACY_CARRYFORWARD_20261024.md). Runtime activation is a separate operator action.

Source validation is complete on coordinator-pinned accepted main `23e87f15b1e973f4520cedb28c5998036374c55e`:1073 affected tests pass with1skip, plus required native checks and build. The inherited static relay refusal and unmeasured runtime/concurrency probes are disclosed. This task and its claim remain in progress for coordinator publication; no runtime completion is asserted.
