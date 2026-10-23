# Proposed n8n lane `main-ci-watch` — main-HEAD exact-SHA CI for the Releases page

```
Status:      PROPOSED (not registered; the health contract is DRAFT)
as_of:       2026-10-22T22:10:00-04:00
Measured at: origin/main 0f5bf2453; one read-only `scripts/main_ci_watch.py --dry-run` on the host
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Source:      fix/releases-page-queue-ci-20261022
```

## Why

On 2026-10-22 the operator looked at System → Releases & schedules and saw "Releasing next 0f5bf2453 · main CI
UNAVAILABLE". The page reads exact-SHA CI only from `post_merge_ci.json`. The deploy writes that file only for the SHA
it promotes, so it named f7c1e96cb. The page never calls GitHub from the request path.

Before writing anything, we searched for an existing post-merge or CI-watch mechanism (AGENTS.md §13.5):

- `release_grant_preflight.py --ci-only` runs only inside a deploy.
- `release_train_controller` checks main CI only while a train is running, and the train is not armed.
- `tradeai-release-train-claim.timer` answers window requests; it never reads CI.

None of these runs on a schedule, so this is a new lane.

## What is built in the PR (inert until scheduled)

- **`scripts/main_ci_watch.py`** reads main HEAD (`gh api repos/<slug>/commits/main`) and the push/main runs for that
  exact SHA. It reuses the selection rule from `release_grant_preflight.evaluate_push_checks`. It writes
  `data/runtime/main-ci-watch_last.json` with a state of SUCCESS, FAILURE or PENDING. Every gh call goes through
  `pr_hygiene_audit._assert_read_only_gh` and is GET only.
- **The page** shows the state, its age and each workflow. FAILURE workflows also appear under Release errors.

Dry run, 2026-10-22 22:05 ET:

```
[main-ci-watch] main 0f5bf2453 CI PENDING (success=2 failure=0 pending=1 missing=0)
DRY-RUN {"dry_run": true, "lane_id": "main-ci-watch", ... "would_write": ["data/runtime/main-ci-watch_last.json"]}
```

## What is proposed here (the owner's step)

| File | Goes into |
|---|---|
| `registry_row.json` | `config/lane_registry.json`: n8n dispatcher, every 10 min, stage **shadow**, dispatch `dry_run` |
| `allowlist_entry.json` | `config/n8n_run_allowlist.json`: `--dry-run`, `live_arg null`, its own flock, no secret env |
| `health_contract.DRAFT.json` | `config/n8n_health_contracts.json`: **DRAFT**, owner platform |

Why this is not registered in this PR: AGENTS.md §23.19 says no lane enters shadow without a contract its owner has
REVIEWED, and an agent never marks one REVIEWED. A DRAFT contract in the config turns the contract gates red, as
#1957 shows.

The path to live:

1. The owner reviews the contract.
2. One PR adds all three entries at shadow, together with the onboarding-standard checklist, a cron-inventory row
   and the lane-list pins.
3. A forced `dry_run` fire is the shadow proof.
4. Canary is a separate PR, made on the operator's word, that sets `live_arg []` and dispatch `live` and adds the lane
   to `TRADEAI_N8N_RELAY_LIVE_LANES`.

Until the lane is scheduled, the page says "no main-ci-watch receipt (scripts/main_ci_watch.py has not run …)".
Before the lane is in place, an operator can also run `python3 scripts/main_ci_watch.py` by hand from the canonical
checkout. A real run writes only its own receipt.
