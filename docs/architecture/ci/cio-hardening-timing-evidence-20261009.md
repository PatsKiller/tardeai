# CI timing evidence: why `cio-hardening` takes ~15 minutes (2026-10-09)

This is a read-only measurement. Nothing in the repo was changed and nothing was pushed. The repo is PatsKiller/tardeai, and origin/main was `3b5c248569908adfad9a60ca895e0fa9b2aa2c49` when the measurements were taken (14:00 to 14:14Z on 10-09).
The plan was reproduced in a detached worktree at `/home/johnclaw/tradeai-wt-citiming-20261009`, checked out at `932dd9801`, `bbff99766` and `3b5c24856`.
The raw data is in `/tmp/claude-1000/-home-johnclaw/77a6de60-3513-40ce-9220-25d684930e93/scratchpad/citiming/`: `api/*.json` holds the job and step JSON, `logs/*.log` holds the job logs, and `parsed.json` holds the parsed gate lines.
Percentiles are linear-interpolated. Step timestamps from the GitHub API have 1-second resolution.

## 0. Commands used

```
gh run list --workflow cio-production-hardening-ci.yml --limit 60 --json databaseId,event,createdAt,updatedAt,conclusion,headSha,status,headBranch
gh api repos/PatsKiller/tardeai/actions/runs/<id>/jobs          # per job + per step started_at/completed_at, labels, runner
gh api repos/PatsKiller/tardeai/actions/jobs/<job_id>/logs      # full job log (gh run view --log failed when run in parallel)
gh run list --workflow {agent-governance,provider-cost-ci,release-readiness,financial-senses-ci} --limit 20 ... ; gh api .../runs/<id>/jobs
gh pr list --state merged --limit 40 --json number,mergedAt,mergeCommit,headRefOid,headRefName
git rev-parse <sha>^{tree} ; git diff --stat <pr_head> <merge_sha>
python3: import scripts/run_cio_hardening_ci.py in the worktree -> plan_units(GATES), load_duration_hints()
cat ~/.local/state/cio-phase2-exact-main/{deploy_receipt,post_merge_ci}.json
local logs: scratchpad/*acceptance*.log
```

Sample: 58 completed non-schedule runs, from 2026-10-08 15:07Z to 2026-10-09 13:51Z.
- 53 succeeded: 18 `push` to main and 35 `pull_request`. These are the runs analysed below.
- 5 were excluded: 3 PR failures (`37804065428`, `37814666843`, `37818919154`) and 2 PR cancellations.
- One scheduled run (`37900362846`, the nightly `full` profile) ended in **failure** at 08:12Z on 10-09.

---

## 1. GitHub Actions timing, per step

Workflow facts, from `git show origin/main:.github/workflows/cio-production-hardening-ci.yml`:
- The job runs on `runs-on: ubuntu-latest` with `actions/checkout@v4` (`fetch-depth: 0`) and `actions/setup-python@v5` (Python 3.13).
- There is **no pip cache and no cache-restore step**. pip installs `pytest pyyaml requests python-docx ruff==0.16.2`.
- On push the gate step runs `--profile fast`. On pull_request it runs `--profile pr --base origin/$BASE_REF`.
- Concurrency group is `cio-hardening-${{ github.workflow }}-${{ github.ref }}`, with `cancel-in-progress` only for pull_request. Main-branch runs therefore **queue behind each other** rather than cancel.

### cio-hardening job: push to main (n=18 successful runs)

| stage | median s | p90 s | min | max |
|---|---|---|---|---|
| queue (run created → job start) | 4 | 496 | 3 | 814 |
| Set up job | 1 | 1 | 0 | 2 |
| checkout (fetch-depth 0) | 13 | 15 | 10 | 17 |
| setup-python | 0 | 1 | 0 | 1 |
| install deps (no cache) | 7 | 10 | 5 | 12 |
| cache restore | — no such step — | | | |
| **CIO hardening gates step** | **822** | **911** | 441 | 915 |
| Phase 11 adversarial suite | 2 | 3 | 1 | 3 |
| Dark contract guard | 10 | 10 | 6 | 11 |
| retention/line-ending/coverage/host-path guards + HTML/DOCX smoke | 0–1 each | ≤1 | | |
| PDF smoke | 3 | 3 | 2 | 4 |
| artifact upload | 2 | 2 | 0 | 2 |
| **job wall** (job start → complete) | **904** | **955** | 471 | 959 |
| run wall (run created → run updated) | 950 | 1363 | 474 | 1615 |

### cio-hardening job: pull_request (n=35 successful runs)

