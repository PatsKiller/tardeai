# CI design audit: the CIO hardening process, end to end (2026-10-09)

This is a read-only audit. Nothing was changed and nothing was pushed. It was done in the detached worktree `/home/johnclaw/tradeai-wt-ciaudit-20261009` at origin/main `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`, which is the merge of PR #1547.

**Sources.** Every claim below cites one of these:
- the workflow YAML, scripts or docs, as `file:line`
- the GitHub API: runs, jobs, logs, branch protection, repo and user metadata
- the live deploy receipts in `~/.local/state/cio-phase2-exact-main/`
- the sibling timing measurement, `/home/johnclaw/CI_TIMING_EVIDENCE_20261009.md` (cited as **[T §n]**)

Timing numbers come from [T] wherever it has them. I did not repeat its measurements. Anything I could not confirm is marked **NOT VERIFIED**.

Scratch evidence is in `/tmp/claude-1000/-home-johnclaw/77a6de60-3513-40ce-9220-25d684930e93/scratchpad/`: `runs400.json`, `ag400.json`, `prs.json`, `c_<PR>.json`, `log_<run>.txt` and `nightly.txt`.

---

## Current-state architecture

### Path of one change today

```
author worktree
  ├─ pre-commit   .githooks/pre-commit:6        check_no_secrets.py (staged files only)
  ├─ local accept scripts/ai_local_acceptance.sh  fast profile = EVERY gate, jobs=8, + Postgres test DB
  │               (447–637 s of gate wall on the host [T §4])
  ├─ pre-push     .githooks/pre-push:120-125     check_no_secrets.py --tree (all 10,127 tracked files, ~10–11.5 s measured)
  ▼
PR opened / pushed
  ├─ cio-hardening (REQUIRED)   cio-production-hardening-ci.yml:28-224, profile=pr (selection), ubuntu-latest 4 vCPU
  │      job wall median 449 s / p90 551 s [T §1]
  ├─ agent-governance (REQUIRED) agent-governance.yml, ~48–55 s [T §1]
  ├─ release-readiness, aif-financial-senses, provider-cost (always run, NOT required)
  └─ ~12 path-filtered workflows (UI/Playwright, options, bitemporal, research …), NOT required
  ▼
strict=true (branch protection): the PR must contain main's tip → "update branch" → full PR CI again
  ▼
merge (merge commit; tree == PR head tree in 24/24 merges since 10-08, verified)
  ▼
push to main
  ├─ cio-hardening profile=fast: EVERY gate, same tree, job wall median 904 s / p90 955 s [T §1]
  │      main runs share one concurrency group, never cancelled → queue 422–814 s in 4 of 19 runs [T §5]
  └─ agent-governance, release-readiness, aif, provider-cost, financial-senses …
  ▼
deploy  scripts/cio_phase2_exact_main_deploy.sh
  ├─ prepare  :573-623  rsync prev release, overlay main, npm ci (if absent) + `npm run build` (design guards + tsc + vite),
  │                     stamp, pin check (:529-545), integrity manifest hook (:131-145)
  └─ promote  :639-691  grant preflight, conformance gate, then release_grant_preflight.py --ci-only:
                        REFUSES unless the exact-SHA push/main runs of cio-production-hardening-ci.yml AND
                        agent-governance.yml are completed+success (release_grant_preflight.py:52-55, 58-92). No polling.
  ▼
nightly 07:17Z  cio-hardening-full (serial isolation reference, ~1,913 s); red on 10-08 and 10-09
```

### The required gate in detail

**Branch protection** (from `gh api repos/PatsKiller/tardeai/branches/main/protection`):
- `strict: true`
- required contexts `cio-hardening` and `agent-governance`
- `enforce_admins: true`
- `required_pull_request_reviews: null`, so CODEOWNERS is advisory only (`.github/CODEOWNERS` header)
- No rulesets (`gh api .../rulesets` returns `[]`).
- The owner is a **User** account (`gh api users/PatsKiller` gives `"type":"User"`), and the repo is **PUBLIC**.

**Workflow** `cio-production-hardening-ci.yml`:
- Triggers are push to main, every PR (no path filter, `:13-16`), dispatch, and nightly.
- PR runs cancel superseded runs; main runs never do (`:23-25`).
- One job runs on `ubuntu-latest`, so `os.cpu_count()=4` and `jobs=4` ([T §3]; `_default_jobs` at `scripts/run_cio_hardening_ci.py:3724-3728` caps at 8).
- Steps:
  - checkout with `fetch-depth: 0` (`:46-48`)
  - setup-python 3.13 with no cache (`:50-53`)
  - pip install (`:55-71`)
  - the gate runner (`:73-82`)
  - nine tail steps: adversarial, dark contract, retention, line endings, test coverage, host paths, HTML/DOCX/PDF smokes (`:84-213`)
  - artifact upload

**Runner** `scripts/run_cio_hardening_ci.py` (4,102 lines):
- `GATES` (`:25-3640`) holds **329 gates, 914 path entries and 886 unique files**. The repo has 1,796 top-level `tests/test_*.py` files; 949 are named in `UNLISTED_BASELINE` (`scripts/check_test_coverage.py`) and do not run in this job.
- Profiles are described at `:3646-3676`:
  - `pr` is a test-impact selection within a 540 hint-second budget.
  - `fast` runs every gate in a `ThreadPoolExecutor` of pytest subprocesses, packed into ~25 s units by duration hints. Shared-state files then run one at a time in a "serial tail" (`plan_units` `:3754-3785`, `run_gates` `:3800-3841`).
  - `full` is the historical serial loop.
- Every profile ends with the tail checks (`:4035-4098`): docs index drift, committed manifest, candidate manifest.

**Selection** `scripts/lib/test_impact.py`:
- It builds a static reverse-import and path-reference map over `scripts/` and `tests/`. The map is cached in the git dir and keyed on **path+size+mtime** (`:94-102`, `:170-187`).
- Mandatory files: smoke gates (`config/ci_risk_tiers.json:6-19`), the named gates of each HIGH tier touched, changed tests, and distance-0 impacted tests (`:289-352`).
- Optional files are added nearest-first within `budget_seconds=540` (`config/ci_risk_tiers.json:4`). The rest is DEFERRED and listed (`run_cio_hardening_ci.py:3903-3937`).

### Measured envelope

All figures are from [T].

| What | median | p90 | max |
|---|---|---|---|
| PR `cio-hardening` job wall | 449 s | 551 s | 622 s |
| main push `cio-hardening` job wall | 904 s | 955 s | 959 s |
| **merge → exact-SHA green on main (promotable)** | **951.5 s** | 1,365 s | 1,617 s |
| agent-governance job wall | ~50 s | ~56 s | — |
| local acceptance gate wall (jobs=8) | 447–637 s across 8 logs | | |

---

## Root causes of the ~15 minutes

The ~15 minutes is the **push-to-main `fast` run**: job wall median 904 s, run wall 950 s [T §1]. The deploy gate waits on exactly that run (`release_grant_preflight.py:52-55`). Ranked by seconds:

