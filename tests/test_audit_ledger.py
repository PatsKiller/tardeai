#!/usr/bin/env python3
"""Audit ledger — hash chain (non-mutating verify) + live-adjacent coverage (P1-2).

Runs under pytest and standalone.
"""
import copy
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
    assert cond, f"{name} {detail}"


def _ledger(td):
    import audit_ledger as al
    al.LEDGER_DIR = Path(td)
    al.LEDGER_PATH = Path(td) / "events.jsonl"
    return al


def test_record_and_chain():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        r1 = al.record_event("test_event", decision="pass", reason="t1")
        r2 = al.record_event("test_event", decision="pass", reason="t2")
        check("record ok", r1.get("ok") and r2.get("ok"))
        check("hashes differ", r1.get("event_hash") != r2.get("event_hash"))
        v = al.verify_chain(10)
        check("chain verifies", v.get("ok") and v.get("verified", 0) >= 2)


def test_verify_does_not_mutate_rows():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        al.record_event("a")
        al.record_event("b")
        before = copy.deepcopy(al.tail(10))
        al.verify_chain(10)
        after = al.tail(10)
        # event_hash must still be present and identical after verification.
        check("rows retain event_hash after verify", all("event_hash" in r for r in after))
        check("rows unchanged by verify", before == after)


def test_tamper_detected():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        al.record_event("x", reason="orig")
        al.record_event("y", reason="orig2")
        # Tamper with the file: flip a reason without recomputing the hash.
        text = al.LEDGER_PATH.read_text().splitlines()
        text[0] = text[0].replace("orig", "TAMPERED")
        al.LEDGER_PATH.write_text("\n".join(text) + "\n")
        v = al.verify_chain(10)
        check("tamper breaks chain", not v.get("ok"))


def test_partial_window_verifies():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        for i in range(6):
            al.record_event("e", reason=str(i))
        # Verifying only the last 3 must NOT report a spurious chain break.
        v = al.verify_chain(3)
        check("partial window verifies", v.get("ok") and v.get("verified") == 3, v)


def test_coverage_report_missing_events_warn():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        al.record_event("readiness_evaluated")  # only one live-adjacent type
        cov = al.coverage_report(release_mode="review")
        check("coverage chain ok", cov["ok"] is True)
        check("missing criticals reported", "submit_requested" in cov["missing_critical"])
        check("review-mode missing critical is WARN/FAIL not PASS", cov["status"] in ("WARN", "FAIL"))


def test_coverage_full_is_pass():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        for et in al.EXPECTED_LIVE_ADJACENT_EVENTS:
            al.record_event(et)
        cov = al.coverage_report(release_mode="review")
        check("full coverage PASS", cov["status"] == "PASS", cov["missing_expected"])


def test_coverage_live_mode_fails_on_missing_critical():
    with tempfile.TemporaryDirectory() as td:
        al = _ledger(td)
        al.record_event("readiness_evaluated")  # live activity but missing criticals
        cov = al.coverage_report(release_mode="live")
        check("live-mode missing critical FAIL", cov["status"] == "FAIL", cov)


ALL = [
    test_record_and_chain, test_verify_does_not_mutate_rows, test_tamper_detected,
    test_partial_window_verifies, test_coverage_report_missing_events_warn,
    test_coverage_full_is_pass, test_coverage_live_mode_fails_on_missing_critical,
]


if __name__ == "__main__":
    print("\n— audit ledger —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