| stage | median s | p90 s | min | max |
|---|---|---|---|---|
| queue | 4 | 6 | 3 | 516 |
| checkout | 13 | 15 | 10 | 16 |
| setup-python | 0 | 1 | 0 | 1 |
| install deps | 8 | 12 | 4 | 17 |
| **CIO hardening gates step** | **386** | **479** | 105 | 551 |
| Phase 11 adversarial | 2 | 3 | 1 | 3 |
| Dark contract guard | 9 | 10 | 5 | 11 |
| PDF smoke | 20 | 52 | 4 | 75 |
| artifact upload | 1 | 2 | 0 | 2 |
| **job wall** | **449** | **551** | 151 | 622 |
| run wall | 471 | 569 | 158 | 772 |

### Fast workflows for comparison (last 20 runs each; median/p90 in seconds)

| workflow / job | event | n | queue | checkout | setup-python | install | job wall |
|---|---|---|---|---|---|---|---|
| agent-governance | pull_request | 12 | 3/4 | 13/15 | 0/0 | 5/7 | 48/55 |
| agent-governance | push | 8 | 3/3 | 13/14 | 0/0 | 6/10 | 50/56 |
| provider-cost | pull_request | 12 | 3/4 | 4/5 | 0/1 | 5/6 | 38/47 |
| provider-cost | push | 8 | 3/3 | 5/5 | 0/1 | 4/7 | 40/44 |
| release-readiness | pull_request | 12 | 3/4 | 5/5 | 0/0 | 4/5 | 102/106 |
| release-readiness | push | 8 | 3/3 | 4/5 | 0/1 | 4/5 | 99/107 |
| financial-senses-ci / financial-senses | push | 20 | 4/5 | 5/5 | 0/1 | 5/7 | 18/22 |
| financial-senses-ci / broader-regression | push | 20 | 3/4 | 5/5 | 0/0 | 4/6 | 17/19 |

Setup costs are the same across all workflows: checkout plus Python plus install comes to 20–30 s in cio-hardening and 9–20 s elsewhere. Checkout is 13 s in both workflows that use fetch-depth 0. **The whole difference is in the gate-runner step.**

---

## 2. Inside the gate-runner step

Runner logic, from `git show origin/main:scripts/run_cio_hardening_ci.py`, lines 3646–3850:
- `jobs = min(os.cpu_count(), 8)`.
- Each GATE is split into "units" of about 25 hint-seconds (`UNIT_TARGET_SECONDS`), using `config/ci_test_duration_hints.json`.
- Each unit is one `python -m pytest -q --tb=line -p no:cacheprovider <files>` subprocess.
- Units run in a `ThreadPoolExecutor(max_workers=jobs)`, sorted longest-first by hint.
- Files that match `SHARED_STATE_PATTERNS` run afterwards, **one at a time** (the "serial tail").
- The `pr` profile first runs `select_pr_gates` (test-impact selection), then uses the same pool.

The log lines parsed were `[plan]`, `[select]`, `[PASS|FAIL] gate (k files, Xs)` and `[timing]`. All 53 successful runs were parsed: 18 push and 35 PR.

Every run logged **`jobs=4`**, for example `[plan] profile=fast jobs=4 parallel_units=340 serial_gates=20` in run 37939797812. That means `os.cpu_count()` was 4 on the runner.

### Phase breakdown of the gate step (median / p90 / min / max, seconds)

| metric | push (fast profile, n=18) | pull_request (pr profile, n=35) |
|---|---|---|
| pre-plan (imports + PR selection) | 0.6 / 0.6 / 0.3 / 0.9 | **19.2** / 20.4 / 10.6 / 21.7 (`select_secs`, `map=rebuilt` on every PR run) |
| parallel units | 335.5 / 339 / 330 / 340 | 107 / 130 / 8 / 135 |
| serial gates | 20 / 20 / 20 / 20 | 10 / 12 / 5 / 13 |
| test files executed | 907.5 / 912 / 898 / 913 | 224 / 309 / 38 / 326 |
| distinct gates executed | 324.5 / 328 / 319 / 329 | 107 / 128 / 12 / 137 |
| **parallel phase wall** | **677 / 761** / 364 / 764 | 319 / 419 / 78 / 451 |
| sum of parallel unit seconds | 2547 / 2885 / 1381 / 2887 | 1144 / 1508 / 89 / 1630 |
| pool utilisation = sum / (wall × 4) | 0.94 / 0.95 / 0.93 / 0.95 | 0.88 / 0.90 / 0.29 / 0.93 |
| **serial tail wall** (= sum of serial units) | **144 / 149** / 77 / 150 | 35 / 75 / 11 / 85 |
| tail checks (docs index, manifests) | 0.8 | 0.8 |
| largest single unit | 155 / 170 / 86 / 170 | 141 / 161 / 78 / 165 |

