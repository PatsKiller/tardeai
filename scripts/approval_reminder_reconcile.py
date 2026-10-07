#!/usr/bin/env python3
"""Reconcile an approval-reminder run against an existing transport receipt.

This does not send, and it does not call the reminder planner. A transport row
counts only when it names the same run_id and a provider message id. The same
provider message id is counted once. Without that id the delivery stays
DELIVERY_UNMEASURED. Adapter success is not a receipt.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


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