1. **Too much CPU work for one 4-vCPU runner.** The full registered suite is **2,547 unit-seconds** in the median push run and 2,887 at p90 [T §2], spread over ~908 files in ~336 pytest subprocesses.
   - Pool utilisation is 0.93–0.95, so the parallel phase is throughput-bound: 2,547 / 4 = 637 s floor against 677 s actual [T §2].
   - The design doc assumed about 1,048 CPU-s and 567 files (`docs/ops/CI_FAST_CORE_20260925.md:17-22`; workflow comment `:34-36`). The suite has since grown to 886 unique files.
   - This is the dominant term: **~677 s**.
   - The structural cause is that everything runs in one job. Nothing shards across runners, and on a public repo standard runners are unmetered.
2. **The serial tail adds 144 s** (p90 149) [T §2], strictly after the pool.
   - The serial classifier is a regex over test *source text* (`run_cio_hardening_ci.py:3692-3702`, `:3740-3746`). At least **14 of the 26 serial files are false positives** (see Performance P2).
   - The two biggest serial units are real probe-planting ratchets: `goal_work_minter_ratchet` 54.7 s and `test_provider_chokepoint_ratchet` 34.8 s [T §2].
3. **One slow grab-bag gate.** `maturity_overnight_20260912` (133 files) is **779 s of unit time, 31% of the work** [T §2]. Its slowest files are `test_data_source_authority_20260913.py` (162 s) and `test_sot_phase9_quotes_prices_writers.py` (146 s) [T §2]. The tests themselves are slow. **Why** each is slow is **NOT VERIFIED**; no per-test profile was taken.
4. **The main concurrency queue.** `cancel-in-progress` is false on main (`cio-production-hardening-ci.yml:23-25`), so each main run waits for the previous one.
   - In 4 of 19 merges the queue was **422–814 s** [T §5].
   - It caused the live refusal at 14:01:17Z of promote `3b5c24856`: `post_merge_ci.json` shows `not_successful:.github/workflows/cio-production-hardening-ci.yml` while every other push workflow was already green.
5. **Runner variance.** centralus runners finish the gates step in a median 503.5 s, against 901.5 s in other regions, for the same file set [T §3]. The cause is **NOT VERIFIED** (hardware).
6. **Stale duration hints mis-pack work.** The hints cover 48 files and were measured once on 2026-09-25 (`config/ci_test_duration_hints.json`, commit `c41ecd6ae`); every other file defaults to 1.0 s (`run_cio_hardening_ci.py:3686`).
   - The total estimate is 1,563 s against 2,887 s measured [T §2].
   - `options_order_authorization` is hinted 2 s and takes 151 s, so it is scheduled late (plan position 117) and ends at +695 s.
   - `ci_self_guards` is 23 files packed as one 23-hint-second unit that takes 155–167 s [T §2].
   - This adds roughly 40–85 s of tail on push (761 − 677 = 84 s at p90), and it sets the **PR** critical path (see 8).
7. **Duplicate executions.** 25 files are registered in two to four gates, giving 28 extra executions per push run (my count from `GATES`; [T §2]).
   - `fast` does not dedupe. Only `test_impact.select` does (`test_impact.py:364-367`).
   - The expensive ones are `test_alarm_coverage.py` (~80 s, run twice) and `test_options_broker_gates_20260927.py` (~80–88 s, run twice).
   - That is **≈160–170 CPU-s, ≈40 s of wall**.
8. **What drives the PR-side ~7.5 minutes.**
   - The smoke set always includes `ci_self_guards` (`config/ci_risk_tiers.json:10`), which is one 135–167 s unit. That gives the PR job a floor of about 200 s even for a docs-only PR: #1547 took 255–278 s.
   - The impact map is rebuilt on every PR run (`map=rebuilt` in 35/35, 19.2 s) because its cache key uses mtime (`test_impact.py:94-102`) and CI keeps no cache.
   - PDF smoke takes 20 s median and 52 s p90 on PRs [T §1], even though it is `continue-on-error` (`cio-production-hardening-ci.yml:186-213`).
   - The budget is in hint-seconds, so "540" really ran 1,144 unit-seconds (2.1×) [T §2].

The end-to-end lifecycle is longer than the main run itself:
- PR CI: 449 s median
- plus strict-forced reruns: 6 of today's 20 PR runs were on main-merge heads (see Operational Efficiency O1)
- plus the re-test of the identical tree on main: 951.5 s median merge → green
- plus prepare's frontend build: its duration was not measured by me or by [T], **NOT VERIFIED**.

---

## Findings by category

The seconds-saved figures are estimates from the measured numbers above. "Wall" means the blocking path.

### Performance

**P1. The full suite runs in a single 4-vCPU job.**
- **Evidence:**
  - `cio-production-hardening-ci.yml:28-39` has one job and no `strategy.matrix`.
  - `jobs=4` appears in every run [T §3].
  - 2,547–2,887 unit-s per push [T §2].
  - The repo is PUBLIC (`gh repo view` → `"visibility":"PUBLIC"`), so standard runners carry no minute charge. The 2026-08-27 quota outage happened only while the repo was private (`docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md:1-6`).
- **Impact:** ~677 s of the 904 s job.
- **Recommendation:**
  - Shard the registered file list across N runners with a `strategy.matrix` of shard index and count, balancing by measured durations.
  - Inside each runner, use `pytest -n 4` (pytest-xdist) instead of one subprocess per unit. Workers then stay warm and the 336 interpreter and collection start-ups go away.
  - Add a final aggregate job that `needs:` all shards and reports the single required context.
- **Seconds saved:** with N=10, 2,887 / 40 ≈ 72 s of throughput. The floor becomes the slowest single file (162 s on a slow-region runner, 91 s on centralus [T §2]) unless that file is split at test level (`--dist load`) or fixed (P4). Expect **~550–700 s saved on push**, from 822 s down to ~120–200 s for the gates.
- **Risk / mitigation:**
  - Hidden ordering dependencies: the nightly serial run is already red on `maturity_overnight` (`nightly.txt`: `FAILED tests/test_hermes_join_internal_first_20260923.py::test_sentinel_one_spaced_and_lowercase_bind_guid`). Keep the nightly isolation run.
  - Concurrent-job limits: GitHub Free allows 20 concurrent jobs; the account plan is **NOT VERIFIED**. At N=10, two PRs at once saturate it. Pick N=6–8, or a shard count adaptive to the selection.

