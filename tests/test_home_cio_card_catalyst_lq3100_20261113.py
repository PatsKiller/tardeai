"""LQ-20261113-3100 (A06): a card with no catalyst event says why, with the synopsis as-of. Synthetic fixtures only."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import test_home_cio_card_20261108 as base  # noqa: E402
from lib import home_cio_card as h  # noqa: E402


def _card(mutate=None):
    sc = copy.deepcopy(base.SC)
    if mutate:
        mutate(sc["cio_brief"]["synopsis"])
    return base._build(sc=sc)["card"]


def test_event_present_has_no_state():
    c = _card()
    assert c["catalyst"]["event"] == "Consumer Price Index"
    assert c["catalyst_state"] is None


def test_every_event_passed_is_none_with_reason_and_as_of():
    c = _card(lambda s: s["this_week"].update(macro=[{"date": "2031-03-01", "event": "Old print", "time_et": "08:30"}]))
    assert c["catalyst"] is None
    assert c["catalyst_state"]["state"] == "NONE"
    assert c["catalyst_state"]["reason"] and c["catalyst_state"]["as_of"] == base.SYN_AT


def test_empty_calendar_is_none():
    c = _card(lambda s: s["this_week"].update(macro=[]))
    assert c["catalyst_state"]["state"] == "NONE"


def test_missing_calendar_is_unknown_not_none():
    c = _card(lambda s: s["this_week"].pop("macro"))
    assert c["catalyst"] is None
    assert c["catalyst_state"]["state"] == "UNKNOWN"
    assert "macro" in c["catalyst_state"]["reason"]


def test_synopsis_without_as_of_is_unknown_even_with_events():
    # item() refuses a record without provenance, so the catalyst is None; that must not read as "none scheduled".
    c = _card(lambda s: s.update(as_of=None))
    if c["catalyst"] is None:
        assert c["catalyst_state"]["state"] == "UNKNOWN"


def test_no_synopsis_is_unknown():
    assert h._catalyst_state(None, None)["state"] == "UNKNOWN"
    assert h._catalyst_state({}, None)["reason"]


# ----------------------------------------------------------------- LQ-20261113-3100-r1 (REVIEW-3104 C1, C2, M2)
import pytest  # noqa: E402


def _macro(rows):
    return lambda s: s["this_week"].update(macro=rows)


@pytest.mark.parametrize("rows", [
    [{"date": "2031-03-01", "time_et": "08:30"}],                 # rows with no event
    ["CPI Nov 18"],                                               # non-mapping rows
    [{"event": "CPI", "date": "Nov 18"}],                         # no ISO date
    [{"event": "CPI"}],                                           # no date at all
], ids=["no-event", "non-mapping", "non-iso-date", "no-date"])
def test_rows_present_but_none_usable_is_unknown_never_none(rows):
    c = _card(_macro(rows))
    assert c["catalyst"] is None
    st = c["catalyst_state"]
    assert st["state"] == "UNKNOWN" and "could not be read" in st["reason"] and st["as_of"] == base.SYN_AT
    assert f"{len(rows)} of {len(rows)}" in st["reason"]


def test_one_unreadable_row_among_past_events_is_still_unknown():
    c = _card(_macro([{"date": "2031-03-01", "event": "Old print", "time_et": "08:30"}, "junk"]))
    assert c["catalyst_state"]["state"] == "UNKNOWN" and "1 of 2" in c["catalyst_state"]["reason"]


def _stale(**fr):
    sc = copy.deepcopy(base.SC)
    sc["freshness"].update(fr)
    sc["cio_brief"]["synopsis"]["this_week"]["macro"] = []
    return base._build(sc=sc)["card"]


@pytest.mark.parametrize("fr", [{"stale": True, "age_seconds": 36 * 3600}, {"window_current": False}, {"stale": True}])
def test_stale_synopsis_empty_calendar_is_unknown_not_none(fr):
    st = _stale(**fr)["catalyst_state"]
    assert st["state"] == "UNKNOWN" and "synopsis is" in st["reason"] and st["as_of"] == base.SYN_AT


def test_stale_synopsis_names_its_age():
    assert "36" in _stale(stale=True, age_seconds=36 * 3600)["catalyst_state"]["reason"]


def test_fresh_empty_calendar_is_none():
    assert _stale()["catalyst_state"]["state"] == "NONE"


def test_stale_synopsis_all_past_events_is_unknown():
    sc = copy.deepcopy(base.SC)
    sc["freshness"]["stale"] = True
    sc["cio_brief"]["synopsis"]["this_week"]["macro"] = [{"date": "2031-03-01", "event": "Old", "time_et": "08:30"}]
    assert base._build(sc=sc)["card"]["catalyst_state"]["state"] == "UNKNOWN"


def test_non_iso_date_is_not_a_future_event():
    # "Nov 18" > "2026-11-16" as text; it must not be drawn as the next catalyst.
    c = _card(_macro([{"event": "CPI", "date": "Nov 18", "time_et": "08:30"}]))
    assert c["catalyst"] is None
    assert h._iso_date("Nov 18") is None and h._iso_date("2026-11-18") == "2026-11-18"
    assert all(x.get("date") != "Nov 18" for x in c["this_week"])
