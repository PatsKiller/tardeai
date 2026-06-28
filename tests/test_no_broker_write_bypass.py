#!/usr/bin/env python3
"""Broker writes must route through the approved transport + readiness (P1-1).

Backed by ``scripts/broker_write_scanner.py`` (AST + regex). Findings carry file, line,
symbol, and reason. Runs under pytest and standalone.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def _fmt(findings):
    return "; ".join(f"{f['file']}:{f['line']} {f['symbol']} ({f['reason'][:40]})" for f in findings)


def test_schwab_transport_has_readiness():
    st = (SCRIPTS / "schwab_transport.py").read_text()
    check("schwab_transport calls execution_readiness",
          "execution_readiness" in st and "evaluate_execution_readiness" in st)


def test_scanner_clean_overall():
    import broker_write_scanner as bws
    r = bws.scan()
    check("no broker-write bypass findings", r["ok"], _fmt(r["findings"]))


def test_no_direct_client_write_calls():
    import broker_write_scanner as bws
    bad = [f for f in bws.scan()["findings"] if "direct broker write" in f["reason"]]
    check("no direct client place/cancel/replace outside transport", not bad, _fmt(bad))


def test_no_raw_http_to_order_endpoints():
    import broker_write_scanner as bws
    bad = [f for f in bws.scan()["findings"] if "raw HTTP" in f["reason"]]
    check("no raw HTTP to Schwab order endpoints", not bad, _fmt(bad))


def test_no_schwab_py_import_outside_boundary():
    import broker_write_scanner as bws
    bad = [f for f in bws.scan()["findings"] if "schwab-py" in f["reason"]]
    check("schwab-py imported only at boundary", not bad, _fmt(bad))


def test_replace_order_fenced_in_transport():
    # replace_order must remain a fenced no-write everywhere (multi-leg/replace bypass guard).
    trans = (SCRIPTS / "schwab_transport.py").read_text()
    import re
    check("replace_order fenced (raises NotProvenWrite)",
          bool(re.search(r"def replace_order\([^\n]*\n\s+raise NotProvenWrite", trans)))


def test_pilots_route_through_transport():
    for name in ("options_order_pilot.py", "broker_entry_pilot.py", "protective_stop_pilot.py"):
        p = SCRIPTS / "brokers" / name
        if p.exists():
            src = p.read_text()
            check(f"{name} uses schwab_transport", "schwab_transport" in src)


def test_readiness_module_exists():
    check("execution_readiness exists", (SCRIPTS / "brokers" / "execution_readiness.py").exists())


def test_approved_module_list_is_small():
    import broker_write_scanner as bws
    check("approved write modules list is small + explicit", len(bws.APPROVED_WRITE_MODULES) <= 4)


ALL = [
    test_schwab_transport_has_readiness,
    test_scanner_clean_overall,
    test_no_direct_client_write_calls,
    test_no_raw_http_to_order_endpoints,
    test_no_schwab_py_import_outside_boundary,
    test_replace_order_fenced_in_transport,
    test_pilots_route_through_transport,
    test_readiness_module_exists,
    test_approved_module_list_is_small,
]


if __name__ == "__main__":
    print("\n— no broker write bypass —")
    for t in ALL:
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