**P2. Serial-tail false positives.**
- **Evidence:** the patterns at `run_cio_hardening_ci.py:3692-3701` match text, not behaviour. I checked every matched line (`--list-plan` → 20 serial gates, 26 files). False positives:
  - `test_alarm_fires_scalp_alerts_20261005.py:86`: a string inside an assert.
  - `test_detectors_distinguish_states.py:35,56`: a skipif reason.
  - `test_runtime_state_survives_checkout.py:1`: the docstring.
  - `test_ci_fixture_immutability.py:147`: a skipif reason.
  - `test_docs_tip_hygiene_enforcer.py:27`: an assert string.
  - `test_alarm_fires_documents_20260922.py:152`: a comment.
  - `test_cio_ci_profiles_20260925.py:64-76`: a comment and a tmp_path write.
  - `test_telegram_chokepoint_ratchet.py:94`: plants into `tmp_path / "scripts"`.
  - git operations in temporary repos: `test_guard_push_auth.py:80-138`, `test_guard_push_scope_20260925.py:133-147`, `test_generated_file_merge_driver.py:21`, `test_agent_session_and_lease.py:184-186`, `test_agent_hooks_ci_hermetic.py:65-121`, `test_agent_worktree_identity.py:29-201`, `test_sop_attestation_base.py:32-42`, `test_ff_dev_tree_20260914.py:55-116`.
  - Five DB files (`psycopg2.connect`/`m2_conn`) are `importorskip`/skip in CI because CI installs no psycopg2 (`cio-production-hardening-ci.yml:57-63`).

  Genuine shared state:
  - `test_overnight_g3_docs_index.py:60-71` rewrites the committed `docs/INDEX.md`.
  - Four tests plant probe files into the real `scripts/`: `test_goal_work_minter_ratchet.py:84`, `test_provider_chokepoint_ratchet.py:43`, `test_scripts_lib_bootstrap.py:26`, `test_overnight_g2_import_normalise.py:186`.
- **Impact:** 144 s strictly additive on push; 35–75 s on PR [T §2].
- **Recommendation:**
  - Replace text matching with an explicit marker (`@pytest.mark.serial`) plus a CI lint that requires the marker for writes outside `tmp_path`.
  - Make the four ratchet probes hermetic: run the checker against a `tmp_path` copy or a `--root` override, or plant under a name the other tree-scans exclude.
  - Make the INDEX test operate on a copy.
- **Seconds saved:** **~110–140 s on push** (the tail moves into the pool and adds ~144 / 4 ≈ 36 s of throughput there) and ~25–60 s on PR.
- **Risk / mitigation:** a missed real collision shows up as flaky failures. Keep `full` nightly as the isolation reference, and add a CI test that fails if a non-serial test leaves files in `scripts/` or `docs/`.

**P3. Stale and partial duration hints.**
- **Evidence:** `config/ci_test_duration_hints.json` lists 48 files, measured 2026-09-25 under different conditions (its `note` says "psycopg2 absent, 4 workers", run locally). Examples: `test_p26_shadow_autonomy.py` is hinted 121.8 s and takes 3.0 s in CI; `options_order_authorization` is hinted 2 s and takes 151 s [T §2].
- **Impact:** `ci_self_guards` stays one 155–167 s unit, which is the PR critical path. Late starts add ~40–85 s of push tail. The PR budget actually runs 2.1× over.
- **Recommendation:** generate hints automatically from each main run's `[PASS] name (k files, Xs)` lines, or from pytest `--durations`/junit, and save them as an artifact or cache entry rather than a hand-committed file. Use per-file timings, not per-unit.
- **Seconds saved:** **~60–100 s per PR** (splits `ci_self_guards`, **NOT VERIFIED** until one of its 23 files is known to dominate) and **~40–85 s per push**.
- **Risk / mitigation:** hints only order work and never select it (`:3683-3685`), so there is no coverage risk.

**P4. A handful of slow tests dominate.**
- **Evidence:** [T §2] lists `test_data_source_authority_20260913.py` 162 s, `test_sot_phase9_quotes_prices_writers.py` 146 s, `test_overnight_g4_archive_mechanism.py` 109 s, `test_options_broker_gates_20260927.py` 88 s, `test_alarm_coverage.py` 80 s, `test_cio_operator_artifacts_20261003.py` 68 s. Several of these are repo-wide scanners: `test_overnight_g4_archive_mechanism.py:58` "tripwire quiet on live tree", and `test_alarm_coverage.py:16,32-66` imports `alarm_firing_coverage` and scans call sites.
- **Impact:** after sharding these set the floor (P1).
- **Recommendation:** profile with `pytest --durations=20`. Cache tree scans in session-scoped fixtures so a test module scans once rather than per test. Split files at test level under xdist.
- **Seconds saved:** brings the shard floor from ~162 s to roughly ~60–90 s. **NOT VERIFIED** without profiles.
- **Risk / mitigation:** caching a scan inside one session could hide a mid-session mutation. Scope fixtures per module where tests plant probes.

**P5. Duplicate registrations run twice in `fast`.**
- **Evidence:** 25 files and 28 extra executions (my count; [T §2]). `plan_units` iterates gate by gate with no dedupe (`:3766-3783`). `select` dedupes (`test_impact.py:364-367`) but only in `pr`.
- **Impact:** ≈160–170 CPU-s, ≈40 s of push wall.
- **Recommendation:** dedupe in `plan_units`, keep the first registration, and report the file under every gate name. Or add a lint forbidding duplicates.
- **Seconds saved:** **~40 s push**.
- **Risk / mitigation:** none for coverage. A gate's pass/fail attribution must still include the shared file.

**P6. PR selection rebuilds the impact map every run.**
- **Evidence:** `map=rebuilt` in 35/35 runs, `select_secs` median 19.2 s [T §2]. The cache key is size+mtime (`test_impact.py:94-102`), and checkout resets mtimes. The workflow has no `actions/cache`.
- **Recommendation:** key on content: `git ls-files -s` blob SHAs, which are already in the index at no cost. Persist the map with `actions/cache` keyed on `hashFiles('scripts/**/*.py','tests/**/*.py','config/**')` with restore-keys.
- **Seconds saved:** **~15–19 s per PR**.
- **Risk / mitigation:** a stale map would select too little. The content key makes staleness impossible by construction.

**P7. Setup overhead.**
- **Evidence:** checkout with `fetch-depth: 0` takes 13 s against 4–5 s for shallow-checkout workflows; pip without cache takes 7–8 s [T §1].
- **Recommendation:** use `fetch-depth: 1` plus `git fetch --depth=200 origin $BASE_REF` (the line-ending guard and the selector need only the merge-base), and `setup-python` with `cache: pip`. A pre-built container image would save only ~7 s, so it is low value.
- **Seconds saved:** **~8–12 s per job** (and per shard).
- **Risk / mitigation:** a shallow merge-base can be missing on long-lived branches. Fall back to `git fetch --unshallow` when `git merge-base` fails; the selector already falls back to `fast` when the base is unusable (`run_cio_hardening_ci.py:3872-3874`).

**P8. The optional PDF/DOCX smokes sit in the required job.**
- **Evidence:** both steps are `continue-on-error: true` (`cio-production-hardening-ci.yml:154-155`, `186-187`). PDF takes 20 s median and 52 s p90 on PRs, max 75 s [T §1].
- **Recommendation:** move both to the nightly job or a separate non-required job. The HTML smoke (`:120-152`) asserts a known regression (`578107.50%`) and is blocking, so it stays.
- **Seconds saved:** **~20 s median / ~50 s p90 per PR**.
- **Risk / mitigation:** nothing is lost, because these steps can never fail the check today.