### Critical path with jobs=4

- Push, median run: the throughput floor for the parallel phase is 2547 / 4 = 637 s, against 677 s actual. The longest unit (155 s) is far below that floor.
- The **parallel phase is throughput-bound, not chain-bound**: 4 workers stay busy for 94% of the phase.
- The serial tail is strictly additive (+144 s).
- Push critical path ≈ 637–722 s of parallel throughput, + 144 s serial, + about 20 s of setup and about 20 s of post-gate steps. This matches the measured 904 s median job wall.
- `jobs=8` never occurs in CI. It appears only in local runs (§4).

### 25 slowest gates, push runs (sum of the gate's unit seconds per run; median across 18 runs)

| rank | gate | median s | p90 s | units/run | largest unit median s | has serial part |
|---|---|---|---|---|---|---|
| 1 | maturity_overnight_20260912 (133 files) | 779.1 | 875.7 | 15 | 145.9 | no |
| 2 | ci_self_guards (23 files, 1 unit) | 154.9 | 169.6 | 1 | 154.9 | no |
| 3 | options_order_authorization_20260927 | 127.9 | 153.4 | 1 | 127.9 | no |
| 4 | overnight_g4_archive_mechanism | 104.8 | 109.3 | 1 | 104.8 | no |
| 5 | alarm_document_sites_20260922 | 89.1 | 100.5 | 2 | 75.6 | yes |
| 6 | alarm_fires | 88.8 | 93.1 | 3 | 78.9 | yes |
| 7 | campaign_m2_canary_lanes | 80.9 | 93.0 | 5 | 23.5 | no |
| 8 | options_broker_gates_20260927 | 79.9 | 88.7 | 1 | 79.9 | no |
| 9 | cio_operator_artifacts_20261003 | 63.6 | 70.0 | 1 | 63.6 | no |
| 10 | goal_work_minter_ratchet | 54.7 | 56.2 | 1 | 54.7 | yes (whole gate serial) |
| 11 | no_swallowed_alarms | 49.0 | 53.4 | 1 | 49.0 | no |
| 12 | comms_gateway_phase0 | 48.0 | 50.7 | 2 | 34.8 | yes |
| 13 | ci_honesty_ws4_20260926 | 47.0 | 54.9 | 1 | 47.0 | no |
| 14 | gate_honesty_and_archive_or_wire | 37.9 | 41.4 | 1 | 37.9 | no |
| 15 | telegram_notification_normalization | 36.6 | 40.3 | 2 | 35.7 | yes |
| 16 | n8n_parallel_20261007 | 31.2 | 36.3 | 2 | 28.1 | no |
| 17 | report_model_and_parity | 30.1 | 41.2 | 1 | 30.1 | no |
| 18 | alarm_imports_resolve | 30.0 | 32.2 | 1 | 30.0 | no |
| 19 | gate_honesty_p6_20260922 | 25.4 | 28.2 | 1 | 25.4 | no |
| 20 | health_paper_siem_20261003 | 24.8 | 31.6 | 2 | 24.0 | yes |
| 21 | at_alert_sync_20261005 | 23.6 | 26.1 | 1 | 23.6 | no |
| 22 | cogx_w1_foundations | 20.1 | 22.9 | 1 | 20.1 | no |
| 23 | architect_remediation_20260915 | 17.7 | 20.9 | 1 | 17.7 | no |
| 24 | cc_header_truth_v2 | 15.8 | 17.3 | 1 | 15.8 | no |
| 25 | holdings_data_clock | 14.6 | 15.5 | 1 | 14.6 | no |

In the median push run, maturity_overnight_20260912 alone accounts for 779 of 2547 parallel unit-seconds (31%).

### Serial tail, push (all 20 serial units run every push; total median 144 s)

| unit | median s | p90 s |
|---|---|---|
| goal_work_minter_ratchet (`tests/test_goal_work_minter_ratchet.py`) | 54.7 | 56.2 |
| comms_gateway_phase0 (`tests/test_provider_chokepoint_ratchet.py`) | 34.8 | 35.9 |
| alarm_document_sites_20260922 (`tests/test_alarm_fires_documents_20260922.py`) | 13.9 | 14.2 |
| telegram_chokepoint_ratchet | 10.9 | 11.3 |
| guard_push_auth | 4.1 | 4.2 |
| overnight_g3_docs_index | 3.6 | 4.1 |
| agent_governance_sop | 3.5 | 3.8 |
| test_host_paths_ratchet_20260925 | 3.2 | 3.5 |
| ci_fixture_immutability | 3.1 | 3.2 |
| 11 others | ≤2.1 each (about 10 s total) | |

