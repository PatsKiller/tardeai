"""Wave 5 tranche 1 — conformance gate, maturity re-measurement, self-heal shadow, embedding step 7."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import conformance_gate as cg  # noqa: E402
import embedding_index as ei  # noqa: E402
import maturity_remeasure as mr  # noqa: E402

NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


def _report(states, as_of=None):
    return {"as_of": (as_of or NOW).isoformat(), "silos": [{"silo_id": f"s{i}", "state": s, "score": 0.5 if s == "NON_CONFORMANT" else 0.9} for i, s in enumerate(states)]
            + [{"silo_id": "UNASSIGNED", "state": "NON_CONFORMANT", "score": 0}]}


def test_conformance_gate_verdicts():
    ok = cg.evaluate(_report(["CONFORMANT", "CONFORMANT"]), now=NOW, max_age_h=36, mode="warn", override=None)
    assert ok["allow"] and ok["verdict"] == "PASS"
    warn = cg.evaluate(_report(["CONFORMANT", "DEGRADED"]), now=NOW, max_age_h=36, mode="warn", override=None)
    assert warn["allow"] and warn["verdict"] == "WARN" and warn["silos_degraded"] == ["s1:0.9"]
    below = cg.evaluate(_report(["NON_CONFORMANT"]), now=NOW, max_age_h=36, mode="warn", override=None)
    assert below["allow"] and below["verdict"] == "WARN" and below["silos_below"] == ["s0:0.5"]     # warn never blocks
    blk = cg.evaluate(_report(["NON_CONFORMANT"]), now=NOW, max_age_h=36, mode="block", override=None)
    assert not blk["allow"] and blk["verdict"] == "BLOCKED"
    ovr = cg.evaluate(_report(["NON_CONFORMANT"]), now=NOW, max_age_h=36, mode="block", override="operator: hotfix 2026-09-28")
    assert ovr["allow"] and ovr["verdict"] == "OVERRIDDEN"
    stale = cg.evaluate(_report(["CONFORMANT"], as_of=NOW - dt.timedelta(hours=48)), now=NOW, max_age_h=36, mode="block", override=None)
    assert not stale["allow"] and any(r.startswith("STALE_REPORT") for r in stale["reasons"])
    assert not cg.evaluate(None, now=NOW, max_age_h=36, mode="block", override=None)["allow"]
    assert cg.evaluate(None, now=NOW, max_age_h=36, mode="off", override=None)["verdict"] == "SKIPPED"


def test_gate_cli_writes_a_receipt_and_exit_code(tmp_path, monkeypatch):
    gov = tmp_path / "data" / "governance"; gov.mkdir(parents=True)
    rp = gov / "platform_conformance_latest.json"; rp.write_text(json.dumps(_report(["NON_CONFORMANT"])))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path)); monkeypatch.setenv("TRADEAI_GOVERNANCE_DIR", str(gov))
    monkeypatch.setenv("TRADEAI_CONFORMANCE_GATE", "warn")
    assert cg.main(["--sha", "abc", "--report", str(rp)]) == 0
    monkeypatch.setenv("TRADEAI_CONFORMANCE_GATE", "block")
    assert cg.main(["--sha", "abc", "--report", str(rp)]) == 1
    rows = [json.loads(l) for l in (gov / "conformance_gate_receipts.jsonl").read_text().splitlines()]
    assert [r["verdict"] for r in rows] == ["WARN", "BLOCKED"] and rows[-1]["sha"] == "abc"


def test_remeasure_scores_from_receipts_only(tmp_path):
    cio = tmp_path / "data" / "cio"; rt = tmp_path / "data" / "runtime"; gov = tmp_path / "data" / "governance"
    for d in (cio, rt, gov, cio / "agent_checkpoints", rt / "heartbeats"): d.mkdir(parents=True, exist_ok=True)
    empty = mr.collect(tmp_path, window_hours=168, now=NOW)
    rows = mr.score(empty)
    assert {r["domain"] for r in rows} == set(mr.DOMAINS) and all(r["score"] == 1 for r in rows)
    t = NOW.isoformat()
    (cio / "memory_contexts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"event": "OPENED", "as_of": t, "purpose": "DECIDE", "degraded": False, "actor": {"lane_id": f"l{i}"}} for i in range(3)] + [
        {"event": "COMMITTED", "committed_at": t, "influence": {"mir": True}}]))
    (cio / "retrieval_receipts.jsonl").write_text(json.dumps({"as_of": t, "decision": "HIT_FRESH"}) + "\n")
    (cio / "research_write_path_receipts.jsonl").write_text("".join(json.dumps({"ts": t, "lane_family": f, "mode": m}) + "\n" for f, m in (("a", "LIVE"), ("b", "SHADOW"), ("c", "SHADOW"))))
    (cio / "edge_fanout_work_items.jsonl").write_text(json.dumps({"produced_at": t, "kind": "reproject"}) + "\n")
    (cio / "agent_checkpoints" / "cio.jsonl").write_text(json.dumps({"written_at": t}) + "\n")
    (rt / "gir_projector_state.json").write_text(json.dumps({"as_of": t, "applied": {"entities": 10, "edges": 5}}))
    (rt / "supervisor_breaches.jsonl").write_text(json.dumps({"detected_at": t, "kind": "SILENT"}) + "\n")
    for i in range(11):
        (rt / "heartbeats" / f"l{i}.json").write_text(json.dumps({"lane_id": f"l{i}", "last_beat": t}))
    ev = mr.collect(tmp_path, window_hours=168, now=NOW)
    assert ev["lanes_with_contexts"] == 3 and ev["mir_commits"] == 1 and ev["write_path_lanes"] == 3 and ev["lanes_beating"] == 11
    by = {r["domain"]: r for r in mr.score(ev)}
    assert by["memory"]["score"] == 4 and "L5" in by["memory"]["missing"][0]
    assert by["cross_silo"]["score"] == 3 and by["knowledge_graph"]["score"] == 3 and by["agents"]["score"] == 3
    assert by["workers"]["score"] == 3 and by["continuous_research"]["score"] == 3 and by["decision_intelligence"]["score"] == 3
    assert by["model_routing"]["score"] == 1 and by["operational_reliability"]["score"] == 2


def test_remeasure_cli_writes_latest(tmp_path):
    (tmp_path / "data" / "cio").mkdir(parents=True)
    assert mr.main(["--root", str(tmp_path), "--write"]) == 0
    latest = json.loads((tmp_path / "data" / "governance" / "maturity_latest.json").read_text())
    assert latest["schema"] == "MaturityScore@v1" and latest["scorer"] == "maturity-remeasure" and latest["overall"] == 1.0 and latest["target"] == 4.7


def test_self_heal_shadow_records_without_restarting(tmp_path, monkeypatch):
    import supervisor_breach_detector as sbd
    rt = tmp_path / "data" / "runtime"; rt.mkdir(parents=True)
    calls = []
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or type("CP", (), {"returncode": 0, "stderr": ""})())
    lanes = [{"lane_id": "L", "state": "ACTIVE", "scheduler": {"kind": "systemd", "expression": "tradeai-l.timer"}},
             {"lane_id": "C", "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 * * * * x.py"}}]
    rows = [{"breach_id": "b1", "lane_id": "L", "kind": "SILENT"}, {"breach_id": "b2", "lane_id": "C", "kind": "NO_OUTPUT"}, {"breach_id": "b3", "lane_id": "L", "kind": "UNGOVERNED"}]
    out = sbd._self_heal_l1_l2(rows, lanes, {"C": {"alternate": "tradeai-c-alt.service"}}, NOW, rt, live=False)
    assert out == {"l1_candidates": 1, "l1_executed": 0, "l2_candidates": 1, "l2_executed": 0, "mode": "shadow"} and not calls
    recs = [json.loads(l) for l in (rt / "supervisor_recoveries.jsonl").read_text().splitlines()]
    assert recs[0]["action"] == "systemctl --user restart tradeai-l.service" and recs[0]["executed"] is False and recs[0]["would_execute"]
    assert recs[1]["level"] == 2 and "tradeai-c-alt.service" in recs[1]["action"]
    out2 = sbd._self_heal_l1_l2(rows, lanes, {"C": {"alternate": "tradeai-c-alt.service"}}, NOW, rt, live=True)
    assert out2["l1_executed"] == 1 and out2["l2_executed"] == 1 and len(calls) == 2
    # the 10-minute budget: two executed restarts already → the third would not execute
    out3 = sbd._self_heal_l1_l2(rows, lanes, {}, NOW, rt, live=True)
    out4 = sbd._self_heal_l1_l2(rows, lanes, {}, NOW, rt, live=True)
    assert out3["l1_executed"] == 1 and out4["l1_executed"] == 0


def test_embedding_step_is_not_installed_by_default(monkeypatch):
    assert ei.enabled({}) is False and ei.embed("x", {}) is None and ei.index("r", "x", env={})["pg"] == "not_installed" and ei.semantic("q", env={}) == []
    import intelligence_client as ic
    ctx = ic.open_context({"lane_id": "l"}, "RESEARCH", ["V"], loaders=ic.Loaders(resolve_subject=lambda s: {"security_guid": "g", "ticker_alias": s}),
                          env={"TRADEAI_MEMORY_CONTEXTS_PATH": "/dev/null", "TRADEAI_RETRIEVAL_RECEIPTS_PATH": "/dev/null"})
    ladder, decision, _ = ic.run_ladder(ctx, {"text": "q", "question_class": "thesis"}, ic.Loaders(resolve_subject=lambda s: {"security_guid": "g"}))
    step7 = [s for s in ladder if s["step"] == 7][0]
    assert step7["hit"] is False and step7["note"] == "not_installed"
