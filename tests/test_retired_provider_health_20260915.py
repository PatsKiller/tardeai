"""R-02 (2026-09-15): a retired provider's old 401 is not 'operator must rotate the key'."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import retired_providers as rp  # noqa: E402


def test_finnhub_is_retired_on_2026_09_13():
    assert rp.is_retired("finnhub") and rp.retired_on("finnhub") == "2026-09-13"


def test_the_failure_written_at_retirement_is_history():
    last_failure = datetime(2026, 9, 13, 20, 3, 38, tzinfo=timezone.utc)
    assert rp.called_since_retirement("finnhub", datetime(2026, 7, 27, tzinfo=timezone.utc), last_failure) is False


def test_activity_after_the_retirement_day_means_a_caller_still_reaches_it():
    assert rp.called_since_retirement("finnhub", None, "2026-09-15T11:00:00+00:00") is True


def test_the_health_agent_skips_retired_sources_before_the_auth_classification():
    src = (ROOT / "scripts" / "health_agent.py").read_text()
    i_skip = src.index("if is_retired(src):")
    i_auth = src.index('"data_source_auth_failed", "critical"')
    assert i_skip < i_auth and "retired_provider_still_called" in src
