# Source Export: scripts/run_agent_chain.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_agent_chain.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `fb87a6529c4fb23ab79779ba67956f94f105d89d4e0dd717ae5c33110619c712` |
| **File Size** | 1617 bytes |

## Full Source

```py
#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; ROUTER=ROOT/"scripts"/"agent_router.py"; CONFIG=ROOT/"config"/"agent_runtime.json"
def call_router(message, save=False):
    cmd=["python3",str(ROUTER),"--message",message,"--json"]
    if save: cmd.append("--save")
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    if p.returncode!=0: raise RuntimeError(p.stderr or p.stdout)
    return json.loads(p.stdout)
def get_chain(intent, route):
    cfg=json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    chain=cfg.get("agent_chain",{}).get("chains",{}).get(intent,[]) or [route.get("to_agent","orchestrator")]
    for reviewer in route.get("reviewers",[]):
        if reviewer not in chain: chain.append(reviewer)
    return chain
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--message","-m",required=True); ap.add_argument("--execute",action="store_true"); ap.add_argument("--save",action="store_true"); args=ap.parse_args()
    route=call_router(args.message,args.save)
    print(json.dumps({"created_at":datetime.now(timezone.utc).isoformat(),"dry_run":not args.execute,"user_message":args.message,"route":route,"chain":get_chain(route.get("intent","unknown"),route),"status":"pending_approval" if route.get("action_type")=="pending_write" else "planned","next_step":"Wire chain agents to actual specialist scripts. No portfolio write executed."},indent=2))
    return 0
if __name__ == "__main__": raise SystemExit(main())
```
