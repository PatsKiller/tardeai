# Source Export: scripts/report_alert_sla_status.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_alert_sla_status.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c952ba94ff5d99e4af49989c510adc3d9e9eacdd6eaf0a8a7b37cd1482a50c24` |
| **File Size** | 2568 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_alert_sla_status.py — Alert SLA tracking.

Read-only. No approvals. No trades.

Usage:
    .venv/bin/python scripts/report_alert_sla_status.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

SLA_TARGETS = {
    "ACTIONABLE_READY": 60,
    "BLOCKED_NEEDS_REBUILD": 60,
    "BLOCKED_EXECUTION_FAILED": 120,
    "NEEDS_OPERATOR_DECISION": 120,
    "WATCHPOOL_READY": 300,
}


def main():
    p = argparse.ArgumentParser(description="Alert SLA status (read-only)")
    p.add_argument("--since-days", type=int, default=7)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    log_path = PROJ / "logs" / "proposal_alerts.log"
    alerts = []
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            try:
                alerts.append(json.loads(line))
            except Exception:
                pass

    by_type = {}
    for a in alerts:
        t = a.get("alert_type", "unknown")
        by_type.setdefault(t, {"total": 0, "sent": 0, "dry_run": 0, "suppressed": 0})
        by_type[t]["total"] += 1
        if a.get("sent"): by_type[t]["sent"] += 1
        elif a.get("status") == "dry_run": by_type[t]["dry_run"] += 1
        elif a.get("status") == "suppressed": by_type[t]["suppressed"] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_alerts": len(alerts),
        "by_type": by_type,
        "sla_targets": SLA_TARGETS,
        "note": "SLA latency tracking requires proposal creation timestamps — full measurement available after ALERT-1 dispatcher is cron-active",
    }

    if args.verbose:
        print(f"Alert SLA Status — {len(alerts)} alerts")
        for t, d in sorted(by_type.items()):
            print(f"  {t}: total={d['total']} sent={d['sent']} dry_run={d['dry_run']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Alert SLA Status\n", f"Total alerts: {len(alerts)}\n",
              "| Type | Total | Sent | Dry Run |", "|------|-------|------|---------|"]
        for t, d in sorted(by_type.items()):
            md.append(f"| {t} | {d['total']} | {d['sent']} | {d['dry_run']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
