"""Join design Phases 3-4 (operator-approved 2026-10-03).

Phase 3: capital-plan decision ids are recomputed per request and were never
saved, so an id the operator opened stopped resolving once its text changed; and
no CIO-run record carried the decisions it produced. Phase 4: the framework that
sized each capital-plan decision is recorded with it.
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

from scripts.lib import cio_capital_plan_decision_store as store  # noqa: E402
from scripts.lib.cio_decision_lineage_projection import project_decision_lineage  # noqa: E402
from scripts.lib.cio_lineage import (  # noqa: E402
    iter_lineage_records,
    load_envelope,
    persist_canonical_checkpoint,
    record_cio_generation,
    record_notification,
    record_specialist_dispatch,
)
from scripts.lib.cio_run_worker import _produced_decision_ids  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path_factory.mktemp("id") / "registry.json"))
    monkeypatch.delenv("CIO_CAPITAL_PLAN_DECISIONS_JSONL", raising=False)
    store._INDEX.clear()


def _decision(did: str, **kw) -> dict:
    return {"decision_id": did, "symbol": "SCHD", "cio_stance": "HOLD", "stance": "Hold", "stance_code": "HOLD",
            "recommended_delta_usd": 0.0,
            "why_now": "inside band", "decision_input_digest": f"in_{did}", "decision_evidence_digest": f"ev_{did}",
            "decision_policy_version": "capital_plan_1.3.0", "generated_at": "2026-10-03", **kw}


# ── store ────────────────────────────────────────────────────────────────────

def _lines(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def test_store_appends_each_new_id_once_and_repeat_builds_write_nothing(tmp_path):
    p = tmp_path / "decisions.jsonl"
    assert store.record_position_decisions([_decision("dec_a"), _decision("dec_b")], path=p)["written"] == 2
    assert store.record_position_decisions([_decision("dec_a"), _decision("dec_b")], path=p)["written"] == 0
    assert store.record_position_decisions([_decision("dec_a"), _decision("dec_c")], path=p)["written"] == 1
    rows = _lines(p)
    assert [r["decision_id"] for r in rows] == ["dec_a", "dec_b", "dec_c"]
    assert rows[0]["schema"] == "CIOCapitalPlanDecision@v1"
    assert rows[0]["source_ref"] == "cio_capital_plan_decisions:dec_a"
    assert rows[0]["authority"] == "READ_ONLY_ADVISORY" and rows[0]["memory_behavior_influence"] == 0


def test_store_index_refreshes_when_another_writer_appends(tmp_path):
    p = tmp_path / "decisions.jsonl"
    store.record_position_decisions([_decision("dec_a")], path=p)
    with p.open("a") as fh:  # another process
        fh.write(json.dumps({"decision_id": "dec_x", "symbol": "VTI"}) + "\n")
    assert store.load_decision("dec_x", path=p)["symbol"] == "VTI"
    assert store.record_position_decisions([_decision("dec_x")], path=p)["written"] == 0


def test_store_never_raises_when_the_path_is_unwritable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    out = store.record_position_decisions([_decision("dec_a")], path=blocker / "sub" / "d.jsonl")
    assert out["written"] == 0 and "error" in out
    assert store.load_decision("dec_a", path=blocker / "sub" / "d.jsonl") is None


def test_rows_without_an_id_are_ignored(tmp_path):
    p = tmp_path / "decisions.jsonl"
    assert store.record_position_decisions([{"symbol": "X"}, None, {}], path=p)["written"] == 0
    assert not p.exists()


# ── churned id resolves through the real lineage endpoint ────────────────────

def _cio_root(tmp_path: Path) -> Path:
    root = tmp_path / "cio"
    root.mkdir(parents=True)
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    return root


def _endpoint(monkeypatch, root: Path, did: str) -> dict:
    import scripts.api_v3_cio as api

    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: None
    monkeypatch.setitem(sys.modules, "api_v2", stub)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    return api.get_cio_decision_lineage(did)


def test_a_churned_capital_plan_id_still_resolves_from_the_store(tmp_path, monkeypatch):
    root = _cio_root(tmp_path)
    store.record_position_decisions([_decision("dec_churned")], path=root / "cio_capital_plan_decisions.jsonl")
    result = _endpoint(monkeypatch, root, "dec_churned")
    assert result["ok"] is True, result
    lineage = result["lineage"]
    office = lineage["stages"]["office_truth"]
    assert office["state"] == "LIVE" and office["value"] == "in_dec_churned"
    assert office["source_ref"] == "cio_capital_plan_decisions:dec_churned"
    judgment = lineage["stages"]["judgment"]
    assert judgment["state"] == "LIVE" and judgment["value"] == "Hold"


def test_an_unknown_id_is_still_not_found(tmp_path, monkeypatch):
    root = _cio_root(tmp_path)
    store.record_position_decisions([_decision("dec_other")], path=root / "cio_capital_plan_decisions.jsonl")
    assert _endpoint(monkeypatch, root, "dec_never_seen")["error"] == "decision_lineage_not_found"


# ── decision_ids stamping ────────────────────────────────────────────────────

def test_produced_ids_come_only_from_the_synthesis_product():
    assert _produced_decision_ids({"result": {"decision_id": "cio_books_1", "product_id": "prod_cio_books_1"}}) == [
        "cio_books_1", "prod_cio_books_1"]
    assert _produced_decision_ids({"result": {"summary": "fallback"}}) == []
    assert _produced_decision_ids(None) == []


def test_envelope_decision_ids_union_and_survive_later_upserts(tmp_path):
    p = tmp_path / "lineage.jsonl"
    record_cio_generation("run_1", generation_id="gen_1", decision_ids=["prod_a"], path=p)
    record_cio_generation("run_1", generation_id="gen_2", decision_ids=["prod_b", "prod_a"], path=p)
    record_notification("run_1", notification_id="ntf_1", classification="IMMEDIATE", path=p)
    assert load_envelope("run_1", p)["decision_ids"] == ["prod_a", "prod_b"]


def test_stamped_run_joins_its_stages_to_the_product_decision(tmp_path):
    p = tmp_path / "lineage.jsonl"
    record_specialist_dispatch("run_2", "dispatch_1", agent_id="maria", artifact_id="art_1", path=p)
    record_cio_generation("run_2", generation_id="gen_9", decision_ids=["prod_cio_books_9"], path=p)
    record_notification("run_2", notification_id="ntf_9", classification="IMMEDIATE", path=p)
    stages = project_decision_lineage("prod_cio_books_9", workflow_records=iter_lineage_records(p))["stages"]
    assert stages["specialist_delegation"]["state"] == "LIVE"
    assert stages["notification"]["state"] == "LIVE" and stages["notification"]["value"] == "ntf_9"
    # The run's own id still joins exactly as before.
    assert project_decision_lineage("run_2", workflow_records=iter_lineage_records(p))["stages"][
        "notification"]["state"] == "LIVE"
    # A decision the run did not produce does not join.
    assert project_decision_lineage("prod_other", workflow_records=iter_lineage_records(p))["stages"][
        "notification"]["state"] != "LIVE"


def test_checkpoint_row_carries_the_produced_ids(tmp_path):
    p = tmp_path / "lineage.jsonl"
    out = persist_canonical_checkpoint(tmp_path, "run_3", {
        "decision_id": "run_3", "subject_id": "goal_x", "entity_type": "GOAL", "recommendation": "OBSERVE",
        "producer_id": "cio_run_worker", "decision_ids": ["prod_cio_books_3"]}, "sha", path=p)
    assert out["checkpoint"]["decision_ids"] == ["prod_cio_books_3"]


# ── Phase 4: the framework that sized each capital-plan decision ─────────────

DESK = {"thesis_id": "desk", "version": 5, "thesis_version": "desk@v5"}


def test_framework_named_only_when_the_desk_thesis_supplied_a_sizing_parameter():
    applied = store.framework_fields(DESK, {"max_single_name_weight_pct": 12.0, "cash_band_min_pct": 20.0})
    assert applied["framework_refs"] == ["cio_thesis:desk@v5"]
    assert applied["framework_parameters"] == {"max_single_name_weight_pct": 12.0}
    assert "portfolio" in applied["framework_scope"]
    # Policy defaults were used: the thesis had no influence on sizing.
    assert store.framework_fields(DESK, {"cash_band_min_pct": 20.0}) == {}
    assert store.framework_fields(DESK, {}) == {}
    assert store.framework_fields({}, {"concentration_fire_pct": 16.5}) == {}


def test_stored_row_records_the_policy_version_as_its_methodology(tmp_path):
    p = tmp_path / "d.jsonl"
    store.record_position_decisions([_decision("dec_m")], path=p,
                                    extra=store.framework_fields(DESK, {"concentration_fire_pct": 16.5}))
    row = store.load_decision("dec_m", path=p)
    assert row["methodology_ref"] == "capital_plan_1.3.0"
    assert row["framework_refs"] == ["cio_thesis:desk@v5"]
    # extra never overrides a decision field
    store.record_position_decisions([_decision("dec_n")], path=p, extra={"decision_id": "forged", "symbol": "X"})
    assert store.load_decision("dec_n", path=p)["symbol"] == "SCHD"


def test_canon_frameworks_live_from_the_stored_row(tmp_path, monkeypatch):
    root = _cio_root(tmp_path)
    store.record_position_decisions(
        [_decision("dec_canon")], path=root / "cio_capital_plan_decisions.jsonl",
        extra=store.framework_fields(DESK, {"max_single_name_weight_pct": 12.0}),
    )
    stage = _endpoint(monkeypatch, root, "dec_canon")["lineage"]["stages"]["canon_frameworks"]
    assert stage["state"] == "LIVE"
    assert stage["value"] == ["cio_thesis:desk@v5"]
    assert stage["source_ref"] == "cio_capital_plan_decisions:dec_canon"


def test_canon_frameworks_stays_unwired_for_a_decision_with_no_row(tmp_path, monkeypatch):
    root = _cio_root(tmp_path)
    store.record_position_decisions([_decision("dec_canon")], path=root / "cio_capital_plan_decisions.jsonl")
    trace = {"trace_id": "tr", "wake_id": "wk", "role": "reentry", "started_at": "2026-10-03T00:00:00+00:00",
             "ended_at": "2026-10-03T00:00:00+00:00", "decision": {"decision_id": "dec_reentry_X", "symbol": "X",
             "as_of": "2026-10-03T00:00:00+00:00", "current_action": "WAIT"}}
    (root / "agent_run_traces.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    stage = _endpoint(monkeypatch, root, "dec_reentry_X")["lineage"]["stages"]["canon_frameworks"]
    assert stage["state"] == "UNWIRED"
