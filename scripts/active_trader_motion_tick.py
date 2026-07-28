#!/usr/bin/env python3
"""Produce or record Active Trader shadow motion evidence.

This utility is intentionally one-shot. A future supervised service/timer may invoke
``tick`` at the cadence returned in the snapshot. The script itself does not loop,
subscribe to data, or call a broker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.motion_engine import MotionEngine  # noqa: E402
from active_trader.motion_journal import ALLOWED_KINDS, MotionJournal  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI  # noqa: E402


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _default_session_store() -> Path:
    env = os.environ.get("ACTIVE_TRADER_SESSION_STORE", "").strip()
    return Path(env).expanduser() if env else ROOT / "data" / "active_trader" / "sessions.json"


def _load_active_session(path: str | Path | None = None) -> dict[str, Any]:
    session_path = Path(path).expanduser() if path else _default_session_store()
    try:
        raw = _load_json(session_path)
    except Exception:
        return {}
    if not isinstance(raw, Mapping):
        return {}
    sessions = [value for value in raw.values() if isinstance(value, Mapping)]
    sessions.sort(key=lambda row: float(row.get("updated_at") or 0.0), reverse=True)
    for session in sessions:
        if str(session.get("state") or "").upper() == "ACTIVE":
            return dict(session)
    return dict(sessions[0]) if sessions else {}


def _dedupe_candidates(queue: Mapping[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    signals = queue.get("signals") if isinstance(queue.get("signals"), list) else []
    arming = queue.get("arming") if isinstance(queue.get("arming"), Mapping) else {}
    near = arming.get("near_firing") if isinstance(arming.get("near_firing"), list) else []
    for row in [*signals, *near]:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        current = merged.get(symbol, {})
        # Rich IGN/trigger evidence wins, while scanner timestamps/prices fill gaps.
        merged[symbol] = {**current, **dict(row), "symbol": symbol}
    return list(merged.values())


def _record(args: argparse.Namespace) -> int:
    payload = _load_json(args.payload_json)
    if not isinstance(payload, Mapping):
        raise SystemExit("payload JSON must be an object")
    journal = MotionJournal(args.journal, fsync=args.fsync)
    record = journal.append(args.kind, payload, recorded_at=args.recorded_at)
    print(json.dumps(record, indent=2, sort_keys=True, default=str))
    return 0


def _tick(args: argparse.Namespace) -> int:
    api = ReadOnlyActiveTraderAPI()
    queue = api.permission_queue()
    candidates = _dedupe_candidates(queue)
    session = _load_active_session(args.session_store)
    journal = MotionJournal(args.journal, fsync=args.fsync)
    engine = MotionEngine(
        snapshot_path=args.snapshot,
        state_path=args.state,
        journal=journal,
    )
    snapshot = engine.tick(
        candidates,
        session=session,
        now=args.now if args.now is not None else time.time(),
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    tick = sub.add_parser("tick", help="produce one aggregate motion snapshot")
    tick.add_argument("--snapshot", default=None)
    tick.add_argument("--state", default=None)
    tick.add_argument("--journal", default=None)
    tick.add_argument("--session-store", default=None)
    tick.add_argument("--now", type=float, default=None)
    tick.add_argument("--fsync", action="store_true")
    tick.set_defaults(func=_tick)

    record = sub.add_parser("record", help="append one local shadow observation")
    record.add_argument("--kind", required=True, choices=sorted(ALLOWED_KINDS - {"motion_snapshot"}))
    record.add_argument("--payload-json", required=True)
    record.add_argument("--journal", default=None)
    record.add_argument("--recorded-at", type=float, default=None)
    record.add_argument("--fsync", action="store_true")
    record.set_defaults(func=_record)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
