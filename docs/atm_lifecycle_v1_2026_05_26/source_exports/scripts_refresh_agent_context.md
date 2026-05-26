# Source Export: scripts/refresh_agent_context.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/refresh_agent_context.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `6881024ad4792a598558b5d9d39517d8ba06ceb2afc8d02bf04a3ad49c623d7f` |
| **File Size** | 4527 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""Refresh/audit agent context state files.

No manual editing required. This wrapper runs existing producer scripts when present and
then stamps the expected state files with explicit metadata so the router can trust
freshness checks without relying only on mtime.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

PRODUCER_MAP = {
    "light": [
        ("scripts/portfolio_repricer.py", ["holdings.json"]),
        ("scripts/portfolio_signals.py", ["action_signals.json"]),
        ("scripts/asset_intelligence_pipeline.py", ["analyst_data.json", "etf_intelligence.json", "mutual_fund_intelligence.json", "stock_intelligence.json", "asset_intelligence.json"]),
    ],
    "full": [
        ("scripts/portfolio_repricer.py", ["holdings.json"]),
        ("scripts/portfolio_risk.py", ["risk_management.json", "stops.json", "technical_snapshot.json"]),
        ("scripts/portfolio_signals.py", ["action_signals.json"]),
        ("scripts/portfolio_news.py", ["portfolio_news.json"]),
        ("scripts/asset_intelligence_pipeline.py", ["analyst_data.json", "etf_intelligence.json", "mutual_fund_intelligence.json", "stock_intelligence.json", "asset_intelligence.json"]),
        ("scripts/proactive_discovery.py", ["discovery_candidates.json", "ai_watchlist.json"]),
        ("scripts/watchlist_review.py", ["ai_watchlist_review.json"]),
    ],
    "deep": [
        ("scripts/portfolio_repricer.py", ["holdings.json"]),
        ("scripts/portfolio_risk.py", ["risk_management.json", "stops.json", "technical_snapshot.json"]),
        ("scripts/portfolio_signals.py", ["action_signals.json"]),
        ("scripts/portfolio_news.py", ["portfolio_news.json"]),
        ("scripts/asset_intelligence_pipeline.py", ["analyst_data.json", "etf_intelligence.json", "mutual_fund_intelligence.json", "stock_intelligence.json", "asset_intelligence.json"]),
        ("scripts/proactive_discovery.py", ["discovery_candidates.json", "ai_watchlist.json"]),
        ("scripts/watchlist_review.py", ["ai_watchlist_review.json"]),
    ],
}


def run_cmd(script: str) -> Dict:
    path = ROOT / script
    if not path.exists():
        return {"cmd": f"python3 {script}", "status": "skipped_missing"}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = LOG_DIR / f"agent_refresh_{Path(script).stem}_{ts}.log"
    proc = subprocess.run(["python3", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_text(proc.stdout or "")
    return {"cmd": f"python3 {script}", "returncode": proc.returncode, "status": "ok" if proc.returncode == 0 else "failed", "log": str(log)}


def stamp(filename: str, source: str, status: str) -> Dict:
    proc = subprocess.run([
        "python3", "scripts/state_freshness_writer.py",
        "--file", filename,
        "--source", source,
        "--status", status,
        "--json",
    ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"file": filename, "source": source, "status": "stamp_failed", "output": proc.stdout}


def audit() -> Dict:
    proc = subprocess.run(["python3", "scripts/state_freshness_writer.py", "--mode", "audit", "--json"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return json.loads(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["audit", "light", "full", "deep"], default="audit")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    commands: List[Dict] = []
    files_written: List[Dict] = []

    if args.mode != "audit":
        for script, outputs in PRODUCER_MAP[args.mode]:
            print(f"[refresh-agent-context] running: python3 {script}")
            result = run_cmd(script)
            commands.append(result)
            if result.get("status") == "ok":
                for out in outputs:
                    files_written.append(stamp(out, Path(script).name, "ok"))

    result = audit()
    result["mode"] = args.mode
    result["commands"] = commands
    result["files_written"] = files_written

    print(json.dumps(result, indent=2) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
