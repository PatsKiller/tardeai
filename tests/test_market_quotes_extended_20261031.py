"""Extended-session quotes for the Market Risk Engine (scripts/market_quotes_extended.py, P1-T4). Hermetic."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import scripts.market_quotes_extended as mqe
from scripts.lib.market_risk.reader import EXTENDED_SOURCE, quote_session

ET = ZoneInfo("America/New_York")
FX = Path(__file__).parent / "fixtures" / "market_quotes_extended" / "bars_20261029_20261030.json"


def _bars():
    return json.loads(FX.read_text())["bars"]


def test_after_hours_row_uses_the_regular_close_and_is_knowable_only_at_bar_end():
    rows = mqe.rows_from_bars(_bars(), mqe.load_config(), now=datetime(2026, 10, 29, 18, 15, tzinfo=ET))
    by = {r["symbol"]: r for r in rows}
    assert by["INTC"]["_session"] == "afterhours"
    assert by["INTC"]["prev_close"] == 92.1
    assert by["INTC"]["day_change_pct"] < -15  # the INTC after-hours collapse
    assert by["QQQ"]["fetched_at"].isoformat() == "2026-10-29T21:00:00+00:00"  # 16:45 bar, knowable 17:00 ET
    assert "SPY" not in by  # newest SPY bar is regular-session: nothing to write


def test_premarket_row_and_no_lookahead():
    cfg = mqe.load_config()
    early = mqe.rows_from_bars(_bars(), cfg, now=datetime(2026, 10, 30, 8, 10, tzinfo=ET))
    assert all(r["fetched_at"] <= datetime(2026, 10, 30, 8, 10, tzinfo=ET) for r in early)
    late = {r["symbol"]: r for r in mqe.rows_from_bars(_bars(), cfg, now=datetime(2026, 10, 30, 8, 31, tzinfo=ET))}
    assert (
        late["QQQ"]["_session"] == "premarket" and late["QQQ"]["price"] == 696.88
    )  # 08:15 bar, the last complete at 08:31


def test_no_regular_close_in_window_means_no_row():
    bars = {"QQQ": [b for b in _bars()["QQQ"] if b["t"] != "2026-10-29T19:45:00Z"]}
    assert mqe.rows_from_bars(bars, mqe.load_config(), now=datetime(2026, 10, 29, 18, 15, tzinfo=ET)) == []


def test_dry_run_writes_nothing():
    out = mqe.run(apply=False, bars_json=str(FX), now=datetime(2026, 10, 29, 18, 15, tzinfo=ET))
    assert out["apply"] is False and out["written"] == 0 and out["candidates"] >= 2


class _Cur:
    def __init__(self, seen):
        self.seen, self.executed = seen, []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.seen


class _Conn:
    def __init__(self, cur):
        self.cur, self.committed = cur, False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def test_apply_skips_rows_already_written(monkeypatch):
    now = datetime(2026, 10, 29, 18, 15, tzinfo=ET)
    rows = mqe.rows_from_bars(_bars(), mqe.load_config(), now=now)
    seen = [(r["symbol"], r["fetched_at"]) for r in rows]
    written = []

    def fake_write(cur, rws, *, source):
        written.extend(rws)

        class R:
            rows_accepted = len(rws)

        return R()

    monkeypatch.setattr("lib.writers.market_quotes_writer.write_market_quotes", fake_write)
    out = mqe.run(apply=True, bars_json=str(FX), now=now, conn=_Conn(_Cur(seen)))
    assert out["skipped"] == len(rows) and written == []


def test_reader_labels_only_extended_writer_rows():
    ah = {"source": EXTENDED_SOURCE, "fetched_at": "2026-10-29T22:15:00+00:00"}
    pm = {"source": EXTENDED_SOURCE, "fetched_at": "2026-10-30T12:30:00+00:00"}
    early_regular_producer = {"source": "alpaca", "fetched_at": "2026-10-30T11:15:00+00:00"}  # 07:15 ET cron quote
    assert quote_session(ah) == "afterhours"
    assert quote_session(pm) == "premarket"
    assert quote_session(early_regular_producer) == "regular"
