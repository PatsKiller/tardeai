#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_release_json_shape():
    proc = subprocess.run(
        [sys.executable, "scripts/validate_release_readiness.py", "--json", "--skip-build"],
        cwd=ROOT, text=True, capture_output=True, timeout=180,
    )
    check("runs", proc.returncode in (0, 1))
    data = json.loads(proc.stdout)
    check("has checks", "checks" in data)
    check("has blockers key", "blockers" in data)
    names = [c["name"] for c in data.get("checks", [])]
    check("execution_state check", any("execution_state" in n for n in names))
    check("no_broker_write test", any("no_broker_write" in n for n in names))


if __name__ == "__main__":
    print("\n— release readiness —")
    test_release_json_shape()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)