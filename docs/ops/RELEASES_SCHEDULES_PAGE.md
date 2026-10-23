# Releases & schedules — Command Center page and read model

```
Status:      DRAFT (branch feat/releases-schedules-20261022; not served until a release carries it)
as_of:       2026-10-22T16:10:00-04:00
Measured at: base origin/main b9804fa57; one read-only local run of build() against the host at 15:52 ET (below)
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Approval:    operator 2026-10-22 ("perfect approved"), mockup gate3 Pipeline.dc.html
```

## What it is

One page, **System → Releases & schedules** (`/v3/system/releases`, NavRail Ops → "Releases & Schedules"), answering:
what is serving, what releases next and when, what shipped, what failed, and what n8n and host cron run in the next
three hours. It is backed by one read-only projection, `GET /api/v2/ops/releases-schedules`
(`scripts/lib/releases_schedules_view.py`), wired in `scripts/api_v2.py` `handle()` right after the release-train view
block (exact path, GET only, 405 otherwise; it shadows no other route).

There is **no control** on this page. STOP RELEASES and the train's own queue / trains / events views stay on
Coordination → Release train (`ReleaseTrainTab.tsx`, `ReleaseStopControl.tsx`); that tab now carries a link to this
page. The Home release-train card is unchanged. No new store, no new POST.

## Response (`ReleasesSchedules@v1`)

Every section is a Field envelope `{value, as_of, freshness: OK|STALE|UNAVAILABLE, source, reason, age_s}`
(`release_train_view.field` plus `age_s`). UNAVAILABLE always has `value: null` and a reason; the page renders
"UNAVAILABLE · reason", never 0, empty or green. Each source is read in a worker with its own deadline (4 s total,
pattern of `scripts/lib/release_train_view.py`); the response is cached 30 s.

| Section | Source (existing reader reused) | Notes |
|---|---|---|
| `serving` | `~/trade-ai-releases/portfolio-server/CURRENT` via `exact_release_receipt.observed_identity` (BUILD_SHA = GIT_SHA = SOURCE_COMMIT), `ACTIVE_RELEASE` / `EXPECTED_RELEASE`, `~/.local/state/cio-phase2-exact-main/deploy_receipt.json` | STALE when a pin file does not name CURRENT. `since` is the deploy receipt's `at` when it names the served SHA, else the CURRENT symlink mtime (labelled). |
| `next_release` | canonical checkout `refs/remotes/origin/main` (local `git rev-parse` / `git log`; **no fetch, no network**); PRs since serving via `release_window.prs_from_messages`; CI from `post_merge_ci.json` only when it names the same SHA | STALE when `.git/FETCH_HEAD` is older than 6 h. Exact-SHA CI for main HEAD is otherwise **UNAVAILABLE**: no cached source exists and GitHub is never called from the request path. |
| `windows` | `config/release_train_policy.json` + `release_train_view.upcoming_windows`; state and reason from `release_train_window.readiness_view` + `decide` (STOP latch, armed, delegation, shadow, window enabled) | States LIVE / SHADOW / OFF / STOPPED; last shadow tick per slot. |
| `queue` | `release_train_view.build_queue` (Postgres `release_queue`) + the PR-hygiene census receipt (`release_train_census`) | Each open PR with its census bucket as "why not riding". |
| `history` | `~/.local/state/cio-phase2-exact-main/release_pins/{apply,rollback}-*.json` (ReleasePinReceipt@v1), SHA from the target's `BUILD_SHA` (else the dir-name prefix, labelled), PRs per release from first-parent `git log` between consecutive releases, verify from `deploy_receipt.json` | Verify is shown only for the release the deploy receipt names; older releases say "not retained" (the receipt is overwritten on every operation). |
| `release_errors` | `release_window/windows/*.json` outcomes other than RELEASED / NO_CHANGE, `release_pins/rollback-*`, a not-ok deploy receipt, non-success checks in `post_merge_ci.json`, the STOP latch (last 48 h) | Not covered, stated in the payload: CI timeouts / cancellations on main for SHAs that were never deployed. |
| `n8n_today` | `<state root>/data/governance/n8n_coordination_ledger.sqlite`, opened `mode=ro` + `PRAGMA query_only`, `runs` and `dead_letters` | Day = America/New_York, by `requested_at`. Totals by mode/state, failures (reason only; receipt env names never leave the ledger), lock skips, unreleased dead letters, busiest 10 lanes. |
| `timeline` | host crontab (`crontab_snapshot.read_crontab`: `crontab -l`, else its fresh snapshot) including `# PAUSED <date> <note> <line>`; `config/lane_registry.json` (n8n `cadence`, dispatcher `stage`); relay live list names (`check_registry_runtime_truth.read_live_lanes`); fires from `cron_schedule.fires_between` | Next 3 h. A schedule firing more than 4 times becomes one "every N min" recurring row. Cron rows have no last-run (not in the ledger); n8n rows show today's last ledger run. |
| `kpis` | derived | A KPI over an UNAVAILABLE section is null → "UNAVAILABLE". |

