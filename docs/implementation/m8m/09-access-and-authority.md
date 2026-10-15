# 09 — Access and authority

## What this session was allowed to do

Trade AI session receipt `a48841ab-c468-4df1-8c8d-2f250e8c2b59`, agent `grok`, mode mutating, ceiling `MUTATING_LOCAL_ONLY`. Claimed path `docs/implementation/m8m`. Denials recorded by the session tool: remote sync, deployment, production, financial. Worktree `/home/johnclaw/tradeai-wt-m8m-phase0-baseline-20261006`, branch `wt/m8m-phase0-baseline-20261006`, base `65fbeecf31161e0b51790d5761f7d3fc20c9ea7c`.

The repo's `scripts/new-worktree.sh` names branches `wt/<name>`. That is the branch that was created. A `docs/` branch name was not used.

No release-write grant was requested. No push was attempted. Implementing the work order is not a push phrase under `AI_WORK_POLICY.md`.

## Access that worked

| Surface | Result |
|---|---|
| This host | `ms01-openclaw`. SSH to "somewhere else" was not required. |
| Trade AI git and `CURRENT` | read |
| DOF git | `origin` is `https://github.com/PatsKiller/nyc-dof-auction.git`, HEAD `5d3c39e` |
| DOF HTTP | 127.0.0.1:7776 200 |
| Trade AI HTTP | 127.0.0.1:7777 build-meta, health, `/v3/cio` |
| johnclaw crontab | 1089 lines |
| user and system systemd list | returned |
| Postgres as role `trade_ai` | read-only catalog and aggregates. Password was not printed. |
| Drive metadata | list and two title reads. No upload. |

## Access that failed or was refused

| Surface | Result |
|---|---|
| `crontab -u` for every account other than johnclaw, including root and postgres | `must be privileged to use -u`. Those crontabs are **ACCESS_BLOCKED**, not empty. |
| DOF cron's database login | authentication failed. The Trade AI `.env` login worked, which shows the failure is the DOF environment, not a missing role. DOF `.env` was not read. |
| Dump restore | not attempted |
| Broker, 2FA, bid, mail, Telegram send | not attempted |
| Non-johnclaw unit managers | system `systemctl list-timers` returned 20 rows, so system timers were listed. That is not a root crontab. |

## Authority boundaries still closed

Buying a workflow subscription, installing n8n, Kestra, or Windmill, changing a cron or timer, promoting a SHA, sending mail or Telegram, pushing this branch, and any broker, 2FA, bid, or order call.

The n8n design file recommends Community n8n. That recommendation is **DESIGN_ONLY**. This phase does not adopt it. The incumbent was not given a "sufficient" verdict: D-DOF-001, D-DOF-002, and D-SCHED-001 are open on the live pin. A platform purchase would not fix a bad DOF password or a motion daemon on an old directory.
