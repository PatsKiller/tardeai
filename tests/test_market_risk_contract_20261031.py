from datetime import datetime, timezone

import pytest

from scripts.lib.market_risk import contract as c


def test_unknown_is_not_zero():
    o = c.unknown("breadth", datetime(2026, 10, 29, 20, tzinfo=timezone.utc), "no store yet")
    assert o.state == "UNKNOWN" and o.score is None and o.reason_unknown


def test_behavior_fields_refused():
    with pytest.raises(ValueError):
        c.assert_no_behavior_fields({"drivers": [{"symbol": "QQQ", "stop_price": 1.0}]})
    c.assert_no_behavior_fields({"drivers": [{"symbol": "QQQ", "stop_distance_pct": 4.1}]})


def test_categories_are_nine():
    assert len(c.CATEGORIES) == 9 and len(set(c.CATEGORIES)) == 9
