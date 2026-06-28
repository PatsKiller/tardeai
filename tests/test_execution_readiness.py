#!/usr/bin/env python3
"""Execution readiness resolver — gates + P0-4 preflight/submit/dry_run/audit modes.

Runs under pytest (assert-based) and standalone.
"""
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
    assert cond, f"{name} {detail}"


class _FakeCursor:
    """Cursor that answers the write-fence/db-arm lookups as enabled."""
    def execute(self, *a, **k):
        return None
    def fetchone(self):
        return (True,)
    def fetchall(self):
        return []


class _FakeConn:
    def cursor(self):
        return _FakeCursor()


def _fake_db():
    import db_adapter
    return mock.patch.object(db_adapter, "_get_conn", return_value=_FakeConn())


def test_live_locked_without_standing_unlock():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=False):
        r = evaluate_execution_readiness(
            {"intent_id": "t1", "id": "p1", "strategy": "covered_call", "symbol": "V"},
            asset_class="option", account_key="schwab_taxable", mode="submit",
        )
    gate = r.get("gate_results", {}).get("global_live_allowed", {})
    check("global gate fails when locked", gate.get("ok") is False)
    check("autonomous false", r.get("autonomous_live_submit_allowed") is False)
    check("evidence_hash present", bool(r.get("evidence_hash")))
    check("readiness_hash mirrors evidence_hash", r.get("readiness_hash") == r.get("evidence_hash"))


def test_live_allowed_with_standing_unlock_still_needs_2fa():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
            r = evaluate_execution_readiness(
                {"intent_id": "t1a", "id": "p1", "strategy": "covered_call", "symbol": "V"},
                asset_class="option", account_key="schwab_taxable", mode="submit",
            )
    check("global gate passes when standing unlock", r.get("gate_results", {}).get("global_live_allowed", {}).get("ok"))
    check("submit still needs operator path or blocks", r.get("mode") in ("operator_required", "blocked", "dry_run"))
    check("submit not final_submit_ready without 2FA", r.get("final_submit_ready") is False)


def test_preflight_returns_operator_required_without_failing_gates():
    """Preflight: when only operator confirmation remains, mode==operator_required
    and the missing 2FA is NOT a hard block."""
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True), \
         mock.patch("brokers.execution_readiness._paper_mode", return_value=False), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=False), _fake_db():
        r = evaluate_execution_readiness(
            {"intent_id": "tp1", "id": "pp1", "strategy": "scalp", "symbol": "AAPL"},
            asset_class="equity", account_key="schwab_taxable", mode="preflight",
        )
    codes = [b.get("code") for b in r.get("hard_blocks", [])]
    check("2FA not a hard block in preflight", "operator_2fa_confirmed" not in codes, str(codes))
    check("preflight operator_required when only 2FA remains", r.get("mode") == "operator_required", r.get("mode"))
    check("operator_required_steps mentions 2FA",
          any("2FA" in s for s in r.get("operator_required_steps", [])))


def test_submit_blocks_when_2fa_absent():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True), \
         mock.patch("brokers.execution_readiness._paper_mode", return_value=False), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=False), _fake_db():
        r = evaluate_execution_readiness(
            {"intent_id": "ts1", "id": "ps1", "strategy": "scalp", "symbol": "AAPL"},
            asset_class="equity", account_key="schwab_taxable", mode="submit",
        )
    codes = [b.get("code") for b in r.get("hard_blocks", [])]
    check("2FA IS a hard block in submit", "operator_2fa_confirmed" in codes, str(codes))
    check("submit not ok without 2FA", r.get("ok") is False)


def test_audit_mode_has_no_side_effects_and_full_matrix():
    from brokers.execution_readiness import evaluate_execution_readiness
    # record_event is imported lazily from audit_ledger inside the resolver; patch it there.
    import audit_ledger
    with mock.patch.object(audit_ledger, "record_event") as rec:
        r = evaluate_execution_readiness(
            {"intent_id": "ta1", "id": "pa1", "strategy": "covered_call", "symbol": "V"},
            asset_class="option", account_key="schwab_taxable", mode="audit",
        )
    check("audit writes no ledger event", rec.call_count == 0, f"calls={rec.call_count}")
    check("audit returns full gate matrix", len(r.get("gate_results", {})) >= 3)
    check("audit mode label", r.get("mode") == "audit")


def test_dry_run_never_writes_and_reports():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
            r = evaluate_execution_readiness(
                {"intent_id": "td1", "id": "pd1", "strategy": "scalp", "symbol": "AAPL"},
                asset_class="equity", account_key="schwab_taxable", mode="dry_run",
            )
    check("dry_run mode reported", r.get("mode") in ("dry_run", "blocked"))
    check("dry_run never final_submit_ready", r.get("final_submit_ready") is False)


def test_llm_cannot_unlock():
    from brokers.execution_readiness import evaluate_execution_readiness
    r = evaluate_execution_readiness(
        {"intent_id": "t2", "model_snapshot": {"unlock_live": True, "override_risk": True}},
        asset_class="equity", mode="submit",
    )
    check("llm unlock blocked", "llm_advisory_only" in str(r.get("gate_results", {})) or not r["ok"])


def test_unknown_quote_fail_closed():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_readiness._global_live_allowed",
                    return_value={"ok": True, "code": "global_live_allowed", "reason": "ok", "severity": "hard"}):
        with mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
            r = evaluate_execution_readiness(
                {"intent_id": "t3", "id": "p3", "strategy": "covered_call", "symbol": "RTX"},
                asset_class="option", account_key="schwab_taxable", mode="submit",
            )
    gate = r.get("gate_results", {}).get("fresh_market_data", {})
    check("unknown quote fails closed", gate.get("ok") is False or r["mode"] == "blocked")


def test_live_alias_maps_to_submit():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=False):
        r = evaluate_execution_readiness(
            {"intent_id": "tl1", "id": "pl1", "strategy": "scalp", "symbol": "AAPL"},
            asset_class="equity", account_key="schwab_taxable", mode="live",
        )
    check("live alias recorded as requested_mode", r.get("requested_mode") == "live")


ALL = [
    test_live_locked_without_standing_unlock,
    test_live_allowed_with_standing_unlock_still_needs_2fa,
    test_preflight_returns_operator_required_without_failing_gates,
    test_submit_blocks_when_2fa_absent,
    test_audit_mode_has_no_side_effects_and_full_matrix,
    test_dry_run_never_writes_and_reports,
    test_llm_cannot_unlock,
    test_unknown_quote_fail_closed,
    test_live_alias_maps_to_submit,
]


if __name__ == "__main__":
    print("\n— execution_readiness tests —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
