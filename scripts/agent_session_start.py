#!/usr/bin/env python3
"""Governed agent session start (SOP Stage 3).

Read-only by default. Mutating mode requires a MECHANICAL registered client,
hooks, documentation attestation, dirty acknowledgment, and successful leases.

Does not authorize remote sync, deployment, production, or financial authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", required=True, help="agent_id from config/agent_clients.yaml")
    ap.add_argument("--mode", choices=("read_only", "mutating"), default="read_only")
    ap.add_argument("--claim", action="append", default=[], help="repo-relative path claim (repeatable)")
    ap.add_argument("--store", action="append", default=[], help="named state-store claim")
    ap.add_argument("--doc-read", action="append", default=[], help="document path attested as read")
    ap.add_argument("--doc-search", action="append", default=[], help="search term attested")
    ap.add_argument("--task-scope", default="")
    ap.add_argument("--acknowledge-dirty", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None, help="repo root (default: detect)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else ROOT
    from scripts.lib.agent_session_receipt import start_session

    receipt = start_session(
        agent_id=args.agent,
        repo_root=root,
        claimed_paths=list(args.claim),
        claimed_stores=list(args.store),
        docs_read=list(args.doc_read),
        docs_searched=list(args.doc_search),
        mode=args.mode,
        task_scope=args.task_scope,
        acknowledge_dirty=bool(args.acknowledge_dirty),
    )
    if args.json:
        print(json.dumps(receipt, indent=2, default=str))
    else:
        print(
            f"ok={receipt.get('ok')} session={receipt.get('session_id')} "
            f"agent={receipt.get('agent_id')} mode={receipt.get('mode')} "
            f"errors={receipt.get('errors')}"
        )
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
