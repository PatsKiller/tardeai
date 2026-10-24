# WP-13 shadow-wave dry-run proof isolation

Status: VERIFIED_LOCAL — publication and coordinator merge pending
as_of: 2026-10-24T03:50:29Z
Measured at: main base `ef115e38e5d9b9a52c3b480898afe72b30678121`
Owner: codex-wp13-log-isolation-20261024; DSN-20261024-wp13-log-isolation-P1-T1

The LD-W1 offline dry-run test sampled every file's modification time in the shared
repository `logs/` directory. Independent CI shards and aggregate timing receipts can change
that directory while the lane itself writes nothing, making the no-write assertion flaky.

Each lane test now copies the exact source entrypoint into its own temporary code root.
The child's cwd, `__file__`-derived logs/data, project root, HOME, state, flock logs and active
TMPDIR all resolve inside that fixture. No environment or credential files are copied.
The child environment contains only runtime basics and the test's explicit paths; a
fixture-only startup audit hook refuses network connections, DNS resolution and child
execution. Existing production lane code and its dry-run precedence are unchanged.

The no-write proof compares the entire owned tree before and after execution, including
relative paths, directory/file nanosecond modification times and file bytes. A seeded log
checks existing-file changes; new logs, temporary files, directories and receipts are also
observable. The explicit empty-state assertion remains. It no longer watches unrelated
repository logs.

The existing CI-registered test file now includes four mutation controls: an exit-zero
DRY-RUN that creates a log, modifies the seeded log, creates a temporary file, or writes a
state receipt must fail the no-write assertion. These controls prove that isolating the
log root did not remove file-creation or state-write detection.

Validation: **24 tests passed**, including all six real offline CLI paths and the four
write mutations; Ruff and whitespace checks pass. The test file was already registered
in the canonical CI gate, so no new registry entry was added. Raw output is
`/home/johnclaw/.cache/rtc/codex-wp13-log-isolation-20261024/shadow-wave-tests.log`.
No production log, database, schedule, lane implementation or financial code changed.

The branch is `work/DSN-20261024-wp13-log-isolation-P1-T1` in
`/home/johnclaw/wt-codex-wp13-log-isolation-20261024`. Its single PUSH_NEEDED publication
command is in PROGRESS_LOG.md; the claim stays held for coordinator review and publication.
