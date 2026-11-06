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


def _row(lane_id, state="ACTIVE", coverage="Covered", presence="present"):
    return {"lane_id": lane_id, "registry_state": state, "coverage": coverage,
            "scheduler_kind": "n8n", "registry_presence": presence}


def test_a_retired_or_removed_lane_does_not_count_towards_current_registry_figures():
    """Codex cloud at 4eb07317f: retiring a lane gave active_total 492 beside a 493-member coverage_active, and removing
    one gave 687 lanes in a 686-lane registry. Current figures count current presence only."""
    rows = [_row("a"), _row("b"),
            # retired: still in the registry, no longer active
            _row("old", state="RETIRED", coverage="Covered"),
            # removed: preserved row, absent from the current registry
            _row("gone", presence="absent")]
    s = G._recount(rows, as_of="2026-11-05T00:00:00Z")
    assert s["registry_total"] == 3, s                      # the removed row is not in the registry
    assert s["active_total"] == 2, s                        # the retired lane is not active
    assert sum(s["coverage_active"].values()) == 2, s       # and neither inflates current coverage
    assert sum(s["coverage_all"].values()) == 3, s


def test_two_refreshes_keep_the_original_runtime_evidence_stamp():
    """Cloud finding 2: two refreshes relabelled unchanged 2 Nov evidence as 5 Nov. The tool never re-measures."""
    inv = {"rows": [_row("a")], "summary": {"registry_total": 1}, "snapshot": {"captured_at": "2026-11-02T18:45:27Z",
                                                                             "runtime_evidence_from": "2026-11-02T18:45:27Z"}}
    reg = {"lanes": [{"id": "a", "state": "ACTIVE", "owner": "x", "scheduler": {"kind": "n8n"}}]}
    one = G.refresh(inv, reg, as_of="2026-11-05T10:00:00Z", registry_path="config/lane_registry.json")
    assert one["snapshot"]["runtime_evidence_from"] == "2026-11-02T18:45:27Z", one["snapshot"]
    two = G.refresh(one, reg, as_of="2026-11-05T12:00:00Z", registry_path="config/lane_registry.json")
    assert two["snapshot"]["runtime_evidence_from"] == "2026-11-02T18:45:27Z", two["snapshot"]
    assert two["snapshot"]["captured_at"] == "2026-11-05T12:00:00Z"


def test_an_acknowledged_absence_does_not_re_report_as_drift():
    """Cloud at e3c4f7c84: a refreshed capture records a removal in its own row; without this, --check could never pass
    after any removal."""
    a = _row("a"); a["owner"] = "x"
    inv = {"rows": [a, {"lane_id": "gone", "registry_state": "RETIRED", "registry_presence": "absent"}],
           "summary": {}, "snapshot": {"captured_at": "2026-11-05T00:00:00Z"}}
    reg = {"lanes": [{"lane_id": "a", "state": "ACTIVE", "owner": "x", "scheduler": {"kind": "n8n"}}]}
    report = G.drift(inv, reg)
    assert report["removed"] == [], report["removed"]
    assert G.is_clean(report), report


def test_a_reschedule_with_the_same_kind_is_reported():
    """Cloud at e3c4f7c84: cron/cadence/timezone changes were invisible because only the scheduler kind was compared.

    Cloud at 2968676ed: the comparison then read `scheduler_expression`, a singular key that no committed capture row
    carries — all 687 rows store `schedule_expressions`, a list — so it still never ran. This test uses the capture's
    own shape.
    """
    row = _row("a")
    row.update({"owner": "x", "scheduler_kind": "cron", "schedule_expressions": ["0 9 * * *"],
                "schedule_timezone": "America/New_York"})
    inv = {"rows": [row], "summary": {}, "snapshot": {"captured_at": "2026-11-05T00:00:00Z"}}
    reg = {"lanes": [{"lane_id": "a", "state": "ACTIVE", "owner": "x",
                      "scheduler": {"kind": "cron", "expression": "30 9 * * *", "timezone": "America/New_York"}}]}
    report = G.drift(inv, reg)
    assert report["removed"] == []
    assert report["changed"] and report["changed"][0]["fields"]["schedule_expressions"] == [
        ["0 9 * * *"], ["30 9 * * *"]], report
    assert not G.is_clean(report)


