"""Research governance — trial registry immutability + anti-gaming tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import trial_registry as tr  # noqa: E402


def _registry_with_frozen_family():
    reg = tr.TrialRegistry()
    reg.freeze_family("fam", "h1", protocol_hash="ph",
                      planned_trials=[("t1", "cfg1"), ("t2", "cfg2"), ("t3", "cfg3")])
    return reg


def test_freeze_requires_protocol_hash():
    reg = tr.TrialRegistry()
    with pytest.raises(ValueError):
        reg.freeze_family("f", "h", protocol_hash="", planned_trials=[("t", "c")])


def test_freeze_requires_planned_universe():
    reg = tr.TrialRegistry()
    with pytest.raises(ValueError):
        reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[])


def test_frozen_family_rejects_unplanned_trial():
    reg = _registry_with_frozen_family()
    with pytest.raises(ValueError):
        reg.record_trial("fam", "unplanned", config_hash="x", result_payload={"s": 1})


def test_trial_must_match_frozen_config_hash():
    reg = _registry_with_frozen_family()
    with pytest.raises(ValueError):
        reg.record_trial("fam", "t1", config_hash="WRONG", result_payload={"s": 1})


def test_duplicate_trial_with_changed_content_is_hard_error():
    reg = _registry_with_frozen_family()
    reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": 0.5})
    with pytest.raises(ValueError):
        reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": 99.0})


def test_duplicate_trial_identical_payload_is_idempotent():
    reg = _registry_with_frozen_family()
    a = reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": 0.5})
    b = reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": 0.5})
    assert a == b


def test_result_hash_required_no_parameter_fallback():
    reg = _registry_with_frozen_family()
    with pytest.raises(ValueError):
        reg.record_trial("fam", "t1", config_hash="cfg1")  # no result_hash / payload


def test_result_hash_hashes_actual_payload():
    reg = _registry_with_frozen_family()
    rec = reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": 0.5})
    assert rec.result_hash
    # The hash is content-addressed over the RESULT, not the config: same result
    # content hashes the same; different result content hashes differently.
    same = reg.record_trial("fam", "t2", config_hash="cfg2", result_payload={"sharpe": 0.5})
    assert rec.result_hash == same.result_hash
    diff = reg.record_trial("fam", "t3", config_hash="cfg3", result_payload={"sharpe": -0.5})
    assert rec.result_hash != diff.result_hash


def test_selection_is_separate_append_only_event():
    reg = _registry_with_frozen_family()
    rec = reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": -0.5})
    reg.record_selection("fam", "t1", False, reason="loser")
    # Recording a selection does not mutate the immutable trial record.
    assert rec.result_hash == reg.get_trial("fam", "t1").result_hash
    assert len(reg.selection_events("fam")) == 1


def test_loser_cannot_be_rewritten_as_winner():
    reg = _registry_with_frozen_family()
    reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": -0.5})
    # Trying to overwrite the same trial_id with a different (winning) result must fail.
    with pytest.raises(ValueError):
        reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"sharpe": 5.0})


def test_complete_family_requires_every_planned_trial_accounted():
    reg = _registry_with_frozen_family()
    reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"s": 1})
    reg.record_trial("fam", "t2", config_hash="cfg2", result_payload={"s": -1})
    # t3 still unaccounted -> incomplete even though a loser exists.
    assert reg.completeness_report("fam")["complete"] is False
    reg.record_trial("fam", "t3", config_hash="cfg3", result_payload={"s": 0})
    assert reg.completeness_report("fam")["complete"] is True


def test_incomplete_planned_family_cannot_claim_complete():
    reg = tr.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1"), ("b", "c2")])
    reg.record_trial("f", "a", config_hash="c1", result_payload={"x": 1})
    assert reg.completeness_report("f")["complete"] is False


def test_oos_window_requires_frozen_family():
    reg = tr.TrialRegistry()
    with pytest.raises(ValueError):
        reg.register_oos_window("unfrozen", "w", oos_generation=1)


def test_first_oos_consumption_timestamp_is_immutable():
    reg = _registry_with_frozen_family()
    reg.register_oos_window("fam", "w1", oos_generation=1)
    reg.consume_oos_window("fam", "w1", at="2026-01-01T00:00:00Z")
    reg.consume_oos_window("fam", "w1", at="2026-12-31T00:00:00Z")
    win = reg.get_oos_window("fam", "w1")
    assert win.oos_consumed_at == "2026-01-01T00:00:00Z"
    assert reg.oos_is_untouched("fam", "w1") is False


def test_repeat_registration_does_not_reset_consumption():
    reg = _registry_with_frozen_family()
    reg.register_oos_window("fam", "w1", oos_generation=1)
    reg.consume_oos_window("fam", "w1")
    reg.register_oos_window("fam", "w1", oos_generation=1)
    assert reg.oos_is_untouched("fam", "w1") is False


def test_invalid_terminal_status_rejected():
    reg = _registry_with_frozen_family()
    with pytest.raises(ValueError):
        reg.record_trial("fam", "t1", config_hash="cfg1", result_payload={"x": 1},
                         terminal_status="PENDING")
