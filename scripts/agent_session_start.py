#!/usr/bin/env python3
"""Governed agent session start (SOP Stage 3).

Read-only by default. Mutating mode requires a MECHANICAL registered client,
hooks, documentation attestation, dirty acknowledgment, and successful leases.

Worktree / Git identity is asserted fail-closed **before any write** (leases,
receipt files, generated artifacts). Verifier mode requires
``--expected-worktree`` + ``--expected-head`` and is read-only.

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
    ap.add_argument(
        "--expected-worktree",
        default=None,
        help="canonical registered worktree path that must equal cwd and git toplevel",
    )
    ap.add_argument(
        "--expected-head",
        default=None,
        help="expected HEAD SHA (full or unique prefix); required with --verifier",
    )
    ap.add_argument(
        "--verifier",
        action="store_true",
        help="read-only verifier mode: require --expected-worktree and --expected-head",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else ROOT
    expected_wt = Path(args.expected_worktree).resolve() if args.expected_worktree else root
    if args.verifier:
        if not args.expected_worktree:
            print("error: --verifier requires --expected-worktree", file=sys.stderr)
            return 2
        if not args.expected_head:
            print("error: --verifier requires --expected-head", file=sys.stderr)
            return 2
        if args.mode == "mutating":
            print("error: --verifier cannot combine with --mode mutating", file=sys.stderr)
            return 2

    from scripts.lib.agent_session_receipt import start_session

    receipt = start_session(
        agent_id=args.agent,
        repo_root=root,
        claimed_paths=list(args.claim),
        claimed_stores=list(args.store),
        docs_read=list(args.doc_read),
        docs_searched=list(args.doc_search),
        mode="read_only" if args.verifier else args.mode,
        task_scope=args.task_scope,
        acknowledge_dirty=bool(args.acknowledge_dirty),
        expected_worktree=expected_wt,
        expected_head=args.expected_head,
        cwd=Path.cwd(),
        verifier=bool(args.verifier),
    )
    if args.json:
        print(json.dumps(receipt, indent=2, default=str))
    else:
        print(
            f"ok={receipt.get('ok')} session={receipt.get('session_id')} "
            f"agent={receipt.get('agent_id')} mode={receipt.get('mode')} "
            f"verifier={receipt.get('verifier')} errors={receipt.get('errors')}"
        )
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
