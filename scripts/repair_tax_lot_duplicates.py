#!/usr/bin/env python3
"""Phase A: remove exact-duplicate CLOSED tax lots, and nothing else.

A writer defect appended the whole transaction history on top of its own previous output
on every run, leaving tax_lots.json 98% duplicates. The duplicates split into two
populations with completely different risk, and this tool only ever touches one of them.

  CLOSED duplicates   shares_remaining == 0. Removing them changes no quantity, no cost
                      basis and no realized gain. Provably lossless, and this tool
                      removes them.

  OPEN duplicates     removing them CHANGES a share count -- by up to 100x in the
                      observed data (ARKQ 11,300 -> 100). None of the fifteen affected
                      securities is still held at the broker, so no authority can say
                      which value is right. This tool refuses to touch them, and fails
                      closed if asked.

The invariants are checked after the rewrite, in memory, before anything is written:
every record's open-lot total is unchanged, every open lot survives byte-identical, the
key set is unchanged, and no lot that was not an exact duplicate of a retained lot is
missing. Any violation aborts with the file untouched.

    python3 scripts/repair_tax_lot_duplicates.py --path <tax_lots.json>            # dry run
    python3 scripts/repair_tax_lot_duplicates.py --path <...> --apply --backup-dir <dir>
"""

from __future__ import annotations

NO_CONSUMER_REASON = (
    "one-shot data repair with an evidence receipt an operator reads; the schema stamps that "
    "receipt rather than being imported by another module."
)

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "TaxLotDuplicateRepair@v1"


class RepairRefusal(RuntimeError):
    def __init__(self, rail: str, detail: str):
        super().__init__(f"REFUSED[{rail}]: {detail}")
        self.rail, self.detail = rail, detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ident(lot: dict) -> str:
    return json.dumps(lot, sort_keys=True, default=str)


def is_closed(lot: dict) -> bool:
    """A lot is closed only if it says so AND carries no remaining shares.

    Both conditions, deliberately. A row flagged closed while still holding shares is
    not something this tool should quietly delete a copy of.
    """
    if not isinstance(lot, dict):
        return False
    try:
        remaining = float(lot.get("shares_remaining") or 0)
    except (TypeError, ValueError):
        return False
    return bool(lot.get("closed")) and remaining == 0.0


def open_total(lots: Any) -> float:
    if not isinstance(lots, list):
        return 0.0
    total = 0.0
    for lot in lots:
        if isinstance(lot, dict) and not is_closed(lot):
            try:
                total += float(lot.get("shares_remaining") or 0)
            except (TypeError, ValueError):
                continue
    return round(total, 6)


def dedupe_record(lots: Any) -> tuple[Any, dict[str, Any]]:
    """Drop repeat occurrences of exact-duplicate CLOSED lots. Order is preserved."""
    if not isinstance(lots, list):
        return lots, {"removed": 0, "kept": 0, "skipped_open_duplicates": 0}

    seen_closed: set[str] = set()
    seen_open: set[str] = set()
    kept: list[Any] = []
    removed = 0
    open_dupes = 0

    for lot in lots:
        if not isinstance(lot, dict):
            kept.append(lot)
            continue
        ident = _ident(lot)
        if is_closed(lot):
            if ident in seen_closed:
                removed += 1
                continue
            seen_closed.add(ident)
        else:
            # An open duplicate is counted and KEPT. Removing it would change a share
            # count that no authority has confirmed.
            if ident in seen_open:
                open_dupes += 1
            seen_open.add(ident)
        kept.append(lot)

    return kept, {"removed": removed, "kept": len(kept), "skipped_open_duplicates": open_dupes}


def verify_invariants(before: dict, after: dict) -> dict[str, Any]:
    """Everything that must still be true. Any failure aborts before a write."""
    problems: list[str] = []

    if set(before) != set(after):
        lost = sorted(set(before) - set(after))
        gained = sorted(set(after) - set(before))
        problems.append(f"key set changed (lost={lost[:5]} gained={gained[:5]})")

    for key in sorted(set(before) & set(after)):
        b, a = before[key], after[key]
        bt, at = open_total(b), open_total(a)
        if bt != at:
            problems.append(f"{key}: open-lot total moved {bt} -> {at}")
        if isinstance(b, list) and isinstance(a, list):
            b_open = [_ident(x) for x in b if isinstance(x, dict) and not is_closed(x)]
            a_open = [_ident(x) for x in a if isinstance(x, dict) and not is_closed(x)]
            if b_open != a_open:
                problems.append(f"{key}: open lots changed ({len(b_open)} -> {len(a_open)})")
            # Every retained lot must have existed before; nothing is invented.
            if not set(a_open + [_ident(x) for x in a if isinstance(x, dict) and is_closed(x)]).issubset(
                set(_ident(x) for x in b if isinstance(x, dict))
            ):
                problems.append(f"{key}: a lot exists after that did not exist before")
            # Every distinct closed lot must survive; only repeats go.
            b_closed = {_ident(x) for x in b if isinstance(x, dict) and is_closed(x)}
            a_closed = {_ident(x) for x in a if isinstance(x, dict) and is_closed(x)}
            if b_closed != a_closed:
                problems.append(f"{key}: a DISTINCT closed lot was lost ({len(b_closed)} -> {len(a_closed)})")

    return {"ok": not problems, "problems": problems}


