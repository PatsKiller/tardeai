"""Extended-session prints for the Market Risk Engine (scripts/market_quotes_extended.py, P1-T4). Hermetic: saved
public SIP bars (10-29 15:50 -> 10-30 09:30 ET for QQQ/INTC/SPY), fake cursors, fake HTTP."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import scripts.market_quotes_extended as mqe
from scripts.lib.data_broker import latest_quote
from scripts.lib.writers import market_quotes_extended_writer as w

ET = ZoneInfo("America/New_York")
FX = Path(__file__).parent / "fixtures" / "market_quotes_extended" / "sip_20261029_20261030.json"
CFG = mqe.load_config()


def _fx():
    d = json.loads(FX.read_text())
    return d["bars"], d["daily"]


def _rows(now):
    bars, daily = _fx()
    return {r["symbol"]: r for r in mqe.rows_from_bars(bars, daily, CFG, now=now)}


def test_after_hours_uses_the_official_daily_close_and_labels_its_basis():
    r = _rows(datetime(2026, 10, 29, 18, 15, tzinfo=ET))
    assert r["QQQ"]["session"] == "afterhours" and r["QQQ"]["reference_close"] == 715.34
    assert r["QQQ"]["reference_date"] == date(2026, 10, 29) and r["QQQ"]["reference_basis"] == CFG["reference_basis"]
    assert r["INTC"]["change_pct"] < -15


def test_bar_is_known_only_after_it_ends():
    r = _rows(datetime(2026, 10, 29, 18, 2, tzinfo=ET))
    assert r["QQQ"]["bar_end"] <= datetime(2026, 10, 29, 18, 2, tzinfo=ET)


def test_premarket_references_the_previous_session_close():
    r = _rows(datetime(2026, 10, 30, 8, 31, tzinfo=ET))
    assert r["QQQ"]["session"] == "premarket" and r["QQQ"]["reference_date"] == date(2026, 10, 29)


def test_sessions_are_bounded_and_trading_days_only():
    assert mqe.session_of(datetime(2026, 10, 29, 20, 5, tzinfo=ET), CFG) is None  # overnight
    assert mqe.session_of(datetime(2026, 10, 30, 3, 55, tzinfo=ET), CFG) is None
    assert mqe.session_of(datetime(2026, 10, 31, 9, 0, tzinfo=ET), CFG) is None  # Saturday
    assert mqe.session_of(datetime(2026, 11, 26, 8, 0, tzinfo=ET), CFG) is None  # Thanksgiving
    assert mqe.session_of(datetime(2026, 11, 27, 13, 5, tzinfo=ET), CFG) == "afterhours"  # early close 13:00
    assert mqe.session_of(datetime(2026, 11, 27, 12, 55, tzinfo=ET), CFG) is None
    assert mqe.session_of(datetime(2026, 10, 29, 16, 0, tzinfo=ET), CFG) == "afterhours"


def test_early_close_reference_uses_that_day_close():
    # a bar at 13:05 on the early-close day references that day's close (it closed at 13:00)
    bars = {"QQQ": [{"t": "2026-11-27T18:05:00Z", "c": 100.0, "v": 1}]}
    daily = {"QQQ": [{"t": "2026-11-25T05:00:00Z", "c": 98.0}, {"t": "2026-11-27T05:00:00Z", "c": 99.0}]}
    rows = mqe.rows_from_bars(bars, daily, CFG, now=datetime(2026, 11, 27, 14, 0, tzinfo=ET))
    assert rows and rows[0]["reference_date"] == date(2026, 11, 27) and rows[0]["reference_close"] == 99.0


def test_lookback_starts_at_the_previous_nyse_session():
    assert mqe.previous_session(date(2026, 11, 2)) == date(2026, 10, 30)  # Monday -> Friday
    assert mqe.previous_session(date(2026, 11, 27)) == date(2026, 11, 25)  # day after Thanksgiving


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body or {}

    def json(self):
        return self._b


def test_fetch_ends_16_minutes_before_now_and_backs_off_on_429():
    calls, slept = [], []
    seq = [_Resp(429), _Resp(200, {"bars": {"QQQ": []}}), _Resp(200, {"bars": {"QQQ": []}})]

    def get(url, headers, params, timeout):
        calls.append(params)
        return seq.pop(0)

    mqe.fetch(CFG, now=datetime(2026, 11, 2, 8, 0, tzinfo=ET), get=get, creds=("k", "s"), sleep=slept.append)
    assert slept == [CFG["retry"]["backoff_seconds"][0]]
    assert calls[0]["feed"] == "sip" and calls[0]["end"] == "2026-11-02T12:44:00+00:00"
    assert calls[0]["start"].startswith("2026-10-30T08:00:00")  # Friday 04:00 ET (EDT)


class _Cur:
    def __init__(self):
        self.sql, self.rowcount = [], 1

    def execute(self, sql, params=None):
        self.sql.append(sql)


class _Conn:
    def __init__(self):
        self.cur = _Cur()

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def test_apply_writes_only_market_quotes_extended(tmp_path, monkeypatch):
    monkeypatch.setattr(mqe, "domain_promoted", lambda *a, **k: True)
    bars, daily = _fx()
    saved = tmp_path / "b.json"
    saved.write_text(json.dumps({"bars": bars, "daily": daily}))
    conn = _Conn()
    out = mqe.run(apply=True, bars_json=str(saved), now=datetime(2026, 10, 29, 18, 15, tzinfo=ET), conn=conn)
    assert out["inserted"] == len(conn.cur.sql) > 0
    assert all("INSERT INTO market_quotes_extended" in s for s in conn.cur.sql)
    assert not any("market_quotes " in s or "market_quotes(" in s for s in conn.cur.sql)


def test_latest_quote_still_returns_the_regular_alpaca_row_after_hours_and_premarket(tmp_path):
    """The data broker's latest quote reads market_quotes only; the extended feed writes a different table, so a read at
    17:10 and at 06:25 returns the 16:00 alpaca row, not an extended print (review of #2384)."""
    alpaca_row = {
        "symbol": "QQQ",
        "price": 715.34,
        "prev_close": 725.61,
        "day_change_pct": -1.42,
        "volume": 1,
        "fetched_at": datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc),
        "source": "alpaca",
    }
    tables = {"market_quotes": [alpaca_row], "market_quotes_extended": []}
    bars, daily = _fx()
    for now in (datetime(2026, 10, 29, 17, 10, tzinfo=ET), datetime(2026, 10, 30, 6, 25, tzinfo=ET)):
        for r in mqe.rows_from_bars(bars, daily, CFG, now=now):
            tables[w.TABLE].append(r)

        def db_query(sql, params):
            assert "FROM market_quotes m" in sql and "market_quotes_extended" not in sql
            return [dict(r) for r in tables["market_quotes"] if r["symbol"] in params[0]]

        q = latest_quote.get_latest_quotes(db_query, ["QQQ"], now=now, max_age_seconds=10**9)
        assert q["symbols"]["QQQ"]["price"] == 715.34 and q["symbols"]["QQQ"]["provider"] == "alpaca"
    assert tables["market_quotes_extended"] and w.TABLE == "market_quotes_extended"


