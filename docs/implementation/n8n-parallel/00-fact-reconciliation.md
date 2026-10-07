# Fact reconciliation

Measured 2026-10-07T01:46:08Z (2026-10-06 21:46:08 ET). This file records that read. It is not a deployment receipt. Nothing in the local branch `wt/n8n-parallel-20261007` is served.

## Pins

| Item | Observed |
| --- | --- |
| Served git SHA | `18a27ff288894c4e428151d5f385e68522ecd47b` |
| Build | `built_at` 2026-10-06T22:08:40.117Z, `ui_version` 3.14+mux8d5sp, label `main-exact-phase2` |
| CURRENT realpath | `/home/johnclaw/trade-ai-releases/portfolio-server/18a27ff28-main-exact-phase2-20261006-180747` |
| portfolio-server | user unit active, PID 2159225, FragmentPath the user unit, WorkingDirectory that release |
| origin/main | `18a27ff288894c4e428151d5f385e68522ecd47b` |
| Worktree HEAD at the read | `fe6a607b13c72e6a94219cca2b76885c8896eda7` |
| Parent of that commit | `fd904479403871c8c5471c62e09c8a368f411abc` |
| Worktree | `/home/johnclaw/tradeai-wt-n8n-parallel-20261007`, clean at the read, not pushed |
| n8n | container `m8m-n8n`, image `n8nio/n8n:2.43.0`, running, `GET /healthz` returned `{"status":"ok"}` |
| n8n license field | not present in the version/license/plan keys of the unauthenticated `/rest/settings` body on this read |
| DOF served master | `/home/johnclaw/nyc-dof-auction` clean at `1f3186d563076da62c38c4294321b0c65086be50` |
| DOF policy branch | `/home/johnclaw/dof-wt-n8n-policy-20261007` clean at `d1dad13f868edbdc8c27fec22ddc7a3d517b7529` |
| dof-dashboard | user unit active, PID 1800291, WorkingDirectory the live master |
| Grants | every scope in the local grant file was already expired. None named this branch. No approval code is recorded here. |

`CURRENT/data` is a directory. `CURRENT/data/runtime` is a symlink to `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime`. The git HEAD inside a release directory is not the served content hash. The hash above is the build stamp from `GET /v3/build-meta.json`.

## What is local only

At `fe6a607b1`, these paths differed from the served tree. Short SHA-256 prefixes:

| Path | Worktree | Served |
| --- | --- | --- |
| `scripts/approval_package_reminder.py` | `d34728e3999f4ee2` | `5cf0e37ec2bb89a4` |
| `scripts/lib/n8n_coordination_gateway.py` | `7034f6b84aac3513` | MISSING |
| `scripts/n8n_coordination_gateway.py` | `5a01214e7c9601aa` | MISSING |
| `scripts/lib/n8n_pilot_contracts.py` | `4fd98a2ff8881668` | MISSING |
| `scripts/n8n_lab_watchdog.py` | `302a0716ae5dd7e8` | MISSING |
| `config/lane_registry.json` | `b29a4fc67cc23eda` | `970b48520074a505` |
| `docs/architecture/cio/ADR_LLM_GOVERNANCE_BOUNDARY.md` | `c214adbd5000045c` | `6a667c1ea1f07d9f` |
| `scripts/maturity_remeasure.py` | `da9d76680e8ad1ee` | same |
| `scripts/contradiction_adjudicator.py` | `49a9a6a2f0aea03e` | same |

The corrective commit that contains this file is also local only until a push grant names it. Push was not performed.

## Census

Definitions, counted separately:

| Count | Definition | Value |
| --- | --- | --- |
| 482 | user crontab lines that are not comments and not a leading environment assignment | matches the supplied report |
| 475 | those 482 lines that contain `trade-ai-releases`, `$PROJ`, or `portfolio-server/CURRENT` | the supplied report said 474. This read used the marker above. The one-line difference is not a missed-fire rate |
| 2 | those 482 lines whose command path is the DOF checkout | matches |
| 4 | active lines in `/etc/crontab` under the same non-comment rule | |
| 3 | active lines in `/etc/cron.d` | together with the 4, this is the supplied "seven /etc commands" |
| 1 | entry under `/etc/cron.hourly` | a script file, not one of those seven command lines |
| 117 | `systemctl --user list-unit-files --type=timer` | 92 enabled, 25 disabled |
| 112 | `*.timer` files in `~/.config/systemd/user` | the other five unit files are Ubuntu or snap timers, not Trade AI units |
| 25 | user services in state running | |
| 173 | lane registry rows | 134 ACTIVE, 15 NEVER_SCHEDULED, 13 PAUSED, 11 RETIRED |

A command line is not a launched process, a successful job, an artifact, or a consumer receipt. The previously supplied 19-day journal volume of 164,687 command lines was not re-counted on this read. Missed opportunities are NOT_MEASURED: this read did not pair each due calendar with a trigger receipt and a result receipt.

## Two real drifts

1. `tradeai-contradiction-adjudicator.timer` is enabled and waiting. Last trigger 2026-10-06 19:30 ET. Next elapse 2026-10-07 19:30 ET. The registry row is still NEVER_SCHEDULED, and its reason evidence still says the verdict file does not exist. The verdict file is present. State was not flipped.
2. User crontab contains `40 6 * * 1` `scripts/maturity_remeasure.py --write`. `data/governance/maturity_latest.json` exists under persistent-state (schema `MaturityScore@v1`, as_of 2026-10-05T10:40:01Z, nine domains). The registry row is still NEVER_SCHEDULED and says that file has never been written. State was not flipped. The numeric headline was not read and is not a claim.

## Two one-shot non-issues

`at-observation-01.timer` and `at-observation-01-closeout.timer` are UnitFileState=enabled, SubState=elapsed, and NextElapseUSecRealtime is empty. That is the spent one-shot the registry already calls RETIRED. Enabled is not a contradiction. They were not disabled.

## Not claimed

No broker call, no model call, no approval `--send` invocation, no crontab edit, no `systemctl` enable or disable, no DOF ACL change, no n8n workflow install, no grant minted, no push, no promotion.