### Slowest individual units mapped to files

The plan was reproduced at each run's SHA with `plan_units(GATES)`. For both runs, the unit order and file counts matched the log exactly.

| CI s, westus run 37939797812 @932dd9801 | CI s, centralus run 37936770971 @bbff99766 | hint-estimate s | plan position | gate | file(s) |
|---|---|---|---|---|---|
| 167.0 | 92.8 | 23.0 | 20 | ci_self_guards | 23 files (tests/test_ci_test_coverage_gate.py, …) |
| 162.1 | 90.8 | 43.3 | 4 | maturity_overnight_20260912 | tests/test_data_source_authority_20260913.py |
| 150.6 | 76.2 | 2.0 | 117 | options_order_authorization_20260927 | test_options_order_authorization_20260927.py + test_options_broker_gates_20260927.py |
| 146.4 | 82.9 | 49.1 | 2 | maturity_overnight_20260912 | tests/test_sot_phase9_quotes_prices_writers.py |
| 109.3 | 61.9 | 39.4 | 5 | overnight_g4_archive_mechanism | tests/test_overnight_g4_archive_mechanism.py |
| 87.8 | 52.0 | 1.0 | 300 | options_broker_gates_20260927 | tests/test_options_broker_gates_20260927.py |
| 83.5 | 45.9 | 29.5 | 8 | alarm_document_sites_20260922 | tests/test_alarm_coverage.py |
| 82.4 | 46.8 | 29.5 | 7 | alarm_fires | tests/test_alarm_coverage.py |
| 76.2 | 40.2 | 24.7 | 13 | maturity_overnight_20260912 | 4 files (test_watch_directives_writer_phase9.py, …) |
| 75.1 | 42.8 | 24.7 | 12 | maturity_overnight_20260912 | 6 files (test_data_gap_registry_writer_20260913.py, …) |
| 74.8 | 41.5 | 20.2 | 24 | maturity_overnight_20260912 | tests/test_sot_p9_news_articles_writer.py |
| 73.9 | 40.1 | 24.2 | 17 | maturity_overnight_20260912 | 5 files (test_subject_memory_recall_20260913.py, …) |
| 72.1 | 40.7 | 20.3 | 23 | maturity_overnight_20260912 | tests/test_sot_p9_hermes_research_writer.py |
| 72.1 | 39.7 | 18.9 | 26 | maturity_overnight_20260912 | tests/test_sot_p9_symbol_profiles_writer.py |
| 68.0 | 38.7 | 1.0 | 151 | cio_operator_artifacts_20261003 | tests/test_cio_operator_artifacts_20261003.py |
| 54.8 | 23.6 | 6.0 | 53 | ci_honesty_ws4_20260926 | 6 files (test_r18_2_production_hardening.py, …) |
| 53.0 | 28.1 | 18.4 | 27 | no_swallowed_alarms | tests/test_no_swallowed_alarms.py |

The plan's first unit is `tests/test_p26_shadow_autonomy.py`, with a hint of 121.8 s. In CI it took **3.0 s** in run 37939797812 (`[PASS] maturity_overnight_20260912 (1 files, 3.0s) 44 passed in 2.39s`).

Other hint facts:
- Sum of hint-estimates over all 340 parallel units: 1563.5 s. Measured sum in the same run: 2887.2 s.
- 17 units took ≥30 s in CI despite an estimate ≤25 s. Together they took 1206 s.
- The hints file holds **48 files** (sum 759.4 s), "measured 2026-09-25". It was last changed in commit `c41ecd6ae` on 2026-09-25 (`git log -- config/ci_test_duration_hints.json`). Every other file defaults to 1.0 s.

### Duplicate registrations

`GATES` holds 914 registered paths but only 886 unique files. **25 files are registered in more than one gate, which means 28 extra executions per push run.**

Two of the duplicates are expensive:
- `tests/test_alarm_coverage.py`, in alarm_fires and alarm_document_sites_20260922: 82–84 s per execution in the westus run, so ≈80 s spent twice.
- `tests/test_options_broker_gates_20260927.py`, in options_broker_gates_20260927 and options_order_authorization_20260927: 87.8 s alone, and inside a 150.6 s unit the second time.