def test_a_declared_expression_carrying_its_command_is_compared_on_the_schedule_only():
    """The registry writes the whole crontab entry ("5 7 * * * cd …"); the capture keeps the schedule. That is not a
    reschedule, and reporting it would flood --check."""
    row = _row("a")
    row.update({"owner": "x", "scheduler_kind": "cron", "schedule_expressions": ["5 7 * * *"]})
    inv = {"rows": [row], "summary": {}, "snapshot": {"captured_at": "2026-11-05T00:00:00Z"}}
    reg = {"lanes": [{"lane_id": "a", "state": "ACTIVE", "owner": "x",
                      "scheduler": {"kind": "cron",
                                    "expression": "5 7 * * * cd /srv/app/CURRENT && flock -n /tmp/x.lock "
                                                  "$(which python3) scripts/thing.py --apply"}}]}
    assert G.is_clean(G.drift(inv, reg)), G.drift(inv, reg)
    multi = {"lanes": [{"lane_id": "a", "state": "ACTIVE", "owner": "x",
                        "scheduler": {"kind": "cron", "expression": "0 4-9 * * 1-5 + 30 4-15 * * 1-5"}}]}
    row2 = _row("a")
    row2.update({"owner": "x", "scheduler_kind": "cron",
                 "schedule_expressions": ["0 4-9 * * 1-5", "30 4-15 * * 1-5"]})
    inv2 = {"rows": [row2], "summary": {}, "snapshot": {"captured_at": "2026-11-05T00:00:00Z"}}
    assert G.is_clean(G.drift(inv2, multi)), G.drift(inv2, multi)


def test_a_timezone_change_with_the_same_kind_is_reported():
    row = _row("a")
    row.update({"owner": "x", "scheduler_kind": "cron", "schedule_expressions": ["0 9 * * *"],
                "schedule_timezone": "America/New_York"})
    inv = {"rows": [row], "summary": {}, "snapshot": {"captured_at": "2026-11-05T00:00:00Z"}}
    reg = {"lanes": [{"lane_id": "a", "state": "ACTIVE", "owner": "x",
                      "scheduler": {"kind": "cron", "expression": "0 9 * * *", "timezone": "Europe/London"}}]}
    report = G.drift(inv, reg)
    assert report["changed"] and report["changed"][0]["fields"]["schedule_timezone"] == [
        "America/New_York", "Europe/London"], report


