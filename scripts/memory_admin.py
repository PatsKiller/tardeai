#!/usr/bin/env python3
"""Operator/admin CLI for durable governed memory. READ_ONLY_ADVISORY.

Never grants broker/order/stop/risk/2FA authority. Admission is fail-closed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider, default_store_path
from scripts.lib.agent_memory_admission import admit_candidate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Durable memory admin (advisory only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--type", required=True)
    admit.add_argument("--subject", required=True)
    admit.add_argument("--content", required=True)
    admit.add_argument("--source", required=True, help="source_ref, e.g. case:1")
    admit.add_argument("--source-kind", default="operator_feedback")
    admit.add_argument("--symbols", default="")
    admit.add_argument("--by", default="operator")
    sub.add_parser("health")
    search = sub.add_parser("search")
    search.add_argument("--query", required=True)
    retract = sub.add_parser("retract")
    retract.add_argument("--id", required=True, help="memory_id to retract")
    retract.add_argument("--reason", default="operator")
    retract.add_argument("--apply", action="store_true", help="persist retraction (otherwise dry-run)")
    args = p.parse_args(argv)
    prov = DurableJsonlMemoryProvider(path=default_store_path())
    if args.cmd == "health":
        print(json.dumps(prov.health(), indent=2, default=str))
        return 0
    if args.cmd == "search":
        print(json.dumps(prov.search(query=args.query), indent=2, default=str))
        return 0
    if args.cmd == "retract":
        rec = prov.get(args.id)
        out = {
            "memory_id": args.id,
            "found": rec is not None,
            "status_before": (rec or {}).get("status"),
            "apply": bool(args.apply),
            "retracted": False,
            "reason": args.reason,
            "authority": "READ_ONLY_ADVISORY",
            "financial_action": False,
        }
        if rec is None:
            print(json.dumps(out, indent=2, default=str))
            return 2
        if args.apply:
            out["retracted"] = bool(prov.retract(args.id, reason=args.reason))
            stored = prov.get(args.id) or {}
            out["status_after"] = stored.get("status")
            out["retraction_reason"] = stored.get("retraction_reason")
        print(json.dumps(out, indent=2, default=str))
        return 0 if (out["retracted"] or not args.apply) else 2
    if args.cmd == "admit":
        rec = admit_candidate({
            "memory_type": args.type,
            "subject": args.subject,
            "content": args.content,
            "source_refs": [args.source],
            "source_kind": args.source_kind,
            "symbols": [s for s in args.symbols.split(",") if s],
        }, provider=prov, admitted_by=args.by)
        print(json.dumps(rec, indent=2, default=str))
        return 0 if rec.get("accepted") else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
