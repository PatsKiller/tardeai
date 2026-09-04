#!/usr/bin/env python3
"""Phase B1: close tax lots for positions two independent authorities say are gone.

Phase A removed duplicate CLOSED lots and deliberately left 1,800 duplicate OPEN lots
alone, because removing them would change a share count nothing had confirmed. Asking
the transaction history answered the question differently than expected: for fourteen of
the fifteen affected records the position was fully exited, so BOTH the stored total
(ARKQ 11,300) and the deduplicated total (100) are wrong. The correct open total is zero.

That makes this a different operation from deduplication. Nothing is removed and no
share count is chosen. Lots whose position is provably closed are marked closed, and
lot_date, shares and cost_per_share are preserved untouched so realized-gain and
holding-period history survive.

A record is eligible only when ALL of these hold, recomputed here rather than read from
any earlier worksheet:

  * the broker reports no position for (symbol, account)
  * the transaction history nets to exactly zero shares
  * every action in that history is classified; one unknown action disqualifies it

FCNTX:schwab_rollover_ira fails the second test (net +3.0, a share-class transfer
artifact) and is therefore skipped by the rule rather than by a hardcoded exception.

    python3 scripts/close_exited_tax_lots.py --path <tax_lots.json> \
        --authority <broker_snapshot.json>                          # dry run
    ... --apply --backup-dir <dir>
"""

from __future__ import annotations

NO_CONSUMER_REASON = (
    "one-shot data repair whose receipt an operator reads; the schema stamps that receipt "
    "rather than being imported by another module."
)

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ExitedTaxLotClosure@v1"

#: Actions that increase or decrease share count. Anything outside these three sets is
#: UNCLASSIFIED and disqualifies the record: a transaction type this tool does not
#: understand must never be silently scored as zero.
SHARES_IN = frozenset(
    {
        "buy",
        "reinvest shares",
        "reinvest dividend",
        "reinvested dividend",
        "long term cap gain reinvest",
        "security transfer",
        "transfer in",
        "journaled shares",
        "internal transfer",
        "journal",
        "adjustment",
    }
)
SHARES_OUT = frozenset({"sell", "transfer out"})
SHARES_NEUTRAL = frozenset(
    {
        "dividend",
        "qualified dividend",
        "cash dividend",
        "cash receipt",
        "bank interest",
        "moneylink transfer",
    }
)

#: Share counts are floats from two systems; exact zero is not a fair demand.
NET_ZERO_TOLERANCE = 1e-6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ident(lot: dict) -> str:
    return json.dumps(lot, sort_keys=True, default=str)


def is_open(lot: Any) -> bool:
    if not isinstance(lot, dict):
        return False
    try:
        return not lot.get("closed") and float(lot.get("shares_remaining") or 0) != 0.0
    except (TypeError, ValueError):
        return False


def open_total(lots: Any) -> float:
    if not isinstance(lots, list):
        return 0.0
    return round(sum(float(x.get("shares_remaining") or 0) for x in lots if is_open(x)), 6)


