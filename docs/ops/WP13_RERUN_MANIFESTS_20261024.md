# WP-13 follow-up: aggregate manifests across rerun attempts

Design-Task: DSN-20261024-wp13-rerun-P1-T1

The required `cio-hardening` aggregate must accept a successful failed-jobs rerun
without treating historical attempts as duplicate current shards. This correction
is source-tested locally; workflow changes remain operator-merged. No deployment
or new GitHub rerun has been performed by this worker.

## Reproduced failure

The coordinator identified run `40057184808`, aggregate job `120765800643`:
`ran_files=1383/1383`, `failed_shards=[]`, but duplicate manifests failed the gate.
A read-only GitHub artifacts query on 2026-10-24 confirmed two
`cio-hardening-shard-0` artifacts and two `cio-hardening-shard-timings` artifacts.
The timing artifact contains downloaded manifest copies and matched the same
`cio-hardening-shard-*` glob as raw shard uploads. Flattening downloaded artifacts
also allowed overlapping paths to overwrite each other before verification.

A fixture invokes the actual manifest loader and aggregate with an older failed
shard followed by its successful rerun, plus nine successful shards retained from
the first attempt. Before this correction it failed with
`duplicate_manifest:0, failed_shard:0`. The numeric ordering case (attempt 10 after
attempt 2) also reproduced the failure. An aggregate-only rerun already passed.

## Corrected behavior

- Raw upload names include the shard and `github.run_attempt`.
- The download glob selects raw attempt artifacts only. Each artifact retains its
  own directory; manifests cannot silently overwrite one another.
- The aggregate's timing upload has a separate name with its attempt, and never
  matches the raw download glob.
- The integrity evidence upload is attempt-specific too: immutable artifact v4
  uploads cannot conflict with evidence left by an earlier failed integrity job.
- Each GitHub-produced manifest records `run_id` and integer `run_attempt`.
  The consumer selects the numerically latest attempt **per shard** from the
  current run, including earlier successful shards GitHub did not rerun.
- Selection never searches for a passing result: a failed latest attempt fails
  even when an earlier attempt passed. A duplicate shard within the same attempt
  fails, including duplicates in an older attempt. Missing, malformed, foreign-run
  and future-attempt evidence fails. Tree, plan, file-accounting, unit-result and
  required-job-result checks continue through the existing strict verifier.
- Non-GitHub/local aggregation keeps the existing strict duplicate behavior.
  The GitHub aggregate reports selected attempt numbers in its JSON evidence.

Independent review found the same raw/timing collision in the required
`cio-full-suite-sharded.yml` aggregate, so its raw/timing uploads and downloads
use the same attempt isolation. Its attestation upload is attempt-qualified too.
The tree-attested evidence reader requests that exact workflow attempt and checks
the payload's run ID and attempt as well as its existing head/tree/check/run
requirements. It never falls back to a static older attestation. An older run
without the new artifact is unavailable for tree-attested reuse; the existing
exact-main evidence path remains its fallback. No release flag or authority is
changed.

## Verification

The focused workflow/shard suites passed **109 tests**, including malformed
schema and exact-attempt attestation cases. The final combined CI-tooling and
registry regression passed **294 tests** in58.59 seconds; the command below plus
`tests/test_ci_gates_registry_20261021.py` exercises that complete selection:

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_ci_cio_hardening_fast_shards_20261022.py \
  tests/test_ci_shards_tree_attest_20261009.py \
  tests/test_cio_ci_profiles_20260925.py \
  tests/test_ci_pr_selection_20260925.py \
  tests/test_ci_duration_hints_20261021.py \
  tests/test_ci_frontend_dependencies_20261018.py \
  tests/test_ci_fail_all_skipped_20261021.py \
  tests/test_ci_draft_pr_skip_20261023.py
```

Fixtures cover mixed attempts, aggregate-only reruns, numeric ordering, missing
shards, latest-attempt failure, same-attempt duplication, invalid attempt types,
foreign runs, future attempts, wrong tree and wrong plan. They use isolated files
under `$HOME/.cache/rtc`; no live application, database, model or broker is called.
The existing CI gate already registers the expanded test file.

Local evidence:
`/home/johnclaw/.cache/rtc/codex-wp13-rerun-20261024/final-combined.log` and
`/home/johnclaw/.cache/rtc/codex-wp13-rerun-20261024/reported-run-artifacts.json`.

## Coordinator follow-through

Publish the single queued `PUSH_NEEDED` command, verify exact-head required checks,
and have the operator merge the workflow change. A fresh workflow run must use
this commit: rerunning an older SHA continues to execute its old workflow and
runner. On a subsequent failed-jobs rerun, inspect `selected_attempts`, exact file
coverage and all required job results; confirm the aggregate passes only when the
latest available attempt of every shard passes. The independent LD-W1 shared-log
test race is being fixed under a separate WP-13 follow-up task/branch.
