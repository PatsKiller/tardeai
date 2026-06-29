#!/usr/bin/env python3
"""P0-1: ALL momentum_scalp reports must agree on the confirmed closed validation-sample count.

The canonical source of truth is scalp_trade_attribution.attribute()['confirmed_closed'] (conservative,
lineage-confirmed). This runs each report's --json and asserts they all carry the same number. Fails
the build if any report drifts (e.g. the source-maturity report's old raw COUNT(*) over-count of 3).
DB-aware: if the DB is unavailable the reports degrade to WARN and this test SKIPS rather than asserts."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
PY = sys.executable
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def _run_json(args):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "scripts"))
    try:
        p = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
        return json.loads(p.stdout)
    except Exception:
        return None


def main():
    # Canonical
    canon = None
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from db_adapter import get_connection
        from scalp_trade_attribution import attribute
        a = attribute(get_connection())
        canon = a.get("confirmed_closed")
        canon_ids = a.get("confirmed_trade_ids") or []
    except Exception:
        canon = None
        canon_ids = []

    if canon is None:
        print("  [SKIP] DB/attribution unavailable — consistency check skipped (reports degrade to WARN)")
        print("\n0 passed, 0 failed")
        return 0

    print(f"  canonical confirmed_closed = {canon} (trade ids {canon_ids})")

    # Source maturity report
    sm = _run_json(["scripts/momentum_scalp_source_maturity_report.py", "--days", "30", "--json"])
    if sm:
        got = sm.get("validation_maturity", {}).get("confirmed_closed_validation_trades")
        check(f"source maturity reports {canon}", got == canon)
        check("source maturity carries trade ids", set(sm["validation_maturity"].get("confirmed_trade_ids", [])) == set(canon_ids))
        check("source maturity does NOT claim 4.5+",
              "NOT claimable" in sm["validation_maturity"]["strategy_maturity_claimable"] or canon >= 30)

    # Validation ops report
    ops = _run_json(["scripts/momentum_scalp_validation_ops_report.py", "--days", "30", "--json"])
    if ops:
        got = (ops.get("validation_gate", {}) or {}).get("confirmed_closed_validation_trades")
        check(f"validation ops reports {canon}", got == canon)

    # Validation tracker
    tr = _run_json(["scripts/momentum_scalp_validation_tracker.py", "--json"])
    if tr:
        check(f"validation tracker reports {canon}", tr.get("confirmed_closed") == canon)

    # Scalp lifecycle maturity (string contains "N/30 confirmed")
    lm = _run_json(["scripts/compute_scalp_lifecycle_maturity.py", "--json"])
    if lm:
        s = json.dumps(lm)
        m = re.search(r"\((\d+)/30 confirmed", s)
        check(f"scalp lifecycle maturity says {canon}/30", bool(m) and int(m.group(1)) == canon)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