Frontend: `apps/command-center-v3/src/lib/releasesSchedules.ts` (pure projection; test
`releasesSchedules.test.ts`, in the build script) and `src/pages/ReleasesSchedules.tsx` (design tokens only). A
response older than 5 minutes, or a failed refresh, marks every section STALE with its value kept and labelled.

## Measured at build time `[VERIFIED]` 2026-10-22 15:52 ET

One local, read-only `build()` on the host (queue `db_query` stubbed): serving `82180caba` (pins agree, since
15:11Z deploy receipt); main HEAD `b9804fa57`, 11 commits / 11 PRs ahead, CI UNAVAILABLE ("post_merge_ci.json names
82180caba, not main HEAD"); 18:00 window SHADOW ("train not armed (simulate only)"); ledger today 2,434 runs
(1,345 live, 1,089 dry_run), 3 errors, 21 lock skips, 58 unreleased dead letters; crontab 337 active + 17 paused
lines; relay live list 70 lanes; history newest three: `82180caba` (8 PRs, #1914–#1921, LIVE · VERIFIED),
`c81eb463c` (#1911–#1913), `4104effb9` (#1910); census UNAVAILABLE (`no_receipt`: no
`pr-hygiene-audit_last.json` under the state root); release errors: none in the sources read.

## Pre-build check (AGENTS.md §13.5)

Searched for readers of `ACTIVE_RELEASE`, `build-meta.json`, `deploy_receipt`, `post_merge_ci`,
`n8n_coordination_ledger`, `crontab -l`, `PAUSED`, `n8n-live-lanes.env`, release windows and the census. Found and
**reused**: `exact_release_receipt.observed_identity`, `release_window.prs_from_messages`,
`release_train_view.{run_probes, field, upcoming_windows, read_stop, build_queue, _load_policy, _receipt_titles}`,
`release_train_window.{readiness_view, decide}`, `crontab_snapshot.read_crontab`, `cron_schedule.{cron_fields,
fires_between}`, `check_registry_runtime_truth.read_live_lanes`. Not reused, with reason: `n8n_coordination_projection`
(no per-day aggregation; this view needs today's counts), `data_broker/n8n_today` (reads run receipt files, not the
ledger the operator asked for — both stay available, on Coordination → n8n today), `options_desk_accuracy.
paused_from_crontab` (one lane at a time; this view lists every paused line, same grammar). No cached main-HEAD CI
reader exists; that is reported UNAVAILABLE rather than adding a GitHub call.

## Tests

`tests/test_releases_schedules_view_20261022.py` (gate `config/ci_gates/RELEASES_SCHEDULES_VIEW.json`): hermetic —
every path under `tmp_path`, `TRADEAI_STATE_ROOT` = tmp, git / crontab / readiness injected, queue DB stubbed.
Covers every section, UNAVAILABLE-is-null for each, window states (SHADOW / STOPPED / OFF), paused crontab parsing,
ledger day boundary, env-name redaction, route GET-only + cache, wiring order in `api_v2.handle`, and the git runner
refusing non-read subcommands.

## Open gaps

- Main-HEAD exact-SHA CI and CI timeouts / cancellations on main are UNAVAILABLE until a cached, read-only CI source
  exists (the release-window runner and the deploy query GitHub at release time only).
- Verify / rollback detail for releases older than the latest operation is not retained by the deploy script.
- Refused promotes inside the manual deploy script (for example an exact-SHA CI refusal before retry) leave no
  durable record this view can read; only release-window receipts and rollbacks are visible.
