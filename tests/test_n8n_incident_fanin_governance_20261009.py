"""Incident fan-in sources `n8n_activation_grants` (P16) and `n8n_workflow_drift` (P18), 2026-10-09.

Receipts written by scripts/check_n8n_activation_grants.py / scripts/check_n8n_workflow_drift.py on the
host-side cron. An UNGRANTED_ACTIVATION of a currently active workflow opens a P1; drift opens a P2; a
clean receipt opens nothing; a missing or stale receipt is a P2 only once the lane is scheduled (registry
row ACTIVE), otherwise a note. Fixture files under tmp_path and a stubbed registry row; the live state
root, the live registry and the n8n DB are never read.

COVERS = ["scripts/n8n_incident_fanin.py", "scripts/check_n8n_activation_grants.py", "scripts/check_n8n_workflow_drift.py"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_n8n_activation_grants as A  # noqa: E402
from scripts import check_n8n_workflow_drift as D  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
P16_REL = "data/runtime/n8n_activation_grants_last.json"
P18_REL = "data/runtime/n8n_workflow_drift_last.json"


def _act(wid, status, *, active=True, at="2026-10-09T12:59:17+00:00"):
    return {"workflow_id": wid, "name": f"wf-{wid}", "version_id": "v1", "currently_active": active,
            "activated_at": at, "last_activated_at": at, "imported_at": None, "sources": ["published_version"],
            "status": status, "grants": []}


def _wf(wid, status="OK", *, diffs=(), unsub=False):
    return {"id": wid, "name": f"wf-{wid}", "active": True, "placeholder_unsubstituted": unsub,
            "status": status, "git_file": None, "diffs": list(diffs)}


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _p16(root, rows, *, age_h=0.2):
    rec = A.build_receipt([dict(r) for r in rows], since=NOW - timedelta(days=7), source="fixture",
                          guard_log=Path("audit.jsonl"), tiers=A.DEFAULT_TIERS, now=NOW - timedelta(hours=age_h))
    _write(root, P16_REL, rec)
    return rec


def _p18(root, rows, *, age_h=0.2):
    rec = D.build_receipt(rows, source="fixture", now=NOW - timedelta(hours=age_h))
    _write(root, P18_REL, rec)
    return rec


@pytest.fixture
def wire(monkeypatch):
    rows = {
        "n8n-activation-grants": {"lane_id": "n8n-activation-grants", "state": "ACTIVE",
                                  "expected_cadence_hours": 0.5, "scheduler": {"kind": "cron", "expression": "*/30"}},
        "n8n-workflow-drift-check": {"lane_id": "n8n-workflow-drift-check", "state": "ACTIVE",
                                     "expected_cadence_hours": 1.0, "scheduler": {"kind": "cron", "expression": "7 *"}},
    }
    monkeypatch.setattr(fanin, "_governance_lane", lambda lane_id: rows.get(lane_id))
    monkeypatch.delenv("TRADEAI_FANIN_GOVERNANCE", raising=False)
    return rows


def _gov(found):
    return [f for f in found if f["source"] in {"n8n_activation_grants", "n8n_workflow_drift"}]


def _only(found, source):
    return [f for f in found if f["source"] == source]


def test_ungranted_activation_of_a_live_workflow_is_a_p1_incident(wire, tmp_path):
    _p16(tmp_path, [_act("283ceeb030de5e66", A.UNGRANTED_ACTIVATION), _act("e18d7849b4142927", A.GRANTED)])
    (f,) = _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants")
    assert (f["source"], f["item"], f["severity"]) == ("n8n_activation_grants", "283ceeb030de5e66:UNGRANTED_ACTIVATION:P1", "P1")
    assert f["artifact_rel"] == P16_REL and f["store"] == "data/runtime"
    assert f["detected_at"] == "2026-10-09T12:59:17+00:00"     # the activation time: stable payload across runs
    # dedupe: one incident per source|item|UTC day, the same key on every run of the day
    day = NOW.strftime("%Y-%m-%d")
    again = _only(fanin._governance_findings(tmp_path, NOW + timedelta(minutes=30)), "n8n_activation_grants")
    assert fanin.idem_key(again[0], day) == fanin.idem_key(f, day)
    ev1 = fanin.build_event(f, day=day, now=NOW, sha="x")
    ev2 = fanin.build_event(again[0], day=day, now=NOW + timedelta(minutes=30), sha="x")
    assert ev1 == ev2
    assert "sev=P1;src=n8n_activation_grants" in ev1["subject_key"]


def test_ungranted_but_already_off_and_weak_attribution_are_p3(wire, tmp_path):
    _p16(tmp_path, [_act("s57KBllvqf6Jb5xF", A.UNGRANTED_ACTIVATION, active=False),
                    _act("078e8fcbea0c5020", A.NAME_ONLY_GRANT), _act("aaaa", A.NAMED_IN_OTHER_TIER)])
    sev = {f["item"]: f["severity"] for f in _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants")}
    assert sev == {"s57KBllvqf6Jb5xF:UNGRANTED_ACTIVATION:P3": "P3", "078e8fcbea0c5020:NAME_ONLY_GRANT:P3": "P3",
                   "aaaa:NAMED_IN_OTHER_TIER:P3": "P3"}


def test_clean_receipts_open_nothing(wire, tmp_path):
    _p16(tmp_path, [_act("e18d7849b4142927", A.GRANTED)])
    _p18(tmp_path, [_wf("e18d7849b4142927")])
    assert fanin._governance_findings(tmp_path, NOW) == []
    assert fanin.NOTES["n8n_activation_grants_source"].startswith("ok:0:verdict=CLEAN")
    assert fanin.NOTES["n8n_workflow_drift_source"].startswith("ok:0:verdict=CLEAN")


def test_drift_missing_in_git_and_placeholder_are_p2(wire, tmp_path):
    _p18(tmp_path, [_wf("w1", "DRIFT", diffs=["node:Schedule:parameters"]), _wf("w2", "MISSING_IN_GIT"),
                    _wf("w3", unsub=True), _wf("w4")])
    found = _only(fanin._governance_findings(tmp_path, NOW), "n8n_workflow_drift")
    assert {(f["item"], f["severity"]) for f in found} == {
        ("w1:DRIFT:P2", "P2"), ("w2:MISSING_IN_GIT:P2", "P2"), ("w3:placeholder_unsubstituted:P2", "P2")}
    day0 = NOW.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    assert all(f["detected_at"] == day0 and f["artifact_rel"] == P18_REL for f in found)
    assert "node:Schedule:parameters" in [f for f in found if f["item"] == "w1:DRIFT:P2"][0]["detail"]


def test_fanin_and_checker_agree_on_items_and_severity(wire, tmp_path):
    rec16 = _p16(tmp_path, [_act("a", A.UNGRANTED_ACTIVATION), _act("b", A.UNGRANTED_ACTIVATION, active=False),
                            _act("c", A.NAME_ONLY_GRANT), _act("d", A.GRANTED)])
    rec18 = _p18(tmp_path, [_wf("w1", "DRIFT", diffs=["settings"]), _wf("w2", "MISSING_IN_GIT"), _wf("w3", unsub=True)])
    mine = {(f["source"], f["item"], f["severity"]) for f in fanin._governance_findings(tmp_path, NOW)}
    theirs = {(f["source"], f["item"], f["severity"]) for f in rec16["fanin_findings"] + rec18["fanin_findings"]}
    assert mine == theirs and rec16["fanin_wired"] is True and rec18["fanin_wired"] is True


def test_stale_receipt_of_a_scheduled_lane_is_a_p2_and_its_findings_still_count(wire, tmp_path):
    _p16(tmp_path, [_act("a", A.UNGRANTED_ACTIVATION)], age_h=2.0)       # > 3 x 0.5h
    _p18(tmp_path, [_wf("w1")], age_h=2.5)                               # < 3 x 1h: fresh
    found = {(f["source"], f["item"]): f["severity"] for f in fanin._governance_findings(tmp_path, NOW)}
    assert found == {("n8n_activation_grants", "receipt:stale"): "P2", ("n8n_activation_grants", "a:UNGRANTED_ACTIVATION:P1"): "P1"}
    assert fanin.NOTES["n8n_activation_grants_source"].endswith(":stale")


def test_missing_receipt_is_p2_when_scheduled_and_a_note_when_not(wire, tmp_path):
    found = fanin._governance_findings(tmp_path, NOW)
    assert {(f["source"], f["item"], f["severity"]) for f in found} == {
        ("n8n_activation_grants", "receipt:missing", "P2"), ("n8n_workflow_drift", "receipt:missing", "P2")}
    wire["n8n-activation-grants"].update(state="NEVER_SCHEDULED", scheduler={"kind": "none"})
    wire["n8n-workflow-drift-check"].update(state="NEVER_SCHEDULED", scheduler={"kind": "none"})
    assert fanin._governance_findings(tmp_path, NOW) == []
    assert fanin.NOTES["n8n_activation_grants_source"] == "ok:no_receipt:scheduled=no"


def test_old_hand_run_receipt_of_an_unscheduled_lane_is_not_read(wire, tmp_path):
    wire["n8n-activation-grants"].update(state="NEVER_SCHEDULED", scheduler={"kind": "none"})
    _p16(tmp_path, [_act("a", A.UNGRANTED_ACTIVATION)], age_h=30)
    assert _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants") == []
    assert fanin.NOTES["n8n_activation_grants_source"].startswith("ok:stale_unscheduled")
    _p16(tmp_path, [_act("a", A.UNGRANTED_ACTIVATION)], age_h=0.1)       # a fresh hand run is read
    assert [f["severity"] for f in _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants")] == ["P1"]


def test_env_opt_out_and_broken_registry_are_notes_not_crashes(wire, monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_FANIN_GOVERNANCE", "0")
    assert fanin._governance_findings(tmp_path, NOW, prev={}) == []
    assert fanin.NOTES["n8n_workflow_drift_source"].startswith("unavailable:RuntimeError:disabled_by_env")
    # the opt-out never alarms, even on consecutive runs
    assert fanin._governance_findings(tmp_path, NOW, prev={"source_notes": dict(fanin.NOTES)}) == []
    monkeypatch.delenv("TRADEAI_FANIN_GOVERNANCE")

    def boom(lane_id):
        raise OSError("registry unreadable")

    monkeypatch.setattr(fanin, "_governance_lane", boom)
    # first unavailable run, schedule unknown: a note only
    assert fanin._governance_findings(tmp_path, NOW, prev={}) == []
    assert fanin.NOTES["n8n_activation_grants_source"].startswith("unavailable:OSError")
    # second consecutive unavailable run: P2 governance:source_unavailable per source
    found = fanin._governance_findings(tmp_path, NOW, prev={"source_notes": dict(fanin.NOTES)})
    assert {(f["source"], f["item"], f["severity"]) for f in found} == {
        ("n8n_activation_grants", "governance:source_unavailable", "P2"),
        ("n8n_workflow_drift", "governance:source_unavailable", "P2")}


def test_broken_receipt_of_a_scheduled_lane_alarms_at_once(wire, tmp_path):
    _p18(tmp_path, [_wf("w1")])
    _write(tmp_path, P16_REL, {"as_of": NOW.isoformat(), "activations": ["not-a-row"]})   # malformed rows
    found = fanin._governance_findings(tmp_path, NOW, prev={})
    (f,) = _only(found, "n8n_activation_grants")
    assert (f["item"], f["severity"]) == ("governance:source_unavailable", "P2")
    assert "scheduled=yes" in f["detail"] and fanin.NOTES["n8n_activation_grants_source"].startswith("unavailable:")
    assert _only(found, "n8n_workflow_drift") == []


def test_regularised_window_is_p3_with_its_window_and_escalation_is_a_new_key(wire, tmp_path):
    reg = dict(_act("r1", A.UNGRANTED_ACTIVATION_REGULARISED),
               ungranted_window={"start": "2026-10-04T10:00:00+00:00", "end": "2026-10-09T16:00:00+00:00"})
    _p16(tmp_path, [reg])
    (f,) = _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants")
    assert (f["item"], f["severity"]) == ("r1:UNGRANTED_ACTIVATION_REGULARISED:P3", "P3")
    assert "ungranted 2026-10-04T10:00:00+00:00..2026-10-09T16:00:00+00:00" in f["detail"]
    # same workflow, same UTC day: off (P3) then live again (P1) -> two different idempotency keys
    day = NOW.strftime("%Y-%m-%d")
    _p16(tmp_path, [_act("x", A.UNGRANTED_ACTIVATION, active=False)])
    (p3,) = _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants")
    _p16(tmp_path, [_act("x", A.UNGRANTED_ACTIVATION, active=True)])
    (p1,) = _only(fanin._governance_findings(tmp_path, NOW), "n8n_activation_grants")
    assert (p3["severity"], p1["severity"]) == ("P3", "P1")
    assert fanin.idem_key(p3, day) != fanin.idem_key(p1, day)


def test_collect_includes_the_governance_sources(wire, monkeypatch, tmp_path):
    for env in ("TRADEAI_FANIN_LANE_REGISTRY", "TRADEAI_FANIN_RUNS", "TRADEAI_FANIN_RELAY"):
        monkeypatch.setenv(env, "0")
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    _p16(tmp_path, [_act("a", A.UNGRANTED_ACTIVATION)])
    _p18(tmp_path, [_wf("w1", "DRIFT", diffs=["connections"])])
    got = {(f["source"], f["severity"]) for f in _gov(fanin.collect(tmp_path, NOW, prev={}))}
    assert got == {("n8n_activation_grants", "P1"), ("n8n_workflow_drift", "P2")}
