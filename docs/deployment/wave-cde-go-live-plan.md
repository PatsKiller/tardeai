# Communications Gateway — Wave C/D/E Go-Live Plan (guard plan file)

```
Status: ACTIVE
as_of: 2026-09-07T11:33:00-04:00
Measured at: served build 3cb740e4c69380fe9355da6b4857a94cf21e6c27 (PR #874 Wave E + docs, merged from d18d81208)
```

This file is displayed by `bin/guard plan` before the operator approves the scopes it
declares. It is the single source of the go-live sequence; the fuller rationale lives in
`docs/ops/COMMS_GATEWAY_GO_LIVE_RUNBOOK.md`.

## What this plan does

Take the merged Communications Gateway waves (A/B/C/D/E/F) to live production in order:

1. **Merge** — merge the validated wave branch to `main` and record the merge SHA.
2. **Deploy** — `scripts/cio_phase2_exact_main_deploy.sh prepare` then `promote` from the
   deploy worktree, re-pointing `CURRENT` + systemd at the exact merged SHA.
3. **Restart poller** — `pkill -f run_telegram_callback_poller.py`; the host-local cron
   wrapper relaunches the daemon from the new `CURRENT` (≤2 min). The `telegram` tmux
   session is **Grok's agent window** and is left alone.
4. **Verify** — `/v3/build-meta.json` `git_sha` == merged SHA;
   `/api/v2/communications/health` reports the intended mode.

## Scopes this plan requires

| Scope | Use |
|---|---|
| `git-push` | one push of the validated merge |
| `release-write` | `prepare`/`promote` the release |
| `db-write` | apply communications migrations to prod Postgres |
| `cron` | confirm the poller wrapper cron line is intact |
| `service` | restart the poller daemon; verify the served process |

`secret` and `gate` are **never** auto-accepted.

## Mode posture

Hold **CANARY** (`ops`, `CANARY_CHATS=6993102664,8797974247`) for the soak window before
any switch to **ACTIVE**. The prior ACTIVE-for-`ops` attempt was reverted as premature.

## Rollback (per step)

- Merge → revert PR (nothing deployed yet).
- Deploy → `scripts/cio_phase2_exact_main_deploy.sh rollback`; verify
  `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`.
- Poller → `pkill` + roll back the release; cron relaunches from the rolled-back `CURRENT`.
- Mode → `COMMS_GATEWAY_MODE=OFF`; ledger rows stay.
