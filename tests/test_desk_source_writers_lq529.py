"""LQ-20261107-529: "Writer not identified for this source" on /v3 desk pages. ANCHOR: DESK_SOURCE_WRITERS_LQ529.

Each source card either names its real writer lane (looked up in config/lane_registry.json) or states why no
scheduled writer exists. No writer is invented. This file proves the server-side half:

* the defense "Review console" source states that it is operator-written (config/promote_criteria.json is changed
  only through the review console), so the page does not say "Writer not identified";
* the incident supervisor lane is measured by the receipt it writes after each completed cycle
  (data/coordination/incidents/supervisor_last.json), not declared JOURNAL_ONLY, so the incidents page can map it.

Synthetic fixtures only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import desks_a as desk  # noqa: E402

NOW = datetime(2026, 11, 7, 21, 0, tzinfo=timezone.utc)


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _lanes() -> dict[str, dict]:
    doc = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    return {lane["lane_id"]: lane for lane in doc["lanes"]}


def test_defense_review_source_states_its_operator_writer(tmp_path):
    _write(tmp_path / "config/promote_criteria.json",
           {"criteria_locked": True, "locked_at": "2026-07-18T22:57", "amendments": [], "decisions": [1]})
    out = desk.defense_payload(root=tmp_path, now=NOW, truth={}, states={})
    review = next(s for s in out["sources"] if s["id"] == "review")
    assert review["lane_ids"] == []
    note = review.get("writer_note") or ""
    assert "promote_criteria.json" in note and "review console" in note.lower()
    assert "no scheduled job" in note.lower()


def test_sources_with_a_writer_lane_carry_no_writer_note(tmp_path):
    out = desk.defense_payload(root=tmp_path, now=NOW, truth={}, states={})
    for source in out["sources"]:
        if source["lane_ids"]:
            assert "writer_note" not in source, source["id"]


def test_incident_writer_lanes_are_registered_and_active():
    lanes = _lanes()
    for lane_id in ("tradeai-incident-watchers", "tradeai-incident-supervisor", "conflict-resolver"):
        assert lane_id in lanes, lane_id
        assert lanes[lane_id]["state"] == "ACTIVE", lane_id


def test_incident_supervisor_is_measured_by_its_cycle_receipt():
    signal = _lanes()["tradeai-incident-supervisor"]["output_signal"]
    assert signal["kind"] == "file_mtime", signal
    assert signal["path"] == "data/coordination/incidents/supervisor_last.json"
    # The receipt the registry measures is the one the supervisor actually writes.
    src = (ROOT / "scripts/lib/incident_supervisor.py").read_text(encoding="utf-8")
    assert '"supervisor_last.json"' in src
