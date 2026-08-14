"""Research governance — trial registry dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance.trial_registry import TrialRegistry  # noqa: E402


def test_freezes_family_once():
    reg = TrialRegistry()
    reg.freeze_family("f1", "h1", protocol_hash="ph")
    assert reg.is_frozen("f1")
    with pytest.raises(ValueError):
        reg.freeze_family("f1", "h1", protocol_hash="ph")


def test_records_losing_variants():
    reg = TrialRegistry()
    reg.freeze_family("f1", "h1", protocol_hash="ph")
    reg.record_trial("f1", "t1", {"p": 1}, selected_for_followup=True)
    reg.record_losing_trial("f1", "t2", {"p": 2})
    fam = reg.get_family("f1")
    assert fam.trial_count == 2
    assert fam.losing_count == 1
    assert fam.selected_count == 1


def test_detects_winner_only_registry():
    reg = TrialRegistry()
    reg.freeze_family("f2", "h2", protocol_hash="ph")
    reg.record_trial("f2", "t1", {"p": 1}, selected_for_followup=True)
    rep = reg.completeness_report("f2")
    assert rep["complete"] is False


def test_complete_family_has_losers():
    reg = TrialRegistry()
    reg.freeze_family("f3", "h3", protocol_hash="ph")
    reg.record_trial("f3", "t1", {"p": 1}, selected_for_followup=True)
    reg.record_losing_trial("f3", "t2", {"p": 2})
    rep = reg.completeness_report("f3")
    assert rep["complete"] is True


def test_unfrozen_family_is_incomplete():
    reg = TrialRegistry()
    reg.record_trial("f4", "t1", {"p": 1})
    assert reg.completeness_report("f4")["complete"] is False


def test_oos_consumption_semantics():
    reg = TrialRegistry()
    reg.register_oos_window("f1", "w1", oos_generation=1, segment_start="2000", segment_end="2010")
    assert reg.oos_is_untouched("f1", "w1") is True
    reg.consume_oos_window("f1", "w1")
    assert reg.oos_is_untouched("f1", "w1") is False
    win = reg.get_family("f1").oos_windows["w1"]
    assert win.oos_consumed_at is not None
    assert win.oos_generation == 1


def test_unknown_oos_window_raises():
    reg = TrialRegistry()
    with pytest.raises(KeyError):
        reg.consume_oos_window("f1", "missing")
