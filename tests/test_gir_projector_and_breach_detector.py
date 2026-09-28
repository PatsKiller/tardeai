"""GIR projector v1 and breach detector (Wave 1 tranche 2) — hermetic, tmp roots only."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import gir_projector as gp  # noqa: E402
import supervisor_breach_detector as bd  # noqa: E402

NOW = dt.datetime(2026, 9, 27, 20, 0, tzinfo=dt.timezone.utc)


def _state(tmp_path: Path) -> Path:
    d = tmp_path / "data"; (d / "runtime").mkdir(parents=True); (d / "cio").mkdir()
    (d / "runtime" / "identity_registry.json").write_text(json.dumps({"entities": {
        "g1": {"security_guid": "sec-v", "issuer_guid": "iss-v", "ticker_alias": "V", "aliases": ["V"], "identity_status": "CONFIRMED", "active": True, "first_seen": "2026-09-01", "last_seen": "2026-09-27"},
        "g2": {"security_guid": None, "ticker_alias": "ZZZ", "identity_status": "UNRESOLVED_WITH_REASON"}}}))
    (d / "cio" / "cio_theses_projection.json").write_text(json.dumps({"current": {
        "symbol_v": {"thesis_id": "symbol_v", "version": 24, "parent_version": 23, "status": "active", "stance": "watch", "summary": "s", "updated_ts": (NOW - dt.timedelta(days=2)).isoformat(), "source_lane": "hermes", "evidence_refs": ["e1"]},
        "symbol_qqq": {"thesis_id": "symbol_qqq", "version": 1, "status": "active", "updated_ts": (NOW - dt.timedelta(days=40)).isoformat()},
        "desk": {"thesis_id": "desk", "version": 3}}}))
    (d / "cio" / "cio_instrument_records.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"subject_key": "HELD:V", "beliefs": [{"belief_key": "k", "recommendation": "hold", "sample_size": 7, "success_rate": 0.7, "revision": 1, "as_of": NOW.isoformat(), "outcome_ids": ["o1"]}]},
        {"subject_key": "HELD:V", "beliefs": [{"belief_key": "k", "recommendation": "hold", "sample_size": 8, "success_rate": 0.75, "revision": 2, "as_of": NOW.isoformat(), "outcome_ids": ["o1", "o2"]}]},
        {"subject_key": "SECTOR:Tech", "beliefs": []}]) + "\n")
    (d / "cio" / "holdings_snapshot_latest.json").write_text(json.dumps({"holdings": [{"symbol": "V", "account": "ira", "shares": 10, "updated_at": NOW.isoformat()}, {"symbol": "NOPE", "account": "ira"}]}))
    (d / "cio" / "research_contradiction_candidates.jsonl").write_text("\n".join([
        json.dumps({"schema": "ResearchContradictionCandidate@v1", "candidate_id": "contra_1", "left_symbol": "V", "right_symbol": "V"}),
        json.dumps({"schema": "Other@v1", "candidate_id": "x"}),
        json.dumps({"schema": "ResearchContradictionCandidate@v1", "candidate_id": "contra_2", "left_symbol": "ZZZ", "right_symbol": "V"})]) + "\n")
    return tmp_path


def test_projector_builds_entities_envelopes_edges_and_rekeys(tmp_path):
    pj = gp.build(_state(tmp_path), now=NOW, env={"TRADEAI_RELEASE_SHA": "sha1"})
    assert "SEC:sec-v" in pj.entities and "ISS:iss-v" in pj.entities and pj.entities["SEC:sec-v"]["class"] == "COMPANY"
    assert "THESIS:symbol_v@v24" in pj.entities and "THESIS:desk@v3" not in pj.entities
    env_v = pj.envelopes["THESIS:symbol_v@v24"]
    assert env_v["freshness"]["state"] == "CURRENT" and pj.envelopes["THESIS:symbol_qqq@v1"]["freshness"]["state"] == "STALE"
    assert env_v["history"]["parent_version"] == 23 and env_v["ownership"]["writer"].endswith("accept_research_result")
    rels = {(e["from_guid"], e["relation"], e["to_guid"]) for e in pj.edges.values()}
    assert ("SEC:sec-v", "HAS_THESIS", "THESIS:symbol_v@v24") in rels
    assert ("THESIS:symbol_v@v24", "SUPERSEDES", "THESIS:symbol_v@v23") in rels
    assert ("ISS:iss-v", "ISSUES", "SEC:sec-v") in rels and ("ACCOUNT:ira", "HOLDS", "SEC:sec-v") in rels
    assert ("SEC:sec-v", "BELIEVES", "BELIEF:HELD:V:k") in rels and ("CONTRA:contra_1", "CONTRADICTS", "SEC:sec-v") in rels
    b = pj.envelopes["BELIEF:HELD:V:k"]
    assert b["history"]["revision"] == 2 and b["confidence"]["basis"] == "CALIBRATED" and b["dependencies"]["security_guid"] == "SEC:sec-v"
    assert pj.counts["theses_symbol_unresolved"] == 1 and pj.counts["holdings_symbol_unresolved"] == 1
    assert pj.counts["instrument_records_rekeyed_to_sec"] == 1 and pj.counts["contradictions_projected"] == 2
    # idempotent: same inputs → same keys
    pj2 = gp.build(tmp_path, now=NOW, env={"TRADEAI_RELEASE_SHA": "sha1"})
    assert set(pj2.edges) == set(pj.edges) and set(pj2.envelopes) == set(pj.envelopes)
    assert all(k not in json.dumps(list(pj.envelopes.values())) for k in ("size_usd", "shares\":", "order\":"))


def test_projector_contradiction_cap(tmp_path):
    pj = gp.build(_state(tmp_path), now=NOW, env={}, contra_max_lines=1)
    assert pj.counts.get("contradictions_capped_at") == 1


def test_breach_detector_kinds():
    lanes = [
        {"lane_id": "a-ungoverned", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "file_mtime", "path": "x"}},
        {"lane_id": "b-silent", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "none"}},
        {"lane_id": "c-no-output", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "file_mtime", "path": "y"}},
        {"lane_id": "d-ok", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "file_mtime", "path": "z"}},
        {"lane_id": "e-mem", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "none"}},
        {"lane_id": "f-retired", "state": "RETIRED"},
    ]
    sla = {l: {"lane_id": l, "max_silence_s": 600, "memory_context_required": "fail-closed" if l == "e-mem" else "none"} for l in ("b-silent", "c-no-output", "d-ok", "e-mem")}
    hb = {"b-silent": {"lane_id": "b-silent", "last_beat": (NOW - dt.timedelta(hours=2)).isoformat(), "boot_id": "bb"},
          "d-ok": {"lane_id": "d-ok", "last_beat": (NOW - dt.timedelta(minutes=1)).isoformat()},
          "e-mem": {"lane_id": "e-mem", "last_beat": (NOW - dt.timedelta(minutes=1)).isoformat(), "memory_context_ok": False, "degraded_reasons": ["FACTS_UNAVAILABLE"]}}
    def observe(sig):
        p = sig.get("path")
        if p == "y":
            return {"last_output_at": (NOW - dt.timedelta(hours=5)).isoformat(), "readable": True}
        if p == "z":
            return {"last_output_at": (NOW - dt.timedelta(minutes=30)).isoformat(), "readable": True}
        return {"last_output_at": None, "readable": False}
    rows = bd.detect(lanes=lanes, sla_by_lane=sla, heartbeats=hb, observe=observe, now=NOW)
    kinds = {(r["lane_id"], r["kind"]) for r in rows}
    assert kinds == {("a-ungoverned", "UNGOVERNED"), ("b-silent", "SILENT"), ("c-no-output", "NO_OUTPUT"), ("e-mem", "MEMORY_UNREACHABLE")}
    assert all(r["schema"] == "Breach@v1" and r["state"] == "OPEN" and r["kind"] in bd.KINDS for r in rows)
    assert bd.breach_id("x", "SILENT", "2026-09-27") == bd.breach_id("x", "SILENT", "2026-09-27") != bd.breach_id("x", "SILENT", "2026-09-28")


def test_projector_ticker_graph_and_incremental_state(tmp_path):
    root = _state(tmp_path)
    (root / "data" / "cio" / "ticker_research_graph.jsonl").write_text("\n".join([
        json.dumps({"artifact_id": "a1", "symbol": "V", "created_at": NOW.isoformat()}),
        json.dumps({"artifact_id": "a2", "symbol": "NOPE"}),
        json.dumps({"no": "id"})]) + "\n")
    pj = gp.build(root, now=NOW, env={})
    assert "EVID:tg:a1" in pj.entities and pj.counts["ticker_graph_artifacts"] == 2 and pj.counts["ticker_graph_symbol_unresolved"] == 1
    assert ("SEC:sec-v", "HAS_ARTIFACT", "EVID:tg:a1") in {(e["from_guid"], e["relation"], e["to_guid"]) for e in pj.edges.values()}
    state = tmp_path / "state.json"
    needed, cur, prev = gp.incremental_needed(root, state, {})
    assert needed and prev == {} and cur["cio_theses_projection"]["size"] > 0
    state.write_text(json.dumps({"sources": cur}))
    assert gp.incremental_needed(root, state, {})[0] is False
    (root / "data" / "cio" / "holdings_snapshot_latest.json").write_text(json.dumps({"holdings": []}))
    assert gp.incremental_needed(root, state, {})[0] is True


def test_breach_rows_serialize_when_observe_returns_datetimes(tmp_path):
    lanes = [{"lane_id": "x", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "file_mtime", "path": "p"}}]
    sla = {"x": {"lane_id": "x", "max_silence_s": 600}}
    rows = bd.detect(lanes=lanes, sla_by_lane=sla, heartbeats={}, observe=lambda sig: {"last_output_at": NOW - dt.timedelta(hours=9), "readable": True}, now=NOW)
    assert rows[0]["kind"] == "NO_OUTPUT"
    json.dumps(rows[0])  # must not raise: the 2026-09-27 first live run crashed here
    assert rows[0]["evidence"]["last_output_at"].startswith("2026-09-27T11:00")
