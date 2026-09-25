#!/usr/bin/env python3
"""Tranche 2, Slice 4 (D2 G8): the cross-agent memory-agreement measure.

Hermetic: three tmp JSONL stores, an injected symbol→guid map, a fixed clock.

    .venv/bin/python -m pytest tests/test_cross_agent_memory_agreement_20260925.py -q
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

from scripts.lib import cross_agent_memory_agreement as cam  # noqa: E402

NOW = datetime(2026, 9, 25, 6, 20, tzinfo=timezone.utc)
T = (NOW - timedelta(hours=3)).isoformat()
OLD = (NOW - timedelta(hours=40)).isoformat()
G_NOC = "0bcf1ac9-5d53-513c-824b-44bf09f221d4"
G_V = "d1871bc6-ea2a-57c6-8d9c-8fd6895af9ad"
GUIDS = {"NOC": G_NOC, "V": G_V}


def _w(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _hermes(sg, ids, ts=T):
    return {"event": "HERMES_RESEARCH_REQUESTED", "subject_guid": sg, "created_ts": ts,
            "prompt_context": {"as_of": ts, "memory_context": {
                "supporting": [{"memory_id": i} for i in ids[:2]],
                "counter": [{"memory_id": i} for i in ids[2:]]}}}


def _stores(tmp_path, *, wakes, hermes, retrievals):
    w = tmp_path / "wakes.jsonl"; h = tmp_path / "hermes.jsonl"; r = tmp_path / "retrievals.jsonl"
    _w(w, wakes); _w(h, hermes); _w(r, retrievals)
    return w, h, r


def test_three_way_shared_ids_are_found_and_the_measure_replay_is_excluded(tmp_path):
    w, h, r = _stores(
        tmp_path,
        wakes=[{"agent_id": "cio", "subject_guid": G_NOC, "produced_at": T,
                "memory_fact_ids": ["mem_a", "mem_b", "mem_c", "mem_d"]}],
        hermes=[_hermes(G_NOC, ["mem_a", "mem_b", "mem_x"])],
        retrievals=[
            {"at": T, "query": cam.ADVISORY_QUERY, "symbols": ["NOC", "V"], "memory_ids": ["mem_a", "mem_z"]},
            {"at": T, "query": {"plan_id": None, "symbols": []}, "symbols": ["NOC"], "memory_ids": ["mem_b", "mem_c"]},  # the measure's own replay
            {"at": T, "query": "NOC investment thesis research context", "symbols": ["NOC"], "memory_ids": ["mem_c"]},
        ],
    )
    rep = cam.measure(wakes_path=w, hermes_requests_path=h, retrievals_path=r,
                      guid_for_symbol=GUIDS.get, now=NOW)
    assert rep["schema"] == cam.SCHEMA and rep["memory_behavior_influence"] == 0
    assert rep["agents_present"] == ["advisory", "cio", "hermes"]
    assert rep["verdict"] == "THREE_WAY_SHARED" and rep["g8_closure"] is True
    noc = next(s for s in rep["subjects"] if s["subject_guid"] == G_NOC)
    assert noc["agents"] == ["advisory", "cio", "hermes"]
    assert noc["three_way_shared"] == 1 and noc["shared_sample"] == ["mem_a"]
    assert noc["pairwise_shared"] == {"advisory&cio": 1, "advisory&hermes": 1, "cio&hermes": 2}
    assert rep["stats"]["excluded_measure_replay"] == 1 and rep["stats"]["other_queries"] == 1
    v = next(s for s in rep["subjects"] if s["subject_guid"] == G_V)
    assert v["agents"] == ["advisory"]  # only the desk read V


def test_pairwise_only_and_no_overlap_are_reported_honestly(tmp_path):
    w, h, r = _stores(
        tmp_path,
        wakes=[{"agent_id": "cio", "subject_guid": G_NOC, "produced_at": T, "memory_fact_ids": ["mem_a", "mem_b"]}],
        hermes=[_hermes(G_NOC, ["mem_b", "mem_q"]), _hermes(G_V, ["mem_v1"])],
        retrievals=[],
    )
    rep = cam.measure(wakes_path=w, hermes_requests_path=h, retrievals_path=r, guid_for_symbol=GUIDS.get, now=NOW)
    assert rep["verdict"] == "PAIRWISE_SHARED_ONLY" and rep["g8_closure"] is False
    assert rep["subjects_read_by_2plus_agents"] == 1 and rep["subjects_with_three_way_shared_ids"] == 0
    # disjoint ids -> multi-agent, nothing shared
    w2, h2, r2 = _stores(
        tmp_path / "b",
        wakes=[{"agent_id": "cio", "subject_guid": G_NOC, "produced_at": T, "memory_fact_ids": ["mem_a"]}],
        hermes=[_hermes(G_NOC, ["mem_q"])], retrievals=[],
    )
    rep2 = cam.measure(wakes_path=w2, hermes_requests_path=h2, retrievals_path=r2, guid_for_symbol=GUIDS.get, now=NOW)
    assert rep2["verdict"] == "MULTI_AGENT_NO_SHARED_IDS"


def test_window_and_missing_sources(tmp_path):
    w, h, r = _stores(
        tmp_path,
        wakes=[{"agent_id": "cio", "subject_guid": G_NOC, "produced_at": OLD, "memory_fact_ids": ["mem_a"]}],
        hermes=[_hermes(G_NOC, ["mem_a"], ts=OLD)], retrievals=[],
    )
    rep = cam.measure(wakes_path=w, hermes_requests_path=h, retrievals_path=r, guid_for_symbol=GUIDS.get, now=NOW)
    assert rep["subjects_total"] == 0 and rep["verdict"] == "NO_SUBJECT_READ_BY_MORE_THAN_ONE_AGENT"
    rep2 = cam.measure(wakes_path=tmp_path / "nope1", hermes_requests_path=tmp_path / "nope2",
                       retrievals_path=tmp_path / "nope3", guid_for_symbol=GUIDS.get, now=NOW)
    assert rep2["verdict"] == "UNAVAILABLE" and rep2["sources_present"] == {
        "cio_wakes": False, "hermes_requests": False, "advisory_retrievals": False}


def test_unresolved_advisory_symbols_are_counted_not_invented(tmp_path):
    w, h, r = _stores(tmp_path, wakes=[], hermes=[],
                      retrievals=[{"at": T, "query": cam.ADVISORY_QUERY, "symbols": ["ZZZZ"], "memory_ids": ["mem_a"]}])
    rep = cam.measure(wakes_path=w, hermes_requests_path=h, retrievals_path=r, guid_for_symbol=GUIDS.get, now=NOW)
    assert rep["subjects_total"] == 0 and rep["stats"]["advisory_symbol_unresolved"] == 1


def test_shadow_measure_report_carries_the_section(tmp_path, monkeypatch):
    """The daily measure gains the section fail-soft; influence stays off."""
    from scripts.lib.agent_memory_shadow_measure import run_measure

    monkeypatch.setenv("MEMORY_PROVIDER", "null")
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("TRADEAI_PERSISTENT_WAKE_STATE_ROOT", str(tmp_path / "wake"))
    _w(tmp_path / "wake" / "wakes.jsonl",
       [{"agent_id": "cio", "subject_guid": G_NOC, "produced_at": datetime.now(timezone.utc).isoformat(),
         "memory_fact_ids": ["mem_a"]}])
    _w(tmp_path / "data/cio/hermes_research_requests.jsonl", [_hermes(G_NOC, ["mem_a"], ts=datetime.now(timezone.utc).isoformat())])
    _w(tmp_path / "data/cio/aif_memory_retrievals.jsonl", [])
    _w(tmp_path / "data/cio/cio_wake_traces.jsonl", [])
    _w(tmp_path / "data/cio/agent_run_traces.jsonl", [])
    rep = run_measure(wake_path=tmp_path / "data/cio/cio_wake_traces.jsonl",
                      trace_path=tmp_path / "data/cio/agent_run_traces.jsonl",
                      out_path=tmp_path / "out.json", root=tmp_path)
    sec = rep["cross_agent_memory_agreement"]
    assert sec["schema"] == cam.SCHEMA
    assert sec["verdict"] == "PAIRWISE_SHARED_ONLY"
    assert rep["metrics"]["behavior_influence_active"] is False
