"""LQ-20261107-74 ROTATION_PUBLICATION_ACCOUNT_ALIAS: a row whose account and account_key spell the account differently."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.rotation_publication import account_summary, project_summary  # noqa: E402

NOW = datetime(2026, 10, 18, 22, tzinfo=timezone.utc)
STAMP = "2026-10-16T22:00:00+00:00"


def _doc(summary_key):
    state = {"state": "LIVE", "account_state": {"contract_version": "AccountState@v1", "state": "LIVE",
             "state_as_of": STAMP, "last_sync_at": STAMP, "classified_at": STAMP, "sync_window_hours": 24}}
    # the exact production shape: account='schwab_roth' (summaries key), account_key='schwab_roth_ira'
    return {"as_of": STAMP, "holdings": [
        {"symbol": "V", "account": "schwab_roth", "account_key": "schwab_roth_ira", "broker_position_as_of_at": STAMP,
         "market_value": 100}], "account_summaries": {summary_key: state}}


def _publish(doc):
    return project_summary({"ok": True, "generated_at": NOW.isoformat(), "research_rotation_ideas": []}, doc, now=NOW)


def test_summary_keyed_by_account_field_is_found():
    # old: summaries.get('schwab_roth_ira') -> None -> missing_account_state -> UNAVAILABLE
    out = _publish(_doc("schwab_roth"))
    assert "missing_account_state" not in str(out["publication"]), out["publication"]
    assert out["publication"]["status"] == "READY"


def test_summary_keyed_by_account_key_still_works():
    assert _publish(_doc("schwab_roth_ira"))["publication"]["status"] == "READY"


def test_no_matching_summary_is_still_unavailable():
    out = _publish(_doc("some_other_account"))
    assert out["publication"]["status"] == "UNAVAILABLE"
    assert "missing_account_state" in str(out["publication"])


def test_account_key_wins_when_both_present():
    s = {"a": {"state": "x"}, "b": {"state": "y"}}
    assert account_summary(s, {"account_key": "b", "account": "a"}) == {"state": "y"}
    assert account_summary(s, {"account_key": "zz", "account": "a"}) == {"state": "x"}
    assert account_summary(s, {"account_key": None, "account": ""}) is None
