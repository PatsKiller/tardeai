# Access gaps and risk register

Census: 2026-10-07T00:49:34Z. No risk in this list was closed by a code or schedule change.

## Access

| Need | Result |
|---|---|
| Trade AI source at the served SHA | Present in this worktree. OBSERVED_SOURCE. |
| Served Trade AI process | build-meta HTTP 200 and portfolio-server active. OBSERVED_SERVED. |
| DOF source | Local master `1f3186d563076da62c38c4294321b0c65086be50`, clean. The discovery environment's GitHub 404 does not describe this checkout. |
| DOF agent policy | No policy file on served master. A PROPOSED file is on `wt/n8n-dof-policy-20261007` and is not binding. See `06-findings-and-gateway.md`. |
| DOF served process | dof-dashboard active, `/api/run-scope` HTTP 200. OBSERVED_SERVED. |
| Production Postgres roles for `dof_*` | Measured 2026-10-07: 22 tables, owner `trade_ai`, no role whose name matches `dof`, no row read, no DDL. Schema version still NOT_MEASURED. |
| OpenClaw internal schedules | Unit `openclaw-gateway.service` exists. Its schedule store was not opened. NOT_MEASURED. |
| Companion M8M plan files named in the work order | Not in this worktree. Not used as canonical. |
| Architecture v3.3 diagram edges | File exists. Edges not re-scored. DESIGN_ONLY. |
| n8n enterprise flag list beyond the public settings body | Earlier same-day authenticated read, not repeated. |
| Push, release, broker, 2FA, send | Denied by the session ceiling and by policy. Not requested as a grant because no prepared change needs one. |

## Risks

| Id | Risk | Evidence | State |
|---|---|---|---|
| R1 | n8n is mistaken for the live owner | Two active monitors plus 66 executions exist, while 482 user crontab commands remain the jobs | Open. Docs and workflow names say monitor. Cron was not edited. |
| R2 | A native n8n credential becomes a second secret store | 0 credentials today. Community cannot use Bitwarden as an external store. | Open. BLOCKED_POLICY. |
| R3 | Auth-exempt `/v2/` and `/v3/` routes are reachable from the lab bridge | Prefixes are in `portfolio_server.py`. Ports 7776 and 7777 listen on `0.0.0.0`. The monitors already GET build-meta via `172.19.0.1`. | Open. No new route was added. |
| R4 | Registry state and host state disagree | The two retired timers are elapsed one-shots (classifier miss, left enabled). contradiction-adjudicator is enabled and last succeeded 2026-10-06 19:30 EDT. maturity-remeasure's Monday `--write` line is active. Both registry rows stay NEVER_SCHEDULED. | Open for the two stale rows. One-shot label corrected. No timer or crontab edit. |
| R5 | Approval reminder looks alive in syslog and stale on disk | Flags are `--send` and `--record`. The ledger is written only when the plan has actions. Age about 190h is not proof the hour failed, and a CMD line is not a consumer receipt. | Explained. Worktree receipt added. Live job not run. Pilot refuses `wrong_signal` until a run receipt is supplied. |
| R6 | Shared `trade_ai` database | 22 `dof_*` tables owned by `trade_ai`. No separate DOF role. | Measured. No DDL. Gateway opens no DOF SQL route. |
| R7 | Model ADR names rejected ids | Correction 2026-10-07 names `deepseek-flash` and records the V4 ids as rejected. `FLASH_MODEL` in code was not edited. | Doc corrected. No model call and no live setting change. |
| R8 | n8n outage is invisible unless something runs the checker | `scripts/n8n_lab_watchdog.py` exits non-zero on a closed port and recorded HTTP 200 at 2026-10-07T01:22:22Z. No timer was enabled and nothing is sent. | Checker exists. Unattended coverage is still absent. |
| R9 | Community edition cannot separate DOF and Trade AI projects | Public settings do not show a project wall. Earlier read had team project limit 0. | Open. DOF workflows were not added. |
| R10 | Postgres 16 under n8n | Image `postgres:16.15-alpine` while n8n documents an older major as supported | Open. Not upgraded. Lab only. |
| R11 | High-frequency jobs moved into n8n would add a node process without removing cron risk | Weekday syslog CMD volume is about 9,500–10,200 | Open. Disposition keeps those lanes in code. |
| R12 | A read route that also sends | Not tested per route | Open. NOT_MEASURED. Default for a future workflow is refusal. |

## Effects

Prevented: no crontab edit, no timer enable or disable, no service restart, no production SQL, no n8n credential, no API key, no model call, no send, no queue mode, no community package, no Python runner, no DOF bid or promote, no push.

Performed: read-only HTTP checks, read-only systemctl and journal counts, read-only n8n catalog counts, and these documents.
