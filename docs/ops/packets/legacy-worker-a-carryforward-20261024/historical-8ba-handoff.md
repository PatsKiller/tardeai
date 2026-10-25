# WP-33 registry/n8n stale-set rebuild

Status: SOURCE IMPLEMENTED; archive contract review blocks admission/publication
as_of: 2026-10-24
Owner: codex-stale-n8n-root-20261024; same-branch continuation from the preparation worker
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

## Review decisions and remaining authority boundary

The preparation worker did not act on peer-relayed approval (AGENTS.md §28.4). It voluntarily
handed off the same branch and task at `cf1c7c9242e9f2c5bbce4201128716d36cc5178d`. Root took the
task as claim `20261024T143535Z-codex-f72adc50`, read the carried worklog and applied the direct
user instruction from its own session. No review authority was inferred from an agent message.

`review-handoff.json` records the seven pre-change review shapes. The user's direct authority
covers `cio-ask-research` and the five #1940 contracts: `holdings-drift-monitor`,
`options-desk-staleness-monitor`, `held-exit-coverage-monitor`, `options-desk-quote-refresh`,
`schwab-position-sync`. These six are now REVIEWED at both contract and review level, with
`reviewed_by: operator 2026-10-24 ('go', via coordinator)` and `reviewed_on: 2026-10-24`.
[authorized-review.json](packets/stale-n8n-set-20261024/authorized-review.json) preserves before/after
review fields and hashes. Owner-reviewed assertions remain and now pin the direct decision's
exact attribution/date. Existing main contracts and the operator-owned owner fields are unchanged.

`jsonl-archive-rotate` is also DRAFT, with `reviewed_by` and `reviewed_on` null. Its contract review
is outside that narrow fresh authority; root has requested clarification. Do not promote it or
add a grandfathering exception. Approval K rotation provenance remains historical source material.

## Integration corrections and verification

The first affected-suite run reported 843 passed, four failed and one existing skip. Two failures
were the same pending archive review. The other causes were corrected without weakening checks:

- `cio-ask-research.env_names` is sorted/deduplicated without adding any environment name.
- The shared Ask CIO contract no longer imports Ops Controls merely to inspect policy version/anchor
  text. That optional dependency reached release-train and Telegram sender modules. Its existing
  equivalent fail-closed document reader is retained; the sender-free closure assertion is unchanged.
  Pinned fixtures preserve lower/proposed/active/superseding versions, missing anchors and unreadable
  files, and reject any attempted operational-service import.

After these changes, 250 targeted tests passed with psycopg2 hidden, including Ask CIO contract,
lane, provenance, exact-review, environment and preservation checks. The original broader failure
receipt is retained under the root worker's scratch directory; no all-green full-profile claim is made.

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

After the six authorized reviews, the contract checker refuses exactly
`DRAFT_NOT_GRANDFATHERED jsonl-archive-rotate`. Root asked whether approval K includes this contract
review and is awaiting clarification; no grandfathering exception or invented reviewer was added.
The root scratch directory is `/home/johnclaw/.cache/rtc/codex-stale-n8n-root-20261024/`.

Remaining action: record the owner's archive-review decision, run the complete affected profile and
final registry/contract/coverage/host/docs checks, verify no CHECK mutations, then record one executable
PUSH_NEEDED. No PUSH_NEEDED, remote write, runtime/archive run or source-completion claim is issued
while contract admission fails. The source claim is retained for this continuation.
