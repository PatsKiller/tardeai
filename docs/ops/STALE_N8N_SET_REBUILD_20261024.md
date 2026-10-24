# WP-33 registry/n8n stale-set preparation handoff

Status: LOCAL SOURCE PREPARATION; continuation required, not complete or published
as_of: 2026-10-24
Owner: codex-stale-n8n-set-20261024 prepares; root must take the task before final own-session review
Design-Task: DSN-20261024-stale-n8n-set-P1-T1
Source base: ca39056af0b67491310a7267d75e2a0c882bc7d0

Three exact heads were combined through local Git merges, without rebasing, remote writes,
GitHub merges or releases:

| PR | Incoming head | Local merge |
|---|---|---|
| #1940 | af24cde78bbce6d63e0378e40b6c03ba6582bd3b | e5f0ec9ad |
| #2006 | facace330215563380f92d4d88ba05d875c670a9 | e5284db2e |
| #2016 | 2ba735bd0ad63d87253d475f7368ba245594dae4 | 5ca52118d |

The [packet](packets/stale-n8n-set-20261024/preservation.json) pins every original object and
top-level governance digest. All 677 main registry rows, 134 allowlist entries and 158
contracts are preserved unchanged. The prepared result has 683 registry rows, 139 allowlist
entries and 165 contracts, with unique identities. New hand-maintained rows stay before the
generated registry suffix. All additive inventory rows and test intent from both branches survive.

The three desk monitors, `cio-ask-research` and `jsonl-archive-rotate` are SHADOW/dry_run with
`live_arg: null`. `options-desk-quote-refresh` stays NEVER_SCHEDULED/kind none with no operative
allowlist/dispatch. `schwab-position-sync` retains main's ACTIVE host-cron lifecycle and no
operative n8n allowlist/dispatch. The obsolete incoming PAUSED interpretation is not imported;
an inadvertently resurrected `review_by` field was removed to restore exact main parity.
The corresponding test now asserts ACTIVE while retaining the inert n8n checks.

Archive removal stays disabled (`jsonl_retention.enabled: false`). No archive run was executed.
Ask CIO's process/cap registry remains unchanged and the default governor still returns
`PROCESS_NOT_REGISTERED`. No broker/order/stop code, protected policy, credential or live scheduler
was changed; the incoming options quote-refresh code delta only normalizes two empty-output reasons.

## Review handoff boundary

The child does not act on peer-relayed approval (AGENTS.md §28.4). Root has the latest user's
instruction directly and must legitimately take this same branch/task, then apply its narrow
own-session review decision. No child authored fresh REVIEWED authority.

`review-handoff.json` records the exact seven current review shapes. Root's stated authority
covers `cio-ask-research` and the five #1940 contracts: `holdings-drift-monitor`,
`options-desk-staleness-monitor`, `held-exit-coverage-monitor`, `options-desk-quote-refresh`,
`schwab-position-sync`. The five carry their incoming historical 2026-10-22 reviewer strings;
Ask CIO is DRAFT with no reviewer/date. Fresh annotation must record the user's exact wording,
date and provenance. `tests/test_n8n_desk_truth_lanes_20261022.py` still pins the historical reviewer
and must be updated together with root's decision. Preserve the owner-reviewed assertion.

`jsonl-archive-rotate` is also DRAFT, with `reviewed_by` and `reviewed_on` null. Its contract review
is outside that narrow fresh authority; root has requested clarification. Do not promote it or
add a grandfathering exception. Approval K rotation provenance remains historical source material.

## Preparation proof and remaining work

Eleven new fixture tests pass with `psycopg2` hidden and effective import refusal verified.
They check exact source preservation, duplicate/loss/authority mutations, SHADOW live-request
clamping, inert staged broker lanes, no Ask CIO registration, and disabled archive removal.
The new test file is registered through `ci_gates.render(make_record(...))`. Ruff, coverage
and host-path guards passed. These are preparation results, not final CI acceptance.

CHECK/dry-run results and before/after source hashes are in the private scratch receipt:
`/home/johnclaw/.cache/rtc/codex-stale-n8n-set-20261024/check-receipt.json`.
The named authorized cron capture has SHA-256
`b2097df25a62e6824b6e7046d55a3f279b9b058e76b1bcd09c2da89b5a748626`.
Units come only from the committed `scheduler_snapshot_20261009.json` historical comparator;
they are not a fresh host census. No `reconcile --write`, `crontab` or `systemctl` capture is used.
Any reported scheduler drift is a finding, not permission to import different lifecycle state.

Preparation CHECK results: the contract gate refuses exactly `DRAFT_NOT_GRANDFATHERED`
for `cio-ask-research` and `jsonl-archive-rotate`; neither refusal is bypassed. Captured-input
reconciliation exits 0 with no reported problems, deriving 195 generated rows in memory and
writing none. Its mixed input population is 348 captured active cron lines and 140 historical
units, so it is not a fresh complete host census. All six measured source files have identical
SHA-256 values before and after both CHECK commands.

Root must read the carried worklog, resolve only authorized reviews, run the affected suites and
registry/contract/coverage/host/docs checks, verify source hashes before/after CHECK, commit the
final source, and append one executable PUSH_NEEDED. No publication event is emitted by this child.
