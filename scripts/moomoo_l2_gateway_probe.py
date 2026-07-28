#!/usr/bin/env python3
"""Operator-run, data-only host proof for the dedicated Moomoo L2 gateway.

The probe only reads the IPC snapshot. It never opens OpenD, changes intent, subscribes,
unsubscribes, restarts services, writes a database, or touches an order path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from moomoo.gateway_ipc import SnapshotClient  # noqa: E402

REQUIRED_SUBTYPES = {"QUOTE", "ORDER_BOOK", "TICKER"}


def evaluate_snapshot(payload: dict[str, Any], symbol: Optional[str] = None, *, require_t2: bool = False) -> dict[str, Any]:
    provider = payload.get("provider") or {}
    symbols = payload.get("symbols") or {}
    desired = payload.get("desired_intent") or {}
    selected = str(symbol or "").upper()
    if not selected:
        selected = next(iter(sorted(desired)), "") or next(iter(sorted(symbols)), "")
    detail = symbols.get(selected) or {}
    provider_subtypes = set(detail.get("provider_subtypes") or (provider.get("subscriptions_by_symbol") or {}).get(selected) or [])
    confirmed = set(detail.get("confirmed_subtypes") or [])
    book = detail.get("book") or {}
    tape = detail.get("tape") or {}
    quote = detail.get("quote") or {}
    mark = (payload.get("current_marks") or {}).get(selected) or {}
    checks = {
        "owner_lock": bool((payload.get("owner") or {}).get("exclusive_lock_held")),
        "service_running": payload.get("service_state") == "RUNNING",
        "provider_connected": bool(provider.get("connected")),
        "entitlement_realtime": bool(provider.get("entitled_realtime")),
        "quota_reconciled": isinstance(payload.get("quota"), dict) and (payload.get("quota") or {}).get("remain") is not None,
        "symbol_selected": bool(selected),
        "symbol_is_desired": selected in desired,
        "provider_subtypes": REQUIRED_SUBTYPES.issubset(provider_subtypes),
        "observed_subtypes": REQUIRED_SUBTYPES.issubset(confirmed),
        "book_provider_time": bool(book.get("bid_provider_at") or book.get("ask_provider_at") or book.get("provider_at")),
        "book_receive_time": bool(book.get("received_at")),
        "book_sequence_labeled": bool(book.get("sequence_id") is not None and book.get("sequence_source")),
        "tape_provider_time": bool(tape.get("provider_at")),
        "tape_receive_time": bool(tape.get("received_at")),
        "ticker_provider_sequence": tape.get("provider_sequence") is not None,
        "quote_provider_time": bool(quote.get("provider_at")),
        "quote_receive_time": bool(quote.get("received_at")),
        "current_mark_fresh": bool(mark.get("available") and not mark.get("stale") and mark.get("received_at")),
        "journal_declared": bool((payload.get("journal") or {}).get("durable_replay_available")),
        "zero_order_authority": payload.get("order_path") is False and not any((payload.get("authority") or {}).values()),
    }
    if require_t2:
        checks["t2_admitted"] = bool((detail.get("t2") or {}).get("is_t2"))
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "contract": "moomoo-l2-gateway-host-proof-v1",
        "pass": not failures,
        "symbol": selected or None,
        "gateway_source_commit": payload.get("source_commit"),
        "heartbeat_at": payload.get("heartbeat_at"),
        "reconnect_epoch": provider.get("reconnect_epoch"),
        "provider_subtypes": sorted(provider_subtypes),
        "confirmed_subtypes": sorted(confirmed),
        "book": book,
        "tape": tape,
        "quote": quote,
        "current_mark": mark,
        "quota": payload.get("quota"),
        "checks": checks,
        "failures": failures,
        "authority": {
            "snapshot_read": True,
            "opend_context": False,
            "intent_write": False,
            "subscription_change": False,
            "database_write": False,
            "service_change": False,
            "order": False,
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Moomoo L2 gateway host proof")
    parser.add_argument("--snapshot", help="snapshot path; defaults to MOOMOO_L2_GATEWAY_SNAPSHOT")
    parser.add_argument("--symbol", help="must already be present in desired intent")
    parser.add_argument("--max-age", type=float, default=5.0)
    parser.add_argument("--require-t2", action="store_true")
    args = parser.parse_args(argv)
    client = SnapshotClient(args.snapshot, max_age_seconds=args.max_age)
    read = client.read()
    if not read.fresh or read.payload is None:
        result = {
            "contract": "moomoo-l2-gateway-host-proof-v1",
            "pass": False,
            "failures": [read.reason],
            "snapshot_path": str(client.path),
            "snapshot_age_seconds": read.age_seconds,
            "authority": {"snapshot_read": True, "opend_context": False, "subscription_change": False, "order": False},
        }
    else:
        result = evaluate_snapshot(read.payload, args.symbol, require_t2=args.require_t2)
        result["snapshot_path"] = str(client.path)
        result["snapshot_age_seconds"] = read.age_seconds
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
