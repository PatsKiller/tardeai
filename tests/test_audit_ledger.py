#!/usr/bin/env python3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_record_and_chain():
    import audit_ledger as al
    with tempfile.TemporaryDirectory() as td:
        al.LEDGER_DIR = Path(td)
        al.LEDGER_PATH = Path(td) / "events.jsonl"
        r1 = al.record_event("test_event", decision="pass", reason="t1")
        r2 = al.record_event("test_event", decision="pass", reason="t2")
        check("record ok", r1.get("ok") and r2.get("ok"))
        check("hashes differ", r1.get("event_hash") != r2.get("event_hash"))
        v = al.verify_chain(10)
        check("chain verifies", v.get("ok") and v.get("verified", 0) >= 2)


def test_tail():
    import audit_ledger as al
    with tempfile.TemporaryDirectory() as td:
        al.LEDGER_DIR = Path(td)
        al.LEDGER_PATH = Path(td) / "events.jsonl"
        al.record_event("a")
        al.record_event("b")
        rows = al.tail(5)
        check("tail returns rows", len(rows) == 2)


if __name__ == "__main__":
    print("\n— audit ledger —")
    test_record_and_chain()
    test_tail()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)