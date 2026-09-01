# Hermes autonomous loop — DB resilience (2026-07-26)

Status:      ACTIVE
as_of:       2026-07-26T16:26:55-04:00
Measured at: efcc51365 / not measured

**Branch:** `grok/hermes-loop-db-resilience-20260726`

## Incident

| Night | Symptom |
|-------|---------|
| 2026-07-24 | `psycopg2.OperationalError: SSL connection has been closed unexpectedly` |
| 2026-07-25 | ALB `FAILED: timed out` (Ollama) → AMAT same SSL error on `hermes_v_ticker_context` |

Timer stayed **active (waiting)**; kill switch **off**. Home correctly showed Autonomous loop **ON** (schedule armed). Last **service** run was **failed**.

## Cause

Single long-lived DB connection held open across a 180s Ollama call. Postgres closed the idle SSL session; next ticker’s `get_ticker_context` raised uncaught `OperationalError` and exited the unit with status 1.

Gateway was **not** involved (PHASE208D — fleet via timers).

## Fix

`scripts/hermes_autonomous_loop.py`:

1. TCP keepalives on connect (`keepalives_idle=30`)
2. `ensure_live_conn()` — `SELECT 1` probe; reopen if dead
3. Per-ticker try/except — one failure does not abort remaining targets
4. Close/reopen connection after each Ollama wait before the next ticker
5. Default Ollama timeout 120s (`HERMES_LOOP_OLLAMA_TIMEOUT`)
6. Unit exits 1 only when **all** targets fail (partial success → 0)

Research-only. No broker / order / proposal / GO-WAIT writes.

## Operator deploy

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
# prefer worktree; live tree needs ALLOW_MAINTREE_GIT=1
ALLOW_MAINTREE_GIT=1 git fetch origin
ALLOW_MAINTREE_GIT=1 git checkout main
ALLOW_MAINTREE_GIT=1 git pull origin main   # after PR merge

# optional smoke (dry-run, 1 ticker):
.venv/bin/python scripts/hermes_autonomous_loop.py --loop ticker_challenger --max-rows 1

# next scheduled fire: hermes-autonomous-loop.timer (~21:01 ET)
# or:
systemctl --user start hermes-autonomous-loop.service
journalctl --user -u hermes-autonomous-loop.service -n 40 --no-pager
```

Warm Ollama before the night run if recent timeouts:

```bash
curl -s localhost:11434/api/tags | jq '.models[].name'
```
