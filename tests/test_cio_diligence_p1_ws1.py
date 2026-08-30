"""P1-WS1 diligence as-built pack contract."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AS_BUILT = ROOT / "docs" / "audits" / "diligence" / "P1_WS1_AS_BUILT_ARCHITECTURE_2026-08-30.md"
FAILURES = ROOT / "docs" / "audits" / "diligence" / "P1_WS1_FAILURE_POINT_INVENTORY_2026-08-30.md"
MAPPING = ROOT / "docs" / "architecture" / "cio" / "EXTERNAL_DIAGRAM_TYPE_MAPPING.md"
GAPS = ROOT / "docs" / "audits" / "CIO_DILIGENCE_GAP_REGISTER.md"
SCORE_MD = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.md"
SCORE_JS = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.json"
OPS = ROOT / "docs" / "ops" / "CIO_DILIGENCE_P1_WS1_2026-08-30.md"

STAGE_HEADERS = [
    "Event intake",
    "Operator interface",
    "Identity",
    "Materiality",
    "Graph impact",
    "Research",
    "Specialists",
    "Council",
    "Product",
    "Notify",
    "Outcome",
    "Cognition",
    "Persistence",
]


def test_p1_ws1_files_exist():
    for path in (AS_BUILT, FAILURES, MAPPING, GAPS, SCORE_MD, SCORE_JS, OPS):
        assert path.is_file(), f"missing {path}"


def test_as_built_stage_headers_present():
    text = AS_BUILT.read_text(encoding="utf-8")
    assert "READ_ONLY_ADVISORY" in text
    assert "852ecd47" in text
    for header in STAGE_HEADERS:
        assert header in text, f"missing stage section: {header}"
    # code-path citations expected
    assert "cio_instrument_record.py" in text
    assert "cio_specialist_artifact.py" in text
    assert "cio_council_synthesis.py" in text
    assert "portfolio_rebalancer.py" in text


def test_failure_inventory_stage_headers_present():
    text = FAILURES.read_text(encoding="utf-8")
    for header in STAGE_HEADERS:
        assert header in text, f"missing failure stage: {header}"
    assert "Id fork" in text or "id fork" in text.lower()
    assert "Silent skip" in text or "silent skip" in text.lower()


def test_wave3_mapping_appendix():
    text = MAPPING.read_text(encoding="utf-8")
    assert "InstrumentRecord@v1" in text
    assert "SpecialistArtifact@v1-lite" in text
    assert "CIOCouncilSynthesis@v1" in text
    assert "Wave 3" in text
    assert "cio_instrument_record.py" in text
    assert "cio_specialist_artifact.py" in text
    assert "cio_council_synthesis.py" in text


def test_gap_register_g_auth_01_locked():
    text = GAPS.read_text(encoding="utf-8")
    assert "G-AUTH-01" in text
    assert "852ecd47" in text
    assert "cio_rebalancer_readonly" in text or "rebalancer_readonly" in text
    assert "G-DUAL-01" in text
    assert "merged" in text.lower()
    # PR-G closeout: G-AUTH-01 mitigated via #695; G-DUAL-01 closed by design
    assert "#695" in text
    assert "CLOSED" in text


def test_scoreboard_p1_ws1_done():
    md = SCORE_MD.read_text(encoding="utf-8")
    assert "P1-WS1" in md
    assert "DONE" in md
    assert "pre-promote" in md.lower() or "pre-promote" in md
    data = json.loads(SCORE_JS.read_text(encoding="utf-8"))
    assert data.get("authority") == "READ_ONLY_ADVISORY"
    assert data.get("memory_behavior_influence") in {0, "0"}
    assert data["packages"]["P0"]["status"] == "DONE"
    assert data["packages"]["P1-WS1"]["status"] == "DONE"
    # All diligence packages P0–P9 restamped DONE on main tip
    assert data["packages"]["P1-WS2"]["status"] == "DONE"
    assert data["packages"]["P1-WS3"]["status"] == "DONE"
    assert data["now"]["phase_cursor"] in {"COMPLETE", "DONE"}
    # Not a literal. Pinning the SHA made this assert track the document
    # rather than the tree -- it still read "015a7891" while origin/main was
    # 9d92b6e0, and restamping it to the newer SHA would only reproduce that.
    # Assert the shape and the snapshot's internal agreement instead;
    # tests/test_cio_diligence_scoreboard.py checks the SHA is a real commit.
    pin = data["now"]["current_pin"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", pin), pin
    assert data["now"]["origin_main_full"].startswith(pin)
    assert data["now"].get("this_package_pre_promote") is True
    assert data["now"]["health"] == 200
    assert data["now"]["cio"] == 200