def test_the_committed_capture_reports_no_phantom_schedule_drift():
    """A captured row with no schedule is "not recorded", not "no schedule", so it must never be compared as one."""
    inventory = json.loads((FROZEN / "inventory.json").read_text(encoding="utf-8"))
    registry = json.loads(G.DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    report = G.drift(inventory, registry, registry_path=G.DEFAULT_REGISTRY)
    rows = {row["lane_id"]: row for row in inventory["rows"]}
    for item in report["changed"]:
        if "schedule_expressions" in item["fields"]:
            assert rows[item["lane_id"]]["schedule_expressions"], item


def test_a_lane_restored_after_an_acknowledged_absence_is_reported_and_re_measured_as_unknown():
    """Cloud at 2968676ed: remove a lane, acknowledge it with a refresh, restore it with the same owner/state/kind — the
    preserved historical row matched the registry, so --check reported clean while the capture still recorded the lane
    as absent, and its "Measured" coverage predated the absence."""
    a = _row("a")
    a["owner"] = "x"
    gone = {"lane_id": "b", "registry_state": "RETIRED", "registry_presence": "absent", "coverage": "Measured"}
    inv = {"rows": [a, gone], "summary": {}, "snapshot": {"captured_at": "2026-11-05T00:00:00Z"}}
    reg = {"lanes": [
        {"lane_id": "a", "state": "ACTIVE", "owner": "x", "scheduler": {"kind": "n8n"}},
        {"lane_id": "b", "state": "RETIRED", "owner": None, "scheduler": {"kind": "n8n"}},
    ]}
    report = G.drift(inv, reg)
    assert [item["lane_id"] for item in report["added"]] == ["b"], report
    assert not G.is_clean(report)
    refreshed = G.refresh(inv, reg, as_of="2026-11-05T04:00:00Z", registry_path="config/lane_registry.json")
    restored = {row["lane_id"]: row for row in refreshed["rows"]}["b"]
    assert restored["registry_presence"] == "present"
    assert restored["coverage"] != "Measured", restored["coverage"]
    assert "returned" in restored["classification"], restored["classification"]


def test_both_modes_fingerprint_the_registry_identically(tmp_path):
    """Cloud at 2968676ed: refresh() hashed a sorted compact JSON serialization while drift() hashed the file's bytes,
    so the same registry produced two fingerprints and a snapshot's could not be checked against its named source."""
    import hashlib

    registry = _mini_registry()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")  # deliberately not the compact form
    refreshed = G.refresh(_mini_inventory(), registry, as_of="2026-11-05T05:00:00Z", registry_path=str(path))
    report = G.drift(_mini_inventory(), registry, registry_path=path)
    on_disk = hashlib.sha256(path.read_bytes()).hexdigest()
    assert refreshed["snapshot"]["registry_sha256"] == report["registry_sha256"] == on_disk


def test_write_has_a_dry_run_that_reports_its_targets_and_writes_nothing(tmp_path):
    """AGENTS.md §6: a writing path exposes a real-path dry run that reports the intended changes first.
    `--check` is not one — it returns before `refresh()` and reports registry drift, not the proposed writes."""
    inventory = _dump(tmp_path / "inventory.json", _mini_inventory())
    registry = _dump(tmp_path / "registry.json", _mini_registry())
    out = tmp_path / "capture"
    plan = G._write_preview(_mini_inventory(), G.refresh(_mini_inventory(), _mini_registry(),
                                                         as_of="2026-11-05T06:00:00Z", registry_path=str(registry)), out)
    assert plan["dry_run"] is True
    assert plan["files"] == [str(out / "inventory.json"), str(out / "inventory.csv"), str(out / "summary.json")]
    assert plan["rows_before"] == plan["rows_after"] == 3
    assert plan["added"] == plan["removed"] == []
    # a refresh rewrites every row it projects (presence, declared schedule), so all three are reported as changed
    assert plan["changed"] == ["lane-a", "lane-b", "lane-c"]

    code = G.main(["--write", "--dry-run", "--out", str(out), "--inventory", str(inventory),
                   "--registry", str(registry), "--as-of", "2026-11-05T06:00:00Z"])
    assert code == 0
    assert not out.exists(), "the dry run created its target directory"
    assert G.main(["--write", "--dry-run", "--json", "--out", str(out), "--inventory", str(inventory),
                   "--registry", str(registry), "--as-of", "2026-11-05T06:00:00Z"]) == 0
    assert not out.exists()


def test_every_audit_document_carries_the_provenance_header():
    """AGENTS.md §14: Status, an ISO as_of and Measured at, on every document in the audit set."""
    import re
    for name in ("EXECUTIVE_SUMMARY.md", "README.md", "PROOF_INDEX.md"):
        text = (FROZEN.parent / name).read_text(encoding="utf-8")
        assert re.search(r"^Status:\s+(ACTIVE|SUPERSEDED BY |HISTORICAL|DRAFT)", text, re.MULTILINE), name
        assert re.search(r"^as_of:\s+\d{4}-\d{2}-\d{2}T", text, re.MULTILINE), name
        assert re.search(r"^Measured at:\s+\S", text, re.MULTILINE), name
