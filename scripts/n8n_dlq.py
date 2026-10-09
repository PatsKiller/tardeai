#!/usr/bin/env python3
"""Host CLI for the n8n dispatch dead-letter queue and lane breakers (n8n maturity B5.4, design 02 §3.3).

    n8n_dlq.py list [--lane L] [--all] [--json]
    n8n_dlq.py release --slot-key K --note N [--by WHO] [--dry-run]
    n8n_dlq.py release --lane L --note N [--by WHO] [--dry-run]

``release --slot-key`` marks one dead letter released; ``coordination/due`` then re-arms that slot as RETRY_DUE
(attempt = attempts + 1, reason ``dlq_release``) while it is inside its catch-up window. ``release --lane`` releases
every unreleased dead letter of the lane AND its open breaker. Every real release appends one DeadLetterRelease@v1
line to ``<state root>/data/runtime/n8n_dlq_releases.jsonl`` (``--receipts`` overrides). ``--dry-run`` prints what
would be released and writes nothing. The ledger path resolves exactly as the gateway/executor resolve it
(``TRADEAI_N8N_COORDINATION_LEDGER`` / ``TRADEAI_STATE_ROOT``); ``--ledger`` overrides. A missing ledger file is
refused, never created.

Review of #1594: ``list`` opens the ledger READ-ONLY (no migration of a production schema). A dead letter that
``dead_letter_rearmable`` refuses (class send/learn, single-attempt policy, unknown class/policy) is never
released: ``--slot-key`` exits 4 with a typed ``release_refused`` error; ``--lane`` releases the breaker and the
re-armable dead letters and lists the refused ones. The receipt is written (fsync'd, ``phase: intent``) BEFORE the
single ledger transaction, then a ``phase: committed`` (or ``aborted``) line follows it.

Exit codes: 0 ok, 2 usage, 3 not found (no ledger, no such dead letter, nothing to release on the lane),
4 refused (every target is non-re-armable).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

NO_CONSUMER_REASON = (
    "Operator/agent host CLI (design 02 §3.3 release path); writes DeadLetterRelease@v1 receipts that the "
    "coordination/due route (B5.3) honours through the ledger rows, not by reading the receipt file."
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_coordination_ledger import (  # noqa: E402
    CoordinationLedger,
    LedgerError,
    LedgerRunStore,
    dead_letter_rearmable,
)
from scripts.lib.n8n_pilot_observations import state_root  # noqa: E402
from scripts.n8n_coordination_gateway import default_ledger_path  # noqa: E402

RECEIPT_SCHEMA = "DeadLetterRelease@v1"
RECEIPTS_REL = Path("data") / "runtime" / "n8n_dlq_releases.jsonl"
EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND, EXIT_REFUSED = 0, 2, 3, 4


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="n8n dispatch dead-letter queue and lane breakers")
    ap.add_argument("--ledger", default=None, help="coordination ledger (default: gateway/executor resolution)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="list dead letters (unreleased unless --all) and open breakers")
    ls.add_argument("--lane", default=None)
    ls.add_argument("--all", action="store_true", help="include released dead letters")
    ls.add_argument("--json", action="store_true")
    rel = sub.add_parser("release", help="release one dead letter, or a lane's dead letters and its breaker")
    tgt = rel.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--slot-key", default=None)
    tgt.add_argument("--lane", default=None)
    rel.add_argument("--note", required=True)
    rel.add_argument("--by", default=None, help="who releases (default: $USER)")
    rel.add_argument("--dry-run", action="store_true")
    rel.add_argument("--receipts", default=None, help="DeadLetterRelease@v1 jsonl path override")
    return ap


def _ledger_path(arg: str | None) -> Path:
    return Path(arg) if arg else default_ledger_path(dict(os.environ))


def _cmd_list(store: LedgerRunStore, args: argparse.Namespace) -> int:
    rows = store.list_dead_letters(args.lane, include_released=args.all)
    lanes = sorted({args.lane} if args.lane else {r["lane_id"] for r in store.list_dead_letters(None, True)})
    breakers = [b for b in (store.breaker(lane) for lane in lanes) if b and b["open"]]
    if args.json:
        print(json.dumps({"dead_letters": rows, "open_breakers": breakers}, indent=1, sort_keys=True))
        return EXIT_OK
    for r in rows:
        flag = " released" if r["released_at"] else ""
        print(f"{r['slot_key']}  lane={r['lane_id']} attempts={r['attempts']} {r['last_state']}"
              f" {r['last_reason'] or ''} dead_at={r['dead_at']}{flag}")
    for b in breakers:
        print(f"BREAKER OPEN lane={b['lane_id']} consecutive={b['consecutive']} opened_at={b['opened_at']}")
    if not rows and not breakers:
        print("no dead letters")
    return EXIT_OK


def _append_receipt(path: Path, body: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(body), sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _cmd_release(store: LedgerRunStore, args: argparse.Namespace, ledger_path: Path) -> int:
    by = args.by or os.environ.get("USER") or "unknown"
    now = time.time()
    with store.lock:
        if args.slot_key:
            row = store.get_dead_letter(args.slot_key)
            candidates = [row] if row and not row["released_at"] else []
            breaker = None
        else:
            candidates = store.list_dead_letters(args.lane)
            b = store.breaker(args.lane)
            breaker = b if b and b["open"] else None
        targets, refused = [], []
        for c in candidates:
            ok, why = dead_letter_rearmable(c)
            (targets if ok else refused).append(c if ok else {"slot_key": c["slot_key"], "reason": why})
        if not targets and breaker is None:
            if refused:
                print(json.dumps({"error": "release_refused", "refused": refused}), file=sys.stderr)
                return EXIT_REFUSED
            print(json.dumps({"error": "not_found", "slot_key": args.slot_key, "lane": args.lane}), file=sys.stderr)
            return EXIT_NOT_FOUND
        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "phase": "intent",
            "at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "by": by,
            "note": args.note,
            "target": {"slot_key": args.slot_key} if args.slot_key else {"lane_id": args.lane},
            "dry_run": bool(args.dry_run),
            "ledger": str(ledger_path),
            "released": [{k: t[k] for k in ("slot_key", "lane_id", "attempts", "last_state", "dead_at", "class",
                                            "max_attempts")} for t in targets],
            "refused": refused,
            "breaker_released": breaker is not None,
        }
        if args.dry_run:
            print(json.dumps(receipt, indent=1, sort_keys=True))
            return EXIT_OK
        out = Path(args.receipts) if args.receipts else state_root() / RECEIPTS_REL
        _append_receipt(out, receipt)  # durable BEFORE the ledger commit
        try:
            store.release_dead_letters([t["slot_key"] for t in targets], by, args.note, now,
                                       breaker_lane=args.lane if breaker is not None else None)
        except (LedgerError, OSError, ValueError) as exc:
            _append_receipt(out, {**receipt, "phase": "aborted", "error": str(exc)})
            print(json.dumps({"error": "release_failed", "detail": str(exc)}), file=sys.stderr)
            return EXIT_REFUSED if str(exc).startswith("release_refused") else EXIT_NOT_FOUND
        _append_receipt(out, {**receipt, "phase": "committed"})
    print(json.dumps({**receipt, "phase": "committed", "receipt_path": str(out)}, indent=1, sort_keys=True))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0) and EXIT_USAGE
    ledger_path = _ledger_path(args.ledger)
    if not ledger_path.is_file():
        print(json.dumps({"error": "ledger_not_found", "ledger": str(ledger_path)}), file=sys.stderr)
        return EXIT_NOT_FOUND
    ro = CoordinationLedger(ledger_path, read_only=True)  # never migrates
    try:
        migrated = ro.has_table("dead_letters")
        if args.cmd == "list":
            if not migrated:
                print(json.dumps({"dead_letters": [], "open_breakers": [], "schema_not_migrated": True}))
                return EXIT_OK
            return _cmd_list(LedgerRunStore(ro), args)
    finally:
        ro.close()
    if not migrated:  # nothing can be dead-lettered in a ledger without the table; do not migrate it here
        print(json.dumps({"error": "not_found", "schema_not_migrated": True}), file=sys.stderr)
        return EXIT_NOT_FOUND
    ledger = CoordinationLedger(ledger_path)
    try:
        return _cmd_release(LedgerRunStore(ledger), args, ledger_path)
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
