# WP-12: draft and ready CI smoke control

Status: DRAFT — throwaway PR, close after proof; do not merge
as_of: 2026-10-24T02:12:00Z
Measured at: base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5` (merged PR #2032)

This documentation-only change is the control input for WP-12's requested GitHub experiment. It changes no workflow or application code. The test PR starts as a draft, is marked ready only after draft observations are captured, and is closed after the ready observations are captured. It must never be merged or selected as a release-train rider.

## Expected observations

1. On draft `opened`, only `draft-quick-check` and `agent-governance` execute. Heavy check jobs are skipped; no heavy suite should actually run.
2. Capture the PR number, immutable head SHA, event, workflow run/check IDs, conclusions and timestamps before changing state.
3. Mark the same PR ready, preserving the same head. `ready_for_review` must schedule the full fleet, including the four required checks `cio-hardening`, `agent-governance`, `release-readiness`, and `ci-gate`.
4. Capture those new run/check IDs and their outcomes. Do not count an earlier skipped draft check as ready-phase proof.
5. Close the smoke PR and append the result and evidence paths to `PROGRESS_LOG.md`. A local source-guard test is preliminary evidence; it does not substitute for this GitHub experiment.

## Execution boundary

The worker's sandbox cannot push. The operator publishes `work/DSN-20261023-handoff-v3-P3-T12` and opens it with `gh pr create --draft`; the worker keeps its claim and continues other packages while publication is pending. No agent push retry, alternative transport, branch reset, merge or release is part of this proof.

Results are retained under `/home/johnclaw/.cache/rtc/codex-wp12-20261023/` and appended to the shared progress log. At authoring time no remote draft/ready proof has been collected; its status is **PENDING_PUBLICATION**.
