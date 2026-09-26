# CI fast core, risk tiers and digest-free evidence (2026-09-25)

Operator direction, 2026-09-25: "plan and build the evidence-file change, speed up to like 5 mins",
then "the current approach is slowing down the entire lifecycle; need faster feedback with appropriate
governance". Budget decision: the required check must finish in **5 minutes of CI wall clock on a
GitHub-hosted runner, including setup**.

`docs/governance/ENGINEERING_STANDARD.md` is referenced by the directive but is not on main (it arrives with
PR #1232), so this page is the reference until that lands.

## What was slow (measured)

| Measure (before) | Value |
|---|---|
| `cio-hardening` job wall clock, 3 green runs on 2026-09-25 | 1,077 to 1,127 s |
| Gates step (181 pytest invocations, one after another) | 610 to 1,090 s |
| Sum of pytest-reported seconds | about 1,048 s |
| Largest gate, `maturity_overnight_20260912` (130 files) | 226 to 385 s |
| Everything else in the job (checkout, setup, installs, 9 other steps) | about 35 s |

The tests are CPU-bound: for every slow file, wall time is about equal to user+sys time. On a 4-vCPU runner,
running every registered test cannot go below about 5 to 6 minutes, however it is parallelised. So:

* **PRs** run a *selection* (the `pr` profile). The selection always includes the governance smoke set and the
  full suites of any high-risk area touched.
* **Every test** still runs after merge, on each push to main (`fast` profile, parallel). It also runs nightly
  in the serial `full` profile, and on demand.
* A red post-merge or nightly run opens or updates one `ci-main-red` issue. It does not block open PRs.

## Profiles (`scripts/run_cio_hardening_ci.py --profile ...`)

| Profile | Where | What runs |
|---|---|---|
| `pr` | required `cio-hardening` on `pull_request` | the smoke gates, the named gates of every HIGH tier touched, changed tests, then impacted tests nearest-first within `budget_seconds`; the rest are DEFERRED and listed |
| `fast` | `cio-hardening` on push to main and on dispatch; `ai_local_acceptance.sh` default | every registered gate, in a worker pool; shared-state files run afterwards, one at a time |
| `full` | `cio-hardening-full`, nightly and on dispatch; `ai_local_acceptance.sh --full` | the historical serial loop, as the isolation reference |

All three profiles run the same tail checks: docs index drift, committed release manifest, and candidate
manifest. Registration is unchanged: a test file is covered only if it appears in `GATES`, and
`check_test_coverage.py` enforces that.

### Test-impact selection (`scripts/lib/test_impact.py`)

The selection works from a static reverse-dependency map over `scripts/` and `tests/`. It follows three kinds
of reference:

* `import` statements. `scripts.lib.x`, `lib.x` and bare `x` all resolve.
* Path strings, such as `spec_from_file_location(..., "scripts/x.py")`, `subprocess` calls on `scripts/x.py`,
  and `config/*.json`.
* Bare `"x.py"` names of top-level scripts.

A change selects every test in its reverse transitive closure. The map is cached in the worktree's git dir
(`git rev-parse --git-path tradeai/test_impact_map.json`), keyed on the path, size and mtime of every scanned
file. A stale map is rebuilt, which takes about 10 s.

If the diff base cannot be resolved, or the map or tiers cannot be loaded, the profile falls back to `fast`
(every gate).

### Risk tiers (`config/ci_risk_tiers.json`)

| Tier | Paths (summary) | PR behaviour |
|---|---|---|
| HIGH | policy and guard (AGENTS.md, AI_WORK_POLICY.md, CLAUDE.md, `.cursor/`, `.githooks/`, `docs/governance/`, `bin/guard`, guard scripts, check_no_secrets); broker and execution (`scripts/brokers/`, moomoo, active_trader, schwab scripts, trading-session grant, instrument record, data_source_authority); memory and SQL (`sql/`, `migrations/`, `cio_memory_*`, `m2_*`); deploy and release; schedule (lane_registry, systemd, cron); CI control surface (workflows, runner, the tier/hint/baseline configs, SOP evidence, requirements, pyproject) | the category's named gates run **in full, regardless of budget**. Every gate of 60 s or less that holds a test directly importing the path also runs. The job summary says **independent review required** and lists the paths. |
| LOW | `docs/**`, `**/*.md`, top-level `*.txt`, archive and reference | smoke gates plus the docs-index gate only |
| MEDIUM | everything else | smoke gates plus impacted tests within budget |

Every path in the CODEOWNERS file proposed by PR #1232 classifies HIGH, and
`tests/test_ci_pr_selection_20260925.py` holds that. When `.github/CODEOWNERS` exists on main, the same test
reads it. Smoke plus every HIGH category together is about 224 hint-seconds. The test also asserts that this
fits the budget.

`budget_seconds` (540) is the sum of per-file duration hints (`config/ci_test_duration_hints.json`). The tests
are CPU-bound and about 4 run at once on a runner, so 540 is roughly 150 to 180 s of CI wall clock.

## Local commands

| Command | When | Measured here |
|---|---|---|
| `scripts/fast_check.sh` | while iterating; read-only; changed files only | 13 to 63 s (see Timings) |
| `scripts/ai_local_acceptance.sh` | before asking for a push (fast profile, every gate, per-worktree test DB `m2_shadow_test_<sha12>`, created if missing, never `m2_shadow`) | |
| `scripts/ai_local_acceptance.sh --full` | isolation reference (serial) | |

`fast_check.sh` runs these checks:

1. ruff on the changed `.py` files. It fails only when a file has more violations than it had at the merge base.
2. `check_no_secrets --tree`.
3. `check_test_coverage --fail-on-new`.
4. `check_test_host_paths --fail-on-new`.
5. The read-only docs-index check.
6. The `pr` selection with `--budget 120 --no-tail`.

It never writes generated files, never runs `git add` and never runs `npm ci`.

## Timings (after)

These were measured on 2026-09-25 on the shared dev host (load average 5 to 9 from other sessions). The CI
mimic shadows psycopg2 with a module that raises `ModuleNotFoundError(name="psycopg2")`, as the runner has no
driver, and uses `--jobs 4` (the runner has 4 vCPU). Earlier measurements put this host at about 0.86 times
the runner's time for the same gates. The CI projection is the local time divided by 0.86, plus about 12 s to
build the map, plus the 35 s of other job steps.

| Diff | Tier | Selected files (deferred) | PR core, local CI mimic | Projected CI job |
|---|---|---|---|---|
| one doc (`docs/ops/README.md`) | LOW | 17 (0) | 11 s | about 1 min |
| `scripts/lib/comms_editor.py` | MEDIUM | 249 (150) | 152 s | about 3.7 min |
| `scripts/lib/__init__.py` (imported by nearly every test) | MEDIUM | 204 (243) | 147 s | about 3.6 min |
| `scripts/lib/cio_memory_integration.py` | HIGH memory | 152 (0) | 63 s | about 1.8 min |
| six HIGH categories at once | HIGH | 229 (239) | 114 s | about 2.9 min |

Before the change, the job took 1,077 to 1,127 s on the runner, and every PR paid that cost.

For `fast_check.sh`, the local time is 8 workers with a warm map, and the total adds about 3 s of checks:

| Diff | Impacted-test step | Total |
|---|---|---|
| one doc | 11 s | about 14 s |
| `comms_editor.py` (MEDIUM) | 31 s | about 34 s |
| `cio_memory_integration.py` (HIGH) | 23 s | about 26 s |
| this branch: 33 paths across 3 HIGH categories, cold map | 61 s | 63 s |

A HIGH diff's named gates are never deferred, so a diff that touches several HIGH areas can pass 60 s.

## `strict` (require branches to be up to date): data for the open decision

Branch protection today requires `cio-hardening` and `agent-governance`, with `strict: true`. The data below
covers `cio-production-hardening-ci` runs on 2026-09-25 (UTC), 44 in total: 7 on main pushes and 37 on
branches or PRs.

* **9 of the 37 branch runs (24%)** ran on commits that existed only because of staleness or generated-file
  churn:
  * 2 "Merge origin/main into ..." commits.
  * 7 "regenerate evidence / rebind control_surface_digest / refresh index fingerprint" commits. 3 of those
    runs failed, and each failure cost another push.
* **0 real conflicts.** `git merge-tree` shows that both main-merges conflicted only in the 4 digest files and
  `docs/INDEX.md`, which the `merge=regenerate` driver handled. This PR stops committing those per-PR values.
* **7 more runs were exact duplicates**: the same SHA ran once on `push` (to wt/**, feat/**, hardening/**) and
  once on `pull_request`. The push trigger is now `main` only.

With digest-free evidence, the main source of forced refreshes is gone. A strict refresh now costs a 1 to 4
minute PR core instead of an 18-minute job. Two choices remain:

* **Keep strict.** Correctness is simple, and a refresh is cheap now.
* **Drop strict.** There are fewer refresh loops, and main is guarded by the post-merge full run and the
  `ci-main-red` issue.

Either way, this is an administrator's setting and it is not changed here.

## Evidence files: what they attest now

The four SOP files that used to embed `control_surface_digest` and were rewritten on every PR are:

* `FULL_TEST_MATRIX.txt`
* `RUFF_SHELLCHECK.txt`
* `CONTROL7_WORKFLOW_PROOF.txt`
* `CONTROL7_LOCAL_EQUIVALENT.txt`

They now carry `control_surface_digest=AT_HEAD`. The digest is still computed over the 31 manifest paths by
`validate_sop_evidence_integrity.py`. It is recorded per run in the `SopRuntimeAttestation@v1` artifact that
`agent-governance` emits.

What is committed still binds the workflow blob hashes, line counts and path filters. A committed 64-hex
digest in those four files fails `EVIDENCE_EMBEDS_VOLATILE_DIGEST`. `docs/INDEX.md` commits rows only; the
tree fingerprint and counts are printed by `--check-index`.

`scripts/regenerate_generated_files.sh` stages nothing. If there are untracked docs, it stops and prints the
`git add` command to run.