def test_writer_rejects_bad_rows():
    good = dict(next(iter(_rows(datetime(2026, 10, 29, 18, 15, tzinfo=ET)).values())))
    assert w.validate(good) is None
    assert "session" in w.validate(dict(good, session="overnight"))
    assert "price" in w.validate(dict(good, price=0.0))


def test_engine_reader_reads_extended_prints_only_when_knowable():
    from scripts.lib.market_risk.reader import EXTENDED_TABLE, PgReader

    seen = {}

    class Rd(PgReader):
        def _rows(self, sql, params):
            if "to_regclass" in sql:
                return [{"present": True}]
            if EXTENDED_TABLE in sql:
                seen["sql"], seen["params"] = sql, params
                return [
                    {
                        "symbol": "QQQ",
                        "session": "afterhours",
                        "session_date": date(2026, 10, 29),
                        "price": 704.45,
                        "reference_close": 715.34,
                        "reference_date": date(2026, 10, 29),
                        "change_pct": -1.52,
                        "volume": 9,
                        "bar_end": datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc),
                        "feed": "sip",
                        "reference_basis": CFG["reference_basis"],
                    }
                ]
            return []

    end = datetime(2026, 10, 29, 18, 31, tzinfo=ET)
    rows = Rd(conn_factory=lambda: None).quotes(["QQQ"], start=datetime(2026, 10, 29, 0, 0, tzinfo=ET), end=end)
    assert "inserted_at <= %s" in seen["sql"] and "bar_end <= %s" in seen["sql"]
    assert seen["params"][-1] == end and seen["params"][-2] == end
    ext = [r for r in rows if r["session"] == "afterhours"]
    assert ext and ext[0]["prev_close"] == 715.34 and ext[0]["source"].startswith(EXTENDED_TABLE)
    assert ext[0]["reference_date"] == "2026-10-29"


