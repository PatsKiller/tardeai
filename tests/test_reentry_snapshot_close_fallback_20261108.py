"""LQ-20261107-1240: stopped-out cards fall back to the repricer snapshot's last close when market_quotes has none."""
import json
from datetime import datetime, timezone

from scripts.lib.market_risk import book_precision as bp

SUN = datetime(2032, 3, 7, 22, 0, tzinfo=timezone.utc)  # a Sunday


def _write(tmp_path, tickers):
    p = tmp_path / "ticker_snapshot_latest.json"
    p.write_text(json.dumps({"_meta": {}, "tickers": tickers}))
    return p


def test_fallback_labels_last_closed_session_and_skips_bad_prices(tmp_path):
    p = _write(tmp_path, {
        "AAA": {"fetched_at": "2032-03-07T16:45:13", "quote": {"price": 10.5, "source": "finviz_elite"}},
        "BBB": {"fetched_at": "2032-03-07T16:45:13", "quote": {}},
        "CCC": {"fetched_at": "2032-03-07T16:45:13", "quote": {"price": 0}},
        "DDD": {"fetched_at": "2032-03-07T16:45:13", "quote": {"price": True}},
    })
    out = bp.snapshot_close_quotes(["AAA", "BBB", "CCC", "DDD", "ZZZ"], now=SUN, path=p)
    assert set(out) == {"AAA"}
    q = out["AAA"]
    assert q["status"] == "available" and q["price"] == 10.5
    assert q["source"] == "ticker_snapshot:finviz_elite" and q["session"] == "last_close"
    assert q["session_date"] == "2032-03-05"  # the Friday before
    assert q["as_of"] == "2032-03-07T21:45:13Z"  # naive wall-clock is America/New_York (EST in March 2032 before the 14th)


def test_missing_or_corrupt_file_is_empty_not_an_error(tmp_path):
    assert bp.snapshot_close_quotes(["AAA"], now=SUN, path=tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert bp.snapshot_close_quotes(["AAA"], now=SUN, path=bad) == {}


def test_display_quote_computes_pct_vs_exit_from_the_fallback(tmp_path):
    p = _write(tmp_path, {"AAA": {"fetched_at": "2032-03-07T16:45:13", "quote": {"price": 11.0}}})
    q = bp.snapshot_close_quotes(["AAA"], now=SUN, path=p)["AAA"]
    d = bp.reentry_display_quote(q, exit_price=10.0, sma20=None)
    assert round(d["pct_vs_exit"], 2) == 10.0