def load_transactions(env_path: Path) -> dict[tuple[str, str], list[dict]]:
    """Read the canonical transaction history. Read-only."""
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    proc = subprocess.run(
        [
            "psql",
            "-h",
            env["DB_HOST"],
            "-p",
            env["DB_PORT"],
            "-U",
            env["DB_USER"],
            "-d",
            env["DB_NAME"],
            "-tA",
            "-F",
            "\x1f",
            "-c",
            "select upper(symbol), account, action, quantity, trade_date from trade_transactions",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PGPASSWORD": env["DB_PASSWORD"]},
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"transaction read failed: {proc.stderr[-300:]}")
    out: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\x1f")
        if len(parts) >= 5:
            out[(parts[0], parts[1])].append({"action": parts[2], "qty": float(parts[3] or 0), "date": parts[4]})
    return dict(out)


def position_index(snapshot: dict) -> dict[tuple[str, str], float]:
    idx: dict[tuple[str, str], float] = {}
    for account_key, entry in (snapshot.get("brokers") or {}).items():
        if not entry.get("accepted"):
            # An account we could not read is not an account holding nothing. Every
            # record in it must fail eligibility rather than be treated as exited.
            continue
        for p in entry.get("positions") or []:
            try:
                idx[(str(p.get("symbol")), account_key)] = float(p.get("qty"))
            except (TypeError, ValueError):
                continue
    return idx


def assess(record_key: str, lots: Any, txns: dict, positions: dict, accepted_accounts: set[str]) -> dict[str, Any]:
    """Decide whether one record's position is provably closed."""
    symbol, _, account = record_key.partition(":")
    history = txns.get((symbol.upper(), account), [])
    shares_in = round(sum(t["qty"] for t in history if t["action"].lower() in SHARES_IN), 6)
    shares_out = round(sum(t["qty"] for t in history if t["action"].lower() in SHARES_OUT), 6)
    unknown = sorted(
        {t["action"] for t in history if t["action"].lower() not in SHARES_IN | SHARES_OUT | SHARES_NEUTRAL}
    )
    net = round(shares_in - shares_out, 6)
    broker_qty = positions.get((symbol, account))

    reasons: list[str] = []
    if account not in accepted_accounts:
        reasons.append(f"account {account!r} was not read from the broker")
    if broker_qty is not None:
        reasons.append(f"the broker still holds {broker_qty}")
    if not history:
        reasons.append("no transaction history for this symbol and account")
    if unknown:
        reasons.append(f"unclassified transaction action(s): {unknown}")
    if abs(net) > NET_ZERO_TOLERANCE:
        reasons.append(f"transaction history nets to {net}, not zero")

    return {
        "record_key": record_key,
        "symbol": symbol,
        "account": account,
        "stored_open_total": open_total(lots),
        "broker_position": broker_qty,
        "transaction_shares_in": shares_in,
        "transaction_shares_out": shares_out,
        "transaction_net": net,
        "transaction_count": len(history),
        "unclassified_actions": unknown,
        "eligible": not reasons,
        "ineligible_reasons": reasons,
    }


def close_lots(lots: list) -> tuple[list, int]:
    """Mark every open lot closed, preserving everything that carries tax meaning."""
    out: list = []
    closed = 0
    for lot in lots:
        if is_open(lot):
            new = dict(lot)
            new["shares_remaining"] = 0
            new["closed"] = True
            new["closed_reason"] = "POSITION_EXITED_PER_BROKER_AND_TRANSACTIONS"
            out.append(new)
            closed += 1
        else:
            out.append(lot)
    return out, closed


def verify_invariants(before: dict, after: dict, eligible: set[str]) -> dict[str, Any]:
    problems: list[str] = []
    if set(before) != set(after):
        problems.append("key set changed")

    for key in sorted(set(before) & set(after)):
        b, a = before[key], after[key]
        if key not in eligible:
            if _ident({"v": b}) != _ident({"v": a}):
                problems.append(f"{key}: an INELIGIBLE record was modified")
            continue
        if not isinstance(b, list) or not isinstance(a, list):
            continue
        if len(b) != len(a):
            problems.append(f"{key}: lot count changed {len(b)} -> {len(a)}")
            continue
        if open_total(a) != 0.0:
            problems.append(f"{key}: open total is {open_total(a)} after closure, expected 0")
        for i, (lb, la) in enumerate(zip(b, a)):
            if not isinstance(lb, dict) or not isinstance(la, dict):
                continue
            for field in ("symbol", "account", "lot_date", "shares", "cost_per_share", "total_cost"):
                if lb.get(field) != la.get(field):
                    problems.append(f"{key}[{i}]: {field} changed {lb.get(field)!r} -> {la.get(field)!r}")
            changed = {f for f in set(lb) | set(la) if lb.get(f) != la.get(f)}
            if not changed <= {"shares_remaining", "closed", "closed_reason"}:
                problems.append(f"{key}[{i}]: unexpected fields changed: {sorted(changed)}")
    return {"ok": not problems, "problems": problems}


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
    ap.add_argument("--authority", required=True, help="broker authority snapshot")
    ap.add_argument("--env", default="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    path = Path(args.path)
    original = path.read_bytes()
    doc = json.loads(original)
    snapshot = json.loads(Path(args.authority).read_text())
    positions = position_index(snapshot)
    accepted = {a for a, e in (snapshot.get("brokers") or {}).items() if e.get("accepted")}
    txns = load_transactions(Path(args.env))

    assessments = [
        assess(k, v, txns, positions, accepted)
        for k, v in sorted(doc.items())
        if ":" in k and isinstance(v, list) and open_total(v) != 0.0
    ]
    eligible = {a["record_key"] for a in assessments if a["eligible"]}

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _now(),
        "mode": "apply" if args.apply else "dry-run",
        "path": str(path),
        "sha256_before": sha256_bytes(original),
        "authority_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "rule": (
            "a record is eligible only when the broker reports no position, the transaction "
            "history nets to zero, and every action in that history is classified"
        ),
        "records_with_open_lots": len(assessments),
        "eligible": sorted(eligible),
        "ineligible": [
            {"record_key": a["record_key"], "reasons": a["ineligible_reasons"]}
            for a in assessments
            if not a["eligible"]
        ],
        "assessments": assessments,
    }

    after = {}
    closed_total = 0
    for key, value in doc.items():
        if key in eligible and isinstance(value, list):
            new_lots, n = close_lots(value)
            after[key] = new_lots
            closed_total += n
        else:
            after[key] = value
    receipt["lots_closed"] = closed_total

    checks = verify_invariants(doc, after, eligible)
    receipt["invariants"] = checks
    if not checks["ok"]:
        receipt["applied"] = False
        _emit(receipt, args)
        print("REFUSED: invariants violated, nothing written", file=sys.stderr)
        for p in checks["problems"][:10]:
            print(f"  {p}", file=sys.stderr)
        return 2

    _print(receipt)
    if not args.apply:
        receipt["applied"] = False
        _emit(receipt, args)
        return 0
    if not args.backup_dir:
        print("--backup-dir is required for --apply", file=sys.stderr)
        return 2

    bdir = Path(args.backup_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = bdir / f"{path.name}.pre-closure.{stamp}.bak"
    shutil.copy2(path, backup)
    if sha256_bytes(backup.read_bytes()) != receipt["sha256_before"]:
        print("REFUSED: backup did not verify", file=sys.stderr)
        return 2
    os.chmod(backup, 0o444)
    receipt["backup"] = {"path": str(backup), "sha256": receipt["sha256_before"], "verified": True}

    if sha256_bytes(path.read_bytes()) != receipt["sha256_before"]:
        print("REFUSED: the file changed while the closure was being computed", file=sys.stderr)
        return 2

    receipt["sha256_after"] = atomic_write(path, after)
    reread = json.loads(path.read_text())
    post = verify_invariants(doc, reread, eligible)
    receipt["post_write_invariants"] = post
    if not post["ok"]:
        shutil.copy2(backup, path)
        receipt["rolled_back"] = True
        receipt["applied"] = False
        _emit(receipt, args)
        print("REFUSED after write: restored from backup", file=sys.stderr)
        return 2

    receipt["applied"] = True
    _emit(receipt, args)
    print(f"applied: {closed_total} lots closed; backup {backup}")
    return 0


def _emit(receipt: dict, args: Any) -> None:
    if args.out:
        Path(args.out).write_text(json.dumps(receipt, indent=1, default=str) + "\n")


def _print(r: dict) -> None:
    print(f"mode                    : {r['mode']}")
    print(f"records with open lots  : {r['records_with_open_lots']}")
    print(f"eligible (both agree)   : {len(r['eligible'])}")
    print(f"ineligible              : {len(r['ineligible'])}")
    for row in r["ineligible"]:
        print(f"    SKIP {row['record_key']}: {'; '.join(row['reasons'])}")
    print(f"lots to close           : {r['lots_closed']}")
    print(f"invariants              : {'OK' if r['invariants']['ok'] else 'VIOLATED'}")


if __name__ == "__main__":
    raise SystemExit(main())