def repair(doc: dict) -> tuple[dict, dict[str, Any]]:
    out: dict = {}
    per_record: list[dict] = []
    removed = kept = open_dupes = 0

    for key, value in doc.items():
        if ":" not in key or not isinstance(value, list):
            out[key] = value  # envelope keys and non-lot values pass through untouched
            continue
        new_lots, stats = dedupe_record(value)
        out[key] = new_lots
        removed += stats["removed"]
        kept += stats["kept"]
        open_dupes += stats["skipped_open_duplicates"]
        if stats["removed"] or stats["skipped_open_duplicates"]:
            per_record.append(
                {
                    "record_key": key,
                    "lots_before": len(value),
                    "lots_after": len(new_lots),
                    "closed_duplicates_removed": stats["removed"],
                    "open_duplicates_left_alone": stats["skipped_open_duplicates"],
                    "open_total_before": open_total(value),
                    "open_total_after": open_total(new_lots),
                }
            )

    summary = {
        "closed_duplicates_removed": removed,
        "open_duplicates_left_alone": open_dupes,
        "lots_after": kept,
        "records_changed": sum(1 for r in per_record if r["closed_duplicates_removed"]),
        "records_with_untouched_open_duplicates": sum(1 for r in per_record if r["open_duplicates_left_alone"]),
        "per_record": per_record,
    }
    return out, summary


def atomic_write(path: Path, doc: dict) -> str:
    body = (json.dumps(doc, indent=2, default=str) + "\n").encode()
    st = path.stat()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, st.st_mode & 0o777)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return sha256_bytes(body)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    path = Path(args.path)
    original = path.read_bytes()
    doc = json.loads(original)

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _now(),
        "mode": "apply" if args.apply else "dry-run",
        "path": str(path),
        "sha256_before": sha256_bytes(original),
        "lots_before": sum(len(v) for v in doc.values() if isinstance(v, list)),
    }

    repaired, summary = repair(doc)
    receipt["summary"] = summary

    checks = verify_invariants(doc, repaired)
    receipt["invariants"] = checks
    if not checks["ok"]:
        receipt["applied"] = False
        _emit(receipt, args)
        print("REFUSED: invariants violated, nothing written", file=sys.stderr)
        for p in checks["problems"][:10]:
            print(f"  {p}", file=sys.stderr)
        return 2

    if not args.apply:
        receipt["applied"] = False
        _emit(receipt, args)
        _print(receipt)
        return 0

    if not args.backup_dir:
        print("--backup-dir is required for --apply", file=sys.stderr)
        return 2

    bdir = Path(args.backup_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = bdir / f"{path.name}.pre-dedupe.{stamp}.bak"
    shutil.copy2(path, backup)
    if sha256_bytes(backup.read_bytes()) != receipt["sha256_before"]:
        print("REFUSED: backup did not verify", file=sys.stderr)
        return 2
    os.chmod(backup, 0o444)
    receipt["backup"] = {"path": str(backup), "sha256": receipt["sha256_before"], "verified": True}

    # The file must not have moved between reading and writing.
    if sha256_bytes(path.read_bytes()) != receipt["sha256_before"]:
        print("REFUSED: the file changed while the repair was being computed", file=sys.stderr)
        return 2

    receipt["sha256_after"] = atomic_write(path, repaired)
    reread = json.loads(path.read_text())
    post = verify_invariants(doc, reread)
    receipt["post_write_invariants"] = post
    if not post["ok"]:
        shutil.copy2(backup, path)
        receipt["rolled_back"] = True
        receipt["applied"] = False
        _emit(receipt, args)
        print("REFUSED after write: restored from backup", file=sys.stderr)
        return 2

    receipt["applied"] = True
    receipt["lots_after"] = sum(len(v) for v in reread.values() if isinstance(v, list))
    _emit(receipt, args)
    _print(receipt)
    return 0


def _emit(receipt: dict, args: Any) -> None:
    if args.out:
        Path(args.out).write_text(json.dumps(receipt, indent=1, default=str) + "\n")


def _print(r: dict) -> None:
    s = r["summary"]
    print(f"mode                        : {r['mode']}")
    print(f"lots before                 : {r['lots_before']}")
    print(f"closed duplicates removed   : {s['closed_duplicates_removed']}")
    print(f"open duplicates LEFT ALONE  : {s['open_duplicates_left_alone']}")
    print(f"records changed             : {s['records_changed']}")
    print(f"invariants                  : {'OK' if r['invariants']['ok'] else 'VIOLATED'}")
    if r.get("applied"):
        print(f"lots after                  : {r['lots_after']}")
        print(f"backup                      : {r['backup']['path']}")


if __name__ == "__main__":
    raise SystemExit(main())
