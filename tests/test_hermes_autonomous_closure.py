"""Tests for Hermes autonomous closure loops (source auto-approval thresholds)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load_auto_approval():
    spec = importlib.util.spec_from_file_location(
        "hermes_source_auto_approval",
        ROOT / "scripts" / "hermes_source_auto_approval.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_core_outcome_proven_auto_activates():
    mod = _load_auto_approval()
    ok, reason = mod._should_activate(
        {"action": "APPROVE_FOR_CORE_ACTIVATION", "score": 70.8, "outcome_proven": True, "source": "google_news:CNBC"},
        use_llm=False,
    )
    assert ok is True
    assert "outcome" in reason or "core" in reason


def test_core_low_score_skipped():
    mod = _load_auto_approval()
    ok, reason = mod._should_activate(
        {"action": "APPROVE_FOR_CORE_ACTIVATION", "score": 55, "outcome_proven": False, "source": "x"},
        use_llm=False,
    )
    assert ok is False


def test_trusted_tier_floor_auto_activates():
    mod = _load_auto_approval()
    ok, reason = mod._should_activate(
        {"action": "REVIEW_FOR_ACTIVATION", "score": 51.5, "source": "google_news:Barchart.com"},
        use_llm=False,
    )
    assert ok is True
    assert "trusted" in reason


def test_trusted_below_floor_skipped():
    mod = _load_auto_approval()
    ok, _ = mod._should_activate(
        {"action": "REVIEW_FOR_ACTIVATION", "score": 48, "source": "barrons"},
        use_llm=False,
    )
    assert ok is False


def test_backlog_priority_rank():
    spec = importlib.util.spec_from_file_location(
        "hermes_backlog_drain", ROOT / "scripts" / "hermes_backlog_drain.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._priority_rank([{"priority": "high"}]) == 0
    assert mod._priority_rank([{"priority": "low"}]) == 2