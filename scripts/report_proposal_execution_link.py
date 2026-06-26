#!/usr/bin/env python3
"""report_proposal_execution_link.py — Execution link funnel audit (read-only).

Usage:
    .venv/bin/python scripts/report_proposal_execution_link.py --since-days 5 --output-md docs/audits/EXECUTION_LINK_2026-06-26.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from proposal_execution_readiness import collect_execution_link_audit, collect_execution_readiness


def render_md(link: dict, readiness: dict) -> str:
    return f"""# Proposal Execution Link Audit — {link['generated_at'][:10]}

Window: **{link['since_days']}** days

## Funnel

| Stage | Count | Rate |
|-------|------:|-----:|
| Created | {link['created']} | — |
| Approved | {link['approved']} | {link['approval_rate_pct']}% |
| Execution-linked | {link['execution_linked']} | {link['execution_link_rate_pct']}% |
| Live-submit tagged | {link['live_submit_tagged']} | — |
| Closed trades | {link['closed_trades']} | {link['close_rate_pct']}% |
| Expired | {link['expired']} | — |
| Rejected | {link['rejected']} | — |

## Readiness (blocks)

Target link rate: **{readiness['target_link_rate_pct']}%** (current **{readiness['link_rate_pct']}%**)

Pending now: {readiness['pending_now']} · Broker unrouted >48h: {readiness['broker_unrouted_48h']}

### Risk-gate blocks (window)
{chr(10).join(f'- {k}: {v}' for k, v in readiness.get('risk_gate_blocks', {}).items()) or '- none'}

Price-block dominant: **{readiness.get('price_block_dominant')}**
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since-days", type=int, default=5)
    p.add_argument("--output-md")
    p.add_argument("--output-json")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    link = collect_execution_link_audit(since_days=args.since_days)
    readiness = collect_execution_readiness(since_days=args.since_days)
    report = {"link": link, "readiness": readiness}
    if args.verbose:
        print(json.dumps(report, indent=2))
    md = render_md(link, readiness)
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        print(f"Wrote {args.output_md}")
    else:
        print(md)
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2))
        print(f"Wrote {args.output_json}")


if __name__ == "__main__":
    main()