### Security

**S1. No server-side secrets scan.**
- **Evidence:** `check_no_secrets.py` runs only from `.githooks/pre-commit:6`, `.githooks/pre-push:120-125` and `scripts/fast_check.sh:83`. No workflow calls it (grep of `.github/workflows/`). The hook can be skipped with `TRADEAI_SKIP_SECRETS_SCAN=1` (`pre-push:120`) or `--no-verify`, and it does nothing for commits made in the GitHub UI or by any agent without the hooks installed. The memory index already records "keys in git history; ROTATE".
- **Impact:** the guarantee is advisory on the path that matters, the public remote.
- **Recommendation:**
  - Add a blocking CI step that runs the same pattern set (`check_no_secrets.py:35-56`) over the PR diff, `git diff --name-only base...HEAD`, plus GitHub secret scanning and push protection (free on public repos; current enablement **NOT VERIFIED**).
  - Keep the local hook, where the `.env`-value match (`:59-92`) works because only the host has `.env`.
  - Make pre-push scan only the pushed range instead of all 10,127 files.
- **Seconds saved:** ~10 s per push locally. Measured `--tree` here: 9.9–11.6 s wall for 10,127 files.
- **Risk / mitigation:** a range scan misses a secret that was already committed earlier. Mitigate with a nightly `--tree` scan in CI, and the pre-commit staged scan stays in place.

**S2. Broker-write fences are not required for merge or for promote.**
- **Evidence:** `release-readiness.yml:36-43` runs `run_release_ci_equivalent.py --source-only`, `validate_schwab_write_policy.py --source-only` and `tests/test_no_broker_write_bypass.py`. It is not in the required contexts (`cio-hardening`, `agent-governance`) and not in `REQUIRED_PUSH_WORKFLOWS` (`release_grant_preflight.py:52-55`). It has been green recently (66/67 PR successes since 10-08), but nothing *enforces* it.
- **Impact:** a red broker-write fence can merge and can be promoted.
- **Recommendation:** fold these three steps into the blocking integrity job (I1 below), or add `release-readiness.yml` to both the required contexts and `REQUIRED_PUSH_WORKFLOWS`.
- **Seconds saved:** none. It adds ~100 s in parallel, so it costs no wall time.
- **Risk / mitigation:** none. This strengthens the controls.

**S3. Prepare silently falls back past the design guards and tsc.**
- **Evidence:** `cio_phase2_exact_main_deploy.sh:443-448`: if `npm run build` fails, it logs and runs `npx vite build` only. `npm run build` is the chain of design-token, ui-standards, contrast and ~35 node unit tests, then `tsc`, then `vite` (`apps/command-center-v3/package.json` `scripts.build`). The runbook says a fallback "is a defect to fix before promote, not a signal to proceed" (`docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md:139-141`), but the script does not enforce it.
- **Impact:** type errors and guard violations can ship. Today the frontend chain runs in CI only in path-filtered, non-required workflows (`cc-header-truth-ci.yml`, `cio-truth-gates-ui-validation.yml` and others).
- **Recommendation:** fail closed in prepare. Run `npm run build` in a required CI job whenever `apps/command-center-v3/**` or `scripts/check_*` UI guards change, using an inside-job diff check so the required context always reports. Cache with `setup-node cache: npm`, which the UI workflows already do. Upload `dist/` keyed by tree hash.
- **Seconds saved:** none in CI. It removes a post-merge failure mode.
- **Risk / mitigation:** prepare will now fail where it used to "succeed". That is intended.

**S4. Postgres-backed integrity tests never run in the required CI.**
- **Evidence:** CI installs no psycopg2 (`cio-production-hardening-ci.yml:57-63`), so the `m2_conn`/`psycopg2.connect` suites skip. For example, `test_bitemporal_correctness.py:98-100` skips with "isolated M2 docker/service :55432 not available", and `test_alert_delivery_recording_db.py:38` uses `importorskip`. Only `bitemporal-memory-correctness-ci.yml:23` and `options-lifecycle-ci.yml:54` define `services:`, and both are path-filtered. Local acceptance does create a DB (`ai_local_acceptance.sh:25-36`).
- **Impact:** schema and RLS guarantees, such as `test_suite3_rls_isolation_as_agent`, are verified only on the author's host.
- **Recommendation:** add one shard with a `postgres` service container and psycopg2 that runs every serial-DB file.
- **Seconds saved:** none. Cost is roughly +60–90 s in parallel (**NOT VERIFIED**).
- **Risk / mitigation:** service start-up flakiness. Use health-check options on the service.

**S5. Workflow self-modification.**
- **Evidence:** `pull_request` workflows run the workflow file from the PR's merge ref, and the push run uses the merged file too. The `ci_control_surface` HIGH tier exists (`config/ci_risk_tiers.json`, globs `.github/**`). CODEOWNERS is advisory because reviews are not required (protection `required_pull_request_reviews: null`).
- **Impact:** a PR can weaken its own required check. This is the same today, and it matters for any proposal that trusts PR-run evidence.
- **Recommendation:** enable required code-owner review for `.github/**`, `scripts/run_cio_hardening_ci.py`, `config/ci_*.json` and `scripts/release_grant_preflight.py`. This is an administrator action (`docs/governance/agent-standards/REPOSITORY_PROTECTION_ADMIN_ACTIONS.md`, per CODEOWNERS header). Alternatively, have the deploy preflight reject evidence from a run whose workflow blob differs from main's.
- **Risk / mitigation:** adds operator review latency on CI-surface PRs only.

### Reliability

**R1. agent-governance cancels main runs, which leaves SHAs unpromotable.**
- **Evidence:** `agent-governance.yml:11-13` sets `cancel-in-progress: true` for every event, including push to main. Since 10-01 there are **17 cancelled push/main runs**; examples are `13060dc3c` (10-08 00:55Z) and `772d6403a` (10-07 22:51Z), from `ag400.json`. The preflight requires `completed/success` for that exact SHA (`release_grant_preflight.py:88-89`).
- **Impact:** those SHAs cannot be promoted without a manual re-run.
- **Recommendation:** `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`, as cio-hardening already does (`:25`).
- **Risk / mitigation:** none.

**R2. Python version skew.**
- **Evidence:** cio-hardening uses 3.13 (`:53`) and agent-governance 3.12 (`agent-governance.yml:38`). The production venv that the deploy uses (`VENV_PYTHON`, `cio_phase2_exact_main_deploy.sh:19`) is **3.14.4** (`.venv/bin/python -V`).
- **Impact:** CI green does not prove the production interpreter.
- **Recommendation:** pin every workflow to the production minor version. Add a nightly matrix leg for the next version.

