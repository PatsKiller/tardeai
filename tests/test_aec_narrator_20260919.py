"""Hermetic tests for AEC narrator brief + anti-repeat + alarm firing."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Declared for alarm_coverage: notify path reaches telegram_alert.send_telegram.
COVERS = [
    "scripts/lib/aec_narrator.py",
]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    # Ensure scripts.lib package path for narrator imports
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    return mod


def test_narrator_render_dry_and_anti_repeat(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    narr = _load("aec_narrator", "scripts/lib/aec_narrator.py")
    brief = narr.render_executive_brief(subject_key="WATCH:SCHG")
    assert brief["schema"] == "AecNarratorBrief@v1"
    assert brief["mbi_behavior"] == 0
    assert brief["financial_action"] is False
    assert "Executive Brief" in brief["body"]
    assert brief["would_telegram"] is True
    # Persist fingerprint then suppress
    mem = _load("aec_memory_spines", "scripts/lib/aec_memory_spines.py")
    mem.append_fact("learning", {"claim_fp": brief["claim_fp"], "text": "prior"}, path=tmp_path / "mem.json")
    brief2 = narr.render_executive_brief(subject_key="WATCH:SCHG")
    assert brief2["suppressed_repeat"] is True
    out = narr.notify_executive_brief(brief2, apply=False)
    assert out["telegram"] == "suppressed_repeat"


def test_narrator_notify_reaches_transport(tmp_path, monkeypatch):
    """Firing test: apply=True must call send_telegram at the chokepoint."""
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    captured: list[tuple] = []

    def _send(msg, *a, **k):
        captured.append((msg, dict(k)))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", _send)
    narr = _load("aec_narrator_fire", "scripts/lib/aec_narrator.py")
    brief = narr.render_executive_brief(subject_key="WATCH:SCHG")
    out = narr.notify_executive_brief(brief, apply=True)
    assert out["telegram"] == "accepted"
    assert out["notify_attempted"] is True
    assert captured, "transport never called"
    assert "Executive Brief" in captured[0][0]
    assert captured[0][1].get("bypass_router") is True


def test_cycle_includes_narrator_brief(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    cycle = _load("aec_command_center_cycle", "scripts/aec_command_center_cycle.py")
    out = cycle.run_cycle(subject_key="WATCH:SCHG", apply=False)
    assert out.get("narrator_brief", {}).get("schema") == "AecNarratorBrief@v1"
    assert out.get("narrator_notify", {}).get("telegram") == "dry_run"
    assert out.get("outcome", {}).get("schema_version") == "CommitmentOutcome@v1"
