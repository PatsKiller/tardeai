"""A.1 crontab retarget is exact-line, never silent no-op."""
from scripts.ops_retarget_peak_cron import REPLACEMENTS, patch


def test_patch_all_known_peak_lines():
    original = "\n".join(old for old, _new in REPLACEMENTS) + "\n"
    updated, found, missing = patch(original)
    assert missing == []
    assert len(found) == len(REPLACEMENTS)
    assert "RETARGETED_OFFPEAK" in updated
    assert "0 2 * * *" not in updated
    assert "0 21 * * *" not in updated or "was 21:00" in updated
    assert "hermes-autonomous-loop" not in updated
    assert "premarket_4am" not in updated
