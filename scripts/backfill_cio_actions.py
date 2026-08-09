#!/usr/bin/env python3
"""Backfill CIO actions from heartbeat snapshots to accelerate gate 1 (100 artifacts).

Generates one action per snapshot summarizing domain health, plus drift-detection
actions for material changes between consecutive snapshots.

Usage:
  python scripts/backfill_cio_actions.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.environ.get(
    "TRADE_AI_PROJECT_ROOT",
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
))
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "cio"
ACTION_LEDGER = SNAPSHOT_DIR / "cio_action_ledger.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dval(domains: dict, domain: str, field: str, default: Any = None) -> Any:
    d = domains.get(domain, {})
    data = d.get("data", d)
    return data.get(field, default)


def _make_action(aid: str, domain: str, priority: str, title: str, why_now: str,
                 ts: str, notif: str = "Info", **extra: Any) -> dict[str, Any]:
    return {
        "cio_action_id": aid,
        "status": "OPEN",
        "source": "backfill",
        "created_at": ts,
        "timestamp": ts,
        "priority": priority,
        "domain": domain,
        "title": title,
        "why_now": why_now,
        "estimated_financial_impact": extra.get("estimated_financial_impact", ""),
        "notification_priority": notif,
        "origin_run_id": "",
        "cio_artifact_id": "",
        "followup_condition": "",
        "operator_decision_required": "True",
        "affected_symbols": "[]",
        "affected_accounts": "[]",
        "dependencies": "[]",
        "evidence_refs": "[]",
        "specialist_artifact_refs": "[]",
        "source_snapshot_id": extra.get("snapshot_id", ""),
    }


def run_backfill(dry_run: bool = False) -> dict[str, Any]:
    import time as _time
    t0 = _time.time()
    snapshots = _read_jsonl(SNAPSHOT_DIR / "cio_heartbeat_snapshots.jsonl")
    existing = _read_jsonl(ACTION_LEDGER)
    existing_titles: set[str] = {e.get("payload", {}).get("title", "") for e in existing}

    created = 0

    # 1. Per-snapshot domain health summary (one action per snapshot)
    for snap in snapshots:
        domains = snap.get("domains", {})
        available = [n for n, d in domains.items() if d.get("state") == "AVAILABLE"]
        missing = [n for n, d in domains.items() if d.get("state") != "AVAILABLE"]
        ts = snap.get("collected_at", _now_iso())
        sid = snap.get("snapshot_id", "unknown")

        title = f"[Backfill] Snapshot {sid[:8]}: {len(available)}/{len(domains)} domains OK"
        if title in existing_titles:
            continue
        why = f"{len(available)}/{len(domains)} domains available"
        if missing:
            why += f". Missing: {', '.join(missing[:3])}"

        payload = _make_action(
            f"cio-bf-{uuid.uuid4().hex[:8]}", "system", "LOW",
            title, why, ts, "Info", snapshot_id=sid)

        if not dry_run:
            _append_jsonl(ACTION_LEDGER, {
                "event_type": "CIO_ACTION_CREATED",
                "event_id": str(uuid.uuid4()),
                "timestamp": ts,
                "actor": "backfill",
                "authority": "advisory",
                "payload": payload,
            })
        created += 1
        existing_titles.add(title)

    # 2. Domain drift between consecutive snapshots
    for i in range(len(snapshots) - 1):
        prev_d = snapshots[i].get("domains", {})
        curr_d = snapshots[i + 1].get("domains", {})
        ts = snapshots[i + 1].get("collected_at", _now_iso())
        sid = snapshots[i + 1].get("snapshot_id", "")

        # Portfolio value change > 1 pct
        pv = float(_dval(prev_d, "portfolio", "total_value", 0) or 0)
        cv = float(_dval(curr_d, "portfolio", "total_value", 0) or 0)
        if pv > 0 and cv > 0 and abs(cv - pv) / pv > 0.01:
            d = "up" if cv > pv else "down"
            pct = abs(cv - pv) / pv * 100
            title = f"[Backfill] Portfolio {d} {pct:.1f} pct"
            if title not in existing_titles:
                payload = _make_action(
                    f"cio-bf-{uuid.uuid4().hex[:8]}", "portfolio", "MEDIUM",
                    title, f"${pv:,.0f} → ${cv:,.0f}", ts, "Medium",
                    estimated_financial_impact=f"${abs(cv-pv):,.0f}", snapshot_id=sid)
                if not dry_run:
                    _append_jsonl(ACTION_LEDGER, {
                        "event_type": "CIO_ACTION_CREATED",
                        "event_id": str(uuid.uuid4()),
                        "timestamp": ts, "actor": "backfill",
                        "authority": "advisory", "payload": payload,
                    })
                created += 1
                existing_titles.add(title)

        # Allocation drift > 1 pct
        pa = _dval(prev_d, "model_portfolio", "actual_equity_pct")
        ca = _dval(curr_d, "model_portfolio", "actual_equity_pct")
        if pa is not None and ca is not None and abs(float(ca) - float(pa)) > 1.0:
            d = "widened" if abs(float(ca)) > abs(float(pa)) else "narrowed"
            title = f"[Backfill] Allocation drift {d} to {ca} pct equity"
            if title not in existing_titles:
                payload = _make_action(
                    f"cio-bf-{uuid.uuid4().hex[:8]}", "allocation", "MEDIUM",
                    title, f"Equity {pa} pct → {ca} pct", ts, "Medium",
                    snapshot_id=sid)
                if not dry_run:
                    _append_jsonl(ACTION_LEDGER, {
                        "event_type": "CIO_ACTION_CREATED",
                        "event_id": str(uuid.uuid4()),
                        "timestamp": ts, "actor": "backfill",
                        "authority": "advisory", "payload": payload,
                    })
                created += 1
                existing_titles.add(title)

    elapsed = _time.time() - t0
    return {
        "actions_created": created,
        "snapshots": len(snapshots),
        "dry_run": dry_run,
        "elapsed_ms": int(elapsed * 1000),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill CIO actions from heartbeat snapshots")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"CIO Action Backfill — {_now_iso()[:19]}  dry_run={args.dry_run}")
    summary = run_backfill(dry_run=args.dry_run)
    print(f"  {json.dumps(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
