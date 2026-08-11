# Autonomy Operator Runbook (READ_ONLY_ADVISORY)

## How agents wake

1. **Timers** (backstop): `tradeai-agent-runtime@alex|morgan|steph|hermes.timer`
2. **Reactive cycle** (every ~2 min): `tradeai-cio-reactive.timer` →
   `scripts/cio_reactive_cycle.py`
   - Polls `CIOEventBus` for agent-routed event types
   - Enqueues `EVENT_BUS` wake jobs
   - Enqueues goal-due / event-linked wakes
3. **Heartbeat** (~30 min): still emits material-change events onto the bus

## Inspect goals / thesis

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python - <<'PY'
from scripts.lib.cio_goals import CIOGoalStore
s = CIOGoalStore()
for g in s.list_open_goals():
    print(g["goal_id"], g["owner_agent"], g["status"], g["title"][:60])
    if g.get("thesis_summary"):
        print("  thesis:", g["thesis_summary"][:120])
print("--- context alex ---")
import json
print(json.dumps(s.get_context_for_agent("alex"), indent=2)[:2000])
PY
```

Create a goal:

```bash
.venv/bin/python - <<'PY'
from scripts.lib.cio_goals import CIOGoalStore
s = CIOGoalStore()
g = s.create_goal(
    owner_agent="alex",
    title="Desk living thesis",
    thesis_summary="Risk-aware observe-only; escalate material drift to operator.",
    linked_event_types=["allocation.drift", "portfolio.material_change", "behavioral.flag_raised"],
    priority="HIGH",
    actor_id="operator",
)
print(g["goal_id"])
PY
```

## Force a reactive cycle

```bash
.venv/bin/python scripts/cio_reactive_cycle.py --once --json
# status snapshot
cat data/runtime/cio_reactive_cycle_last.json
```

## Manual agent --once

```bash
set -a; source ~/.config/tradeai/agent-operator.env; set +a
export AGENT_RUNTIME_OPERATOR_AUTH=1
export PYTHONPATH=$PWD/scripts
.venv/bin/python -m scripts.agent_runtime.agents.run_once --agent alex --once --max-batch 4
```

## Ack / rate (existing Telegram /cio path)

- `/cio ack <action_id>` — acknowledge ledger item
- `/cio rate <action_id> <score>` — usefulness feedback into outcome store  
(Do not expect these to trade.)

## Emergency disable

```bash
touch data/runtime/CIO_REACTIVE_DISABLED
systemctl --user stop tradeai-cio-reactive.timer
# optional: stop fleet timers
systemctl --user stop tradeai-agent-runtime@alex.timer
```

## Backup hygiene

```bash
.venv/bin/python scripts/backup_enforcer.py --status
# should show count=1 local
# Drive: only latest of each env_/ops_/memory_/apps_/data_/db_backup_*
```
