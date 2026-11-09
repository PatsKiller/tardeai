"""LQ-20261107-1610 — one VIX for the header tile and the CIO market-risk card, dated by its observation.

ANCHOR: VIX_HEADLINE_ONE_SOURCE_20261109

The header took the scanner run's VIX (Yahoo-first chain) stamped with the RUN's clock, and the card took the
classifier snapshot's input stamped with its INSERT time. Both now read ``vix_complex.complex_record`` through
``vix_headline``. Synthetic rows only; no database.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import cio_truth  # noqa: E402
from lib import vix_headline as vh  # noqa: E402

NOW = datetime(2026, 1, 12, 17, 0, tzinfo=timezone.utc)  # a synthetic Monday, 12:00 ET


def _db(quotes=(), fred=()):
    """A db_query that answers the two reads vix_complex makes, and records every other query."""
    seen = []

    def q(sql, params=None, fetch="all"):
        seen.append(sql)
        if "market_quotes_extended" in sql:
            return [dict(r) for r in quotes]
        if "fred_economic_series" in sql:
            return [dict(r) for r in fred]
        return []
    q.seen = seen
    return q


def _quote(price, bar_end, basis="none_level_only_no_dated_reference_in_payload", feed="schwab", sym="$VIX"):
    return {"symbol": sym, "price": price, "session": "overnight", "session_date": bar_end.date(),
            "bar_end": bar_end, "reference_basis": basis, "feed": feed}


def test_a_schwab_print_is_the_headline_with_its_own_zoned_clock():
    h = vh.vix_headline(db_query=_db([_quote(21.5, datetime(2026, 1, 12, 8, 45, tzinfo=timezone.utc))]), now=NOW)
    assert h["vix"] == 21.5 and h["vix_source"] == "market_quotes_extended:schwab:$VIX"
    assert h["vix_observation_time"] == "2026-01-12T08:45:00+00:00" and h["vix_age_hours"] == 8.25
    assert (h["vix_state"], h["vix_stale"], h["vix_stale_after_hours"]) == ("FRESH", False, 26.0)


def test_a_carried_print_is_dated_by_the_close_it_carries_not_by_the_row():
    # Friday's close carried into a Sunday-night row: the row is recent, the number is not.
    row = _quote(25.5, datetime(2026, 1, 12, 1, 0, tzinfo=timezone.utc),
                 basis="schwab_index_level_carried_print_2026-01-09")
    h = vh.vix_headline(db_query=_db([row]), now=NOW)
    assert h["vix"] == 25.5 and h["vix_observation_time"].startswith("2026-01-09T16:00:00")
    assert h["vix_state"] == "STALE" and h["vix_stale"] is True and "carried print from 2026-01-09" in h["vix_reason"]


def test_a_fred_close_is_dated_at_settlement_in_et_and_named():
    h = vh.vix_headline(db_query=_db(fred=[{"series_id": "VIXCLS", "observation_date": date(2026, 1, 9),
                                            "value": 19.0}]), now=NOW)
    assert h["vix"] == 19.0 and h["vix_source"] == "fred_economic_series:VIXCLS"
    assert h["vix_observation_time"] == "2026-01-09T16:15:00-05:00" and h["vix_state"] == "STALE"


def test_a_banned_feed_is_refused_and_nothing_else_is_substituted():
    row = _quote(30.0, datetime(2026, 1, 12, 16, 0, tzinfo=timezone.utc), feed="yahoo_finance")
    h = vh.vix_headline(db_query=_db([row]), now=NOW)
    assert h["vix"] is None and h["vix_state"] == "UNAVAILABLE"
    assert "vix_close_banned_source:yahoo_finance" in h["vix_reason"]


def test_no_row_is_unavailable_never_zero_and_a_read_failure_is_named():
    h = vh.vix_headline(db_query=_db(), now=NOW)
    assert (h["vix"], h["vix_state"]) == (None, "UNAVAILABLE") and "vix_close_unavailable" in h["vix_reason"]

    def boom(*a, **k):
        raise RuntimeError("synthetic")
    h = vh.vix_headline(conn=type("C", (), {"cursor": boom, "rollback": lambda s: None})(), now=NOW)
    assert h["vix"] is None and h["vix_state"] == "UNAVAILABLE" and "RuntimeError" in h["vix_reason"]


def test_a_future_or_unzoned_clock_is_undated_not_fresh():
    rec = {"vix": {"value": 20.0, "source": "x", "as_of": "2026-01-12T09:00:00"}, "missing": []}
    assert vh.from_record(rec, now=NOW, stale_after_hours=26)["vix_state"] == "UNDATED"
    rec["vix"]["as_of"] = "2026-01-13T09:00:00+00:00"
    out = vh.from_record(rec, now=NOW, stale_after_hours=26)
    assert out["vix_state"] == "UNDATED" and out["vix_observation_time"] is None


def test_the_cio_card_shows_the_headline_vix_not_the_classifier_snapshot_input():
    """Fail-before: regime_for returned the snapshot's vix (99.0) dated by the row's insert time."""
    db = _db([_quote(21.5, datetime(2026, 1, 12, 8, 45, tzinfo=timezone.utc))])
    projection = {"regime": {"regime_label": "risk_off", "vix": 99.0, "snapshot_id": "RS_SYN",
                             "generated_at": "2026-01-12T10:51:00+00:00", "confidence": 0.6}}
    card = cio_truth.regime_for(db_query=db, projection=projection, now=NOW)
    header = vh.vix_headline(db_query=db, now=NOW)
    assert card["vix"] == header["vix"] == 21.5
    assert card["vix_as_of"] == header["vix_observation_time"]
    assert card["vix_source"] == header["vix_source"] and card["vix_state"] == "FRESH"
    assert card["classifier_vix"] == 99.0  # the classifier's own input stays traceable, never shown as the VIX
