# Run from the release: cohort 1 operator packet (2026-10-15)

Branch `refactor/run-from-release-20261015`, from origin/main `ea14e1c3a`. The commit is local only. Nothing was
pushed or installed, and no crontab line or unit was changed.

The design is in `~/n8n-maturity-verification/arch-review-20261014/designs/RUN_FROM_RELEASE.md`. The findings
are WS7-01, WS8-14 and WS6-08.

## Why

Every crontab line already `cd`s into CURRENT. Most of them still execute the dev checkout:
- 334 of 394 active jobs run `$PY`, which is `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`.
- 14 wrappers inside CURRENT hard-code the dev tree.
- 105 of 126 user services name it.

Coding agents move that checkout, so a `pip install` or a `git checkout` there changes production with no release,
no receipt and no rollback.

## What cohort 1 changes

Cohort 1 changes five crontab lines and adds two header lines. No unit is touched.

| Line (script) | Schedule | Writes | Sends |
|---|---|---|---|
| `build_symbol_profiles.py` | Sun 19:00 | `symbol_profiles` rows; `logs/symbol_profiles.log` | nothing |
| `build_symbol_profiles.py --watchlist-top 300` | weekdays 06:45 | same; `logs/symbol_profiles_watchlist.log` | nothing |
| `cio_draft_plan_hygiene.py --apply` | daily 06:52 | expires stale empty draft plans; receipt `data/runtime/cio-draft-plan-hygiene_last.json` | nothing ("No notify") |
| `report_goal_loop_baseline.py --json` | hourly :20 | `~/logs/goal_loop_baseline.log` | nothing |
| `report_agent_number_grounding.py --check-slo` | daily 18:40 | `data/runtime/agent_number_grounding_slo_last_run.json` (linked to persistent-state) | nothing |

Each line gets one exact, strippable prefix, and its `$PY` becomes `$RPY`:

```
export PY=$RPY TRADEAI_VENV_PYTHON=$RPY TRADEAI_RUN_FROM_RELEASE=c1; <original command>
```

The header gains two lines right after `PY=`:

```
RPY=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python
TRADEAI_CODE_ROOT=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
```

No code reads either name, so the other 389 lines behave exactly as before. `TRADEAI_ROOT` is deliberately not
used: CIO code already reads it as the **state** root.

## Evidence (02_dry_run_live.txt)

- **Lane gate.** Undeclared lines go from 0 to 0.
- **Verifier.** 5 of 5 pass. Each script ran `--help`, exit 0, from CURRENT, with a build of the frozen dependency
  lock (134 pins, Python 3.14.4), inside `bwrap`: read-only `/`, private `/tmp` and `/run/user/1000`, no network.
- **Round trip.** `--revert c1` on the candidate gives back the live crontab byte for byte.
- **Forced-run probe.** It fails on all 5 lines with `RPY not executable`. That is correct and is precondition P1
  below.

## Preconditions (all must hold; 03_apply.md step 0 checks them)

| # | Precondition | Status 2026-10-15 |
|---|---|---|
| P1 | `CURRENT/.venv/bin/python` exists. It is a symlink made by **prepare** to `~/trade-ai-releases/venvs/py3.14.4-<lock12>/`, and the release receipt records the lock hash. A link made by hand is dropped by the next prepare (its rsync excludes `.venv`). | **NOT MET.** Needs the prepare PR (design §2, step P0) and a promote |
| P2 | This branch merged and promoted, so `scripts/run_from_release.py` exists in CURRENT | NOT MET |
| P3 | A `cron` guard grant naming this packet, in its reason ("PR #N sha <sha>") | operator |
| P4 | The live crontab still selects exactly these 5 lines (regenerate; the file changes during the day) | checked at apply |

## Files

- `02_dry_run_live.txt`: the dry run, the verifier output, the probe output and the round trip.
- `03_apply.md`: the steps to install cohort 1 and prove it.
- `04_rollback.md`: the revert command (byte-exact), or a restore from the backup.

After cohort 1:
- **c2** is 289 direct-`$PY` lines. It waits for P1 of the design: linking the release-local write paths.
- **c3** is 42 wrapper lines. 12 of them wait for the wrapper code fix.
- **c4** is 53 broker-adjacent lines, run by the operator with the market closed.
- **Units** (`u1` 83, `u2` 11, `u3` 11) go by drop-in, generated with `run_from_release.py dropins`.