**R3. The nightly isolation reference is red and the alarm is saturated.**
- **Evidence:** `cio-hardening-full` failed on 10-08 and 10-09 (`gh run list --event schedule`). 10-09 failed on `maturity_overnight_20260912`: `FAILED tests/test_hermes_join_internal_first_20260923.py::...bind_guid`, so the test passes in `fast` and fails serially, which is an ordering dependency. Issue #1251 `ci-main-red` has been open since 2026-09-26 and has **59 comments**.
- **Impact:** a permanently open issue stops working as an alarm, and the isolation reference is not trustworthy.
- **Recommendation:**
  - Close or open one issue per failing *test id*, and auto-close it on green.
  - Fix the order dependency.
  - Make the nightly run upload junit so failures are attributable.

**R4. Misleading labels.**
- **Evidence:** `[select] DEFERRED to post-merge full run` (`run_cio_hardening_ci.py:3911`) and the profile comment "full: … runs on push to main" (`:3662-3664`) are wrong. Push runs `fast` (`cio-production-hardening-ci.yml:78-82`); `full` runs only on schedule or dispatch (`:231`) [T §2, obs. 12]. The docstring `test_impact.py:7` says the same.
- **Recommendation:** fix the wording. The semantics hold, because `fast` runs every gate.

**R5. The line-ending guard is vacuous on push.**
- **Evidence:** `check_line_endings.py --range origin/main...HEAD` (`:103`) logs `line-ending churn: none (0 files examined)` on push run 37939797812 against `(5 files examined)` on PR run 37939842296, since origin/main equals HEAD on a main push.
- **Impact:** none, because the PR run already checked it. It is just a no-op step on main.
- **Recommendation:** on push, use `--range ${{ github.event.before }}..HEAD`, or skip it.

**R6. A refused promote may consume a grant use.**
- **Evidence:** "a refused promotion may already have consumed its use" (`FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md:146`). `release_grant_preflight promote` (`cio_phase2_exact_main_deploy.sh:648`) runs **before** the CI check (`:653`).
- **Impact:** promoting too early, which is the common case given the 951 s wait, burns grant uses. The live example is the 14:01:17Z refusal.
- **Recommendation:** run `--ci-only` first and consume the grant only after CI evidence is OK.
- **Risk / mitigation:** the order changes, but no control is weakened.

### Scalability

**SC1. The suite grows linearly while the runner is fixed.** It went from 567 files on 09-25 to 886 unique files on 10-09 (workflow comment `:34-36`; `GATES` count). At about 2.9 CPU-s per file [T §3] this adds roughly 20 runner-seconds per day. Sharding (P1) with an adaptive shard count, for example `ceil(total_hint / 150 s / 4)`, keeps wall time flat as files are added.

**SC2. 949 unlisted test files sit outside the gate** (`UNLISTED_BASELINE` in `scripts/check_test_coverage.py`). Promoting them under a 4-vCPU single job is not feasible. Under sharding it is affordable: each 100 files at ~2.9 CPU-s/file costs about 290 CPU-s, or ~7 s on 40 workers.

**SC3. PR concurrency.** The day's burst was 36 PRs merged on 10-08. Each PR fires about 4–5 always-on workflows plus path-filtered ones. With sharding, the per-PR job count rises to N+3. Check the account's concurrent-job limit (**NOT VERIFIED**) before choosing N.

**SC4. Do not use self-hosted runners on the 20-core host.** The repo is public, so PR code would execute on the host that holds `.env`, broker tokens and production services. Stay on GitHub-hosted runners, larger ones if needed.

### User Experience (operator and agents)

**U1. The promote command does not wait.** It refuses and the operator re-runs (`cio_phase2_exact_main_deploy.sh:653-661`; [T §5]). Agents learn the wait by trial: merge → green is a median 951.5 s, max 1,617 s.
- **Recommendation:** add `promote --wait-ci <timeout>`. It polls `collect_push_checks` and exits only on success, failure or timeout, without consuming a grant (combine with R6).
- **Seconds saved:** none in CI, but it removes the manual retry loops.

**U2. PR feedback is 7.5 minutes against a stated 5-minute budget.**
- **Evidence:** the 5-minute budget is stated at `cio-production-hardening-ci.yml:29-31` and `CI_FAST_CORE_20260925.md:5`. The measured PR job wall is 449 s median and 551 s p90 [T §1]. The doc's projections were 1–3.7 min (`CI_FAST_CORE_20260925.md:105-111`).
- **Recommendation:** P3 + P6 + P7 + P8 together bring the PR job to about 300–350 s without changing the design. The proposed workflow below gets it to about 2.5–3.5 min.

**U3. Deferred tests are invisible until after merge.** In 26/35 PR runs, 342–477 files were deferred [T §2]. Authors learn of a failure only from issue #1251, which nobody can read as a signal (R3). Under the proposal, nothing is deferred.

### Operational Efficiency

**O1. strict=true reruns.** Measured from the merged PRs' commit lists, counting PR runs whose head SHA is a commit with two or more parents, i.e. a merge of main:

| day (UTC merge date) | PRs merged | PR cio-hardening runs | PRs with ≥1 merge-of-main commit | runs on a merge-of-main head | runner-s on those runs |
|---|---|---|---|---|---|
| 2026-10-08 | 36 | 57 | 16 | 10 | 4,401 |
| **2026-10-09 (today, to 14:00Z)** | **10** | **20** | **8** | **6** | **1,917** |

