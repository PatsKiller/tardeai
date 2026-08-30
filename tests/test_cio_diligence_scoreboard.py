"""Diligence scoreboard + master plan kickoff contract."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.md"
JS = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.json"
PLAN = ROOT / "docs" / "audits" / "CIO_PLATFORM_DILIGENCE_MASTER_PLAN_2026-08-30.md"
GAPS = ROOT / "docs" / "audits" / "CIO_DILIGENCE_GAP_REGISTER.md"
DIL = ROOT / "docs" / "audits" / "diligence"


def test_diligence_files_exist():
    assert MD.is_file()
    assert JS.is_file()
    assert PLAN.is_file()
    assert GAPS.is_file()
    assert "READ_ONLY_ADVISORY" in MD.read_text(encoding="utf-8")
    assert "Phase 1" in PLAN.read_text(encoding="utf-8")


def test_diligence_json_contract():
    data = json.loads(JS.read_text(encoding="utf-8"))
    assert data.get("authority") == "READ_ONLY_ADVISORY"
    assert data.get("memory_behavior_influence") in {0, "0"}
    now = data["now"]
    assert now["health"] == 200
    assert now["cio"] == 200
    assert "lineage" in now
    assert now["lineage"]["workflows"] >= 1
    assert now["lineage"]["complete_to_checkpoint"] == 406
    assert now["lineage"]["complete_pct"] == 54.0
    assert now["event_lifecycle"]["weighted_full_lifecycle_pct"] == 2.17
    assert now["event_lifecycle"]["claim_99_99"] is False
    assert now["identity_production_resolvable_pct"] == 98.9
    assert now["schg_surface_a"] == "EXITED"
    assert now["phase_cursor"] in {"COMPLETE", "DONE"}
    assert now["current_pin"] == "db08bd11"
    assert now.get("this_package_pre_promote") is True
    pkgs = data["packages"]
    assert pkgs["P0"]["status"] == "DONE"
    assert "P1-WS1" in pkgs
    assert "P9" in pkgs
    assert data["drive"]["status"] in {"OK", "FAIL"}


REQUIRED_PACKAGES = (
    "P0",
    "P1-WS1",
    "P1-WS2",
    "P1-WS3",
    "P2-WS4",
    "P2-WS5",
    "P3",
    "P4",
    "P5",
    "P6",
    "P7",
    "P8",
    "P9",
)

PACKAGE_PRS = {
    "P0": 681,
    "P1-WS1": 686,
    "P1-WS2": 685,
    "P1-WS3": 689,
    "P2-WS4": 688,
    "P2-WS5": 688,
    "P3": 682,
    "P4": 687,
    "P5": 687,
    "P6": 683,
    "P7": 683,
    "P8": 683,
    "P9": 684,
}


def test_all_packages_p0_p9_done_with_pr_and_proof():
    data = json.loads(JS.read_text(encoding="utf-8"))
    pkgs = data["packages"]
    md = MD.read_text(encoding="utf-8")
    assert "COMPLETE" in md or "all packages P0–P9 DONE" in md
    for pid in REQUIRED_PACKAGES:
        assert pid in pkgs, pid
        assert pkgs[pid]["status"] == "DONE", pid
        assert pkgs[pid].get("pr") == PACKAGE_PRS[pid], pid
        assert pkgs[pid].get("sha"), pid
        assert pkgs[pid].get("proof"), pid
        proofs = pkgs[pid]["proof"]
        paths = proofs if isinstance(proofs, list) else []
        for p in paths:
            if "/" in str(p) and not str(p).startswith("weighted_"):
                assert (ROOT / p).is_file(), f"missing proof path {p} for {pid}"
    assert data["now"]["telegram_sent"] is False
    assert data["memory_behavior_influence"] == 0
    assert data["now"].get("packages_done_out_of_order") in ([], None)


def test_p6_p7_p8_packages_done_with_proof():
    data = json.loads(JS.read_text(encoding="utf-8"))
    pkgs = data["packages"]
    for pid in ("P6", "P7", "P8"):
        assert pkgs[pid]["status"] == "DONE", pid
        assert pkgs[pid].get("proof"), pid
    assert (DIL / "P6_COUNCIL_DETERMINISM_2026-08-30.md").is_file()
    assert (DIL / "P7_NOTIFICATION_MATRIX_2026-08-30.md").is_file()
    assert (DIL / "P8_MBI_PARTITION_2026-08-30.md").is_file()
    assert data["now"]["telegram_sent"] is False
    assert data["memory_behavior_influence"] == 0
