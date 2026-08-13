"""Unit tests for scripts/llm_content_quality.py — Home briefing fail-closed."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from llm_content_quality import is_valid_prose, extract_prose, quality_report  # noqa: E402


def test_rejects_hash_spam():
    bad = ". **##. **##. **##. **##. **##. **##. **##. **##. **##. **##. **##."
    assert is_valid_prose(bad) is False


def test_rejects_empty_and_short():
    assert is_valid_prose("") is False
    assert is_valid_prose(None) is False
    assert is_valid_prose("too short") is False


def test_accepts_real_prose():
    good = (
        "The portfolio exhibits concentration risk in the top holdings and has "
        "several positions without stop-loss orders. Cash remains elevated; "
        "consider rebalancing into underrepresented sectors while protecting "
        "the largest positions with stops."
    )
    assert is_valid_prose(good) is True


def test_extract_prose_from_json_blob():
    blob = (
        '{"content": "The market is risk-off today with VIX near 16 and '
        'financials weakening. Focus on defense of existing book."}'
    )
    prose = extract_prose(blob)
    assert "risk-off" in prose
    assert is_valid_prose(prose) is True


def test_quality_report_flags_corruption():
    r = quality_report(". **##. **##. **##. **##. **##. **##.")
    assert r["ok"] is False
    assert r["corrupt_marker_hits"] >= 2
