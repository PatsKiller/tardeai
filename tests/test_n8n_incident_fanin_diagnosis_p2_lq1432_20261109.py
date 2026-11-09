"""ANCHOR: N8N_INCIDENT_FANIN_DIAGNOSIS_P2_LQ1432 — a diagnosis digest P2 is an incident.

LQ-20261107-1432. The 01:18 ET diagnosis parked hermes-research-worker-pool at P2
on the receipt digest (system_health_checks last written 52.2 h ago). The fan-in
read only ``escalations``, which the diagnoser fills with P1, so the P2 never
became a finding and /v3/ops/incidents stayed empty. Synthetic names only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402
from scripts.lib import incidents_view as V  # noqa: E402

NOW = datetime(2026, 11, 9, 6, 18, tzinfo=timezone.utc)
LANE = "synthetic-worker"


def _receipt() -> dict:
    return {
        "as_of": NOW.isoformat(),
        "ok": True,
        "escalations": [
            {
                "priority": "P1",
                "lane": "synthetic-p1",
                "key": "synthetic-p1|sig-aaa",
                "reason": "low_confidence",
                "detail": "low_confidence synthetic",
                "at": NOW.isoformat(),
            }
        ],
        "digest": [
            {
                "priority": "P2",
                "lane": LANE,
                "key": f"{LANE}|sig-bbb",
                "reason": "suggest_only",
                "event_type": "RUN_FAILED",
                "detail": "suggest_only; cause=system_health_checks last written 52.2 h ago",
                "at": NOW.isoformat(),
            },
            {
                "priority": "P3",
                "lane": "synthetic-noise",
                "key": "synthetic-noise|sig-ccc",
                "reason": "note",
                "detail": "not an incident",
                "at": NOW.isoformat(),
            },
        ],
    }


def test_digest_p2_joins_the_finding_list(monkeypatch, tmp_path):
    monkeypatch.setattr(fanin, "_governance_lane", lambda _lane: None)
    path = tmp_path / fanin.DIAGNOSIS_RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_receipt()), encoding="utf-8")
    found = fanin._diagnosis_findings(tmp_path, NOW + timedelta(minutes=1))
    by_item = {f["item"]: f for f in found}
    p1 = "escalate:synthetic-p1/synthetic-p1|sig-aaa"
    p2 = f"escalate:{LANE}/{LANE}|sig-bbb"
    assert p1 in by_item and by_item[p1]["severity"] == "P1"
    assert by_item[p2]["severity"] == "P2"
    assert by_item[p2]["lane"] == LANE
    assert "52.2 h" in by_item[p2]["detail"]
    assert "synthetic-noise" not in {f.get("lane") for f in found}
    assert "digest_p2=1" in fanin.NOTES["diagnosis_source"]


def test_apply_opens_one_incident_record_for_the_digest_p2(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "incidents"))
    findings = [
        {
            "source": fanin.DIAGNOSIS_SOURCE,
            "item": f"escalate:{LANE}/{LANE}|sig-bbb",
            "severity": "P2",
            "lane": LANE,
            "detail": "system_health_checks last written 52.2 h ago",
            "reason": "suggest_only",
        },
        {
            "source": fanin.DIAGNOSIS_SOURCE,
            "item": "escalate:synthetic-p1/synthetic-p1|sig-aaa",
            "severity": "P1",
            "lane": "synthetic-p1",
            "detail": "low_confidence",
        },
    ]
    assert fanin.publish_diagnosis_p2(findings, apply=False) == 0
    assert not (tmp_path / "incidents" / "events.jsonl").exists()
    assert fanin.publish_diagnosis_p2(findings, apply=True) == 1
    assert fanin.publish_diagnosis_p2(findings, apply=True) == 0
    data = V.payload(L.incidents_dir())
    titles = [row["title"] for row in data["incidents"]]
    assert any(LANE in t and "52.2 h" in t for t in titles)
    assert all("synthetic-p1" not in t for t in titles)
    assert data["incidents"][0]["severity"] == "P2"
