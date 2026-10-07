#!/usr/bin/env python3
"""Reconcile an approval-reminder run against an existing transport receipt.

This does not send, and it does not call the reminder planner. A transport row
counts only when it names the same run_id and a provider message id. The same
provider message id is counted once. Without that id the delivery stays
DELIVERY_UNMEASURED. Adapter success is not a receipt.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Mapping

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts"))

NO_CONSUMER_REASON = (
    "hourly lane body (minute 12, after the minute-5 reminder): reads the reminder's run receipt and "
    "its transport rows, writes the reconciled receipt and data/runtime/approval_reminder_reconcile_last.json. "
    "Never sends; a transport row without a provider message id leaves delivery DELIVERY_UNMEASURED."
)


def reconcile(receipt: Mapping[str, object], transport_rows: list[Mapping[str, object]]) -> dict:
    out = dict(receipt)
    if out.get("outcome") == "NO_ACTION" or out.get("action_count") == 0:
        out["delivery_status"] = "NO_ACTION"
        out["delivery_receipt_count"] = 0
        out["delivery_observed"] = False
        return out
    seen: set[str] = set()
    matched = 0
    run_id = str(out.get("run_id") or "")
    for row in transport_rows:
        if str(row.get("run_id") or "") != run_id:
            continue
        provider_id = str(row.get("provider_message_id") or "").strip()
        if not provider_id or provider_id in seen:
            continue
        seen.add(provider_id)
        matched += 1
    out["delivery_receipt_count"] = matched
    attempts = int(out.get("send_attempt_count") or 0)
    if matched <= 0:
        out["delivery_status"] = "DELIVERY_UNMEASURED"
        out["delivery_observed"] = False
    elif attempts and matched >= attempts:
        out["delivery_status"] = "DELIVERY_OBSERVED"
        out["delivery_observed"] = True
    else:
        out["delivery_status"] = "DELIVERY_UNMEASURED"
        out["delivery_observed"] = False
    out["outcome"] = out.get("outcome")
    if out.get("planner_status") == "SUCCESS":
        raise ValueError("refusing SUCCESS")
    return out


def reconcile_files(receipt_path: Path, transport_path: Path, *, out_path: Path | None = None) -> dict:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    rows = []
    for line in Path(transport_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    updated = reconcile(receipt, rows)
    if out_path is not None:
        tmp = Path(out_path).with_suffix(Path(out_path).suffix + ".tmp")
        tmp.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(out_path)
    return updated


def reconcile_receipt_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("TRADEAI_APPROVAL_RECONCILE_RECEIPT")
    if env:
        return Path(env)
    return PROJ / "data" / "runtime" / "approval_reminder_reconcile_last.json"


def _rows_for_run(transport: Path, run_id: str) -> list[dict]:
    if not transport.is_file():
        return []
    rows = []
    for line in transport.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and str(row.get("run_id") or "") == run_id:
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    """Reconcile the latest reminder receipt. Dry run prints; --write replaces the receipt atomically."""
    from approval_package_reminder import receipt_path, transport_path, write_run_receipt  # type: ignore

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--receipt", help="reminder run receipt (default: the reminder's own path)")
    ap.add_argument("--transport", help="transport rows jsonl (default: the reminder's own path)")
    ap.add_argument("--out", help="reconcile run receipt (default data/runtime/approval_reminder_reconcile_last.json)")
    ap.add_argument("--write", action="store_true", help="replace the reminder receipt with the reconciled one and write the run receipt")
    a = ap.parse_args(argv)
    now = _dt.datetime.now(_dt.timezone.utc)
    rpath = receipt_path(a.receipt)
    tpath = transport_path(a.transport)
    run = {"schema": "ApprovalReminderReconcileRun@v1", "as_of": now.isoformat(), "receipt": str(rpath),
           "transport": str(tpath), "written": False}
    if not rpath.is_file():
        run["status"] = "NO_RECEIPT"
        print(json.dumps(run, indent=1))
        return 0
    try:
        receipt = json.loads(rpath.read_text(encoding="utf-8"))
    except ValueError as exc:
        run["status"] = f"RECEIPT_UNREADABLE:{type(exc).__name__}"
        print(json.dumps(run, indent=1))
        return 1
    run_id = str(receipt.get("run_id") or "")
    rows = _rows_for_run(tpath, run_id)
    before = receipt.get("delivery_status")
    updated = reconcile(receipt, rows)
    run.update({"status": "RECONCILED", "run_id": run_id, "transport_rows": len(rows),
                "delivery_status_before": before, "delivery_status": updated.get("delivery_status"),
                "delivery_receipt_count": updated.get("delivery_receipt_count"),
                "reconciled_at": now.isoformat()})
    if a.write:
        updated["reconciled_at"] = now.isoformat()
        write_run_receipt(rpath, updated)
        out = reconcile_receipt_path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        run["written"] = True
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(run, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(out)
    print(json.dumps(run, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
