"""Hermes research joins the decision that asked for it (options MORE_RESEARCH).

Measured 2026-10-03: 0 of 9,692 Hermes requests carried a decision id, so the
lineage research stages could never join a decision. The one real seam: when an
options CIO review returns MORE_RESEARCH, the thesis lifecycle asks Hermes for
follow-up research on behalf of that exact review (decision_guid in hand) and
already records the pair as OPTIONS_THESIS_FOLLOWUP_REQUESTED.for_decision.

Forward: the id rides the request, the projection, the result row and the
workflow envelope. Read side: the producer-recorded follow-up event links the
existing results (17 of 18 options reviews on prod). Nothing joins by symbol or
time; an unlinked request stays unlinked.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

DEC = "dec_c53f707a-1b33-48d4-a02c-33991b38ae19"
OTHER = "dec_00000000-0000-4000-8000-000000000000"


@pytest.fixture()
def cio(tmp_path, monkeypatch):
    import lib.cio_hermes_research as hr

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "cio"
    root.mkdir(parents=True)
    for name in (
        "cio_workflow_lineage.jsonl",
        "intelligence_lineages.jsonl",
        "outcome_checkpoints.jsonl",
        "decision_dispositions.jsonl",
    ):
        (root / name).write_text("", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(hr, "REQUEST_PATH", Path("data/cio/hermes_research_requests.jsonl"))
    monkeypatch.setattr(hr, "RESULT_PATH", Path("data/cio/hermes_research_results.jsonl"))
    monkeypatch.setattr(hr, "PROJECTION_PATH", Path("data/cio/hermes_research_projection.json"))
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: (
        {
            "decision_id": DEC,
            "symbol": "DELL",
            "action": "MORE_RESEARCH",
            "action_class": "options_thesis_review",
            "created_at": "2026-10-02T15:00:00+00:00",
            "metadata": {},
        }
        if params and params[0] == DEC
        else None
    )
    monkeypatch.setitem(sys.modules, "api_v2", stub)
    return hr, root


def _plan(**extra):
    return {
        "plan_id": "plan_dell_1",
        "situation_type": "S7_WATCH_PROMOTION",
        "symbols": ["DELL"],
        "thesis_version": "",
        **extra,
    }


def _questions():
    return [{"intent": "bear_case", "text": "What would make the DELL put thesis wrong before expiry?"}]


def _stage(did, name):
    import scripts.api_v3_cio as api

    api.load_known_decision_catalog = lambda: {}
    out = api.get_cio_decision_lineage(did)
    assert out["ok"] is True, out
    return out["lineage"]["stages"][name]


def _rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_followup_request_and_result_carry_the_review_decision(cio):
    hr, root = cio
    rr = hr.enqueue_research_request(
        _plan(decision_ids=[DEC]), questions=_questions(), actor_id="options_thesis_lifecycle"
    )
    assert rr["ok"] and rr["created"]
    req = [r for r in _rows(root / "hermes_research_requests.jsonl") if r.get("event") == "HERMES_RESEARCH_REQUESTED"]
    assert req[0]["decision_ids"] == [DEC]
    done = hr.complete_research_result(
        rr["research_id"], answers=[{"confidence": 0.6}], findings=["Backlog is the risk"], summary="Bear case found"
    )
    assert done["ok"]
    result = [r for r in _rows(root / "hermes_research_results.jsonl")][-1]
    assert result["decision_ids"] == [DEC]
    envelopes = [r for r in _rows(root / "cio_workflow_lineage.jsonl") if r.get("record_type") == "envelope"]
    assert any(DEC in (e.get("decision_ids") or []) for e in envelopes)
    stage = _stage(DEC, "research_retrieved")
    assert stage["state"] == "LIVE"
    assert stage["value"] == [result["result_id"]]


def test_unlinked_research_never_joins_a_decision(cio):
    hr, root = cio
    rr = hr.enqueue_research_request(_plan(), questions=_questions(), actor_id="cio_situation_detector")
    hr.complete_research_result(rr["research_id"], answers=[{"confidence": 0.6}], findings=["x"], summary="s")
    assert "decision_ids" not in _rows(root / "hermes_research_results.jsonl")[-1]
    assert _stage(DEC, "research_retrieved")["state"] != "LIVE"


def test_a_second_decision_joining_in_flight_research_is_linked_too(cio):
    hr, root = cio
    first = hr.enqueue_research_request(_plan(decision_ids=[OTHER]), questions=_questions())
    again = hr.enqueue_research_request(_plan(decision_ids=[DEC]), questions=_questions())
    assert again["research_id"] == first["research_id"] and not again["created"]
    hr.complete_research_result(first["research_id"], answers=[{"confidence": 0.6}], findings=["x"], summary="s")
    assert _rows(root / "hermes_research_results.jsonl")[-1]["decision_ids"] == sorted([DEC, OTHER])
    linked = [
        r for r in _rows(root / "hermes_research_requests.jsonl") if r.get("event") == "HERMES_RESEARCH_DECISION_LINKED"
    ]
    assert linked and DEC in linked[-1]["decision_ids"]


def test_producer_recorded_followup_links_an_existing_result(cio):
    _hr, root = cio
    (root / "hermes_research_results.jsonl").write_text(
        json.dumps(
            {
                "event": "HERMES_RESEARCH_COMPLETED",
                "research_id": "res_af3949567ece",
                "result_id": "rr_1",
                "status": "completed",
                "symbol": "DELL",
                "completed_ts": "2026-10-02T16:00:00+00:00",
                "as_of": "2026-10-02T16:00:00+00:00",
                "findings": ["x"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "options_theses.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                {
                    "event_type": "OPTIONS_THESIS_FOLLOWUP_REQUESTED",
                    "position_guid": "g1",
                    "research_id": "res_af3949567ece",
                    "for_decision": DEC,
                    "plan_id": "plan_x",
                },
                {
                    "event_type": "OPTIONS_THESIS_FOLLOWUP_REQUESTED",
                    "position_guid": "g2",
                    "research_id": "res_other",
                    "for_decision": OTHER,
                    "plan_id": "plan_y",
                },
            ]
        ),
        encoding="utf-8",
    )
    stage = _stage(DEC, "research_retrieved")
    assert stage["state"] == "LIVE"
    assert stage["value"] == ["rr_1"]
    from scripts.lib.cio_operator_evidence import _research_provenance

    arts = _research_provenance(root, decision_id=DEC)["artifacts"]
    assert arts[0]["decision_link_basis"] == "options_theses:OPTIONS_THESIS_FOLLOWUP_REQUESTED.for_decision"
    assert _research_provenance(root, decision_id=OTHER)["artifacts"] == []


def test_more_research_followup_passes_the_review_decision(tmp_path):
    from lib import options_thesis as ot
    from lib import options_thesis_lifecycle as lc

    cfg = {"options_thesis_lifecycle": {"abandon_after_hours": 48, "cio_review_mode": "live", "max_reviews_per_run": 6}}
    t0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    store = ot.OptionsThesisStore(tmp_path / "t.jsonl")
    store._append(
        {
            "event_type": "OPTIONS_THESIS_VERSION",
            "position_guid": "g1",
            "version": 1,
            "pin": "opt_g1@v1",
            "recorded_at": t0.isoformat(),
        }
    )
    p = {
        "symbol": "DELL",
        "strategy": "cash_secured_put",
        "option_strategy_guid": "g1",
        "expiration": "2026-11-20",
        "dte": 55,
        "options_thesis": {"pin": "opt_g1@v1", "missing_required": []},
    }
    rev = {
        "outcome": "MORE_RESEARCH",
        "confidence": "MEDIUM",
        "reasoning": "Catalyst after expiry",
        "concerns": ["earnings after expiry"],
        "evidence_for": [],
        "evidence_against": [],
    }
    asked = []

    def run(now, review=None):
        return lc.advance(
            [dict(p)],
            store,
            cfg,
            request_research=lambda q, qs=None: asked.append(q) or {"research_id": "r", "plan_id": "pl"},
            research_status=lambda rid: {"status": "queued"},
            review_fn=review or (lambda x, m: {"status": "DRY_RUN"}),
            record_decision=lambda r: None,
            apply=True,
            now=now,
        )

    run(t0 + timedelta(hours=1), review=lambda x, m: {"status": "OK", "review": rev, "decision_guid": DEC})
    step = run(t0 + timedelta(hours=2))[0]
    assert step["action"] == "REQUEST_FOLLOWUP"
    assert asked[-1]["for_decision"] == DEC


def test_lifecycle_adapter_threads_for_decision_onto_the_plan(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "otl_adapter_20261003", ROOT / "scripts" / "options_thesis_lifecycle.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    import lib.cio_plans as plans
    import lib.hermes_research_loop as loop
    import options_desk_enterprise as desk

    seen = {}
    monkeypatch.setattr(
        plans,
        "CIOPlanStore",
        lambda: types.SimpleNamespace(create_plan=lambda **kw: {"plan_id": "plan_t", "symbols": kw.get("symbols")}),
    )
    monkeypatch.setattr(
        loop,
        "emit_research_for_plan",
        lambda plan, **kw: seen.update(plan=plan) or {"ok": True, "research_id": "res_t"},
    )
    monkeypatch.setattr(desk, "load_desk_config", lambda: {})
    adapter.request_research({"symbol": "DELL", "strategy": "cash_secured_put", "for_decision": DEC}, _questions())
    assert seen["plan"]["decision_ids"] == [DEC]
    adapter.request_research({"symbol": "DELL", "strategy": "cash_secured_put"}, _questions())
    assert "decision_ids" not in seen["plan"]
