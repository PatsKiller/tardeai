"""Audit has no decision/apply path; all test state is isolated and clocks pinned."""
import fcntl
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from scripts import policy_enforcement_audit as a
from scripts.lib import operator_approvals as c

NOW = datetime(2032, 4, 12, 14, tzinfo=timezone.utc)
SHA = "a" * 40
TEXT = "Policy-Version: 20.2.0\n\n# 0 · Rules\n\nNever route around a denial."


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root, state = tmp_path / "source", tmp_path / "state"
    (root / "config").mkdir(parents=True)
    (root / "config/policy_enforcement_map.json").write_text(json.dumps({"rules": [{"anchor": "Never route", "tests": ["tests/missing.py"], "runtime_files": [], "ci_gates": []}]}))
    registry = {"domains": [{"domain": "operator_decisions", "store": {"file": "governance/operator_decisions.jsonl"},
                             "writer": c.WRITER, "approval": {"approved_by": "operator", "approved_on": "2032-04-12", "reference": "fixture only"}}]}
    (root / "config/data_source_authority.json").write_text(json.dumps(registry))
    (root / "config/llm_process_registry.json").write_text('{"processes": []}')
    def git(root, *args):
        if args[0] == "rev-parse":
            return SHA
        if args[:2] == ("log", "-1"):
            return SHA
        if args[0] == "show":
            return TEXT
        return SHA + "\tMerge policy fixture"
    monkeypatch.setattr(a, "git", git)
    monkeypatch.setenv("TRADEAI_RUN_ID", "fixture-audit-1")
    monkeypatch.setenv("TRADEAI_CODE_SHA", SHA)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    from scripts.lib import lane_last_receipt as receipts
    monkeypatch.setattr(receipts, "now_iso", lambda: NOW.isoformat())
    return root, state


def policy():
    return c.policy_projection(TEXT, source_sha=SHA) | {"text": TEXT}


def test_dry_run_cannot_reach_lock_model_or_any_writer(isolated):
    root, state = isolated
    def forbidden(*args, **kwargs):
        pytest.fail("dry run reached model")
    result = a.run(root=root, state_root=state, trigger="weekly", now=NOW, llm_review=True, generate=forbidden)
    assert result["mode"] == "dry_run" and result["auto_apply"] is False
    assert not state.exists()


def test_build_permission_without_domain_grant_refuses_before_state_creation(isolated):
    root, state = isolated
    (root / "config/data_source_authority.json").write_text('{"domains": []}')
    with pytest.raises(c.Refused, match="STORE_APPROVAL_PENDING"):
        a.run(root=root, state_root=state, trigger="weekly", now=NOW, apply=True)
    assert not state.exists()


def test_unknown_process_never_calls_model_or_writes(isolated):
    root, state = isolated
    with pytest.raises(c.Refused, match="AUDIT_PROCESS_REGISTRATION_PENDING"):
        a.run(root=root, state_root=state, trigger="weekly", now=NOW, apply=True, llm_review=True,
              generate=lambda *args, **kwargs: pytest.fail("unregistered model"))
    assert not state.exists()


def test_weekly_and_amendment_identities_are_distinct_and_exact():
    p = policy()
    weekly = a.audit_identity(p, trigger="weekly", now=NOW)
    assert weekly == a.audit_identity(p, trigger="weekly", now=NOW + timedelta(days=1))
    assert weekly != a.audit_identity(p, trigger="weekly", now=NOW + timedelta(days=7))
    amendment = a.audit_identity(p, trigger="amendment", now=NOW, amendment_sha=SHA, amendment_version="20.2.0")
    assert weekly != amendment
    with pytest.raises(c.Refused, match="AMENDMENT_IDENTITY_MISMATCH"):
        a.audit_identity(p, trigger="amendment", now=NOW, amendment_sha="b" * 40, amendment_version="20.2.0")


def test_file_existence_cannot_invent_test_or_runtime_pass(tmp_path):
    (tmp_path / "test.py").write_text("# fixture")
    measured = a.mechanical(policy(), {"rules": [{"anchor": "Never route", "tests": ["test.py"], "runtime_files": [], "ci_gates": []}]}, root=tmp_path)
    proof = next(iter(measured["proofs"].values()))
    assert proof["missing_files"] == [] and proof["test_passed"] is False and proof["runtime_passed"] is False


def test_stale_test_receipts_do_not_make_enforcement_green(tmp_path):
    result = a.mechanical(policy(), {"rules": [{"anchor": "Never route", "tests": [], "runtime_files": [], "ci_gates": []}]},
                          root=tmp_path, test_receipt={"source_sha": "stale", "passed_tests": ["anything"]})
    assert result["test_receipt_exact"] is False


