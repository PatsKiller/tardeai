"""One incident, one evidence line, dry by default, operator-only refused (2026-11-03)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

import incident_requeue as R  # noqa: E402
from lib import incidents as L  # noqa: E402


def _blocked(d, title="lane unhealthy: disk-hygiene missed", reason="needs_operator: cron_self_heal ran with rc=0 but returned acted=[]"):
    rec = L.open_incident(source={"kind": "watcher", "watcher": "lane_health"}, title=title,
                          fingerprint="fp-1", d=d)
    rec = rec[0] if isinstance(rec, tuple) else rec
    L.block(rec["id"], actor="incident_supervisor", blocked_reason=reason, handoff="operator decision required", d=d)
    return rec["id"]


def test_dry_run_does_not_write(tmp_path):
    d = tmp_path / "inc"
    iid = _blocked(d)
    before = (d / "events.jsonl").read_text()
    out = R.requeue(iid, evidence="disk-hygiene still misses: last_success 2026-11-02T00:01Z", d=d)
    assert out["ok"] and out["after"].startswith("open (dry run")
    assert (d / "events.jsonl").read_text() == before


def test_apply_reopens_exactly_one(tmp_path):
    d = tmp_path / "inc"
    iid = _blocked(d)
    out = R.requeue(iid, evidence="condition still failing after the last run", d=d, apply=True)
    assert out["ok"] and out["before"] == "blocked" and out["after"] == "open"
    recs = L.fold(L.read_events(d))
    assert recs[iid]["status"] == "open"
    events = [e for e in L.read_events(d) if e.get("kind") == "reopen"]
    assert len(events) == 1 and events[0]["detail"]["evidence"]


def test_an_operator_only_scope_is_refused(tmp_path):
    d = tmp_path / "inc"
    iid = _blocked(d, title="broker order route returned 500")
    out = R.requeue(iid, evidence="the order route still fails; retry it", d=d, apply=True)
    assert not out["ok"] and "operator-only" in out["refused"]
    assert L.fold(L.read_events(d))[iid]["status"] == "blocked"


def test_evidence_is_required(tmp_path):
    d = tmp_path / "inc"
    iid = _blocked(d)
    assert not R.requeue(iid, evidence="short", d=d)["ok"]


def test_a_non_blocked_incident_is_refused(tmp_path):
    d = tmp_path / "inc"
    rec = L.open_incident(source={"kind": "watcher", "watcher": "lane_health"}, title="x",
                          fingerprint="fp-2", d=d)
    rec = rec[0] if isinstance(rec, tuple) else rec
    assert not R.requeue(rec["id"], evidence="why not a blocked incident at all", d=d)["ok"]
