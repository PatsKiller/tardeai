"""Inherited dark WIRE modules, operator-approved 2026-10-03.

decision_rationale: every natural decision and capital-plan decision carries a
DecisionRationale@v1 built only from fields the producer stated, and decision
lineage shows it with the judgment. symbol_thesis_event_wake: consumed by the CIO
wake dispatcher, SHADOW unless both governance flags are set.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import decision_rationale as dr  # noqa: E402
from scripts.lib import symbol_thesis_event_wake as stw  # noqa: E402

RATIONALE_KEYS = {
    "schema", "decision_id", "conclusion", "structured_reason_codes", "evidence_refs",
    "model_provider", "context_digest", "created_at", "authority", "financial_action",
    "source_ref", "as_of",
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    for name in (stw.MODE_ENV, stw.GOVERNANCE_FLAG):
        monkeypatch.delenv(name, raising=False)


def _payload(**over):
    from scripts.lib.agent_decision_payload import build_decision_payload

    base = dict(
        decision_id="dec_reentry_TEST_NEAR", wake_id="wake_t", trace_id="tr_t", symbol="ZZZT",
        surface="reentry", current_action="NEAR", inputs_digest="ctx_1",
        evidence_refs=["ev_1", "", "ev_2"],
        gates_evaluated=[{"id": "fresh", "label": "Fresh quote", "pass": True, "value": "0h"},
                         {"id": "zone", "label": "Inside entry zone", "pass": False}],
        extra={"intel_state": "READY TO REVIEW", "chain_of_thought": "secret musing", "reasoning": "x"},
    )
    base.update(over)
    return build_decision_payload(**base)


# ── decision_rationale ───────────────────────────────────────────────────────

def test_rationale_holds_only_producer_stated_fields():
    r = dr.rationale_for_decision_payload(_payload(), source_ref="agent_run_traces#tr_t")
    assert r["schema"] == "DecisionRationale@v1"
    assert set(r) <= RATIONALE_KEYS
    assert r["conclusion"] == "reentry: NEAR"
    assert r["structured_reason_codes"] == [
        "gate:fresh=pass", "gate:zone=fail", "decision_origin:DETERMINISTIC_RANK", "intel_state:READY TO REVIEW",
    ]
    assert r["evidence_refs"] == ["ev_1", "ev_2"]
    flat = json.dumps(r)
    assert "secret musing" not in flat and "chain_of_thought" not in flat


def test_rationale_refuses_private_reasoning_shapes():
    with pytest.raises(RuntimeError):
        dr.reject_private_reasoning({"scratchpad": "hidden"})


def test_emitted_trace_carries_the_rationale(tmp_path):
    from scripts.lib.agent_decision_payload import emit_decision_payload

    dest = tmp_path / "agent_run_traces.jsonl"
    out = emit_decision_payload(_payload(), flags={"AGENT_DECISION_PAYLOAD": 1},
                                path=dest)
    assert out["emitted"] is True, out
    decision = json.loads(dest.read_text().splitlines()[-1])["decision"]
    assert decision["rationale"]["decision_id"] == "dec_reentry_TEST_NEAR"
    assert decision["rationale"]["source_ref"] == f"agent_run_traces#{out['trace_id']}"


def test_a_rationale_failure_never_costs_the_decision(tmp_path, monkeypatch):
    from scripts.lib.agent_decision_payload import emit_decision_payload

    monkeypatch.setattr(dr, "rationale_for_decision_payload", lambda *a, **k: 1 / 0)
    dest = tmp_path / "agent_run_traces.jsonl"
    out = emit_decision_payload(_payload(), flags={"AGENT_DECISION_PAYLOAD": 1},
                                path=dest)
    assert out["emitted"] is True and out["error"] is None
    assert "rationale" not in json.loads(dest.read_text().splitlines()[-1])["decision"]


def test_capital_plan_store_row_carries_why_now_as_the_rationale(tmp_path):
    from scripts.lib.cio_capital_plan_decision_store import load_decision, record_position_decisions

    store = tmp_path / "cio_capital_plan_decisions.jsonl"
    record_position_decisions([{
        "decision_id": "dec_cp1", "symbol": "SCHD", "cio_stance": "HOLD", "stance_code": "Hold",
        "why_now": "Within target band; no new evidence.", "decision_input_digest": "dig1",
        "decision_policy_version": "capital_plan_1.3.0",
    }], path=store, extra={"framework_refs": ["cio_thesis:desk@v5"]})
    r = load_decision("dec_cp1", path=store)["rationale"]
    assert r["conclusion"] == "Within target band; no new evidence."
    assert r["structured_reason_codes"] == [
        "cio_stance:HOLD", "stance_code:Hold", "decision_policy_version:capital_plan_1.3.0"]
    assert r["evidence_refs"] == ["cio_thesis:desk@v5"]
    assert set(r) <= RATIONALE_KEYS


def test_lineage_shows_the_rationale_with_the_judgment(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    root = tmp_path / "cio"
    root.mkdir()
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    decision = _payload()
    decision["rationale"] = dr.rationale_for_decision_payload(decision, source_ref="agent_run_traces#tr_t")
    trace = {"agent": "alex", "role": "reentry", "trace_id": "tr_t", "wake_id": "wake_t",
             "started_at": decision["as_of"], "ended_at": decision["as_of"], "status": "completed",
             "decision": decision}
    (root / "agent_run_traces.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: None
    monkeypatch.setitem(sys.modules, "api_v2", stub)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    res = api.get_cio_decision_lineage("dec_reentry_TEST_NEAR")
    shown = res["lineage"]["stages"]["judgment"]["rationale"]
    assert shown["conclusion"] == "reentry: NEAR"
    assert "gate:zone=fail" in shown["structured_reason_codes"]


# ── symbol_thesis_event_wake ─────────────────────────────────────────────────

def test_mode_needs_both_flags():
    assert stw.wake_mode({}) == "shadow"
    assert stw.wake_mode({stw.GOVERNANCE_FLAG: "1"}) == "shadow"
    assert stw.wake_mode({stw.MODE_ENV: "active"}) == "shadow"
    assert stw.wake_mode({stw.MODE_ENV: "active", stw.GOVERNANCE_FLAG: "1"}) == "active"


def _bus(root: Path) -> None:
    (root / "data" / "cio").mkdir(parents=True)
    rows = [
        {"event_id": "evt-aaa", "event_type": "watch.new_signal", "payload": {"symbol": "tsla"}},
        {"event_id": "evt-bbb", "event_type": "plan.enriched", "payload": {"symbol": "SCHD"}},
    ]
    (root / stw.EVENTS_RELATIVE).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


DISPATCHED = [
    {"wake_job_id": "w1", "run_id": "r1", "trigger_type": "EVENT_BUS", "trigger_ref": "evt-aaa"},
    {"wake_job_id": "w2", "run_id": "r2", "trigger_type": "EVENT_BUS", "trigger_ref": "evt-bbb"},
    {"wake_job_id": "w3", "run_id": "r3", "trigger_type": "SCHEDULE_DUE", "trigger_ref": "WATCH:PLTR"},
]


def test_shadow_only_plans_and_writes_receipts(tmp_path, monkeypatch):
    _bus(tmp_path)

    def forbidden(*a, **k):
        raise AssertionError("SHADOW must not run checks or emit")

    monkeypatch.setattr(stw, "execute_wake_checks", forbidden)
    monkeypatch.setattr(stw, "emit_cio_wake_if_enabled", forbidden)
    out = stw.consume_dispatched_wakes(DISPATCHED, root=tmp_path, env={stw.GOVERNANCE_FLAG: "1"})
    assert out["mode"] == "shadow" and "error" not in out
    assert (out["considered"], out["planned"], out["unmapped"], out["checks_run"]) == (2, 1, 1, 0)
    receipts = [json.loads(x) for x in (tmp_path / stw.RECEIPTS_RELATIVE).read_text().splitlines()]
    assert [r["action"] for r in receipts] == ["SHADOW_PLANNED", "NOT_A_THESIS_WAKE_EVENT"]
    assert receipts[0]["symbol"] == "TSLA" and receipts[0]["kind"] == "candidate_discovery"
    assert all(r["checks_run"] is False and r["emitted"] is False for r in receipts)
    assert not (tmp_path / "data" / "cio" / "symbol_thesis_wake_dedupe.json").exists()


def test_active_path_runs_checks_only_with_both_flags(tmp_path, monkeypatch):
    _bus(tmp_path)
    calls = []
    monkeypatch.setattr(stw, "execute_wake_checks",
                        lambda symbol, **k: calls.append(symbol) or {"checks": {"coverage_state": "ok"}})
    out = stw.consume_dispatched_wakes(DISPATCHED, root=tmp_path,
                                       env={stw.MODE_ENV: "active", stw.GOVERNANCE_FLAG: "1"})
    assert out["mode"] == "active" and calls == ["TSLA"] and out["checks_run"] == 1


def test_consumer_never_fails_the_dispatch_cycle(tmp_path):
    out = stw.consume_dispatched_wakes([{"trigger_type": "EVENT_BUS", "trigger_ref": "evt-zzz"}], root=tmp_path)
    assert out["mode"] == "shadow" and out["unmapped"] == 1
