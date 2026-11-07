"""LQ-20261107-118: social-sentiment rows name only sources that returned data, flag a saturated page,
and the overnight run skips its second copy when the scheduled lane is fresh. Synthetic data only."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import aegis_overnight as ov  # noqa: E402
import aegis_social_sentiment as ss  # noqa: E402


def _st(n):
    return {"mentions": [{"channel": "stocktwits", "bull_signals": 1, "bear_signals": 0, "title": "t"} for _ in range(n)]}


def test_source_name_lists_only_contributors():
    assert ss.source_name_for({"reddit": 0, "stocktwits": 5, "brave": 0}) == "stocktwits"
    assert ss.source_name_for({"reddit": 2, "stocktwits": 5, "brave": 1}) == "reddit+stocktwits+brave"
    assert ss.source_name_for({}) == "none"
    assert ss.source_name_for(None) == "none"


def test_saturated_page_withholds_spike_and_flags_lower_bound():
    out = ss.normalize_sentiment("TEST", {"mentions": []}, {"mentions": []}, _st(ss.ST_PAGE))
    assert out["stocktwits_saturated"] is True
    assert out["unusual_spike"] is False
    assert out["source_counts"] == {"reddit": 0, "stocktwits": ss.ST_PAGE, "brave": 0}


def test_unsaturated_page_can_still_spike():
    out = ss.normalize_sentiment("TEST", {"mentions": []}, {"mentions": []}, _st(7))
    assert out["stocktwits_saturated"] is False
    assert out["unusual_spike"] is True


def test_no_mentions_still_none():
    assert ss.normalize_sentiment("TEST", {"mentions": []}, {"mentions": []}, _st(0)) is None


NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)


def _rcpt(hours_ago, status="ok"):
    return {"status": status, "ok_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_fresh_lane_receipt_skips_overnight_copy(monkeypatch):
    monkeypatch.delenv("AEGIS_OVERNIGHT_FORCE_SOCIAL", raising=False)
    assert ov._social_lane_is_fresh(now=NOW, receipt=_rcpt(5)) is True


def test_stale_failed_or_unknown_receipt_does_not_skip(monkeypatch):
    monkeypatch.delenv("AEGIS_OVERNIGHT_FORCE_SOCIAL", raising=False)
    assert ov._social_lane_is_fresh(now=NOW, receipt=_rcpt(30)) is False
    assert ov._social_lane_is_fresh(now=NOW, receipt=_rcpt(1, status="fail")) is False
    assert ov._social_lane_is_fresh(now=NOW, receipt={"status": "ok"}) is False
    assert ov._social_lane_is_fresh(now=NOW, receipt=_rcpt(-3)) is False  # future stamp is not evidence


def test_force_env_overrides(monkeypatch):
    monkeypatch.setenv("AEGIS_OVERNIGHT_FORCE_SOCIAL", "1")
    assert ov._social_lane_is_fresh(now=NOW, receipt=_rcpt(1)) is False