def test_reference_close_is_never_taken_from_an_older_session():
    """No 10-29 daily bar: the 10-29 after-hours print must be refused, not measured against 10-28 (review round 2)."""
    bars, daily = _fx()
    daily = {s: [d for d in v if not d["t"].startswith("2026-10-29")] for s, v in daily.items()}
    refused = []
    rows = mqe.rows_from_bars(bars, daily, CFG, now=datetime(2026, 10, 29, 18, 15, tzinfo=ET), refused_out=refused)
    assert rows == [] and {r["symbol"] for r in refused} == {"QQQ", "INTC", "SPY"}
    assert all("2026-10-29" in r["reason"] for r in refused)


def test_apply_refuses_until_the_domain_is_promoted(tmp_path):
    bars, daily = _fx()
    saved = tmp_path / "b.json"
    saved.write_text(json.dumps({"bars": bars, "daily": daily}))
    assert mqe.domain_promoted() is False  # this PR adds the row under proposed_domains
    try:
        mqe.run(apply=True, bars_json=str(saved), now=datetime(2026, 10, 29, 18, 15, tzinfo=ET), conn=_Conn())
    except SystemExit as exc:
        assert "proposed_domains" in str(exc)
    else:
        raise AssertionError("--apply wrote without a promoted §7A domain")


class _ROConn:
    """Fake psycopg connection tracking the session read-only flag the way Postgres does: SET applies to the
    session, but a rollback of the transaction that issued it undoes it."""

    def __init__(self, table_present, fail_select=False):
        self.present, self.fail, self.read_only, self.pending_ro, self.rollbacks = (
            table_present,
            fail_select,
            False,
            False,
            0,
        )
        conn = self

        class Cur:
            description = [("present",)]

            def execute(self, sql, params=None):
                if sql.startswith("SET default_transaction_read_only"):
                    conn.pending_ro = True
                    conn.read_only = True
                    return
                if "to_regclass" in sql:
                    self.description, self._rows = [("present",)], [(conn.present,)]
                    return
                if not conn.present:
                    raise RuntimeError('relation "market_quotes_extended" does not exist')
                if conn.fail:
                    raise RuntimeError("boom")
                self.description, self._rows = [("symbol",)], []

            def fetchall(self):
                return self._rows

            def close(self):
                pass

        self.Cur = Cur

    def cursor(self):
        return self.Cur()

    def rollback(self):
        self.rollbacks += 1
        if self.pending_ro:  # the SET was in the rolled-back transaction
            self.read_only = False


def test_read_only_survives_a_missing_table_and_a_failed_read():
    from scripts.lib.market_risk.reader import PgReader

    for present, fail in ((False, False), (True, True)):
        c = _ROConn(present, fail)
        r = PgReader(conn_factory=lambda c=c: c)
        assert (
            r.extended_quotes(
                ["QQQ"], start=datetime(2026, 10, 29, tzinfo=ET), end=datetime(2026, 10, 29, 18, tzinfo=ET)
            )
            == []
        )
        assert c.read_only is True, (present, fail)
        assert c.rollbacks == (1 if fail else 0)
