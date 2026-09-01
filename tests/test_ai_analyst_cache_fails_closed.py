"""A failed AI analyst run must never destroy the last good analysis.

Cause (2026-09-01): all seven ai_*.json caches under
data/portfolios/state were overwritten between 07:32 and 07:33 with
    {"text": "Analysis unavailable - all LLMs failed"}
destroying real analyses from 2026-08-11. `_save_cache` wrote whatever string it
was handed, so an LLM outage was persisted as though it were the analysis. Each
subsequent daily run destroyed another copy.

These tests fail against the pre-fix `_save_cache` (which wrote unconditionally)
and pass against the fail-closed version.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

paa = pytest.importorskip("portfolio_ai_analyst")


GOOD = "Okay, here is an analysis of the bond allocation strategy for the Rollover IRA..."


def _write_good(tmp_path, key="bond_strategy"):
    paa._save_cache(tmp_path, key, GOOD)
    return tmp_path / f"ai_{key}.json"


@pytest.mark.parametrize("failure_text", [
    "Analysis unavailable - all LLMs failed",
    "Analysis unavailable - LLM returned empty",
    "LLM error: connection refused",
    "Analysis error: HTTPError 503",
    "",
    "   ",
    None,
])
def test_failure_never_overwrites_good_analysis(tmp_path, failure_text):
    """The load-bearing assertion: good content survives a failed run."""
    path = _write_good(tmp_path)
    assert json.loads(path.read_text())["text"] == GOOD

    paa._save_cache(tmp_path, "bond_strategy", failure_text)

    after = json.loads(path.read_text())
    assert after["text"] == GOOD, (
        f"failed run with {failure_text!r} destroyed the cached analysis - "
        "this is the 2026-09-01 data-loss defect"
    )


def test_failure_is_recorded_in_band_not_silently_dropped():
    """Preserving must not hide the outage: the failure is stamped beside the text."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        path = _write_good(tmp_path)
        paa._save_cache(tmp_path, "bond_strategy", "Analysis unavailable - all LLMs failed")
        after = json.loads(path.read_text())
        assert after.get("stale_since_failure") is True
        assert "last_failure_ts" in after
        assert "all LLMs failed" in after.get("last_failure_text", "")


def test_good_analysis_still_overwrites_a_previous_failure(tmp_path):
    """Fail-closed must not become write-once: a real analysis always lands."""
    paa._save_cache(tmp_path, "v_strategy", "Analysis unavailable - all LLMs failed")
    paa._save_cache(tmp_path, "v_strategy", GOOD)
    after = json.loads((tmp_path / "ai_v_strategy.json").read_text())
    assert after["text"] == GOOD
    assert not after.get("stale_since_failure")


def test_failure_writes_normally_when_there_is_nothing_to_protect(tmp_path):
    """With no prior good content the sentinel is still recorded - no crash, no silence."""
    paa._save_cache(tmp_path, "deep_holdings", "Analysis unavailable - all LLMs failed")
    after = json.loads((tmp_path / "ai_deep_holdings.json").read_text())
    assert "Analysis unavailable" in after["text"]


def test_is_failure_text_classifies_the_real_sentinels():
    assert paa._is_failure_text("Analysis unavailable - all LLMs failed")
    assert paa._is_failure_text("LLM error: boom")
    assert paa._is_failure_text("Analysis error: boom")
    assert paa._is_failure_text("")
    assert paa._is_failure_text(None)
    assert not paa._is_failure_text(GOOD)
    # A genuine analysis that merely mentions failure must not be misclassified.
    assert not paa._is_failure_text(
        "The bond sleeve is unavailable for rebalancing until settlement clears.")
