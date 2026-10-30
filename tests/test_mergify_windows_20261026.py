"""Hermetic Mergify ET windows (config + schedule rewrite). No network, no live state."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import mergify_windows as M  # noqa: E402


@pytest.fixture(autouse=True)
def _ci(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")


def test_after_hours_schedules_refuse_market_overlap():
    for s in M.schedules_for("after_hours"):
        M.assert_not_market_hours(s)
    with pytest.raises(ValueError, match="market freeze"):
        M.assert_not_market_hours("Mon-Fri 09:00-17:00[America/New_York]")


def test_apply_schedules_rewrites_or_blocks(tmp_path):
    src = (ROOT / ".mergify.yml").read_text(encoding="utf-8")
    assert src.count("schedule=") >= 4
    out = M.apply_schedules_to_mergify_yml(src, preset="weekends_only")
    assert "Sat-Sun 00:00-23:59[America/New_York]" in out
    assert "Mon-Fri 16:15-23:59" not in out
    # Indent stays valid for Mergify (6-space - or:).
    assert "      - or:\n          - schedule=Sat-Sun" in out


def test_view_market_freeze_then_open():
    # Thu 2026-10-22 15:00 ET = freeze
    freeze = datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc)
    v = M.view_for_ops(freeze)
    assert v["open_now"] is False and v["market_freeze"] is True
    assert v["windows"][0]["local_time"] == "16:15" and v["windows"][0]["state"] == "NEXT"
    # Same day 21:00 ET = open
    open_et = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)
    v2 = M.view_for_ops(open_et)
    assert v2["open_now"] is True and v2["market_freeze"] is False
    assert any(w["state"] == "OPEN" for w in v2["windows"])


def test_set_preset_in_config(tmp_path):
    cfg = json.loads((ROOT / "config" / "mergify_windows.json").read_text(encoding="utf-8"))
    p = tmp_path / "mergify_windows.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    M.set_preset_in_config("narrow_four", path=p)
    assert json.loads(p.read_text(encoding="utf-8"))["preset"] == "narrow_four"
