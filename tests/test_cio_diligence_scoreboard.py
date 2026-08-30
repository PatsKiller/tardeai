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
    pkgs = data["packages"]
    assert pkgs["P0"]["status"] == "DONE"
    assert "P1-WS1" in pkgs
    assert "P9" in pkgs
    assert data["drive"]["status"] in {"OK", "FAIL"}


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
