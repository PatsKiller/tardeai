"""F2 (#2498): the frozen Command Center inventory must be refreshable, not silently stale.

The 2026-11-02 audit capture asserts the state of every registered lane, root cause and
remediation owner in 64,504 committed lines. Nothing regenerated it, so the first lane that was
added, retired, re-owned or re-scheduled made it wrong and it stayed wrong. These tests pin the
repair:

* the documented refresh path exists (``scripts/build_command_center_audit_inventory.py``);
* ``--check`` names every added, removed or changed lane and exits 2 on drift;
* ``--write`` stamps a new capture and marks lanes added since the capture as unmeasured,
  never inventing runtime evidence;
* the frozen directory is never overwritten;
* the committed capture's summary is an exact recount of its own rows and the on-disk
  documentation carries the capture date.

Red first: the module did not exist before this change, so every test below errored at import.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_command_center_audit_inventory as G  # noqa: E402

FROZEN = ROOT / "docs/audits/20261102-command-center-operations/inventory"
CAPTURE = "2026-11-02T18:45:27.608050Z"


def _dump(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _mini_inventory() -> dict:
    rows = [
        {
            "lane_id": lane_id,
            "owner": owner,
            "registry_state": state,
            "scheduler_kind": kind,
            "coverage": coverage,
            "schedule_expressions": [],
            "schedule_timezone": "America/New_York",
        }
        for lane_id, owner, state, kind, coverage in (
            ("lane-a", "ops", "ACTIVE", "cron", "Measured"),
            ("lane-b", "platform", "ACTIVE", "systemd", "Partially Measured"),
            ("lane-c", "ops", "RETIRED", "none", "Disabled"),
        )
    ]
    return {"schema": "CommandCenterJobCoverageAudit@v1", "summary": {"as_of": CAPTURE}, "rows": rows}


def _mini_registry() -> dict:
    return {
        "lanes": [
            {"lane_id": "lane-a", "owner": "ops", "state": "ACTIVE", "scheduler": {"kind": "cron"}},
            {"lane_id": "lane-b", "owner": "platform", "state": "ACTIVE", "scheduler": {"kind": "systemd"}},
            {"lane_id": "lane-c", "owner": "ops", "state": "RETIRED", "scheduler": {"kind": "none"}},
        ]
    }


def test_the_documented_refresh_path_exists_and_carries_the_capture_date():
    readme = (FROZEN / "README.md").read_text(encoding="utf-8")
    assert "2026-11-02T18:45:27" in readme
    assert "build_command_center_audit_inventory.py --check" in readme
    assert "build_command_center_audit_inventory.py --write" in readme

    job_coverage = (FROZEN.parent / "JOB_COVERAGE.md").read_text(encoding="utf-8")
    assert "2026-11-02T18:45:27" in job_coverage
    assert "build_command_center_audit_inventory.py --check" in job_coverage

    audit_readme = (FROZEN.parent / "README.md").read_text(encoding="utf-8")
    assert "build_command_center_audit_inventory.py" in audit_readme


def test_check_is_clean_against_the_capture_registry(tmp_path):
    inventory = _dump(tmp_path / "inventory.json", _mini_inventory())
    registry = _dump(tmp_path / "registry.json", _mini_registry())
    report = G.drift(_mini_inventory(), _mini_registry())
    assert G.is_clean(report)
    assert G.main(["--check", "--inventory", str(inventory), "--registry", str(registry)]) == 0


def test_check_names_an_added_lane_and_exits_two(tmp_path):
    registry = _mini_registry()
    registry["lanes"].append({"lane_id": "lane-new", "owner": "ops", "state": "PAUSED", "scheduler": {"kind": "none"}})
    report = G.drift(_mini_inventory(), registry)
    assert [item["lane_id"] for item in report["added"]] == ["lane-new"]
    assert not G.is_clean(report)
    inventory = _dump(tmp_path / "inventory.json", _mini_inventory())
    registry_path = _dump(tmp_path / "registry.json", registry)
    assert G.main(["--check", "--inventory", str(inventory), "--registry", str(registry_path)]) == 2


def test_check_names_removed_re_owned_and_re_stated_lanes(tmp_path):
    registry = _mini_registry()
    registry["lanes"] = [lane for lane in registry["lanes"] if lane["lane_id"] != "lane-c"]
    for lane in registry["lanes"]:
        if lane["lane_id"] == "lane-a":
            lane["owner"] = "someone-else"
        if lane["lane_id"] == "lane-b":
            lane["state"] = "PAUSED"
    report = G.drift(_mini_inventory(), registry)
    assert [item["lane_id"] for item in report["removed"]] == ["lane-c"]
    changed = {item["lane_id"]: item["fields"] for item in report["changed"]}
    assert changed["lane-a"] == {"owner": ["ops", "someone-else"]}
    assert changed["lane-b"] == {"registry_state": ["ACTIVE", "PAUSED"]}
    inventory = _dump(tmp_path / "inventory.json", _mini_inventory())
    registry_path = _dump(tmp_path / "registry.json", registry)
    assert G.main(["--check", "--inventory", str(inventory), "--registry", str(registry_path)]) == 2


def test_write_stamps_the_capture_and_never_invents_runtime_evidence(tmp_path):
    registry = _mini_registry()
    registry["lanes"].append({"lane_id": "lane-new", "owner": "ops", "state": "ACTIVE", "scheduler": {"kind": "n8n"}})
    registry["lanes"].append({"lane_id": "lane-retired", "owner": "ops", "state": "RETIRED", "scheduler": {"kind": "none"}})
    inventory = _dump(tmp_path / "inventory.json", _mini_inventory())
    registry_path = _dump(tmp_path / "registry.json", registry)
    out = tmp_path / "capture"
    code = G.main(
        [
            "--write",
            "--out",
            str(out),
            "--inventory",
            str(inventory),
            "--registry",
            str(registry_path),
            "--as-of",
            "2026-11-05T17:30:00Z",
        ]
    )
    assert code == 0
    refreshed = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    assert refreshed["snapshot"]["captured_at"] == "2026-11-05T17:30:00Z"
    assert refreshed["snapshot"]["runtime_evidence_from"] == CAPTURE
    assert refreshed["snapshot"]["captured_by"] == "build_command_center_audit_inventory.py"
    rows = {row["lane_id"]: row for row in refreshed["rows"]}
    assert rows["lane-new"]["coverage"] == "Unmeasured"
    assert rows["lane-retired"]["coverage"] == "Disabled"
    assert rows["lane-new"]["execution_attempt_observed"] is False
    assert rows["lane-new"]["durable_completion_observed"] is False
    assert refreshed["summary"]["registry_total"] == 5
    header = (out / "inventory.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == G.CSV_COLUMNS
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["registry_total"] == 5


def test_write_refuses_to_overwrite_the_frozen_evidence_directory():
    with pytest.raises(SystemExit) as exc:
        G.main(["--write", "--out", str(FROZEN)])
    assert exc.value.code == 2


def test_the_committed_capture_is_an_exact_recount_of_its_own_rows():
    inventory = json.loads((FROZEN / "inventory.json").read_text(encoding="utf-8"))
    rows = inventory["rows"]
    assert len(rows) == 687
    assert len({row["lane_id"] for row in rows}) == 687
    # Rebuild the registry projection from the capture itself: every row maps cleanly, so a
    # refresh against the capture's own registry is a no-op.
    registry = {
        "lanes": [
            {
                "lane_id": row["lane_id"],
                "owner": row["owner"],
                "state": row["registry_state"],
                "scheduler": {"kind": row["scheduler_kind"]},
            }
            for row in rows
        ]
    }
    assert G.is_clean(G.drift(inventory, registry))
    recount = G._recount(rows, as_of=inventory["summary"]["as_of"])
    for key in (
        "registry_total",
        "active_total",
        "registry_state_counts",
        "coverage_all",
        "coverage_active",
        "coverage_all_percent",
        "coverage_active_percent",
        "scheduler_all",
        "scheduler_active",
    ):
        assert recount[key] == inventory["summary"][key], key
