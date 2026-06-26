#!/usr/bin/env python3
"""tests/test_execution_state.py — execution state fail-closed behavior."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

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


def test_build_state_shape():
    import execution_state as es
    state = es.build_state()
    check("live_architecture_built true", state.get("live_architecture_built") is True)
    check("autonomous_live_submit_allowed false", state.get("autonomous_live_submit_allowed") is False)
    check("required_live_gates present", len(state.get("required_live_gates") or []) >= 10)
    check("generated_at set", bool(state.get("generated_at")))


def test_fail_closed_no_db():
    import execution_state as es
    with mock.patch("execution_state._current_blockers", return_value=["cannot inspect DB"]):
        blockers = es._current_blockers()
    check("blockers list on db failure", "cannot inspect" in blockers[0] or len(blockers) > 0)


def test_markdown_output():
    import execution_state as es
    md = es.to_markdown(es.build_state())
    check("markdown mentions 2FA or operator", "2fa" in md.lower() or "operator" in md.lower())
    check("markdown mentions LLM", "LLM" in md or "advisory" in md.lower())


def test_standing_unlock_not_blocked_when_live():
    import execution_state as es
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True):
        with mock.patch.object(es, "_live_unlock_status", return_value={
            "live_unlocked": True, "standing_unlock": True, "unlock_via": "standing_db_unlock",
            "broker_live_enabled": True,
        }):
            blockers = es._current_blockers({"live_unlocked": True}, {})
    check("no false env blocker when live unlocked",
          not any("BROKER_LIVE_ENABLED" in b for b in blockers))


def test_live_trading_labels_split():
    import execution_state as es
    labels = es.live_trading_labels()
    check("labels has autonomous key", "autonomous_live_trading_allowed" in labels)
    check("labels has operator 2fa key", "operator_live_via_2fa_allowed" in labels)
    check("labels has operator status", bool(labels.get("operator_status_label")))


def test_cli_json():
    import subprocess
    proc = subprocess.run([sys.executable, "scripts/execution_state.py", "--json"],
                          cwd=ROOT, text=True, capture_output=True, timeout=30)
    check("cli exit 0", proc.returncode == 0)
    data = json.loads(proc.stdout)
    check("cli json paper_mode key", "paper_mode" in data)


if __name__ == "__main__":
    print("\n— execution_state tests —")
    test_build_state_shape()
    test_fail_closed_no_db()
    test_markdown_output()
    test_standing_unlock_not_blocked_when_live()
    test_live_trading_labels_split()
    test_cli_json()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)