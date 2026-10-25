---
id: DSN-20261024-kept-pr2034-refresh
title: Refresh kept PR2034 against accepted main without enabling dual write
owner: codex-kept-pr2034-20261024
status: IN_PROGRESS
phases:
  - id: DSN-20261024-kept-pr2034-refresh-P1
    title: Preserve source history, merge accepted main and prove isolated compatibility
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261024-kept-pr2034-refresh-P1-T1
        title: Refresh existing prospect writer PR and its affected evidence
        status: IN_PROGRESS
---

# Existing PR2034 refresh

The operator requests a fresh worktree from the remote prospect-writer branch, a merge of accepted main, the evidence-only test repair on that merged head, and C1 fact-only compatibility proof. The dual-write flag remains off. Existing `wt-prospect-writer` and `wt-wpboard` are outside this task; their local commits must not be discarded or published.

Acceptance requires isolated hidden-driver tests, preserved negative assertions, the affected native/ratchet gates and a single push-only handoff targeting the existing PR branch. The coordinator/operator owns publication and rollout. No new PR, live database access, flag change, policy edit or release is part of this worker task.
