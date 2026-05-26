# Source Export: scripts/telegram_agent_router_bridge.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/telegram_agent_router_bridge.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:50:11Z` |
| **SHA256** | `3ac818b4964bf4b6fc9e64abf83b9fc1315339ef9ecd4bb1b59f6ee702c18bb7` |
| **File Size** | 943 bytes |

## Full Source

```py
#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--message","-m",required=True); ap.add_argument("--save",action="store_true"); args=ap.parse_args()
    cmd=["python3","scripts/agent_router.py","--message",args.message,"--json"]
    if args.save: cmd.append("--save")
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    if p.returncode!=0: print(json.dumps({"ok":False,"error":p.stderr or p.stdout})); return p.returncode
    route=json.loads(p.stdout)
    print(json.dumps({"ok":True,"reply_text":route.get("short_telegram","Route created."),"route":route,"should_call_chain":route.get("to_agent")!="orchestrator","approval_required":route.get("action_type")=="pending_write"},indent=2))
    return 0
if __name__ == "__main__": raise SystemExit(main())
```
