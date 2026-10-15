# Apply once (operator)

Run this after the PR is merged and promoted. `--apply` writes durable state in the live coordination ledger (two
additive tables plus `comms_intents.state`), so it is your run. It changes no crontab, unit or n8n workflow, and it
sends nothing.

```bash
S=$HOME/trade-ai-releases/persistent-state
L=$S/data/governance/n8n_coordination_ledger.sqlite
CODE=$HOME/trade-ai-releases/portfolio-server/CURRENT
P=$CODE/docs/ops/packets/n8n-comms-intent-consumer-20261015
cd "$CODE"

# 0. Back up the ledger with the online sqlite backup API (consistent copy under WAL; nothing is deleted)
python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" \
  "$L" "$S/data/governance/n8n_coordination_ledger.pre-comms-intent-consumer-$(date -u +%Y%m%dT%H%M%SZ).sqlite"

# 1. Evidence before + the dry run (read-only). Expect the 02_dry_run_live.txt shape:
#    ci-2a845bc6aa846e66525eb957 -> incident wferr:tradeai-fabric-error-probe P2, incident_key inc-7b246a5388b496801e92
python3 "$P/evidence.py" --state-root "$S"
TRADEAI_STATE_ROOT=$S python3 scripts/n8n_comms_intent_consumer.py --dry-run

# 2. Apply once
TRADEAI_STATE_ROOT=$S python3 scripts/n8n_comms_intent_consumer.py --apply; echo "exit=$?"
#    expect: {"mode": "apply", "ok": true, ..., "done": 1, "incidents_created": 1, ...} exit=0

# 3. Evidence after
python3 "$P/evidence.py" --state-root "$S"
#    expect: comms_intents ci-2a845... state DONE; comms_intent_consumption row DONE attempts 1
#            incident_key inc-7b246a5388b496801e92; comms_intent_incidents row OPEN P2 count 1;
#            receipt present, status ok, ok_at set
TRADEAI_STATE_ROOT=$S python3 scripts/n8n_comms_intent_consumer.py --apply   # rerun: done 0 (idempotent)

# 4. The fan-in sees it (dry run: read-only, no gateway call)
TRADEAI_STATE_ROOT=$S python3 scripts/n8n_incident_fanin.py --dry-run          # whole run, prints a sample of 8
TRADEAI_STATE_ROOT=$S python3 -c "
import sys; sys.path.insert(0, '.')
from datetime import datetime, timezone
from scripts import n8n_incident_fanin as f
rows = f.collect(f.state_root(), datetime.now(timezone.utc))
print([(r['severity'], r['source'], r['item'], r.get('count')) for r in rows
       if r['source'].startswith('n8n_comms_intent') or r['item'] == 'wferr:tradeai-fabric-error-probe'])
print(f.NOTES.get('comms_intent_source'))"
#    expect: [('P2', 'n8n_workflow_error', 'wferr:tradeai-fabric-error-probe', 1)]
#            incidents:ok:open=1:merged=0:dlq:ok:dead_letter=0:queued_stale=0
# 5. The notifier would batch it as P2 (dry run: plans, sends nothing). Run this after the next */5 fan-in apply has
#    written its receipt.
TRADEAI_STATE_ROOT=$S python3 scripts/incident_notifier.py --dry-run
```

The incident stays open until `open_until`, one hour after the apply, so it reaches one P2 batch (subject to quiet
hours, 22:00-07:00 ET). After that, the next `--apply` closes it, and the fan-in records a recovery. Until the lane is
scheduled, re-run step 2 by hand when new intents arrive. The fan-in's `queued_stale` line tells you when one has
waited more than 2 h.
