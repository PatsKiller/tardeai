# Completion train for the 119 outstanding source/integration lanes

Status: SOURCE_ONLY — local source corrections; admission held
Owner: Codex integration
As of: 2026-10-11

Evidence: SOURCE_ONLY and TEST_ONLY. Production, exact CURRENT, installed scheduler state and natural-fire acceptance are NOT_MEASURED. This is a local source train, with no push, PR, deployment, workflow import, scheduler cutover, operational config change or contract review.

## Result and scope

All 119 are accounted for: **84 received source corrections, four existing preparations were retained, and31 remain at owner/authority boundaries**. The84 include partial corrections; they are not84 migration-ready lanes. This train integrates the17 previously local proposals and repairs shared prerequisites. Admission candidates remain separate from executor configuration and all proposed contracts remain DRAFT.

The eight-shard inventory has 297 lanes. This train covers 98 prior blockers, 17 local proposals and four held source preparations. The 25 reviewed shadow rows, 123 excluded sender/broker/class rows and 30 retired rows stay outside this scope.

The [before/after table](BEFORE_AFTER_119.md) and [machine-readable report](BEFORE_AFTER_119.json) enumerate every lane, correction and remaining blocker. [Frozen scope](scope-119.json) is a source worklist, not a live scheduler census. `scripts/check_completion_119_candidates.py` checks that all 119 appear once, remain SOURCE_ONLY, retain DRAFT/disabled admission, and never masquerade timer identities as cron.

## Corrections

- Strict offline previews precede business work, state reads, environment loading and model/DB calls. Unknown flags refuse with usage status. Fake real-run tests retain exact legacy argv and successful/failed receipt behavior.
- Governed process routing uses existing server-approved caller/task identities, validates process/governance/cost proof and binds validated executor metadata. Unknown routes remain blocked. No provider keys or routing authority move to n8n.
- DB and heartbeat helpers load explicit environment names only when a connection is requested. The hermetic test bootstrap honors empty fixture paths and rejects production access, including swallowed refusals and child attempts.
- Shared manifest previews create no artifacts. Explicit dry-run wins in both flag orders; inherited DRY_RUN=0 does not authorize apply. Real stages preserve per-step isolation, wait for workers and durably report incomplete or failed receipt work.
- The shared CIO merge preserves both declared lane receipts and the legacy soft-error exit policy. A soft error leaves both receipts unhealthy. The cron/timer ownership overlap still requires an operator decision.

The [shared prerequisites](SHARED_PREREQUISITES.md), group reports and candidate packets carry implementation detail. The [timer proposal](TIMER_ADMISSION_DESIGN.md) and [fragment metadata](TIMER_SOURCE_METADATA.json) cover36 source timer identities. Nine exact fragment pairs are missing or incomplete. No timer-native admission rule is implemented or ratified here.

## Validation and refusals

All new tests are registered in the native CI runner. The combined targeted integration suite passed under the unchanged isolated launcher after correcting two legacy preview expectations and retaining their fake DB-failure/component coverage. The accepted full PR-profile command is:

```sh
python3 run-isolated-completion.py final-pr-profile-isolated .venv/bin/python scripts/run_cio_hardening_ci.py --profile pr --base origin/main
```

The launcher sets TRADE_AI_CI=1, M2_SKIP_DOCKER=1, the `.nodeps` PYTHONPATH, empty dotenv inputs and fixture state roots before imports. Each attempt has a distinct tag and retained `reassess-gates/<tag>.{json,log}` artifact in the integration worktree. A final exact-head run must exit 0 with zero capability refusals and all owned children reaped before a source-green claim. Static gate, Ruff, line-ending and configuration-preservation results are in the same local evidence directory and summarized with the exact accepted tag in untracked `PR_BODY.md`. These local files are review artifacts and do not imply CI on GitHub.

Earlier attempts that hit `/run/user/1000/tradeai/env` or a production state-root argv were stopped and are retained as nonaccepted evidence. Source fixture handling was corrected before new-head validation; guards were not widened. Server caller-map extraction was refused because of inherited mixed line endings; that server file remains untouched and the client map is tested against it. Successful terminal stream-fd warnings are recorded once and are not action refusals.

The first native profile at `21a7a3afc` stopped on a host-crontab call and exposed a legacy migration test copying canonical checkout state. That run remains rejected. The migration rehearsal now uses synthetic stores and ledgers, retaining every conflict/hash/quarantine/rollback assertion; the unknown-lane-count CLI test now injects a discovery fixture. Guards, exemptions and native test selection are unchanged. The corrected migration suite passed 62 tests and the corrected registry case passed; final profile acceptance remains required.

The second profile at `82c14f376` passed the migration gate, then stopped at another inherited host-crontab probe. Persistent-wake and schedule-contract tests now use scratch cron/unit snapshots plus process-call spies and mutation-negative controls; 46 tests passed. Goal-loop scheduling checks use the committed source snapshot with good/bad/comment controls; 27 tests passed. Source tests make no installed-scheduler claim. Both stopped profiles remain nonaccepted, and the guards stay unchanged.

No frontend or live browser acceptance is claimed: this train changes lane source and test integration, not Command Center or runtime. Deployment and natural-fire evidence remain separate prerequisites.

## Owner actions and rollback

The 18 DRAFT health-contract candidate IDs are listed one per line in untracked `OPERATOR_REVIEW_LIST.md`. Additional generic admission proposals still need full health contracts and recursive import/env/child review. Financial, sender, recovery, auto-ratification and unruled agent boundaries are retained. The before/after table identifies the remaining owner work for each of the 31 unchanged rows and every partially corrected row.

Before any promotion, re-measure current main, CURRENT and host scheduler identity; prove current argv/locks and code-root chains; resolve unknown model process ownership without inventing a model; review the exact source head and contracts; then obtain separately scoped release/scheduler decisions. Source rollback is a reviewed revert of the local train commits. Runtime rollback is unnecessary because this train changes no runtime.

Recommended next 30 days: finish owner/closure reviews and missing timer fragments first; ratify timer admission only after its semantic tests; deploy an independently approved exact-main source head; then run the shadow/canary acceptance program with host receipts and output evidence before any ownership cutover. No deadline overrides a safety or admission gate.

## Documentation and inventory

Each group supplies row-by-row source candidates and unchanged-stage inventory overlays. The integrator records [the combined 119-row overlay](inventory_rows_completion_119.tsv) and a separate source-only workbook at `inventory-review/COMPLETION_SOURCE_119_20261011.xlsx`. The global workbook builder is not run here: it inspects live crontab/systemd, CURRENT and the canonical checkout, which are outside this isolated source train. Global live scoreboard numbers are therefore unchanged. Its later rebuild requires fresh runtime evidence; no Drive sync or email is performed.
