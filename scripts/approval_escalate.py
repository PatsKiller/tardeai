#!/usr/bin/env python3
"""approval_escalate.py — host lane for tradeai-approval-router. Read-only.

Builds the approval board (open packages, grants near expiry) and writes a
LaneRunReceipt. It does not mint, approve, extend, or settle a grant, and it
does not send. The n8n workflow only POSTs /run; the host notifier sends.

--dry-run is the default. --apply writes data/runtime/approval-escalate_last.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

PROJ = Path(__file__).resolve().parents[1]
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

LANE_ID = "approval-escalate"
RECEIPT_REL = Path("data/runtime/approval-escalate_last.json")


def build_report(board: Mapping[str, Any]) -> dict[str, Any]:
    expiring = board.get("expiring") or []
    return {
        "lane_id": LANE_ID,
        "authority": "READ_ONLY_ADVISORY",
        "status": board.get("status"),
        "expiring_count": int(board.get("expiring_count") or len(expiring)),
        "expiring_ids": [str(row.get("id")) for row in expiring if isinstance(row, dict)],
        "note": "read-only board; this lane does not approve, grant, or send",
    }


def write_receipt(report: Mapping[str, Any], root: Path, *, ok: bool) -> Path:
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "schema": "LaneRunReceipt@v1",
        "lane_id": LANE_ID,
        "ok_at": now if ok else None,
        "finished_at": now,
        "report": dict(report),
        "authority": "READ_ONLY_ADVISORY",
    }
    out = root / RECEIPT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out


def run(
    *,
    apply: bool,
    root: Path,
    board_loader: Optional[Callable[[], Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    if board_loader is None:
        from scripts.lib.approval_board_projection import build_board

        board = build_board()
    else:
        board = board_loader()
    report = build_report(board)
    report["applied"] = apply
    if apply:
        write_receipt(report, root, ok=board.get("status") != "UNAVAILABLE")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only approval escalation board")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    apply = bool(args.apply) and not args.dry_run
    report = run(apply=apply, root=Path(args.root))
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("status") != "UNAVAILABLE" or not apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
