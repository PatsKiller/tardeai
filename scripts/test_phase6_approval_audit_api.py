#!/usr/bin/env python3
"""Phase 6C API-level audit trail validation — mock scenarios.

Exercises audit helper functions with mock approval flows.
No live orders, no real paper trades, no Alpaca submission.

Usage:
    .venv/bin/python scripts/test_phase6_approval_audit_api.py
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

RESULTS = []


def get_conn():
    from session13_db import get_conn
    return get_conn()


def run_scenario(name, flow_fn, expected_status):
    """Run one audit scenario and record result."""
    conn = get_conn()
    try:
        actual_status = flow_fn(conn)
        passed = actual_status == expected_status
        RESULTS.append({"scenario": name, "expected": expected_status,
                        "actual": actual_status, "passed": passed})
    except Exception as e:
        RESULTS.append({"scenario": name, "expected": expected_status,
                        "actual": f"ERROR: {e}", "passed": False})
    finally:
        conn.close()


def scenario_success(conn):
    from phase6_approval_audit import (
        create_approval_audit_attempt, update_approval_audit,
        append_approval_audit_event, finalize_approval_audit)
    prop = {"id": 88001, "symbol": "MOCK", "proposed_entry": 50.0,
            "proposed_stop": 48.0, "proposed_target1": 55.0}
    aid = create_approval_audit_attempt(conn, prop, request_source="mock_test")
    update_approval_audit(conn, aid, gate="session_policy", gate_passed=True)
    update_approval_audit(conn, aid, market_revalidation={"passed": True, "live_price": 50.1},
                          gate="market_revalidation", gate_passed=True)
    update_approval_audit(conn, aid, risk_gate={"result": "APPROVED"},
                          gate="risk_gate", gate_passed=True)
    update_approval_audit(conn, aid, paper_trade={"paper_trade_id": 9999},
                          gate="paper_trade", gate_passed=True)
    update_approval_audit(conn, aid, alpaca_response={"status": "submitted"},
                          gate="alpaca_submission", gate_passed=True)
    finalize_approval_audit(conn, aid, "approved_paper_submitted", "Mock success")
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
    return cur.fetchone()[0]


def scenario_blocked_session(conn):
    from phase6_approval_audit import (
        create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)
    prop = {"id": 88002, "symbol": "MOCK"}
    aid = create_approval_audit_attempt(conn, prop, request_source="mock_test")
    update_approval_audit(conn, aid, session_policy={"allowed": False},
                          gate="session_policy", gate_passed=False)
    finalize_approval_audit(conn, aid, "blocked_session", "After hours")
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
    return cur.fetchone()[0]


def scenario_blocked_stale_quote(conn):
    from phase6_approval_audit import (
        create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)
    prop = {"id": 88003, "symbol": "MOCK"}
    aid = create_approval_audit_attempt(conn, prop, request_source="mock_test")
    update_approval_audit(conn, aid, gate="session_policy", gate_passed=True)
    update_approval_audit(conn, aid, market_revalidation={"passed": False, "blockers": ["stale_quote"]},
                          gate="market_revalidation", gate_passed=False)
    finalize_approval_audit(conn, aid, "blocked_market_revalidation", "Stale quote")
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
    return cur.fetchone()[0]


def scenario_blocked_spread(conn):
    from phase6_approval_audit import (
        create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)
    prop = {"id": 88004, "symbol": "MOCK"}
    aid = create_approval_audit_attempt(conn, prop, request_source="mock_test")
    update_approval_audit(conn, aid, gate="session_policy", gate_passed=True)
    update_approval_audit(conn, aid, market_revalidation={"passed": False, "blockers": ["wide_spread"]},
                          gate="market_revalidation", gate_passed=False)
    finalize_approval_audit(conn, aid, "blocked_market_revalidation", "Wide spread")
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
    return cur.fetchone()[0]


def scenario_blocked_risk_gate(conn):
    from phase6_approval_audit import (
        create_approval_audit_attempt, update_approval_audit, finalize_approval_audit)
    prop = {"id": 88005, "symbol": "MOCK"}
    aid = create_approval_audit_attempt(conn, prop, request_source="mock_test")
    update_approval_audit(conn, aid, gate="session_policy", gate_passed=True)
    update_approval_audit(conn, aid, gate="market_revalidation", gate_passed=True)
    update_approval_audit(conn, aid, risk_gate={"result": "BLOCKED"},
                          gate="risk_gate", gate_passed=False)
    finalize_approval_audit(conn, aid, "blocked_risk_gate", "Risk gate blocked")
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
    return cur.fetchone()[0]


def scenario_error_fail_closed(conn):
    from phase6_approval_audit import (
        create_approval_audit_attempt, finalize_approval_audit)
    prop = {"id": 88006, "symbol": "MOCK"}
    aid = create_approval_audit_attempt(conn, prop, request_source="mock_test")
    finalize_approval_audit(conn, aid, "error_fail_closed", "Unexpected exception")
    cur = conn.cursor()
    cur.execute("SELECT approval_status FROM paper_proposal_approval_audit WHERE id=%s", [aid])
    return cur.fetchone()[0]


def main():
    print("Phase 6C — Approval Audit API Mock Validation")
    print("=" * 60)

    run_scenario("successful_approval", scenario_success, "approved_paper_submitted")
    run_scenario("blocked_session", scenario_blocked_session, "blocked_session")
    run_scenario("blocked_stale_quote", scenario_blocked_stale_quote, "blocked_market_revalidation")
    run_scenario("blocked_spread", scenario_blocked_spread, "blocked_market_revalidation")
    run_scenario("blocked_risk_gate", scenario_blocked_risk_gate, "blocked_risk_gate")
    run_scenario("error_fail_closed", scenario_error_fail_closed, "error_fail_closed")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n{'SCENARIO':<35} {'EXPECTED':>30} {'ACTUAL':>30} {'RESULT':>8}")
    print("-" * 105)
    for r in RESULTS:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['scenario']:<35} {r['expected']:>30} {r['actual']:>30} {status:>8}")
    print(f"\n{passed}/{total} scenarios passed")

    # Write results
    out = PROJECT_ROOT / "docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_api_results.json"
    out.write_text(json.dumps({"date": datetime.now().isoformat(), "total": total,
                               "passed": passed, "scenarios": RESULTS}, indent=2, default=str))
    print(f"\nResults: {out}")

    # Cleanup mock rows
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM paper_proposal_approval_audit_events WHERE audit_id IN (SELECT id FROM paper_proposal_approval_audit WHERE proposal_id BETWEEN 88001 AND 88010)")
    cur.execute("DELETE FROM paper_proposal_approval_audit WHERE proposal_id BETWEEN 88001 AND 88010")
    conn.commit()
    conn.close()
    print("Mock audit rows cleaned up.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
