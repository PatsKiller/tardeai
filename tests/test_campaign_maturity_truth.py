"""Lane T — live maturity truth supersedes stale June-2026 body."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.control_plane_api import handle
from scripts.lib.campaign_maturity_truth import build_maturity_truth


def test_build_maturity_truth_has_explicit_zeroes_and_classes(tmp_path: Path):
    # Minimal fake served root (no DB required)
    (tmp_path / "SOURCE_COMMIT").write_text("abc123\n")
    (tmp_path / "scripts/lib").mkdir(parents=True)
    (tmp_path / "scripts/lib/wake_subject_selector.py").write_text("# stub\n")
    (tmp_path / "scripts/run_persistent_wake.py").write_text("# stub\n")
    wake_dir = tmp_path / "data/persistent_wake/state"
    wake_dir.mkdir(parents=True)
    wake_dir.joinpath("wakes.jsonl").write_text(
        json.dumps(
            {
                "wake_id": "w1",
                "wake_reason": "scheduled_persistent_review",
                "schedule_slot_utc": "2026-09-08T03:00Z",
                "produced_at": "2026-09-08T03:54:41Z",
                "decision_summary": {"effect_kind": "none"},
            }
        )
        + "\n"
    )
    payload = build_maturity_truth(root=tmp_path)
    assert payload["schema"] == "CampaignMaturityTruth@v1"
    assert payload["overall_is_not_a_certification"] is True
    assert payload["computes_maturity"] is False
    assert payload["served_sha"] == "abc123"
    assert payload["staleness_hours"] == 0.0
    dims = {i["dimension"]: i for i in payload["items"]}
    assert dims["behavior_changing"]["count"] == 0
    assert dims["behavior_changing"]["explicit_zero"] is True
    assert dims["behavior_changing"]["evidence_class"] == "absent"
    # CANARY config dimension exists separately from delivery ownership
    assert "comms_gateway_configured" in dims
    assert "comms_delivery_owner_gateway" in dims
    # Controlled canary counted; organic stays zero without organic marker
    assert dims["persistent_wake_controlled_canary"]["count"] >= 1
    assert dims["persistent_wake_organic"]["count"] == 0
    assert dims["persistent_wake_organic"]["evidence_class"] == "absent"
    assert "historical_body_superseded" in payload


def test_control_plane_maturity_is_live_not_june_body(tmp_path: Path, monkeypatch):
    # Point state root at tmp so collection cannot load stale persistent-state file
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    (tmp_path / "SOURCE_COMMIT").write_text("deadbeef\n")
    (tmp_path / "scripts/lib").mkdir(parents=True)
    (tmp_path / "scripts/lib/wake_subject_selector.py").write_text("#\n")
    (tmp_path / "scripts/run_persistent_wake.py").write_text("#\n")
    # Plant a stale historical file that must NOT become the served body
    runtime = tmp_path / "data/runtime"
    runtime.mkdir(parents=True)
    runtime.joinpath("maturity_score_latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-28T02:07:44.233618+00:00",
                "final_maturity_score_of_5": 4.95,
                "score_lines": [],
            }
        )
    )
    status, body = handle("/api/v3/control-plane/maturity")
    assert status == 200
    assert body["freshness"] == "LIVE_RUNTIME"
    assert body["evidence_class"] == "LIVE_RUNTIME"
    data = body["data"]
    assert data.get("generated_at", "").startswith("2026-09") or data.get("generated_at", "").startswith("2026-")
    assert data.get("generated_at") != "2026-06-28T02:07:44.233618+00:00"
    assert data.get("final_maturity_score_of_5") is None
    assert data.get("overall_is_not_a_certification") is True
    items = data.get("items") or []
    assert items, "expected live dimension items"
    assert all("evidence_class" in i for i in items)
    # Must not present CANARY as ownership
    owned = [i for i in items if i["dimension"] == "comms_delivery_owner_gateway"]
    configured = [i for i in items if i["dimension"] == "comms_gateway_configured"]
    assert owned and configured
    assert "CANARY configuration is NOT delivery ownership" in (configured[0].get("notes") or "")
