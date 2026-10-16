"""#1819 follow-ups approved by the operator on 2026-10-16: the P2 digest is wired, the catalogue records its approval,
and the "no SLA row" gap is closed.

1. advice_digest reads the diagnoser receipt's ``digest[]`` (P2 only, receipt <= 24 h old) and renders a
   LANE HEALTH section. P1 rows and stale receipts never show.
2. The generated catalogue carries an ``approvals`` provenance row for the 119 -> 137 rebuild.
3. The breach detector derives a registry SLA row for every lane newer than the seed file, so the four UNGOVERNED
   lanes of 2026-10-16 (heartbeat-watch, advisory-desk-run-now, analyst-prospectus-generate,
   aegis-brief-regenerate) are governed. A seed row still wins.

Hermetic: tmp state root; no DB, no send, no network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import advice_digest as AD  # noqa: E402
from scripts.lib import n8n_remediation_catalogue as C  # noqa: E402
import seed_supervisor_sla as SEED  # noqa: E402
import supervisor_breach_detector as BD  # noqa: E402

NOW = datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc)
UNGOVERNED_20261016 = ("heartbeat-watch", "advisory-desk-run-now", "analyst-prospectus-generate",
                       "aegis-brief-regenerate")


def _receipt(tmp_path, *, as_of=NOW, digest=None):
    p = tmp_path / AD.DIAGNOSER_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"as_of": as_of.isoformat(), "digest": digest if digest is not None else [
        {"key": "lane-b|sig-2", "lane": "lane-b", "event_type": "NO_OUTPUT", "priority": "P2", "reason": "suggest_only",
         "siem_ids": [5, 6, 7], "tried": "diag:0.8"},
        {"key": "lane-a|sig-1", "lane": "lane-a", "event_type": "RUN_FAILED", "priority": "P2",
         "reason": "approval_required", "siem_ids": [4]},
        {"key": "lane-p1|sig-9", "lane": "lane-p1", "priority": "P1", "reason": "low_confidence"},
    ]}))


# ---------------------------------------------------------------- 1. digest


def test_lane_health_reads_p2_digest_rows_only(tmp_path):
    _receipt(tmp_path)
    rows = AD.collect_lane_health(tmp_path, now=NOW)
    assert [r["lane"] for r in rows] == ["lane-a", "lane-b"]          # P1 excluded, sorted


def test_lane_health_ignores_a_stale_or_missing_receipt(tmp_path):
    assert AD.collect_lane_health(tmp_path, now=NOW) == []
    _receipt(tmp_path, as_of=NOW - timedelta(hours=25))
    assert AD.collect_lane_health(tmp_path, now=NOW) == []


def test_render_shows_the_lane_health_section(tmp_path):
    _receipt(tmp_path)
    other = {"rows": [], "lane_health": AD.collect_lane_health(tmp_path, now=NOW)}
    text = "\n".join(AD.render("17", {}, [], {}, None, other, NOW))
    assert "LANE HEALTH (P2)" in text and "lane-b" in text and "×3" in text and "tried diag:0.8" in text
    assert "lane-p1" not in text
    # no rows -> no section (the digest is unchanged for a quiet day)
    assert "LANE HEALTH" not in "\n".join(AD.render("17", {}, [], {}, None, {"rows": []}, NOW))


def test_collect_other_carries_lane_health(tmp_path, monkeypatch):
    _receipt(tmp_path, as_of=datetime.now(timezone.utc))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    import p1_digest_sender as p1

    monkeypatch.setattr(p1, "collect", lambda hours: {"rows": [], "watermark": None})
    out = AD.collect_other(6)
    assert [r["lane"] for r in out["lane_health"]] == ["lane-a", "lane-b"]


# ---------------------------------------------------------------- 2. catalogue approval


def test_committed_catalogue_records_the_operator_approval():
    doc = json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text(encoding="utf-8"))
    assert doc["approvals"] == [dict(a) for a in C.APPROVALS]
    assert "119 -> 137" in doc["approvals"][0]["scope"] and doc["approvals"][0]["date"] == "2026-10-16"
    assert C.validate_catalogue(doc) == []


# ---------------------------------------------------------------- 3. SLA gap


def _lane(lid, cadence=0.25):
    return {"lane_id": lid, "state": "ACTIVE", "owner": "platform", "expected_cadence_hours": cadence,
            "scheduler": {"kind": "n8n"}, "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lid}.json"}}


def test_lanes_newer_than_the_seed_get_a_registry_sla_row():
    seed = [{"lane_id": "old-lane", "max_silence_s": 123, "seeded_from": "config/lane_registry.json"}]
    lanes = [_lane("old-lane")] + [_lane(x) for x in UNGOVERNED_20261016]
    merged = SEED.merged_sla_rows(seed, lanes)
    assert merged["old-lane"]["max_silence_s"] == 123                  # the seed row wins
    for lid in UNGOVERNED_20261016:
        assert merged[lid]["seeded_from"] == SEED.REGISTRY_FALLBACK
        assert merged[lid]["max_silence_s"] == SEED.sla_row(_lane(lid))["max_silence_s"]


def test_breach_detector_no_longer_flags_the_four_lanes_ungoverned():
    lanes = [_lane(x) for x in UNGOVERNED_20261016]
    observe = lambda sig: {"last_output_at": NOW.isoformat(), "readable": True}  # noqa: E731
    before = BD.detect(lanes=lanes, sla_by_lane={}, heartbeats={}, observe=observe, now=NOW)
    assert {r["lane_id"] for r in before if r["kind"] == "UNGOVERNED"} == set(UNGOVERNED_20261016)
    after = BD.detect(lanes=lanes, sla_by_lane=SEED.merged_sla_rows([], lanes), heartbeats={}, observe=observe,
                      now=NOW)
    assert not [r for r in after if r["kind"] == "UNGOVERNED"]


def test_the_four_lanes_are_registered_so_the_fallback_covers_them():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    ids = {r.get("lane_id") for r in reg["lanes"]}
    assert set(UNGOVERNED_20261016) <= ids
