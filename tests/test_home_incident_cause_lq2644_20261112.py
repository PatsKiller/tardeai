"""LQ-20261107-2644 (c): an incident card names its cause from the alert's own words, not "cause not recorded"."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import home_incidents as hi  # noqa: E402

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)
CLS = {"data_integrity": {"category": "Data Integrity", "priority": "P1", "owner": "portfolio", "ttl_h": 4, "home_visible": True}}


def row(**kw):
    base = {"incident_id": "i1", "alert_type": "data_integrity", "symbol": None, "first_seen_at": NOW, "last_seen_at": NOW,
            "occurrence_count": 1, "blocks_trading_declared": None, "account_label": None,
            "payload_cause": None, "payload_message": None, "event_text": None}
    base.update(kw)
    return base


def test_cause_line_strips_markup_emoji_and_takes_the_first_line():
    assert hi.cause_line("🚨 *RELEASE NOT REACHED* after promote\n• detail") == "RELEASE NOT REACHED after promote"
    assert hi.cause_line("[DATA_INTEGRITY] 🚨 off its declared scale") == "[DATA_INTEGRITY] 🚨 off its declared scale"


def test_cause_line_is_bounded_and_none_when_unreadable():
    assert len(hi.cause_line("x" * 500)) == hi.CAUSE_MAX
    for bad in (None, "", "   \n  ", 5, "🚨", "**"):
        assert hi.cause_line(bad) is None, bad


def test_chain_registry_then_cause_then_message_then_event_then_unknown():
    r = row(payload_cause="pc", payload_message="msg line", event_text="evt line")
    assert hi.resolve_cause({"cause": "reg"}, r) == ("reg", "registry")
    assert hi.resolve_cause(None, r) == ("pc", "occurrence.cause")
    assert hi.resolve_cause(None, row(payload_message="msg line", event_text="evt")) == ("msg line", "occurrence.message")
    assert hi.resolve_cause(None, row(payload_message="  ", event_text="evt line")) == ("evt line", "alert_events")
    assert hi.resolve_cause(None, row()) == ("UNKNOWN", "none")


def test_shape_carries_the_cause_and_its_source():
    item = hi.shape(row(payload_message="🚨 stored data disagrees with its source\nmore"), CLS, NOW)
    assert item["cause"] == "stored data disagrees with its source" and item["cause_source"] == "occurrence.message"
    item = hi.shape(row(event_text="[DATA_INTEGRITY] a column is off"), CLS, NOW)
    assert item["cause_source"] == "alert_events"


def test_a_cause_is_never_invented_when_nothing_was_recorded():
    item = hi.shape(row(), CLS, NOW)
    assert item["cause"] == "UNKNOWN" and item["cause_source"] == "none"


def test_sql_selects_the_message_and_the_event_text():
    assert "payload_message" in hi.SQL and "event_text" in hi.SQL and "FROM alert_events" in hi.SQL
    assert "SET LOCAL statement_timeout" in hi.SQL  # still bounded, still read-only
    assert "INSERT" not in hi.SQL.upper() and "UPDATE" not in hi.SQL.upper()


def test_event_text_sql_falls_back_cause_then_reason_then_raw_text_within_an_hour_of_first_seen():
    sql = " ".join(hi.SQL.split())
    assert "COALESCE(e.parsed_payload ->> 'cause', e.parsed_payload ->> 'reason', e.raw_text)" in sql
    assert "interval '1 hour'" in sql.lower().replace("1 hours", "1 hour") or "1 hour" in sql.lower()


def test_the_event_lookup_runs_only_when_the_occurrence_has_no_cause_or_message_and_is_bounded_both_sides():
    """LQ-2660 (REVIEW-2652 C1): the alert_events lookup was a correlated subquery run for every open incident."""
    sql = " ".join(hi.SQL.split())
    assert "LEFT JOIN LATERAL" in sql
    assert "COALESCE(btrim(lo.cause), '') = '' AND COALESCE(btrim(lo.message), '') = ''" in sql
    assert "e.created_at >= i.first_seen_at - interval '1 hour'" in sql
    assert "e.created_at <= i.last_seen_at + interval '1 hour'" in sql
    assert "(i.symbol IS NULL OR e.symbol IS NULL OR e.symbol = i.symbol)" in sql
    assert "e.alert_type = i.alert_type" in sql
    assert sql.count("FROM alert_occurrences") == 1  # one latest-occurrence read, not one per field
