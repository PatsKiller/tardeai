#!/usr/bin/env python3
"""report_governance_status.py — Combined governance status report.

Read-only. No mutations.

Usage:
    .venv/bin/python scripts/report_governance_status.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="Governance status (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)

    # Read latest facts
    facts = {}
    for fp in [PROJ / "docs/generated/SYSTEM_FACTS_LATEST.json",
               PROJ / "data/system_facts.json"]:
        if fp.exists():
            try:
                facts = json.loads(fp.read_text())
                break
            except Exception:
                pass

    # Read latest A1A check
    a1a = {}
    a1a_path = PROJ / "docs/governance/a1a_latest_check_results.json"
    if a1a_path.exists():
        try:
            a1a = json.loads(a1a_path.read_text())
        except Exception:
            pass

    # Safety flags
    env_flags = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() in ("ALPACA_MODE", "LLM_DISABLE_LIVE_EXECUTION"):
                env_flags[k.strip()] = v.strip()

    status = "healthy"
    if a1a.get("by_severity", {}).get("P0", 0) > 0:
        status = "attention_required"
    elif a1a.get("findings_count", 0) > 0:
        status = "warning"

    report = {
        "generated_at": now.isoformat(),
        "status": status,
        "safety": env_flags,
        "facts_summary": {
            "tables": facts.get("tables") or facts.get("counts", {}).get("tables"),
            "scripts": facts.get("scripts") or facts.get("counts", {}).get("scripts"),
            "cron_jobs": facts.get("cron_jobs") or facts.get("counts", {}).get("cron_jobs"),
            "strategies": facts.get("strategies") or facts.get("counts", {}).get("strategies"),
        },
        "a1a_summary": {
            "status": a1a.get("status", "unknown"),
            "findings": a1a.get("findings_count", 0),
            "by_severity": a1a.get("by_severity", {}),
        },
    }

    if args.verbose:
        print(f"Governance Status: {status}")
        print(f"  Safety: {env_flags}")
        print(f"  A1A: {a1a.get('status', 'unknown')} ({a1a.get('findings_count', 0)} findings)")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Governance Status — {status}", f"\n**A1A:** {a1a.get('status', 'unknown')}",
              f"**Safety:** {env_flags.get('ALPACA_MODE', '?')} / {env_flags.get('LLM_DISABLE_LIVE_EXECUTION', '?')}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
