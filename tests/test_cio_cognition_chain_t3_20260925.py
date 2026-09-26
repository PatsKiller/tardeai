"""Tranche 3 (2026-09-25): the research → advice → feedback → outcome → belief
→ later-judgment chain, hermetic controls for the joins measured broken on
the served release 1c60ecb42.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Selector reads record TIPS, not history ────────────────────────────────

def test_selector_uses_latest_record_version_not_oldest():
    from scripts.lib.wake_subject_selector import (
        instrument_record_candidates, latest_record_per_subject,
    )
    now = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
    future = (now + timedelta(days=3)).isoformat()
    history = [
        {"subject_key": "HELD:NOC", "as_of": "2026-09-01T00:00:00Z", "next_eligible_at": None},
        {"subject_key": "HELD:NOC", "as_of": "2026-09-25T14:00:00Z", "next_eligible_at": future},
        {"subject_key": "HELD:MCD", "as_of": "2026-09-20T00:00:00Z", "next_eligible_at": None},
    ]
    tips = {r["subject_key"]: r for r in latest_record_per_subject(history)}
    assert tips["HELD:NOC"]["next_eligible_at"] == future
    cands = instrument_record_candidates(history, now=now, guid_for_symbol=lambda s: f"g:{s}")
    assert [c.source_id for c in cands] == ["HELD:MCD"]


# ── Goals: binding, due advance, honest close ──────────────────────────────

def test_goal_id_recovered_from_wake_goal_trigger_ref():
    from scripts.lib.cio_run_worker import goal_id_from_trigger_ref
    assert goal_id_from_trigger_ref("wake_goal_goal_695a5dbe2401_2026092514") == "goal_695a5dbe2401"
    assert goal_id_from_trigger_ref("goal_695a5dbe2401") == "goal_695a5dbe2401"
    assert goal_id_from_trigger_ref("wake_ev_alex_abc_2026092514") is None
    assert goal_id_from_trigger_ref(None) is None


def _goal_store(tmp_path):
    from scripts.lib.cio_goals import CIOGoalStore
    return CIOGoalStore(event_path=tmp_path / "goals.jsonl",
                        projection_path=tmp_path / "proj.json",
                        cursor_path=tmp_path / "cur.json")


def test_record_wake_advances_past_due_ts_one_cadence(tmp_path):
    store = _goal_store(tmp_path)
    g = store.create_goal(owner_agent="alex", title="t3", description="",
                          priority="HIGH", actor_id="test")
    gid = g["goal_id"]
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    # `update_goal` refuses a due_ts before created_ts (the live inversion
    # defect); the live goals reached this state historically, so fold the
    # raw event the projection reads.
    store._append_event("GOAL_UPDATED", gid, {"due_ts": past}, actor_id="test")
    assert store.get_goal(gid)["due_ts"] == past
    assert store.list_due_or_idle_goals() and store.list_due_or_idle_goals()[0]["goal_id"] == gid
    store.record_wake(gid, agent_id="alex", outcome="run_started:r1")
    after = store.get_goal(gid)
    assert datetime.fromisoformat(after["due_ts"]) > datetime.now(timezone.utc)
    # No longer due; not idle (just woken); so not re-selected next cycle.
    assert not [x for x in store.list_due_or_idle_goals() if x["goal_id"] == gid]
    # Reload from the event log: the advance is durable, not projection-only.
    store2 = _goal_store(tmp_path)
    assert store2.get_goal(gid)["due_ts"] == after["due_ts"]


def test_lane_close_goal_refuses_without_falsifier_and_passes_evidence(tmp_path, monkeypatch):
    import argparse
    import run_dormant_lane_consumers as lane
    (tmp_path / "data" / "cio").mkdir(parents=True)
    store = _goal_store(tmp_path / "data" / "cio")
    # lane builds its own store from root/data/cio with fixed names; mirror them
    from scripts.lib.cio_goals import CIOGoalStore
    store = CIOGoalStore(event_path=tmp_path / "data/cio/cio_goals.jsonl",
                         projection_path=tmp_path / "data/cio/cio_goals_projection.json",
                         cursor_path=tmp_path / "data/cio/cio_goal_event_cursors.json")
    g1 = store.create_goal(owner_agent="alex", title="no falsifier", description="", priority="HIGH", actor_id="t")
    store._append_event("GOAL_UPDATED", g1["goal_id"],
                        {"completed_ts": "2026-09-25T10:00:00Z", "evidence_refs": ["ev:1"]}, actor_id="t")
    g2 = store.create_goal(owner_agent="alex", title="closable", description="", priority="HIGH", actor_id="t")
    store._append_event("GOAL_UPDATED", g2["goal_id"],
                        {"completed_ts": "2026-09-25T10:00:00Z", "evidence_refs": ["ev:2"],
                         "falsifier": "the desk thesis is not restated for five consecutive sessions"},
                        actor_id="t")
    res = lane.lane_close_goal(argparse.Namespace(root=str(tmp_path), apply=True))
    refused = {r["goal_id"]: r["reason"] for r in res["refused"]}
    assert refused.get(g1["goal_id"]) == "no_falsifier"
    fresh = CIOGoalStore(event_path=tmp_path / "data/cio/cio_goals.jsonl",
                         projection_path=tmp_path / "data/cio/cio_goals_projection.json",
                         cursor_path=tmp_path / "data/cio/cio_goal_event_cursors.json")
    assert fresh.get_goal(g2["goal_id"])["status"] == "achieved"
    assert fresh.get_goal(g1["goal_id"])["status"] == "open"


# ── Gate bridge honesty ────────────────────────────────────────────────────

def _ledger_row(aid, refs, snap):
    return {"event_type": "CIO_ACTION_CREATED", "event_id": f"e-{aid}", "stream_id": aid,
            "payload": {"cio_action_id": aid, "domain": "portfolio", "status": "PROPOSED",
                        "evidence_refs": refs, "source_snapshot_id": snap}}


def test_gate2_counts_evidence_refs_and_snapshot_not_domain_label(tmp_path):
    import cio_gate_measurement_bridge as B
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    rows = [_ledger_row("a1", ["ref:x"], "snap-1"), _ledger_row("a2", [], "snap-1"),
            _ledger_row("a3", ["ref:y"], None), _ledger_row("a4", ["ref:z"], "snap-2")]
    (cio / "cio_action_ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    m = B._measure_alex(tmp_path)
    g2 = m["gates"]["retrieval_provenance_completeness"]
    assert g2["measured_value"] == 0.5 and g2["status"] == "FAIL"
    assert "domain label" in g2["evidence"]


def test_gate3_join_works_when_sentinel_names_artifact(tmp_path):
    import cio_gate_measurement_bridge as B
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    rows = [_ledger_row("a1", ["r"], "s"), _ledger_row("a2", ["r"], "s")]
    (cio / "cio_action_ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    reviews = [{"event_type": "SENTINEL_REVIEW", "reviewer_agent_id": "sentinel",
                "producer_agent_id": "alex", "artifact_id": "a1", "verdict": "PASS"},
               {"event_type": "SENTINEL_REVIEW", "reviewer_agent_id": "sentinel",
                "producer_agent_id": "alex", "artifact_id": None, "verdict": "PASS"}]
    (cio / "sentinel_reviews.jsonl").write_text("\n".join(json.dumps(r) for r in reviews) + "\n")
    m = B._measure_alex(tmp_path)
    g3 = m["gates"]["independent_review_coverage"]
    assert g3["measured_value"] == 0.5


def test_sentinel_writes_one_row_per_affected_action_with_artifact_id(tmp_path, monkeypatch):
    import sentinel_artifact_review as S
    monkeypatch.setattr(S, "REVIEW_PATH", tmp_path / "sentinel_reviews.jsonl")
    monkeypatch.setattr(S, "ACTION_LEDGER", tmp_path / "ledger.jsonl", raising=False)
    written = []
    monkeypatch.setattr(S, "_append_jsonl", lambda path, entry: written.append(entry))
    # Drive the writer with a synthetic findings list via the module's own loop
    # shape: monkeypatch the ledger loader to two duplicate-titled actions.
    if hasattr(S, "_read_jsonl"):
        monkeypatch.setattr(S, "_read_jsonl", lambda p: [
            {"event_type": "CIO_ACTION_CREATED", "payload": {"cio_action_id": "a1", "title": "Trim NOC", "domain": "portfolio", "status": "PROPOSED", "created_at": "2026-09-01T00:00:00+00:00"}},
            {"event_type": "CIO_ACTION_CREATED", "payload": {"cio_action_id": "a2", "title": "Trim NOC", "domain": "portfolio", "status": "PROPOSED", "created_at": "2026-09-01T00:00:00+00:00"}},
        ])
    fn = getattr(S, "run_review", None) or getattr(S, "review_artifacts", None) or getattr(S, "run", None)
    assert fn is not None, [n for n in dir(S) if not n.startswith("_")]
    fn()
    assert written, "no review rows written"
    assert all("artifact_id" in r for r in written)
    assert any(r["artifact_id"] in ("a1", "a2") for r in written)


def test_darwin_reviewer_comes_from_review_rows_not_a_constant():
    import darwin_outcome_scorer as D
    m = D.reviewers_by_artifact([
        {"artifact_id": "a1", "reviewer_agent_id": "sentinel"},
        {"artifact_id": None, "reviewer_agent_id": "sentinel"},
        {"artifact_id": "a2", "reviewer": "iris"},
    ])
    assert m == {"a1": "sentinel", "a2": "iris"}
    src = (ROOT / "scripts" / "darwin_outcome_scorer.py").read_text(encoding="utf-8")
    assert '"reviewer": "iris"' not in src


# ── MemoryConsumptionReceipt@v1 ────────────────────────────────────────────

def test_consumption_receipt_written_only_when_memory_ids_returned(tmp_path):
    from scripts.lib import memory_consumption_receipt as R
    path = tmp_path / "r.jsonl"
    none = R.record_consumption(consumer="advisory_desk_operator", purpose="p", symbols=["NOC"],
                                result={"supporting": [], "counter_memory": []}, path=path)
    assert none is None and not path.exists()
    rec = R.record_consumption(consumer="advisory_desk_operator", purpose="p", symbols=["noc"],
                               result={"supporting": [{"memory_id": "m1"}], "counter_memory": [{"memory_id": "m2"}],
                                       "retrieval_status": "OK"}, path=path)
    assert rec["schema"] == "MemoryConsumptionReceipt@v1" and rec["symbols"] == ["NOC"]
    assert rec["memory_ids_supporting"] == ["m1"] and rec["memory_ids_counter"] == ["m2"]
    R.record_consumption(consumer="hermes_research_prompt", purpose="q", symbols=["NOC"],
                         result={"supporting": [{"memory_id": "m1"}]}, path=path)
    rows = R.read_receipts(path=path)
    summ = R.summarize(rows)
    assert summ["by_consumer"] == {"advisory_desk_operator": 1, "hermes_research_prompt": 1}
    assert summ["memory_ids_read_by_two_or_more_consumers"] == 1
    assert summ["examples"]["m1"] == ["advisory_desk_operator", "hermes_research_prompt"]


def test_receipt_carries_no_behavior_fields(tmp_path):
    from scripts.lib import memory_consumption_receipt as R
    from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS
    rec = R.build_receipt(consumer="test", purpose="p", symbols=["X"], supporting=[{"memory_id": "m"}])
    assert not (set(rec) & set(BEHAVIOR_FIELDS))
    assert rec["memory_behavior_influence"] == "0"


# ── Critique writeback is hermetic under env override ──────────────────────

def test_critique_writeback_paths_honor_env_overrides(tmp_path, monkeypatch):
    from scripts.lib import critique_question_writeback as W
    monkeypatch.setenv("TRADEAI_WAKE_INSTRUMENT_RECORDS_PATH", str(tmp_path / "recs.jsonl"))
    monkeypatch.setenv("TRADEAI_WAKE_CRITIQUE_ARTIFACT_PATH", str(tmp_path / "crit.jsonl"))
    assert W._persistent_records_path() == tmp_path / "recs.jsonl"
    assert W._artifact_path() == tmp_path / "crit.jsonl"


# ── Persistent wake: judgment reaches the commitment; beliefs outrank salience ─

def _sel():
    return {"source": "unconsumed_research", "source_id": "ro-1", "symbol": "NOC"}


def test_default_decide_mints_from_directional_judgment_with_real_falsifier():
    from scripts.lib.persistent_agent_wake import default_decide
    ctx = {"selection": _sel(), "memory_facts": [{"fact_id": "f1", "content": "x"}],
           "judgment": {"stance": "BEARISH", "claim": "NOC margin guidance is cut within 14d",
                        "falsifier": "NOC reaffirms or raises FY margin guidance at the next print",
                        "judgment_id": "j-1", "evidence_source_ids": ["f1"]}}
    d = default_decide(ctx)
    c = d["commitment"]
    assert c["commitment_kind"] == "L3_JUDGMENT" and c["stance"] == "BEARISH"
    assert c["falsifier"].startswith("NOC reaffirms") and c["judgment_id"] == "j-1"
    assert d["primary_source_id"] == "ro-1" and d["reason"] == "organic_from_judgment"


def test_default_decide_ignores_insufficient_or_vacuous_judgment():
    from scripts.lib.persistent_agent_wake import default_decide
    base = {"selection": _sel(), "memory_facts": [{"fact_id": "f1", "content": "x"}]}
    insufficient = default_decide({**base, "judgment": {"stance": "INSUFFICIENT", "claim": "c", "falsifier": "real observable"}})
    assert insufficient["commitment"]["commitment_kind"] == "MEMORY_SALIENCE"
    vacuous = default_decide({**base, "judgment": {"stance": "BULLISH", "claim": "c", "falsifier": ""}})
    assert vacuous["commitment"]["commitment_kind"] == "MEMORY_SALIENCE"


def test_belief_review_now_reachable_with_memory_facts_present():
    from scripts.lib.persistent_agent_wake import default_decide
    ctx = {"selection": _sel(), "memory_facts": [{"fact_id": "f1", "content": "x"}],
           "instrument_belief": {"belief_key": "HELD:NOC|TRIM|30d", "revision": 2,
                                 "success_rate": 0.2, "sample_size": 6,
                                 "belief_proposal_id": "bp-1"}}
    d = default_decide(ctx)
    assert d["commitment"]["commitment_kind"] == "BELIEF_REVIEW"
    assert d["commitment"]["belief_proposal_id"] == "bp-1"


def test_operator_turn_outranks_judgment_but_consumed_turn_does_not():
    from scripts.lib.persistent_agent_wake import default_decide
    judgment = {"stance": "BULLISH", "claim": "c", "falsifier": "a concrete print"}
    live = default_decide({"selection": _sel(), "judgment": judgment,
                           "operator_turns": [{"turn_id": "115", "text": "what about NOC?"}]})
    assert live["commitment"]["commitment_kind"] == "OPERATOR_QUESTION"
    replayed = default_decide({"selection": _sel(), "judgment": judgment,
                               "operator_turns": [{"turn_id": "115", "text": "what about NOC?",
                                                   "already_consumed": True}]})
    assert replayed["commitment"]["commitment_kind"] == "L3_JUDGMENT"


def test_normalize_selection_carries_symbol():
    from scripts.lib.persistent_agent_wake import _normalize_selection
    out = _normalize_selection({"source": "unconsumed_research", "source_id": "ro-1", "symbol": "noc"})
    assert out["symbol"] == "NOC"
    assert "symbol" not in _normalize_selection({"source": "s", "source_id": "x"})


def test_salient_belief_prefers_weak_settled_over_latest():
    from scripts.lib.cio_instrument_record import salient_belief
    rec = {"beliefs": [
        {"belief_key": "k1", "as_of": "2026-09-20T00:00:00Z", "revision": 1, "success_rate": 0.2, "sample_size": 6},
        {"belief_key": "k2", "as_of": "2026-09-25T00:00:00Z", "revision": 1, "success_rate": 0.9, "sample_size": 8},
    ]}
    assert salient_belief(rec)["belief_key"] == "k1"
    rec2 = {"beliefs": [{"belief_key": "k3", "as_of": "2026-09-25T00:00:00Z", "revision": 1,
                         "success_rate": 0.3, "sample_size": 2}]}
    assert salient_belief(rec2)["belief_key"] == "k3"   # under-sampled: latest wins
    assert salient_belief({}) is None