### PR selection (`[select]` lines, all 35 PR runs)

| stat | value |
|---|---|
| risk tier | high 27, medium 7, low 1 |
| `map=` | `rebuilt` in 35/35 runs (impact map rebuilt every run; select_secs median 19.2 s) |
| budget_seconds | 540 (hint-seconds) in every run |
| estimate | 539.1–539.9 s (budget filled) in 26/35 runs; 38–347 s when impacted set small |
| selected test files | median 224, range 38–326 (of ~912 in a push run) |
| `deferred=` | 0 in 9 runs; 342–477 in 26 runs |
| actual parallel unit-seconds vs estimate | median 1144 s actual vs ≈540 s estimate (≈2.1×) |

The `[select] DEFERRED to post-merge full run: <file>` lines are capped at 25 per log. The full lists are in the job summaries. "Post-merge full run" in that message refers to the push-to-main `fast` profile, which runs every gate. The `full` serial profile runs only on schedule or workflow_dispatch.

---

## 3. Runner hardware and CPU saturation

- **runs-on**: `ubuntu-latest`. The logs show `Image: ubuntu-24.04`, `Version: 20261004.327.1`, Hosted Compute Agent, Cloud: Azure, with a varying `Region:`.
- **cores**: `jobs=4` in every log, so `os.cpu_count()` = 4. The CPU model is **NOT VERIFIED** because the job logs do not print it.
- **parallelism vs cores**: 4 pytest subprocesses on 4 vCPUs. The `jobs=8` figure in the task brief applies only to the local host (20 CPUs, i9-12900H, `lscpu`).
- **saturation**: pool utilisation is 0.93–0.95 on every push run, so all 4 workers are busy for about 94% of the parallel phase. Whether each worker's own CPU is saturated (as opposed to waiting on I/O or subprocesses) is **NOT VERIFIED**, because there are no CPU metrics in the logs.
- **runner variance by region, push runs only (same 898–913 files):**

| Region | push runs | gates-step s (median) | sum of parallel unit-s | s per file |
|---|---|---|---|---|
| centralus | 4 | 503.5 (441–516) | 1381–1592 | 1.52–1.76 |
| all other regions (eastus, eastus2, southcentralus, westus, westus2, westus3) | 14 | 901.5 (657–915) | 2024–2887 | 2.24–3.19 |

  The same file takes ≈1.8× longer on the slower runners. For example, test_data_source_authority took 162.1 s in westus and 90.8 s in centralus. Region is a correlate only; the hardware difference behind it is **NOT VERIFIED**.
- **step time vs sum of gate times**: for the median push run, the gate step took 822 s. That is ≈ 677 s parallel phase + 144 s serial tail + about 1 s of plan and tail checks. There is no unexplained overhead.

---

## 4. Local equivalent (`scripts/ai_local_acceptance.sh`)

The script's phases, in order: policy hook self-test, policy unit tests, target/repository validation (CI-equivalent release proof), lane registry, `run_cio_hardening_ci.py --profile fast`, adversarial suite, dark-contract / line-ending / host-path / data-source-authority checks, and a final policy pytest.

Before the gates, the script exports `M2_TEST_DATABASE` and creates a Postgres test DB (`ensure_m2_test_database.py`).

The logs carry no per-phase timestamps, so **total acceptance wall time is NOT VERIFIED**. The figures below are the ones the logs print themselves.

| log | release proof s | policy pytest s | cio gates `[timing]` wall s | plan | sum parallel unit-s | serial s | largest unit s |
|---|---|---|---|---|---|---|---|
| acceptance.log (10-09 09:46) | 71.2 | 7.27 | **590** | jobs=8, 339 units / 20 serial | 3341 | 115 | 287.7 |
| cadfix_acceptance.log | 67.81 | 5.27 | 546 | jobs=8, 338/20 | 3164 | 106 | 296.9 |
| n1cut_acceptance.log | 38.05 | 3.44 | 447 | jobs=8, 338/20 | 2511 | 92 | 208.2 |
| gwlock_acceptance.log | 74.71 | 5.57 | 487 | jobs=8, 333/20 | 2744 | 101 | 239.4 |
| train2_acceptance.log | 89.95 | 6.65 | 637 | jobs=8, 332/20 | 3937 | 96 | 360.4 |
| acceptance2.log | 41.89 | 3.83 | 453 | jobs=8, 332/20 | 2507 | 96 | 210.6 |
| wfrunid_acceptance.log | 91.37 | 10.51 | 576 | jobs=8, 330/20 | 3218 | 121 | 289.8 |
| train_acceptance.log | 37.83 | 3.60 | 535 | jobs=8, 328/20 | 2807 | 135 | 234.0 |
| amend / ratify300 / cogx / w1t1 | 30.7–74.2 | 2.7–10.5 | no gates phase in the log (truncated or EXIT=1) | | | | |

