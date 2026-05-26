# Source Export: scripts/report_phase_readiness_gates.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_phase_readiness_gates.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `4b2d3a1a6f8940d3e2a298fbdebbbbb9a26b6ee8079b3e68502e2ddbb7fd2ac6` |
| **File Size** | 3139 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_phase_readiness_gates.py — Phase readiness gate evaluation.

Read-only. No mutations.

Usage:
    .venv/bin/python scripts/report_phase_readiness_gates.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
A5_END = "2026-05-22"


def main():
    p = argparse.ArgumentParser(description="Phase readiness gates (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    a5_complete = today >= A5_END

    # Check rclone
    import subprocess
    try:
        remotes = subprocess.check_output("rclone listremotes", shell=True, stderr=subprocess.DEVNULL).decode().strip()
        rclone_configured = len(remotes) > 0
    except Exception:
        rclone_configured = False

    gates = [
        {"phase": "A-5 observation check", "status": "allowed",
         "reason": "Interim checks allowed anytime"},
        {"phase": "Final A-5 review", "status": "allowed" if a5_complete else "blocked",
         "reason": f"Window ends {A5_END}" if not a5_complete else "Window complete"},
        {"phase": "Phase 8D strategy quality", "status": "blocked" if not a5_complete else "allowed",
         "reason": "Requires A-5 complete" if not a5_complete else "A-5 complete, may proceed"},
        {"phase": "SP-2 shadow outcomes", "status": "allowed",
         "reason": "Design allowed; mutation requires approval"},
        {"phase": "BR-2 offsite backup", "status": "operator_required" if not rclone_configured else "allowed",
         "reason": "Operator must configure rclone" if not rclone_configured else "rclone configured"},
        {"phase": "DOC-CLEAN-1D review triage", "status": "allowed",
         "reason": "Review-required docs can be triaged"},
        {"phase": "Live-readiness dashboard", "status": "allowed",
         "reason": "Design allowed; no live toggle"},
        {"phase": "Live trading", "status": "blocked",
         "reason": "Requires 6-month validation, 100+ closed trades, 55% win rate, operator approval"},
    ]

    report = {"generated_at": now.isoformat(), "a5_complete": a5_complete, "gates": gates}

    if args.verbose:
        print(f"Phase Readiness Gates (A-5 {'complete' if a5_complete else 'in progress'})")
        for g in gates:
            icon = {"allowed": "+", "blocked": "x", "waiting": "~", "operator_required": "!"}
            print(f"  [{icon.get(g['status'],'?')}] {g['phase']:35s} [{g['status']}] {g['reason']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Phase Readiness Gates", "", "| Phase | Status | Reason |", "|-------|--------|--------|"]
        for g in gates:
            md.append(f"| {g['phase']} | {g['status']} | {g['reason']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
