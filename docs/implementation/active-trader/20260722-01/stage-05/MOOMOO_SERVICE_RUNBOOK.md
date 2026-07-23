# Moomoo Service Runbook — Stage 5

## User units (DISABLED by default; NO system units; NO boot persistence; NO linger)
`~/.config/systemd/user/trade-ai-lab-moomoo-{opend,gateway,replay-writer,feature-engine,
health-monitor}.service`. Each has NO `[Install]` section (systemd reports **static** —
cannot be enabled at boot), `Restart=no`, loopback-only intent, best-effort hardening
(NoNewPrivileges, ProtectSystem=strict, ProtectHome=read-only, RestrictAddressFamilies,
IPAddressDeny=any + localhost allow). ExecStart is a placeholder (`/bin/false …`) — the
wired ExecStart lands in a later stage; nothing is runnable-at-boot now.

## Manual validation start (data-only, loopback)
The Stage 5 validator is the smoke driver, run with the ISOLATED venv:
```bash
cd /home/johnclaw/worktrees/active-trader-next
~/.local/venvs/trade-ai-lab/moomoo-api/current/bin/python scripts/active_trader/moomoo/smoke.py
```
It renders config to tmpfs, starts OpenD (loopback :11112), performs data-only ops,
unsubscribes, closes, stops OpenD, and shreds the tmpfs config.

## Stop command (if anything is left running)
```bash
pkill -f '/OpenD'    # stop OpenD binary
python3 -c "import sys;sys.path.insert(0,'scripts');from active_trader.moomoo import secret_render;secret_render.cleanup()"
ss -tlnp | grep -E ':1111[12]'   # expect empty
```
Post-run verification this stage: 0 OpenD processes, 0 listeners on 11111/11112, tmpfs
OpenD.xml shredded.

## Current service state
STOPPED_DISABLED — nothing running, nothing enabled, no linger. (Not
OBSERVATION_RUNNING: the data login is blocked, so no capture is running.)
