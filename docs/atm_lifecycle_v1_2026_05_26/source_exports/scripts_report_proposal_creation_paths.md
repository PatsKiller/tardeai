# Source Export: scripts/report_proposal_creation_paths.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_proposal_creation_paths.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `dec8c136307b2404d2fc77e0faa9f079003c020a3f5044de9ee8655e56dc7ac2` |
| **File Size** | 2966 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_proposal_creation_paths.py — Inventory proposal creation paths and route audit status.

Read-only. No file mutation. No DB writes.

Usage:
    .venv/bin/python scripts/report_proposal_creation_paths.py --verbose
"""
import argparse, json, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="Proposal creation paths audit (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    paths = [
        {"file": "scripts/auto_proposal_generator.py", "function": "create_auto_proposal", "source": "screener signals"},
        {"file": "scripts/incubator_proposal_promoter.py", "function": "promote (main loop)", "source": "incubator candidates"},
        {"file": "scripts/paper_trade_logger.py", "function": "create_paper_proposal_from_scan", "source": "manual scan-based"},
        {"file": "scripts/paper_trade_logger.py", "function": "create_paper_proposal_from_signal", "source": "manual signal-based"},
    ]

    results = []
    for path in paths:
        fpath = PROJ / path["file"]
        exists = fpath.exists()
        src = fpath.read_text() if exists else ""

        has_insert = "INSERT INTO paper_trade_proposals" in src
        has_route_audit = "ensure_route_audit_for_proposal" in src
        has_store_matches = "store_setup_matches" in src
        can_produce_screener = "screener" in src.lower() and "strategy_id" in src

        if has_route_audit:
            status = "wired"
        elif has_store_matches:
            status = "wired"
        elif has_insert:
            status = "missing"
        else:
            status = "unknown"

        results.append({
            "file": path["file"],
            "function": path["function"],
            "source": path["source"],
            "creates_proposal": has_insert,
            "route_audit_wired": has_route_audit,
            "store_matches_wired": has_store_matches,
            "route_audit_status": status,
        })

    report = {"paths": results}

    if args.verbose:
        print("Proposal Creation Paths")
        for r in results:
            icon = "+" if r["route_audit_status"] == "wired" else "x"
            print(f"  [{icon}] {r['file']}::{r['function']} ({r['source']}) — {r['route_audit_status']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2))
    if args.output_md:
        md = ["# Proposal Creation Paths\n"]
        md.append("| File | Function | Source | Route Audit |")
        md.append("|------|----------|--------|-------------|")
        for r in results:
            md.append(f"| {r['file']} | {r['function']} | {r['source']} | {r['route_audit_status']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
