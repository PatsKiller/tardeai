"""eod_consolidated_close_sync: which IEX-derived closes get the consolidated close. Pure, offline."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import eod_consolidated_close_sync as sync  # noqa: E402

COVERS = ["scripts/eod_consolidated_close_sync.py"]


def test_only_disagreeing_quote_derived_closes_are_replaced():
    stored = [("AAPL", "market_quotes", 332.55), ("MNSX", "market_quotes", 24.36),
              ("HPE", "finviz", 55.0), ("XLI", "portfolio_repricer", 7.51)]
    ref = {"AAPL": 332.27, "MNSX": 20.63, "HPE": 62.09, "XLI": 172.37}
    plan = sync.plan_replacements(stored, ref)
    assert [r["symbol"] for r in plan["replace"]] == ["MNSX"]
    assert plan["unchanged"] == 1
    # other sources are not this lane's to rewrite
    assert all(r["symbol"] not in ("HPE", "XLI") for r in plan["replace"] + plan["held_back"])


def test_a_huge_disagreement_is_held_back_for_quarantine_not_synced():
    plan = sync.plan_replacements([("ADTX", "market_quotes", 0.0093), ("ODD", "market_quotes", 3.38)],
                                  {"ADTX": 0.0070, "ODD": 0.4531})
    assert [r["symbol"] for r in plan["replace"]] == ["ADTX"]
    assert [r["symbol"] for r in plan["held_back"]] == ["ODD"]


def test_no_reference_is_counted_and_left_alone():
    plan = sync.plan_replacements([("DELIST", "market_quotes", 1.0)], {"DELIST": None})
    assert plan["no_reference"] == 1 and plan["replace"] == [] and plan["held_back"] == []


def test_default_session_is_today_after_the_close_and_the_last_weekday_before():
    after_close_mon = datetime(2026, 9, 14, 21, 30, tzinfo=timezone.utc)   # 17:30 ET Monday
    before_close_mon = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)   # 09:00 ET Monday
    saturday = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
    assert sync.default_session(after_close_mon).isoformat() == "2026-09-14"
    assert sync.default_session(before_close_mon).isoformat() == "2026-09-11"
    assert sync.default_session(saturday).isoformat() == "2026-09-11"


# The 2026-11-09 oneshot was killed at TimeoutStartSec=1200 after asking Alpaca once per symbol.
_INCIDENT_SYMBOLS = 5528


def test_one_request_per_symbol_does_not_fit_the_unit_timeout_and_a_chunk_does():
    from alpaca_throttle import MIN_INTERVAL

    per_symbol = sync.reference_request_count(_INCIDENT_SYMBOLS, 1) * MIN_INTERVAL
    batched = sync.reference_request_count(_INCIDENT_SYMBOLS, sync.CHUNK_SYMBOLS) * MIN_INTERVAL
    assert per_symbol > sync.UNIT_TIMEOUT_S
    assert batched < sync.UNIT_TIMEOUT_S
    assert sync.DEADLINE_S < sync.UNIT_TIMEOUT_S
    assert sync.reference_request_count(_INCIDENT_SYMBOLS, sync.CHUNK_SYMBOLS) == 56


def test_production_read_uses_one_request_per_chunk_and_the_et_session_close():
    symbols = [f"S{i:04d}" for i in range(250)]
    seen = []

    def fetch_many(chunk, session, *, today):
        seen.append(list(chunk))
        assert session.isoformat() == "2026-11-09"
        assert today.isoformat() == "2026-11-09"
        return {s: [{"t": "2026-11-09T05:00:00Z", "c": 3.5}, {"t": "2026-11-06T05:00:00Z", "c": 1.0}] for s in chunk}

    out = sync._alpaca_closes(
        symbols, date(2026, 11, 9), fetch_many=fetch_many,
        chunk_size=100, deadline_s=10_000, clock=lambda: 0.0, today=date(2026, 11, 9),
    )
    assert [len(c) for c in seen] == [100, 100, 50]
    assert out.requests == 3 and out.deadline_hit is False and out.errors == 0
    assert all(out[s] == 3.5 for s in symbols)


def test_deadline_stops_before_the_unit_kills_the_process_and_keeps_finished_chunks():
    symbols = [f"S{i:04d}" for i in range(350)]
    now = {"t": 0.0}

    def clock():
        return now["t"]

    def fetch_many(chunk, session, *, today):
        now["t"] += 400
        return {s: [{"t": "2026-11-09T05:00:00Z", "c": 2.0}] for s in chunk}

    out = sync._alpaca_closes(
        symbols, date(2026, 11, 9), fetch_many=fetch_many,
        chunk_size=100, deadline_s=900, clock=clock, today=date(2026, 11, 9),
    )
    assert out.requests == 3 and out.deadline_hit is True and out.incomplete is True
    assert sum(1 for s in symbols if out[s] == 2.0) == 300
    assert sum(1 for s in symbols if out[s] is None) == 50


def test_one_failed_chunk_does_not_drop_the_chunks_around_it():
    symbols = [f"S{i:04d}" for i in range(250)]
    calls = {"n": 0}

    def fetch_many(chunk, session, *, today):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("alpaca 429")
        return {s: [{"t": "2026-11-09T05:00:00Z", "c": 4.0}] for s in chunk}

    out = sync._alpaca_closes(
        symbols, date(2026, 11, 9), fetch_many=fetch_many,
        chunk_size=100, deadline_s=10_000, clock=lambda: 0.0, today=date(2026, 11, 9),
    )
    assert out.errors == 1 and out.requests == 2 and out.incomplete is True
    assert all(out[s] == 4.0 for s in symbols[:100] + symbols[200:])
    assert all(out[s] is None for s in symbols[100:200])


class _Body:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_chunk_read_is_one_multi_symbol_bars_request_not_one_url_per_symbol():
    seen = []

    def urlopen(req, timeout):
        seen.append((req.full_url, timeout, req.get_header("Apca-api-key-id")))
        return _Body(
            b'{"bars":{"AAA":[{"t":"2026-11-09T05:00:00Z","c":1.5}],'
            b'"BBB":[{"t":"2026-11-09T05:00:00Z","c":2.5}]}}'
        )

    bars = sync._fetch_alpaca_chunk(
        ["AAA", "BBB"], "2026-11-04T00:00:00Z", "2026-11-09T21:00:00Z",
        urlopen=urlopen, acquire=lambda: seen.append("acquire"), keys=("kid", "sec"),
    )
    urls = [row[0] for row in seen if isinstance(row, tuple)]
    assert urls and urls[0].startswith("https://data.alpaca.markets/v2/stocks/bars?")
    assert "/stocks/AAA/" not in urls[0]
    assert "timeframe=1Day" in urls[0] and "adjustment=split" in urls[0]
    assert "AAA" in urls[0] and "BBB" in urls[0]
    assert seen[1][1] == sync.ALPACA_CHUNK_TIMEOUT_S
    assert seen[1][2] == "kid"
    assert bars["AAA"][0]["c"] == 1.5 and bars["BBB"][0]["c"] == 2.5
    assert seen.count("acquire") == 1


def test_chunk_read_follows_one_page_token_and_stops():
    pages = {"n": 0}

    def urlopen(req, timeout):
        pages["n"] += 1
        if pages["n"] == 1:
            body = b'{"bars":{"AAA":[{"t":"2026-11-08T05:00:00Z","c":1}]},"next_page_token":"p2"}'
        else:
            assert "page_token=p2" in req.full_url
            body = b'{"bars":{"AAA":[{"t":"2026-11-09T05:00:00Z","c":2}]}}'
        return _Body(body)

    bars = sync._fetch_alpaca_chunk(
        ["AAA"], "2026-11-04T00:00:00Z", "2026-11-09T21:00:00Z",
        urlopen=urlopen, acquire=lambda: None, keys=("kid", "sec"),
    )
    assert pages["n"] == 2
    assert [b["c"] for b in bars["AAA"]] == [1, 2]
