"""LQ-20261113-3082: cio.pages takes the ProductSpec off-hours tier at build time (cadence 3600 / stale 9000 / expiry 14400
outside 09:30-16:15 ET weekdays), so the stored-only reader does not grey 30 min after the last evening build."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cc_products import cio_pages, product_builder
from tests import test_cc_products_cio_pages as base

MARKET = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)      # Thu 13:00 ET
EVENING = datetime(2026, 11, 12, 23, 0, tzinfo=timezone.utc)     # Thu 18:00 ET
SATURDAY = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)    # Sat 12:00 ET
PRE_OPEN = datetime(2026, 11, 12, 14, 29, tzinfo=timezone.utc)   # Thu 09:29 ET
AT_CLOSE = datetime(2026, 11, 12, 21, 15, tzinfo=timezone.utc)   # Thu 16:15 ET (market ended)

FAST = (120, 360, 1800)
OFF = (3600, 9000, 14400)


def _build(tmp_path, now):
    events = []
    hot = base.FakeHot(events)
    store = base.FakeStore(events)
    cio_pages.run_once(connect=lambda: base.FakeConn(events), root=tmp_path, hot=hot, dry_run=False, now=now,
                       builder_sha="abc", store=store, codec=base.FakeCodec, db_query_factory=lambda: None,
                       build_fn=base.build_ok)
    return store.row, hot


@pytest.mark.parametrize("now,want", [(MARKET, FAST), (EVENING, OFF), (SATURDAY, OFF)])
def test_stored_row_carries_the_tier_for_its_build_time(tmp_path, now, want):
    row, _ = _build(tmp_path, now)
    assert (row["next_refresh_at"] - row["built_at"]).total_seconds() == want[0]
    assert (row["stale_after_s"], row["hard_expiry_s"]) == want[1:]


def test_hot_key_ttl_follows_the_off_hours_hard_expiry(tmp_path):
    _, hot = _build(tmp_path, EVENING)
    ex_s = hot.sets[0][2]
    assert 1800 < ex_s <= 14400      # the fixed 1800 s would have dropped the key 30 min after an evening build


def test_market_hours_hot_ttl_is_unchanged(tmp_path):
    _, hot = _build(tmp_path, MARKET)
    assert 0 < hot.sets[0][2] <= 1800


@pytest.mark.parametrize("now", [MARKET, EVENING, SATURDAY])
def test_one_definition_of_the_tier_matches_product_builder(now):
    lim = cio_pages.limits_for(now)
    if product_builder.is_market_hours(now):
        want = {"cadence_s": cio_pages.CADENCE_S, "stale_after_s": cio_pages.STALE_AFTER_S,
                "hard_expiry_s": cio_pages.HARD_EXPIRY_S}
    else:
        want = dict(product_builder.OFF_HOURS)
    assert lim == {**want, "purge_after_s": cio_pages.PURGE_AFTER_S}