def test_real_apply_only_creates_proposals_and_standard_attempt_receipt(isolated):
    root, state = isolated
    result = a.run(root=root, state_root=state, trigger="weekly", now=NOW, apply=True)
    rows = c.DecisionLedger(state / c.DECISION_REL, approved=lambda: False).rows()
    assert [r["event"] for r in rows] == ["AUDIT_FINDINGS"]
    assert rows[0]["effect"] == "PROPOSAL_ONLY" and result["auto_apply"] is False
    receipt = json.loads((state / "data/runtime/lane_attempts/policy-enforcement-audit/fixture-audit-1.json").read_text())
    assert receipt["run_id"] == "fixture-audit-1" and receipt["code_sha"] == SHA and receipt["produced_count"] == 1
    assert not any(r.get("decision") for r in rows)
    from scripts.lib.n8n_output_verdict import evaluate, validate_expected_output
    contract = json.loads((Path(__file__).resolve().parents[1] / "config/proposals/operator_approvals/audit_lane.json").read_text())["expected_output"]
    assert validate_expected_output(contract) == []
    verdict = evaluate(contract, receipt, run_id="fixture-audit-1", lane_id=a.LANE, mode="live", attempt=1,
                       code_sha=SHA, started_at=NOW.isoformat(), finished_at=NOW.isoformat())
    assert verdict["verdict"] == "produced"


def test_duplicate_retry_has_new_attempt_receipt_and_no_second_event(isolated, monkeypatch):
    root, state = isolated
    a.run(root=root, state_root=state, trigger="weekly", now=NOW, apply=True)
    monkeypatch.setenv("TRADEAI_RUN_ID", "fixture-audit-2")
    retry = a.run(root=root, state_root=state, trigger="weekly", now=NOW, apply=True)
    assert retry["duplicate"] is True and retry["reviewer_called"] is False
    receipt = json.loads((state / "data/runtime/lane_attempts/policy-enforcement-audit/fixture-audit-2.json").read_text())
    assert receipt["produced_count"] == 0 and receipt["empty_reason"] == "duplicate_audit"
    from scripts.lib.n8n_output_verdict import evaluate
    contract = json.loads((Path(__file__).resolve().parents[1] / "config/proposals/operator_approvals/audit_lane.json").read_text())["expected_output"]
    assert evaluate(contract, receipt, run_id="fixture-audit-2", lane_id=a.LANE, mode="live", attempt=1,
                    code_sha=SHA, started_at=NOW.isoformat(), finished_at=NOW.isoformat())["verdict"] == "empty_allowed"
    assert len(c.DecisionLedger(state / c.DECISION_REL, approved=lambda: False).rows()) == 1


def test_lock_contention_is_75_and_does_not_advance_output(isolated):
    root, state = isolated
    runtime = state / "data/runtime"; runtime.mkdir(parents=True)
    with (runtime / "policy_enforcement_audit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(c.Refused, match="AUDIT_LOCK_BUSY") as caught:
            a.run(root=root, state_root=state, trigger="weekly", now=NOW, apply=True)
    assert caught.value.status == 75
    assert not (runtime / "policy-enforcement-audit_last.json").exists()
    assert not (state / c.DECISION_REL).exists()


def test_reviewer_uses_redacted_input_and_governed_caps():
    p = policy()
    measured = {"mapped_count": 1, "unmapped_count": 2}
    calls = []
    def sanitise(messages, process):
        assert process == a.PROCESS
        return {"messages": [{**m, "content": m["content"].replace("PRIVATE", "[redacted]")} for m in messages]}
    def generate(messages, **kwargs):
        calls.append((messages, kwargs))
        assert "PRIVATE" not in json.dumps(messages)
        return {"_tradeai": {"governance_pass": True, "mock": False, "process_id": a.PROCESS, "provider": "deepseek"},
                "choices": [{"message": {"content": '{"findings": []}'}}]}
    assert a.review_findings(p, measured, [{"ref": "commit:1", "title": "PRIVATE"}], audit_key="a" * 40, generate=generate, sanitise=sanitise) == []
    assert calls[0][1]["process_id"] == a.PROCESS and calls[0][1]["budget"]["cost_ceiling_usd"] == .02
    assert calls[0][1]["tools"] is None


@pytest.mark.parametrize("meta", [{}, {"governance_pass": True, "mock": True, "process_id": a.PROCESS, "provider": "deepseek"}])
def test_ungoverned_or_mock_review_is_never_real_evidence(meta):
    with pytest.raises(c.Refused, match="AUDIT_REVIEW_GOVERNANCE_REFUSED"):
        a.review_findings(policy(), {"mapped_count": 0, "unmapped_count": 1}, [], audit_key="a" * 40,
                          generate=lambda *args, **kwargs: {"_tradeai": meta}, sanitise=lambda m, p: {"messages": m})


def test_fabricated_model_refs_are_rejected():
    rule = policy()["rules"][0]["id"]
    response = {"_tradeai": {"governance_pass": True, "mock": False, "process_id": a.PROCESS, "provider": "deepseek"},
                "choices": [{"message": {"content": json.dumps({"findings": [{"rule_id": rule, "evidence_refs": ["invented"]}]})}}]}
    with pytest.raises(c.Refused, match="AUDIT_REVIEW_UNSUPPORTED_OUTPUT"):
        a.review_findings(policy(), {"mapped_count": 0, "unmapped_count": 1}, [{"ref": "actual"}], audit_key="a" * 40,
                          generate=lambda *args, **kwargs: response, sanitise=lambda m, p: {"messages": m})
