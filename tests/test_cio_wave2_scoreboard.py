"""Wave 2 living scoreboard contract. JSON must parse; NOW + slices present."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "ops" / "CIO_WAVE2_SCOREBOARD.md"
JS = ROOT / "docs" / "ops" / "CIO_WAVE2_SCOREBOARD.json"


def test_scoreboard_files_exist():
    assert MD.is_file()
    assert JS.is_file()
    text = MD.read_text(encoding="utf-8")
    assert "## NOW" in text
    assert "READ_ONLY_ADVISORY" in text
    assert "DRIVE" in text


def test_scoreboard_json_has_now_and_fifty_slices():
    data = json.loads(JS.read_text(encoding="utf-8"))
    assert data.get("authority") == "READ_ONLY_ADVISORY"
    assert data.get("memory_behavior_influence") in {0, "0"}
    now = data["now"]
    # Recorded probe results, not policy floors: pinned to 200 these could only
    # fail when the scoreboard honestly recorded an outage.
    for probe in ("health", "cio"):
        assert isinstance(now[probe], int)
        assert 100 <= now[probe] <= 599, (probe, now[probe])
    assert "current_pin" in now
    slices = data["slices"]
    assert "00" in slices
    assert "50" in slices
    assert len(slices) == 51
    assert slices["00"]["status"] in {"DONE", "PENDING", "SKIP", "FAIL"}
    assert data["drive"]["status"] in {"OK", "FAIL"}
    assert data["wave1_closed"] is True
