# Worker A carry-forward: six shadow lanes

Status: IN_PROGRESS — combined source validated; accepted-main reconciliation pending
as_of: 2026-10-24
Design-Task: DSN-20261024-w8-legacy-carryforward-P1-T1

The approved `legacy-pr-carryforward.md` assigns the Worker A source at `8ba33bd6c4612770a71a814874632eaba3b19f6e` to a fresh task/branch/worktree on accepted main `d635873e1063efb8a9ff8e8ce542654ed2ef7654`. The original W8 source `369de0121` and its one publication request remain frozen and separate.

W8 owns the six registry/allowlist/health integrations: holdings drift, options desk staleness, held exit coverage, options desk quote refresh (inert), Ask CIO research and JSONL archive rotation. Five runnable source entries must stay SHADOW/dry_run with `live_arg=null`. Quote refresh retains no operative allowlist/dispatch and remains NEVER_SCHEDULED. Its shadow candidate is a proposal, not activation.

The JSONL archive health review cites the explicit operator 2026-10-24 carry-forward instruction; it does not invent an earlier review or activate removal. The normally handed-off source adds only `jsonl_retention` to the accepted disk rules and its retention inventory entry. Standing cleanup and JSONL retention remain disabled. Every earlier disk field and all C1 retention changes survive.

The [source packet](packets/w8-legacy-carryforward-20261024/SOURCE_PLAN.json) pins the exact old bundle and new baseline. The fresh main has 678 registry rows; all survive, including `cio-prospect-shadow` and `cio-company-facts-populate`. Six requested rows are added without importing stale whole-file state. The old source contains an extra Schwab health contract; that is outside this six-lane package and belongs to W12's separate reviewed read-lane work. The other 31 F09 host-cron lanes stay unchanged.

Normal claim handoffs preceded every blocked-path edit. W8 continued its original `73e39f48` claim to `65d8aa22`, retaining the frozen initial source/evidence and transferring only the three config paths to the new `899f2f66` carry-forward claim. The coordinator arranged normal earlier-owner continuations for C1 retention, disk rules and the Ask contract. The source helper released its frozen source claim before W8 ordinary-claimed those paths. No force, override or foreign-session edit was used. The ordinary task take recorded an old stale design-tree overlap in audit metadata; direct readback confirmed the foreign `3fd3d5c3` claim remained active and unchanged.

No runnable source is published, migrated or activated by this worker. The configuration and non-config source form one carry-forward candidate with one publication request after final proof. The initial W8 source PR and WP24 registry dependency remain separate.

## Configuration checkpoint

The six-row merge has 684 registry rows, 139 allowlist entries and 164 health contracts. All 678/134/158 previous objects and all other top-level fields are exactly preserved (see `config-preservation.json`). Five runnable source entries are dry-run-only shadow rows; quote refresh remains inert. The archive review now has the explicit carry-forward reference. Staged quote-refresh metadata correctly says policy19.0.0 is ACTIVE, while admission remains a separate unmet condition.

The first focused hidden-Postgres checkpoint passed14cases and failed1 because the source helper had not yet added `jsonl_retention`. That checkpoint was incomplete and did not produce a publication request; the subsequent integrated run supersedes it.

## Combined source and pin correction

W8 integrated the helper's minimal Ask policy-reader import decoupling (`9a478b9969`, carried as `5ba4ddb7f`) and frozen source port (`f75362c253`, carried as `20d21d9d1`). The separate Ask-quality head `87a6d1d0f` has disjoint nullable-cost/operator-request changes; later integration must preserve both. It is not imported wholesale here.

The first combined 20-file hidden-Postgres run passed1068cases, skipped1 and failed5. All five failures came from the existing disk activation packet correctly refusing stale source-config hashes. After the disk owner's normal `3af5cbc1` to `a10b72db` continuation, W8 ordinary-claimed exactly `activation-input-sha256.json` and `review.required.json`. Commit `53adc9312` refreshes four changed config hashes and their binding review digest. Review remains `PENDING_OPERATOR_REVIEW`, its identity and timestamp remain null, and both cleanup enable flags remain false. The activation guard and draft contract are byte-identical. The earlier failed run is retained as evidence.

The offline relay route check reports the inherited missing `approval-escalate` registry row. Running the same static check against accepted main produces the identical finding, and all17 relay/workflow sources are unchanged. This is an inherited defect, not a relay pass. Scratch runtime/concurrency probes are unmeasured because the environment refused the scratch socket probe; no retry or escalation was attempted.

## Accepted-base validation

The complete 20-file affected suite passed **1073 tests with1skip** at `53adc931220db789d8220844d5cffd3a53079392`, with psycopg2 hidden, `TRADE_AI_CI=1` and Telegram interdicted. This includes CIO completeness, the full archive behavior suite and the disk activation/refusal tests. The four ratchets, retention inventory, native lane and health checks, data-source authority checker and Ruff all pass. Historical scheduler reconciliation was CHECK-only; both input snapshot and registry hashes remained unchanged. The frontend build passed, and its entire source tree and build scripts are unchanged from the accepted baseline.

The [d635 validation receipt](packets/w8-legacy-carryforward-20261024/VALIDATION_D635.json) preserves the exact commands, source and log hashes, successful final run, earlier failures, preservation comparisons and relay limitation. Publication remains pending reconciliation with newly accepted main; there is no runtime activation in this package.