- This is a lower bound: rebase-and-force-push updates cannot be detected, and a main-merge pushed together with other commits is attributed to the other commit.
- Each forced rerun costs the author a PR job wall of about 449 s.
- **Merge queue is not an option as-is.** GitHub merge queue requires an organization-owned repository (GitHub docs; this repo's owner is `"type":"User"`). That availability was not probed via the API, **NOT VERIFIED**.
- **Recommendation:**
  - (a) Short term: keep strict, but make the PR check about 3 minutes, so each forced rerun costs about 3 minutes instead of 7.5.
  - (b) Medium term: transfer the repo to a free organization (public) and use the merge queue, which rebuilds once on the queued merge group and promotes that exact tree. Or drop strict and rely on the tree attestation plus post-merge verification below.
- **Seconds saved:** today, 6 × (449 − 180) ≈ **1,600 s of author wait**.
- **Risk / mitigation:** dropping strict without a merge queue lets semantically conflicting PRs land. Keep the post-merge run as a backstop.

**O2. The identical tree is tested three times.**
- (1) Local acceptance runs every gate (`ai_local_acceptance.sh:17,207`), 447–637 s [T §4].
- (2) PR CI runs a selection.
- (3) Main CI runs every gate on a tree that is **byte-identical to the PR head in 24/24 merges since 10-08**. I verified this with `git rev-parse <merge>^{tree}` against `<merge>^2^{tree}` for every first-parent merge since 10-08 ([T §5] confirms 18/18 with timings).
- The only reason main CI is needed today is that the PR run is a *selection*. `release_grant_preflight.py:50` says "PR runs do not execute the same test profile". Once the PR runs the full suite (P1), the main run is redundant for content.
- **Recommendation:** see the proposed workflow, stage 3.
- **Seconds saved:** **~950 s median off merge → promotable**.

**O3. The frontend is built for the first time at deploy.** `npm run build` runs in prepare (`:604`, `:429-449`). For non-UI PRs nothing builds the frontend in CI. Build in CI only when UI inputs change, cache `node_modules` via setup-node, and let prepare reuse `dist/` when the tree hash matches. Seconds saved are **NOT VERIFIED**; the prepare build time was not measured.

**O4. Local acceptance duplicates CI.**
- `ai_local_acceptance.sh` runs the full `fast` profile on the host: 447–637 s of gate wall [T §4] plus a ~38–91 s release proof.
- AI_WORK_POLICY §5 mandates local-first (`AI_WORK_POLICY.md:162-170`, §5). The rationale was Actions cost, and §18 asks for "avoiding duplicate test suites" (`:478-492`). Hosted minutes are unmetered on this public repo.
- **Recommendation:** after P1 lands, make `fast_check.sh` (the impacted subset, 14–63 s per `CI_FAST_CORE_20260925.md:113-120`) the default local gate. Make the full local run optional, except for the DB suites until S4 lands.
- **Seconds saved:** **~400–550 s per change of author time**.
- **Risk / mitigation:** this is a policy change (AI_WORK_POLICY.md), so it needs the operator. Keep the pre-push secrets and policy hooks.

**O5. Workflows overlap.**
- agent-governance runs 8 test files that are also in cio `agent_governance_sop`: `test_agent_session_and_lease.py`, `test_agent_hooks_ci_hermetic.py`, `test_agent_worktree_identity.py`, `test_agent_clients_registry.py`, `test_agent_file_lease_canonical.py`, `test_agent_changed_file_quality.py`, `test_sop_attestation_base.py`, `test_sop_evidence_integrity.py` (my cross-reference script).
- `options-lifecycle-ci.yml` runs 7 files and `cc-header-truth-ci.yml` 4 files that are also in `GATES`.
- `run_release_ci_equivalent.py --source-only` runs in both `release-readiness.yml:37` and `aif-financial-senses-integration-ci.yml:62`.
- These run in parallel with each other, so they cost runner minutes, not wall time.
- **Recommendation:** one owner per test. Remove the 8 duplicates from `GATES` (agent-governance remains required), or from agent-governance.
- **Seconds saved:** ~0 s of wall and a few runner-minutes per PR.

---

## Quick wins (<24h)

Each item is small, local to one file, and weakens no control.

| # | Change | Where | Est. saved (blocking path) | Control impact |
|---|---|---|---|---|
| Q1 | `cancel-in-progress` only on PRs in agent-governance | `agent-governance.yml:13` | prevents unpromotable SHAs (17 since 10-01) | none |
| Q2 | Cancel superseded **main** cio-hardening runs. Prepare requires HEAD == origin/main tip (`cio_phase2_exact_main_deploy.sh:51-70`), so only the tip SHA is ever promotable | `cio-production-hardening-ci.yml:25` → `cancel-in-progress: true` | queue of 422–814 s in 4/19 merges [T §5] | the tip run covers all intermediate commits cumulatively; per-SHA bisect evidence is lost, and the nightly plus tip runs remain |
| Q3 | Regenerate duration hints from the latest CI per-unit data; refresh weekly | `config/ci_test_duration_hints.json` (`--write-duration-hints`, `run_cio_hardening_ci.py:3952-3980`, on a 4-worker setting) | PR ~60–100 s (splits `ci_self_guards`, **NOT VERIFIED**); push ~40–85 s | none (hints only order work, `:3683-3685`) |
| Q4 | Dedupe files across gates in `plan_units` | `run_cio_hardening_ci.py:3766-3783` | push ~40 s | none |
| Q5 | Move PDF and DOCX smokes to the nightly job | `cio-production-hardening-ci.yml:154-213` | PR ~20 s median / ~50 s p90 | none (already `continue-on-error`) |
| Q6 | Shallow checkout plus base fetch; `cache: pip` | `:46-53` | ~8–12 s | none |
| Q7 | Content-keyed impact map plus `actions/cache` | `test_impact.py:94-102`, workflow | PR ~15–19 s | none |
| Q8 | Remove the 14+ serial false positives: an explicit `serial` marker list or tightened regexes | `run_cio_hardening_ci.py:3692-3717` | push ~25–40 s (the small serial units move into the pool) | none; nightly `full` stays |
| Q9 | Run the CI check before consuming the release grant | `cio_phase2_exact_main_deploy.sh:648-653` | stops burned grant uses | equal or stronger |
| Q10 | Make the prepare frontend fallback fail closed | `cio_phase2_exact_main_deploy.sh:443-448` | 0 | **stronger** (S3) |
| Q11 | Pre-push secrets scan on the pushed range; add a CI diff-scan step | `.githooks/pre-push:120-125`, workflow | ~10 s per push locally | **stronger**: server-side enforcement is added (S1) |

Combined effect of the quick wins:
- PR job: from ~449 s to about **~300–340 s** (Q3, Q5, Q6, Q7).
- Push job: from ~904 s to about **~760–800 s** (Q3, Q4, Q6, Q8).
- Merge → promotable: the p90 should fall from 1,365 s toward the job wall plus small queue, about **~800–850 s**, because Q2 removes the queue spikes.

---

## Medium-term (1–3 weeks)

1. **Shard the full suite and run it on every PR** (P1, P2, P4, S4).
   - `strategy.matrix.shard: [0..N-1]` with N≈8.
   - Inside each shard, run `pytest -n 4 --dist loadfile`, splitting the very slow files with `--dist load`.
   - Assign shards by greedy LPT on auto-refreshed durations.
   - Add one Postgres-service shard for the `m2_conn`/psycopg2 files.
   - The `pr` selection then becomes a *fast-feedback* job instead of the merge gate. Nothing is deferred any more.
   - Estimated gates wall per shard is ~90–170 s, depending on runner region and how far P4 gets.
2. **Make the four probe ratchets and the INDEX test hermetic** so that the serial tail disappears (P2). Saves ~110–140 s.
3. **Use one aggregate required context, `ci-gate`.** It is a tiny job that `needs:` every shard, the integrity rails, agent-governance-equivalent steps, and the frontend job when relevant. It fails if any of them failed or was skipped unexpectedly. Branch protection then requires `ci-gate` plus `agent-governance`, and adding a shard no longer touches branch protection (AI_WORK_POLICY §18 "one aggregate required gate", `AI_WORK_POLICY.md:482`).
4. **Accept tree-attested PR evidence at promote** (O2). Change `release_grant_preflight.py` so that a candidate main SHA `M` is accepted when all of the following hold:
   - (a) `M` is a merge commit and `git rev-parse M^{tree}` equals the tree recorded by a **completed+success** required PR run of the same workflow paths. The PR run records `git rev-parse HEAD^{tree}` of `refs/pull/N/merge` into its job summary or attestation artifact; agent-governance already emits a `SopRuntimeAttestation@v1` artifact, `agent-governance.yml:107-130`.
   - (b) That PR run executed the **full** profile, not `pr`.
   - (c) The workflow file blobs in that run equal those at `M`.
   - (d) The run is the latest attempt for that tree, keeping the existing "a later run/attempt supersedes" rule (`release_grant_preflight.py:73-77`).
   - Otherwise fall back to today's push/main rule. Main push runs continue as a post-merge backstop that can trigger the existing ci-main-red alarm and an operator rollback.
   - This touches deploy and release semantics (HIGH tier `deploy_and_release`), so it needs operator approval.
   - Saves **~950 s median, up to 1,617 s,** of merge → promotable.
5. **Required frontend build job** (S3, O3): path detection inside the job, `setup-node cache: npm`, and `npm run build`. Upload `dist/` with its tree hash. Prepare verifies the hash and reuses the artifact, or rebuilds and compares `index.html` and the asset hashes.
6. **Profile and fix the slow files** (P4), starting with `test_data_source_authority_20260913.py`, `test_sot_phase9_quotes_prices_writers.py`, `test_overnight_g4_archive_mechanism.py`, `test_options_broker_gates_20260927.py`, `test_alarm_coverage.py` and the `ci_self_guards` members.
7. **Align Python versions** to the production venv's minor version (R2). Make release-readiness's broker fences blocking (S2).
8. **Fix the nightly order dependency, and restructure ci-main-red into one issue per failing test with auto-close** (R3).

---

## Long-term (1–3 months)

1. **Content-addressed test-result cache**, the Bazel or Pants model applied to pytest.
   - Key = sha256(test file + the transitive import closure from the existing impact map + `config/**` it references + Python version + pinned deps + a CI image digest).
   - A shard skips a file whose key already has a recorded **pass** from a trusted run (main or a required PR run) and logs `CACHED <key>`.
   - Gives the largest saving on typical PRs, since most of the suite is unaffected by a given change: likely 70–90% of files on a median PR. That estimate is **NOT VERIFIED**; it needs a replay over the last 50 PRs using the impact map.
   - **Preconditions:** hermetic tests. Tests that read the clock, the network or files outside their closure must be marked uncacheable. The tree-wide ratchets that scan *all* of `scripts/` must include the whole tree in their key, so they always run.
   - Keep a no-cache full run nightly to detect cache poisoning or under-keying.
2. **Merge queue.** Move the repo to a free GitHub organization (public), replace `strict` with a merge queue, and require `ci-gate` on `merge_group`. The queue tests the exact merge tree once. The deploy accepts the `merge_group` run, whose head SHA becomes main's SHA when merged without a re-merge commit; this needs to be confirmed per configuration, **NOT VERIFIED**. This removes manual "update branch" loops (O1).
3. **Pre-built CI image** (a container with Python, pinned deps, ruff and node): saves about 7–15 s per job. It is low priority compared with the items above but useful once N shards multiply setup costs.
4. **Larger GitHub-hosted runners** (8–16 vCPU) for the shards, if concurrency limits bind. This costs money even on a public repo (**NOT VERIFIED** for this account's plan).
5. **Required-checks minimisation:** two required contexts, `ci-gate` and `agent-governance`, with every other always-on workflow either folded into `ci-gate` or explicitly advisory.

---

## Proposed optimized workflow (target 2–3 minutes for the blocking path)

### Stage 1: local (author; not a remote gate)
- pre-commit: secrets on staged files (unchanged).
- `fast_check.sh`: ruff on changed files, secrets on the diff, coverage registration, host paths, docs index, impacted tests at budget 120. Measured 14–63 s (`CI_FAST_CORE_20260925.md:113-120`).
- pre-push: authorization, push budget, and a secrets scan of the **pushed range** (about 1 s instead of 10 s).
- Full local acceptance becomes optional. It remains required only for DB suites until the Postgres shard exists.

### Stage 2: PR blocking path (required `ci-gate` + `agent-governance`). All jobs start in parallel; the wall is the slowest job.

| Job | Contents (blocking) | Cached/reused | Target wall |
|---|---|---|---|
| **I1 integrity rails** | Secrets diff-scan (new, S1); `check_dark_contracts --fail-on-new`; `check_retention_policy`; `check_line_endings`; `check_test_coverage`; `check_test_host_paths`; `check_data_source_authority` + `render_source_of_truth --check` (one-writer / SoT); `validate_schwab_write_policy --source-only` + `test_no_broker_write_bypass` + `run_release_ci_equivalent --source-only` (broker/2FA fences, now blocking, S2); docs-index drift + `cio_release_manifest check-committed`; adversarial suite; HTML report smoke | pip cache, shallow clone | ~60–100 s |
| **agent-governance** (unchanged, required) | hooks, policy state, leases, SOP evidence, attestation | pip cache | ~50 s |
| **T0..T7 test shards** | every registered `GATES` file (no deferral), `pytest -n 4`, durations-balanced; HIGH-tier gates (guard, broker, memory_sql, deploy, schedule, CI surface) included by construction | pip cache; content-keyed impact/duration data; later the result cache (long-term 1) | ~120–180 s |
| **T-db shard** | `m2_conn`/psycopg2 files with a `postgres` service | — | ~90–150 s (**NOT VERIFIED**) |
| **F1 frontend** (only if UI inputs changed; reports success otherwise) | `npm run build` = design guards + UI unit tests + tsc + vite; upload `dist/` keyed by tree hash | `setup-node cache: npm` | **NOT VERIFIED**: no CI timing for the full chain was taken here |
| **ci-gate** | `needs:` all of the above, fails on any failure or unexpected skip | — | ~5 s |

**Async (non-blocking, alarmed):**
- nightly `full` serial isolation run
- PDF and DOCX smokes
- Playwright e2e suites (already path-filtered and non-required)
- nightly secrets `--tree` scan
- the post-merge main run (below)

### Stage 3: merge → promote
1. Merge: strict for now, merge queue later. The merge tree equals the attested PR tree (24/24 measured).
2. Promote, in this order:
   - (1) the CI check with tree-attested PR evidence (medium-term 4), or the push/main run as fallback
   - (2) then the grant (R6)
   - (3) conformance gate
   - (4) activation
   - (5) health check with automatic rollback (`cio_phase2_exact_main_deploy.sh:663-676`, already present)
3. Prepare reuses the CI `dist/` when the tree hash matches; otherwise it builds and fails closed (S3). Pin check and integrity manifest are unchanged (`:529-545`, `:131-145`).
4. The main push run of the full suite continues **asynchronously** as a backstop. It runs only for the tip (Q2). On red it raises the ci-main-red alarm and recommends `rollback`. I do **not** recommend *automatic* rollback on an async test failure: a release rollback does not undo DB migrations or state writes done by the new release (`link_pipeline_data` shares data directories, `:195-405`). The rollback stays a gated operator action.

### Where each moved or removed check keeps its guarantee

| Check | Today | Proposed | Guarantee kept by |
|---|---|---|---|
| Secrets (patterns) | local hooks only; bypassable | local hooks + **blocking CI diff scan** + nightly tree scan | CI step (new); stronger |
| Secrets (`.env` actual values) | pre-commit / pre-push | unchanged (needs the host `.env`) | local hook |
| Pre-push tree scan | all 10,127 files each push | pushed range + nightly tree | pre-commit staged scan + CI diff scan + nightly tree |
| Authority / guard rails (`guard_push_auth`, `governance_section_zero_parity`, agents policy state) | required (smoke + agent-governance) | required (shards + agent-governance) | unchanged |
| Broker / 2FA fences (`validate_schwab_write_policy`, `no_broker_write_bypass`, `options_order_authorization`, `gog_broker_approval`, `protection_truth`) | release-readiness not required; the cio gates only if selected or HIGH | **all blocking** in I1 and the shards | stronger |
| Dark contract, retention, coverage, host paths, line endings | required tail steps | I1 (blocking) | unchanged |
| One-writer / data_source_authority / SoT docs | cio gates + local only (`render_source_of_truth --check` is local only, `ai_local_acceptance.sh:220-221`) | I1 (blocking) | stronger |
| Schema / memory / RLS (Postgres) | local only (CI skips) | **T-db shard (blocking)** | stronger |
| Docs index + release manifest | runner tail (`:4035-4098`) | I1 | unchanged |
| Exact-SHA evidence at promote | push/main run of the identical tree | tree-attested full PR run (main run as fallback) | tree equality + same workflow blobs + full profile, verified by the preflight |
| Frontend guards + tsc | prepare (with a silent fallback) | blocking CI when UI changes + fail-closed prepare | stronger |
| Pin check, integrity manifest, BUILD_SHA, grant, conformance, health + rollback | prepare / promote | unchanged | unchanged |
| Serial isolation reference | nightly | nightly | unchanged |
| PDF/DOCX smokes | optional, inside the required job | nightly | never blocking today either |

### Honest statement of what cannot meet 2–3 minutes, and why

- **The full suite on one 4-vCPU runner cannot.** 2,547–2,887 CPU-s at full utilisation needs at least 637–722 s [T §2]. Without sharding (or the result cache) there is no path to 3 minutes. Hint fixes and serial-tail fixes alone reach about 12–13 minutes on push.
- **The single slowest test file sets a floor.** `test_data_source_authority_20260913.py` takes 162 s on a slow-region runner (91 s on centralus) [T §2]. Until it is profiled and sped up, or split across xdist workers at test level, a sharded run cannot beat about **2.5–3.2 min** of job wall on slow-region runners (162 s + ~25 s setup + ~10 s collection). That is the honest p90. Median runs on fast regions should land near 2–2.5 min.
- **Runner-region variance is about 1.8×** [T §3] and outside our control on hosted runners. A 3-minute *median* is realistic; a 3-minute *p90* needs P4 done.
- **The Postgres shard and the frontend build are NOT VERIFIED.** Service start-up and `npm ci` + build could each take 1.5–3 min. If the frontend build exceeds 3 minutes it should run only when UI inputs change, which is the proposal. Its p90 on UI PRs may exceed 3 minutes.
- **Merge → promote cannot reach 2–3 minutes if the deploy keeps requiring a fresh push/main run of the full suite.** Even fully sharded, that adds another ~2.5–3 min after merge plus queueing. Only tree-attested PR evidence (medium-term 4) makes promote-ready about equal to "PR green".
- **strict=true without a merge queue** still forces a full PR rerun whenever main moves. That costs about 2.5–3 min per update under the proposal, against 7.5 min today. Only a merge queue (organization-owned repo) removes it.

---

## Risks and trade-offs

1. **Sharding exposes order and shared-state dependencies.** The nightly `full` run is already red on one (R3). *Mitigation:* fix before switching; make the serial marker explicit (P2); keep the nightly isolation run; rerun a shard once and flag flaky tests rather than letting them pass silently.
2. **Tree-attested evidence widens trust to PR-run artifacts.** A PR can edit its own workflow (S5). *Mitigation:*
   - Require identical workflow blob hashes between the attested run and `M`.
   - Require the full profile.
   - Make the `.github/**` and preflight paths code-owner-required.
   - Keep the push/main run as an async backstop and a fallback path.
   - The attestation is only as strong as GitHub's run metadata, the same trust root as today's preflight (`release_grant_preflight.py:95-135`).
3. **Cancelling superseded main runs** (Q2) loses per-SHA post-merge evidence for intermediate commits. *Mitigation:* the deploy only promotes the tip (`require_head_is_origin_main`, `cio_phase2_exact_main_deploy.sh:51-70`); the tip run's tree contains every intermediate change; the nightly run covers isolation.
4. **A content-addressed result cache can under-key and skip a test that should have run.** *Mitigation:* key on the import closure plus referenced configs plus the environment; tree-scanning ratchets are never cacheable; run a weekly no-cache full run; report a cache hit as `CACHED`, never as `PASS`.
5. **Relaxing local acceptance** (O4) shifts validation to GitHub. AI_WORK_POLICY's local-first rule (`AI_WORK_POLICY.md:162` and §5–6) was a cost control from the private-repo era (`GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md:6`). The repo must stay public (memory: "REPO PUBLIC POLICY — NEVER flip private"); if it ever went private, the cost model inverts. This is an operator policy decision.
6. **More jobs per PR** (N+3) can hit the account's concurrent-job cap during bursts (36 PRs on 10-08). *Mitigation:* moderate N, an adaptive shard count, and cancel-superseded on PRs (already set).
7. **Automatic rollback on async failures** is deliberately *not* proposed. Release rollback does not revert shared data or migrations, so a quality signal should alarm and an operator should roll back.
8. **Merge queue requires an organization transfer.** This affects URLs, tokens, the `gh` remotes used by `collect_push_checks` (`release_grant_preflight.py:103-108`, which parses `owner/repo` from the origin URL), and any hard-coded `PatsKiller/tardeai` references. *Mitigation:* plan it as its own tranche; GitHub redirects the old URLs.

---

### Appendix: other evidence used

- **Serial plan:** `python3 scripts/run_cio_hardening_ci.py --list-plan` → `parallel_units=340 serial_gates=20`, the same as the CI log `[plan] profile=fast jobs=4 parallel_units=340 serial_gates=20` (run 37939797812).
- **Main run timeline** (37939797812): the parallel pool ended at +761 s, the serial tail ran from +761 to +911 s, and the tail checks finished at +912 s. The serial units, in order: goal_work_minter 56.6 s, comms_gateway_phase0 35.9 s, alarm_document_sites 14.3 s, telegram_chokepoint 11.0 s.
- **PR #1547 run** (37939842296): `changed=5 tier=high ... selected_files=115 ... deferred=0 select_secs=19.2`. The longest unit was `ci_self_guards (23 files, 135.9s)`.
- **Live promote refusal:** `~/.local/state/cio-phase2-exact-main/deploy_receipt.json` has `extra: post_merge_ci_refused` at 2026-10-09T14:01:17Z for `3b5c24856`. Prepare had created `/home/johnclaw/trade-ai-releases/portfolio-server/3b5c24856-main-exact-phase2-20261009-095833`.
- **Repo merge settings:** `allow_auto_merge: true`, `allow_update_branch: true` (`gh api repos/PatsKiller/tardeai`).
