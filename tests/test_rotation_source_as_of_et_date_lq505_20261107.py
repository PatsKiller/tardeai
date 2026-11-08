"""LQ-20261107-505 ROTATION_SOURCE_AS_OF_ET_DATE: /v3/rotation read "Source as of Nov 8" at 20:00 ET on Nov 7."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.rotation_publication import project_summary  # noqa: E402

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)  # 20:00 EST, Sat 2026-11-07 (DST ended Nov 1)


def _publish(position_stamp, account_stamp):
    state = {"state": "LIVE", "account_state": {"contract_version": "AccountState@v1", "state": "LIVE",
             "state_as_of": account_stamp, "last_sync_at": account_stamp, "classified_at": account_stamp,
             "sync_window_hours": 24}}
    doc = {"as_of": account_stamp, "holdings": [{"symbol": "V", "account_key": "synthetic_acct",
           "broker_position_as_of": position_stamp, "market_value": 100}],
           "account_summaries": {"synthetic_acct": state}}
    out = project_summary({"ok": True, "generated_at": NOW.isoformat(), "research_rotation_ideas": []}, doc, now=NOW)
    return out["publication"]


def test_utc_dated_date_only_source_is_emitted_as_the_et_market_date():
    pub = _publish("2026-11-08", "2026-11-08T00:00:00+00:00")
    assert pub["source_as_of"] == "2026-11-07T00:00:00Z", pub
    assert pub["newest_known_source_as_of"] == "2026-11-07T00:00:00Z"
    assert pub["accounts"][0]["source_as_of"] == "2026-11-07T00:00:00Z"


def test_a_date_that_is_today_in_et_is_not_changed():
    assert _publish("2026-11-07", "2026-11-07T00:00:00+00:00")["source_as_of"] == "2026-11-07T00:00:00Z"


def test_a_real_instant_is_never_rewritten():
    stamp = "2026-11-08T00:30:00+00:00"
    pub = _publish("2026-11-07", stamp)
    assert pub["accounts"][0]["source_as_of"] == "2026-11-08T00:30:00Z"
    assert pub["newest_known_source_as_of"] == "2026-11-08T00:30:00Z"
