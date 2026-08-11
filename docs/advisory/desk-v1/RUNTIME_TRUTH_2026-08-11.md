# Runtime truth — host snapshot (WS0)

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1` @ `acec49a6`+ (goal/thesis work in tree)  
**Host:** ms01-openclaw (timer host)  
**Authority:** READ_ONLY_ADVISORY  

No marketing. Commands and outcomes only.

---

## Checkout

```
$ git branch --show-current
feature/advisory-desk-v1
```

Timers and agent units use WorkingDirectory under this tree (or CURRENT release that rsyncs from it).

---

## backup_enforcer

```
$ .venv/bin/python scripts/backup_enforcer.py --status
local.count = 1
local.full_count = 1
local.max_count = 1
local.compliant = true
newest full: /home/johnclaw/db_backups/trade_ai_20260811_091716.sql.gz (~1.9G)
```

`config/health_agent_policy.json` → `never_auto_remediate` includes  
`backup_cadence_stale`, `db_dump_stale`, `db_dump_missing`, `backup_local_count_exceeded`,  
`backup_local_bytes_exceeded`, `backup_storm_suspected`. Health agent cannot re-storm dumps.

---

## agent_runtime@alex|morgan|steph

### Root cause (fixed)

`AGENT_RUNTIME_PROVIDER_MODULE` in `~/.config/tradeai/agent-operator.env` had an **inline `# comment`**.  
systemd EnvironmentFile does **not** strip comments → module name became:

`agent_runtime_live_providers  # real DeepSeek/...`

**Fix:** strip comment in env file; also strip in `agent_runtime_dispatch_boot._load_provider_module`.  
**Fix:** `agent_runtime_live_providers` missing `import sys`; broken `Environment(...)` ctor replaced with SHADOW processor.

### Proof — each --once

```
$ set -a; source ~/.config/tradeai/agent-operator.env; set +a
$ export PYTHONPATH=scripts
$ .venv/bin/python -m scripts.agent_runtime.agents.run_once --agent alex --once --max-batch 2
AGENT RUNTIME BOUNDED RUNNER — PREPARE-ONLY / DEFAULT-DISABLED
agent=alex state=SHADOW enabled=True
dispatch summary: {..., 'total': 1, 'outcomes': {'COMPLETED': 1, ...}}
exit=0

$ ... --agent morgan ...  → COMPLETED 1  exit=0
$ ... --agent steph  ...  → COMPLETED 1  exit=0
```

Jobs sourced from open CIO goals (`goal_shadow_review`). Model path for financial agents is governed-gateway sentinel (PROVIDER_BLOCKED is recorded; job still completes with retrieval + thesis touch). No broker path.

### Unit timers

Timers still fire periodically; prior failure mode was CONFIG 78 from bad module name. After env fix, oneshot path is green. Operator should `systemctl --user daemon-reload` if drop-ins change.

---

## Goal store + dispatcher (WS1–2 smoke)

```
seeded goals: alex, morgan, steph (due)
enqueue_goal_wakes → NEW_RUN wakes with trigger_type GOAL_DUE
dedup: second pass skips same agent+goal within 30m
poll_and_dispatch → claims/dispatches pending wakes (run_store optional)
```

---

## Explicit non-claims

- Not “fully autonomous.”
- Fleet SHADOW only; maturity catalog still marks morgan/steph DESIGNED for production readiness — goal wakes use FLEET SHADOW operability override.
- 30-min heartbeat remains safety net, not sole wake source.
- Promotion desk still NOT_PROMOTED.
