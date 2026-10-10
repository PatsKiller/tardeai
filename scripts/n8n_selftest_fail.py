#!/usr/bin/env python3
"""n8n_selftest_fail.py — lane `n8n-selftest-fail`: a harmless lane that fails on demand (REMEDIATION_PLAN §6 R6).

Operator decision 3 (2026-10-09 23:38 ET) approved this lane so the whole chain — executor RunReceipt -> SIEM
row -> LLM diagnosis -> bounded remediation -> escalation -> Telegram — can be proven per failure class without
breaking a real lane. It touches no store except its own receipt and its own arm file, calls nothing, sends nothing.

Failure classes (``--mode``, or the armed class when run by the executor with no ``--mode``):

    ok            write the receipt (ok_at advances), exit 0
    exit1         write nothing, print SELFTEST_INDUCED_FAILURE to stderr, exit 1          -> RUN_FAILED
    timeout       sleep --sleep-s (default 600 s) past the allowlist timeout_s (30 s)       -> RUN_TIMEOUT
    no_receipt    exit 0 without writing the receipt (output_signal never advances)         -> STALE_OUTPUT (live)
    stale_output  rewrite the receipt but pin its mtime to the previous one                 -> STALE_OUTPUT (live)

The executor's argv is fixed by the allowlist (mode dry_run|live only), so a validation run chooses the class by
ARMING it first (a durable, expiring control file; ``--count`` runs then back to ok — the S6a/S6b split):

    python3 scripts/n8n_selftest_fail.py --arm exit1 --count 1 --ttl-min 30 --dry-run   # prints the arm, writes nothing
    python3 scripts/n8n_selftest_fail.py --arm exit1 --count 1 --ttl-min 30             # writes data/runtime/n8n_selftest_fail_arm.json
    python3 scripts/n8n_selftest_fail.py --disarm
    python3 scripts/n8n_selftest_fail.py --mode exit1 --dry-run                          # plan only, exit 0, writes nothing

``--dry-run`` writes nothing — no receipt, no arm decrement — and always exits 0 with the plan on stdout.
AUTHORITY: READ_ONLY_ADVISORY. No network, no DB, no send.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "N8nSelftestLane@v1"
LANE_ID = "n8n-selftest-fail"
CLASSES = ("ok", "exit1", "timeout", "no_receipt", "stale_output")
RECEIPT_REL = "data/runtime/n8n_selftest_fail_last.json"
ARM_REL = "data/runtime/n8n_selftest_fail_arm.json"
MAX_ARM_COUNT = 5
MAX_ARM_TTL_MIN = 240
NO_CONSUMER_REASON = ("validation lane for REMEDIATION_PLAN §6 R6; consumed by the executor RunReceipt / SIEM bridge / "
                      "n8n_failure_diagnosis chain; dispatcher row proposed (shadow)")

#: PROPOSED allowlist entry (llm-remediation/PROPOSED_ROWS.md). Not in config/n8n_run_allowlist.json until the
#: reviewed registry+allowlist PR (§23.11). The catalogue generator uses it so the lane's actions are reviewable now.
PROPOSED_ALLOWLIST_ENTRY: dict[str, Any] = {
    "lane_id": LANE_ID,
    "command": ["$PY", "scripts/n8n_selftest_fail.py"],
    "dry_run_arg": ["--receipt", "$STATE_ROOT/data/runtime/n8n_runs/shadow/n8n_selftest_fail_last.json"],
    "live_arg": ["--receipt", "$STATE_ROOT/" + RECEIPT_REL],
    "lock": "/tmp/tradeai_n8n_selftest_fail.lock",
    "timeout_s": 30,
    "output_signal": RECEIPT_REL,
}


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def _atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> Optional[dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def armed(root: Path, now: datetime) -> Optional[dict[str, Any]]:
    """The live arm, or None when absent, expired, exhausted or malformed."""
    doc = _load(root / ARM_REL)
    if not doc or doc.get("class") not in CLASSES:
        return None
    try:
        exp = datetime.fromisoformat(str(doc.get("expires_at")))
    except ValueError:
        return None
    if exp <= now or int(doc.get("remaining") or 0) <= 0:
        return None
    return doc


def resolve_class(mode: Optional[str], root: Path, now: datetime) -> tuple[str, str, Optional[dict]]:
    """(class, source, arm). An explicit --mode wins; then the arm; then ok."""
    if mode:
        return mode, "argv", None
    arm = armed(root, now)
    if arm:
        return str(arm["class"]), "arm", arm
    return "ok", "default", None


def plan(cls: str, receipt: Path) -> dict[str, Any]:
    return {
        "ok": {"exit": 0, "writes": [str(receipt)]},
        "exit1": {"exit": 1, "writes": []},
        "timeout": {"exit": "killed by executor timeout_s", "writes": []},
        "no_receipt": {"exit": 0, "writes": []},
        "stale_output": {"exit": 0, "writes": [f"{receipt} (mtime pinned to previous)"]},
    }[cls]


def run_class(cls: str, receipt: Path, now: datetime, *, sleep_s: float, sleeper=time.sleep) -> int:
    if cls == "ok":
        _atomic(receipt, {"schema": SCHEMA, "lane_id": LANE_ID, "class": "ok", "ok": True, "ok_at": now.isoformat()})
        return 0
    if cls == "exit1":
        print(f"SELFTEST_INDUCED_FAILURE class=exit1 lane={LANE_ID} at={now.isoformat()}", file=sys.stderr)
        return 1
    if cls == "timeout":
        print(f"SELFTEST_INDUCED_FAILURE class=timeout sleeping {sleep_s:g}s", file=sys.stderr, flush=True)
        sleeper(sleep_s)
        return 124
    if cls == "no_receipt":
        print(f"SELFTEST_INDUCED_FAILURE class=no_receipt (receipt {receipt} not written)", file=sys.stderr)
        return 0
    # stale_output: the receipt is rewritten but its mtime does not advance, so output_signal looks stale.
    prev = _load(receipt) or {}
    try:
        old = receipt.stat().st_mtime
    except OSError:
        old = (now - timedelta(days=2)).timestamp()
    _atomic(receipt, {**prev, "schema": SCHEMA, "lane_id": LANE_ID, "class": "stale_output",
                      "ok_at": prev.get("ok_at"), "stale_written_at": now.isoformat()})
    os.utime(receipt, (old, old))
    print(f"SELFTEST_INDUCED_FAILURE class=stale_output (mtime pinned to {old})", file=sys.stderr)
    return 0


def main(argv: Optional[list[str]] = None, *, now: Optional[datetime] = None, sleeper=time.sleep) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", choices=CLASSES, default=None)
    ap.add_argument("--receipt", default=None, help=f"receipt path (default $TRADEAI_STATE_ROOT/{RECEIPT_REL})")
    ap.add_argument("--sleep-s", type=float, default=600.0)
    ap.add_argument("--arm", choices=CLASSES, default=None, help="arm a class for the next --count executor runs")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--ttl-min", type=float, default=30.0)
    ap.add_argument("--disarm", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; write nothing; exit 0")
    args = ap.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    root = state_root()
    receipt = Path(args.receipt) if args.receipt else root / RECEIPT_REL
    arm_path = root / ARM_REL
    if args.arm or args.disarm:
        if args.arm:
            count = max(1, min(MAX_ARM_COUNT, int(args.count)))
            ttl = max(1.0, min(MAX_ARM_TTL_MIN, float(args.ttl_min)))
            doc = {"schema": "N8nSelftestArm@v1", "lane_id": LANE_ID, "class": args.arm, "remaining": count,
                   "armed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=ttl)).isoformat()}
        else:
            doc = {"schema": "N8nSelftestArm@v1", "lane_id": LANE_ID, "class": "ok", "remaining": 0,
                   "armed_at": now.isoformat(), "expires_at": now.isoformat(), "disarmed": True}
        if args.dry_run:
            print(json.dumps({"mode": "dry-run", "would_write": str(arm_path), "arm": doc}))
            return 0
        _atomic(arm_path, doc)
        print(json.dumps({"mode": "arm", "wrote": str(arm_path), "arm": doc}))
        return 0
    cls, source, arm = resolve_class(args.mode, root, now)
    report = {"lane_id": LANE_ID, "class": cls, "class_source": source, "receipt": str(receipt), **plan(cls, receipt)}
    if args.dry_run:
        print(json.dumps({"mode": "dry-run", **report}))
        return 0
    if arm is not None:   # consume one armed run before acting, so a killed (timeout) run still counts
        _atomic(arm_path, {**arm, "remaining": int(arm["remaining"]) - 1, "last_consumed_at": now.isoformat()})
    print(json.dumps({"mode": "run", **report}), flush=True)
    return run_class(cls, receipt, now, sleep_s=float(args.sleep_s), sleeper=sleeper)


if __name__ == "__main__":
    raise SystemExit(main())