Locally, the first unit (`maturity_overnight_20260912`, 1 file) took **208–360 s**. In acceptance.log it shows `44 passed in 286.96s`, against 3.0 s in CI. The local runs have `M2_TEST_DATABASE` set; CI does not. Why this one file is slow locally is **NOT VERIFIED**.

---

## 5. Repeat runs: merge → green `cio-hardening` on main

Deploy gate facts:
- `scripts/cio_phase2_exact_main_deploy.sh` promote (lines 650–661) calls `release_grant_preflight.py --ci-only --sha <sha>`.
- `REQUIRED_PUSH_WORKFLOWS` = {cio-production-hardening-ci.yml, agent-governance.yml}.
- Promotion dies with "exact-SHA push-to-main checks are not completed successfully; activation refused". The script does not poll; the operator re-runs it.

Live example, from `~/.local/state/cio-phase2-exact-main/post_merge_ci.json` and `deploy_receipt.json`:
- At **14:01:17Z** promote of `3b5c24856` (#1547) was refused: `extra: post_merge_ci_refused`, `errors: not_successful:cio-production-hardening-ci.yml`.
- By then every other push workflow for that SHA had already succeeded. The latest, aif-financial-senses-integration, finished at 13:58:39Z.
- cio-hardening run `37940448932` was `pending`. It was created 13:56:15Z, and its job was only created at **14:06:58Z**, the second the previous main run (`37939797812`, #1546) finished at 14:06:57Z. That is the main-branch concurrency queue (646 s).
- The run later completed successfully: job 14:07:01Z→14:16:02Z, so merge→green for #1547 was 1191 s, 646 s of it queue.

### Per merge (PRs merged 10-08 16:00Z → 10-09 14:00Z)

| PR | merged (Z) | merge sha | PR head | PR-head tree == merge tree | last green PR-head cio run (done Z, files, deferred) | push run (created→job start, queue s) | push job done (Z) | merge → green cio on main (s) |
|---|---|---|---|---|---|---|---|---|
| #1525 | 10-08 16:26:09 | b85f879b1 | 799bb7bf7 | **identical** | 16:18:46, 304, 359 | 16:26:13→16:26:17 (4) | 16:38:36 | 747 |
| #1528 (train 2) | 10-08 17:11:38 | 62c86440f | d29e9ec67 | **identical** | 17:01:03, 249, 427 | 17:11:41→17:11:45 (4) | 17:26:47 | 909 |
| #1523/#1524/#1526/#1527 | 10-08 17:11:40 | own merge shas | — | differ (28–48 files) | — | no push run for their merge SHAs (main advanced as 62c86440f) | — | — |
| #1530 | 10-08 18:22:17 | 443774e21 | d5b3a78d4 | **identical** | 18:22:06, 326, 349 | 18:22:20→18:23:00 (40) | 18:38:43 | 986 |
| #1532 | 10-08 19:03:23 | 4d469572f | bb00657d2 | **identical** | 18:56:48, 225, 451 | 19:03:26→19:03:30 (4) | 19:18:37 | 914 |
| #1531 | 10-08 19:07:30 | 6b1ed40e4 | c36055c13 | **identical** | 19:07:19, 50, 0 | 19:07:33→19:18:41 (**668**) | 19:34:27 | **1617** |
| #1533 | 10-08 19:20:54 | 3549125b7 | e55151efd | **identical** | 19:20:32, 38, 0 | 19:20:57→19:34:31 (**814**) | 19:46:13 | **1519** |
| #1529 | 10-08 19:57:12 | 7db8e3bb2 | 3e3e67d87 | **identical** | 19:55:37, 270, 408 | 19:57:15→19:57:19 (4) | 20:06:26 | 554 |
| #1535 | 10-08 20:18:52 | c8cb54906 | 222b44886 | **identical** | 20:18:29, 38, 0 | 20:18:55→20:18:59 (4) | 20:34:58 | 966 |
| #1536 | 10-08 20:28:01 | eec946b2c | f51f6e1b9 | **identical** | 20:27:49, 312, 358 | 20:28:04→20:35:06 (**422**) | 20:49:40 | 1299 |
| #1539 | 10-09 00:41:59 | d8c527aea | 5f4d610db | **identical** | 00:26:13, 254, 439 | 00:42:02→00:42:05 (3) | 00:50:58 | 539 |
| #1540 | 10-09 01:08:02 | 4673f135f | 87b16efd1 | **identical** | 01:07:56, 250, 423 | 01:08:05→01:08:09 (4) | 01:24:00 | 958 |
| #1541 | 10-09 02:01:13 | f8749580b | 0d29cfcf8 | **identical** | 02:00:23, 270, 414 | 02:01:16→02:01:19 (3) | 02:15:40 | 867 |
| **#1542** | 10-09 02:22:23 | 4d7753c12 | a9b8bb854 | **identical** | 02:20:48, 224, 428 | 02:22:26→02:22:29 (3) | 02:30:20 | 477 |
| #1534 | 10-09 02:35:38 | d444fe9eb | e3e906974 | **identical** | 02:35:08, 205, 477 | 02:35:42→02:35:46 (4) | 02:51:42 | 964 |
| #1537 | 10-09 03:07:51 | ea90bd880 | 4b1af1f64 | **identical** | 03:07:20, 205, 454 | 03:07:54→03:07:57 (3) | 03:23:47 | 956 |
| **#1543** | 10-09 12:38:32 | a9fa8b89b | 59f37588c | **identical** | 12:37:53, 224, 429 | 12:38:35→12:38:38 (3) | 12:54:19 | 947 |
| **#1545** | 10-09 13:25:43 | bbff99766 | 670651f3b | **identical** | 13:25:36, 237, 416 | 13:25:47→13:25:50 (3) | 13:34:53 | 550 |
| **#1546** | 10-09 13:50:54 | 932dd9801 | 4e0febba2 | **identical** | 13:48:13, 135, 0 | 13:50:57→13:51:02 (5) | 14:06:57 | 963 |
| **#1547** | 10-09 13:56:11 | 3b5c24856 | a09845461 | **identical** | 13:55:58, 115, 0 | 13:56:15→14:07:01 (**646**) | 14:16:02 (run 37940448932 success; checked after the table was built) | **1191** |

The tree check was `git rev-parse <head>^{tree}` vs `<merge>^{tree}`. Every `git diff --stat <pr_head> <merge_sha>` came back empty.

**Merge → green cio-hardening on main** (18 completed cases, #1525–#1546; #1547 = 1191 s finished later and is not included): median **951.5 s**, p90 1365 s, min 477 s, max 1617 s. The total was 16,732 s, about 4.6 h of waiting across those 18 merges.

**Re-testing unchanged content.** In 18 of 18 single-PR merges the merge tree is byte-identical to the PR head tree, which had a green PR-profile run shortly before: the gap from PR-head green to merge was under 1 min in 11 of 19 cases, and at most about 15.5 min (#1539, 00:26:13 to 00:41:59). The PR run, however, executed only a **selection**: 38–326 of about 912 test files, with 0–477 "deferred". The push run then executes all 898–913 files on the identical tree. Within the push run, the files the PR run had already executed are re-run. Per-file overlap in seconds was not computed (**NOT VERIFIED**).

---

## Timing table (stage → median / p90 s)

| stage | push median | push p90 | PR median | PR p90 |
|---|---|---|---|---|
| queue (run created → job start) | 4 | 496 | 4 | 6 |
| checkout (fetch-depth 0) | 13 | 15 | 13 | 15 |
| setup-python | 0 | 1 | 0 | 1 |
| pip install (no cache) | 7 | 10 | 8 | 12 |
| gate step: pre-plan / PR selection | 0.6 | 0.6 | 19.2 | 20.4 |
| gate step: parallel phase (4 workers) | 677 | 761 | 319 | 419 |
| gate step: serial tail | 144 | 149 | 35 | 75 |
| gate step: tail checks | 0.8 | 0.8 | 0.8 | 0.8 |
| gate step total | 822 | 911 | 386 | 479 |
| post-gate steps (adversarial, dark contract, guards, smokes, upload) | ≈17 | ≈19 | ≈33 | ≈68 (PDF smoke 20/52) |
| job wall | 904 | 955 | 449 | 551 |
| run wall (created → updated) | 950 | 1363 | 471 | 569 |
| merge → green cio on main | 951.5 | 1365 | — | — |
| other workflows' job wall, for comparison | 17–102 | 19–107 | 38–102 | 47–106 |

## Top contributors, ranked by seconds (median push run unless stated)

1. **Parallel test throughput: 2547 unit-seconds over 4 workers = 677 s wall** (p90 761). It covers about 908 test files in 336 pytest subprocesses at 94% pool utilisation.
2. **maturity_overnight_20260912: 779 s** of unit time (p90 876), 31% of the parallel work. That is 133 files in 15 units.
3. **Serial tail: 144 s** (p90 149) of strictly additive one-at-a-time units. goal_work_minter_ratchet alone is 54.7 s and the comms_gateway_phase0 chokepoint ratchet is 34.8 s.
4. **Main-branch concurrency queue: 0 s median but 422–814 s in 4 of 19 push runs.** These are #1531 668, #1533 814, #1536 422 and #1547 646. Each push to main waits for the previous main run to finish.
5. **Runner variance: about +400 s** on non-centralus runners. The gate step's median is 901.5 s there against 503.5 s on centralus, for the same file set.
6. ci_self_guards: 155 s, a single unit (23 files packed as 23 hint-seconds).
7. options_order_authorization: 128 s. This includes a second execution of test_options_broker_gates (80 s on its own).
8. Duplicate executions: 28 per run. The biggest are test_alarm_coverage.py (≈80 s, twice) and test_options_broker_gates (≈80 s, twice).
9. PR-only overhead: impact-map rebuild and selection take 19.2 s on every PR run, and PDF smoke takes 20 s median in PR runs vs 3 s in push runs.
10. Fixed setup: checkout 13 s + install 7 s + dark-contract guard 10 s ≈ 30 s. This is the same order as the fast workflows.

## Factual observations (no recommendations)

1. The ~15-minute figure is the push-to-main run: median job wall 904 s, run wall 950 s. PR runs take a median 449 s job wall (p90 551 s). Both exceed the "5 minutes wall clock" budget stated in the workflow comment.
2. 91% of the push job wall is the gate-runner step: 822 of 904 s. Setup (checkout, Python, install) is 20 s and comparable to the fast workflows. No step uses a cache.
3. CI runs with `jobs=4` (`os.cpu_count()` = 4 on ubuntu-latest), not 8. `jobs=8` appears only in local acceptance logs on the 20-CPU host.
4. The parallel phase is throughput-bound: utilisation is 0.93–0.95, and parallel wall is close to unit-sum / 4 (677 vs 637 floor). The longest single unit (155–170 s) is not the binding constraint in push runs.
5. The push profile runs about 908 test files (336 parallel units + 20 serial gates) on every merge. The workflow comment's "measured before 2026-09-25" baseline was 567 unique files.
6. Duration hints cover 48 files, were measured 2026-09-25, and are wrong in both directions. test_p26_shadow_autonomy has a 121.8 s hint and took 3.0 s in CI. test_options_order_authorization has a 2.0 s hint (default) and its unit took 150.6 s. Total hint estimate is 1563.5 s against 2887.2 s measured. The PR selector budgets in these hint-seconds: an estimate of 540 produced a median 1144 actual unit-seconds.
7. 25 test files are registered in more than one gate, giving 28 duplicate executions per push run, two of them about 80 s each.
8. Gate-step time is bimodal by Azure region: centralus runs median 503.5 s, other regions 901.5 s, on the same file set (s/file 1.5–1.8 vs 2.2–3.2). The cause is not visible in the logs.
9. Main-branch runs share one concurrency group with cancel-in-progress false. When merges land less than about 15 min apart, the next run waits for the previous one, 422–814 s observed. This was the reason the 14:01:17Z promote of 3b5c24856 was refused while every other push workflow for that SHA was already green.
10. The deploy gate needs a successful exact-SHA push run of cio-production-hardening-ci and agent-governance. agent-governance takes about 50 s. cio-hardening sets the merge-to-promotable time: median 951.5 s, max 1617 s, over 18 merges.
11. For every single-PR merge measured (18/18), the merge-commit tree equals the PR-head tree. The push run therefore re-tests content whose PR run passed, usually under a minute before merge. That PR run, though, executed only a selection (38–326 files), not the full set.
12. The `[select]` log line calls the push run the "post-merge full run". The push run is the `fast` profile, which runs every gate in parallel. The serial `full` profile (`cio-hardening-full`) runs only on schedule or dispatch, and its last scheduled run (37900362846, 10-09 07:40Z) failed.
13. PR selection rebuilds the impact map on every run (`map=rebuilt` 35/35, 10.6–21.7 s).
14. Locally, `ai_local_acceptance.sh` runs the same fast profile with `jobs=8` and a Postgres test DB. Gate wall was 447–637 s across 8 logs. There, a single 1-file unit took 208–360 s and was the longest unit; the same file took 3.0 s in CI.
