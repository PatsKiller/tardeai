#!/usr/bin/env python3
"""AST/grep scan: broker writes must route through schwab_transport + readiness."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

PASS = FAIL = 0
APPROVED_WRITE_MODULES = {
    "schwab_transport.py",
    "snaptrade_trade.py",  # fenced separately
}
WRITE_FUNCS = {"place_order", "cancel_order"}


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def _find_direct_writes() -> list[str]:
    violations = []
    for path in SCRIPTS.rglob("*.py"):
        if path.name in APPROVED_WRITE_MODULES:
            continue
        if "test" in path.name or path.parts[-2] == "tests":
            continue
        # Validators and doc generators reference place_order symbolically — not runtime write paths
        if path.name.startswith("validate_") or path.name.startswith("update_docx"):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "client.place_order" in src or "schwab_transport.place_order" in src:
            if path.name not in ("options_order_pilot.py", "broker_entry_pilot.py",
                                 "protective_stop_pilot.py", "api_v2.py", "intent_submit_router.py"):
                violations.append(f"{path}: calls place_order")
    return violations


def test_schwab_transport_has_readiness():
    st = (SCRIPTS / "schwab_transport.py").read_text()
    check("schwab_transport calls execution_readiness",
          "execution_readiness" in st and "evaluate_execution_readiness" in st)


def test_no_stray_client_place_order():
    violations = _find_direct_writes()
    check("no stray place_order outside approved pilots", len(violations) == 0, str(violations))


def test_pilots_route_through_transport():
    for name in ("options_order_pilot.py", "broker_entry_pilot.py", "protective_stop_pilot.py"):
        p = SCRIPTS / "brokers" / name
        if p.exists():
            src = p.read_text()
            check(f"{name} uses schwab_transport", "schwab_transport" in src)


def test_readiness_module_exists():
    check("execution_readiness exists", (SCRIPTS / "brokers" / "execution_readiness.py").exists())


if __name__ == "__main__":
    print("\n— no broker write bypass —")
    test_schwab_transport_has_readiness()
    test_no_stray_client_place_order()
    test_pilots_route_through_transport()
    test_readiness_module_exists()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)