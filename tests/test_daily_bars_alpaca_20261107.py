"""Daily bars are a PRICE series: they come from Alpaca, never yfinance.

LQ-20261107-337 / SPEC_MARKET_EVENT_REENTRY_20261107 §2, §5. On 2026-11-07 ``market_ohlcv_bars`` daily rows
stopped at 2026-10-09 for SPY and did not exist at all for QQQ, because the only daily-bar producer was an
on-demand yfinance fetch inside a page-side technical lookup. ``market_reference_bars_refresh`` existed but had
never been scheduled, and it fetched yfinance too.

These tests pin the two rails that make the repair hold:
  * ``fetch_yfinance_bars`` REFUSES the daily timeframe before it ever touches yfinance (a later caller cannot
    quietly reintroduce the source the operator price rule forbids);
  * ``fetch_alpaca_daily_bars`` stamps ``bar_time`` at midnight America/New_York of the SESSION — the key the
    stored yfinance-era rows already carry — so the upsert updates a session instead of inserting a second row
    for it, and the ``source`` column says ``alpaca``;
  * ``technical_intelligence.load_bars`` uses the Alpaca daily read for the daily timeframe.

No network, no DB: every provider is a fake.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_data_snapshot_loader as mdl  # noqa: E402
import ohlc_charts as oc  # noqa: E402

ET = ZoneInfo("America/New_York")


def _alpaca(t: str, **over):
    bar = {"t": t, "o": 100.0, "h": 103.5, "l": 99.25, "c": 102.75, "v": 1234567}
    bar.update(over)
    return bar


def test_daily_bars_refuse_yfinance_before_importing_it(monkeypatch):
    """The refusal happens above the import: a regression that fell through would call Ticker and be seen here."""
    touched = []

    class _YF:
        def Ticker(self, symbol):  # noqa: N802 - impersonates yfinance.Ticker
            touched.append(symbol)
            raise RuntimeError("yfinance must not be reached for daily bars")

    monkeypatch.setitem(sys.modules, "yfinance", _YF())
    assert mdl.fetch_yfinance_bars("SPY", "daily", 400) == []
    assert touched == []


def test_intraday_yfinance_path_is_untouched():
    """The refusal is scoped to daily: the intraday consumer of this loader keeps working."""
    assert "daily" not in mdl.TIMEFRAME_MAP
    assert mdl.TIMEFRAME_MAP["5m"]["yf_interval"] == "5m"


def test_alpaca_daily_bar_time_is_midnight_et_not_midnight_utc(monkeypatch):
    """05:00Z is midnight EST on 2026-11-06; the stored row is `00:00:00-05`, the same instant, same ON CONFLICT key."""
    monkeypatch.setattr(oc, "alpaca_daily_bars", lambda s, a, b: ([_alpaca("2026-11-06T05:00:00Z")], None))
    bars = mdl.fetch_alpaca_daily_bars("spy", 30)
    assert len(bars) == 1
    bar = bars[0]
    assert bar["symbol"] == "SPY" and bar["timeframe"] == "daily" and bar["source"] == "alpaca"
    assert bar["bar_time"] == datetime(2026, 11, 6, 0, 0, tzinfo=ET)
    assert bar["bar_time"].utcoffset() == timedelta(hours=-5)  # EST — the session's own midnight
    assert bar["bar_time"].astimezone(timezone.utc).hour == 5
    # Midnight UTC would be a SECOND row for the same session; the key is ET midnight.
    assert bar["bar_time"] != datetime(2026, 11, 6, tzinfo=timezone.utc)


def test_edt_session_keeps_the_same_key(monkeypatch):
    monkeypatch.setattr(oc, "alpaca_daily_bars", lambda s, a, b: ([_alpaca("2026-10-30T04:00:00Z")], None))
    bar = mdl.fetch_alpaca_daily_bars("SPY", 30)[0]
    assert bar["bar_time"] == datetime(2026, 10, 30, 0, 0, tzinfo=ET)
    assert bar["bar_time"].utcoffset() == timedelta(hours=-4)


def test_values_are_ohlcv_and_missing_volume_is_zero(monkeypatch):
    monkeypatch.setattr(oc, "alpaca_daily_bars",
                        lambda s, a, b: ([_alpaca("2026-11-06T05:00:00Z", v=None)], None))
    bar = mdl.fetch_alpaca_daily_bars("QQQ", 30)[0]
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (100.0, 103.5, 99.25, 102.75)
    assert bar["volume"] == 0.0


def test_a_malformed_bar_is_skipped_not_fatal(monkeypatch):
    raw = [
        _alpaca("2026-11-05T05:00:00Z"),
        {"t": "2026-11-06T05:00:00Z", "o": 1.0, "h": 1.0, "l": 1.0},  # no close
        {"t": "not-a-time", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0},
    ]
    monkeypatch.setattr(oc, "alpaca_daily_bars", lambda s, a, b: (raw, None))
    bars = mdl.fetch_alpaca_daily_bars("SMH", 30)
    assert [b["bar_time"].date().isoformat() for b in bars] == ["2026-11-05"]


def test_provider_error_is_empty_and_not_a_fallback(monkeypatch):
    monkeypatch.setattr(oc, "alpaca_daily_bars", lambda s, a, b: ([], "alpaca 429"))
    assert mdl.fetch_alpaca_daily_bars("SPY", 30) == []


def test_window_ends_before_the_sip_delay(monkeypatch):
    """A window that reaches 'now' earns HTTP 403 'recent SIP data' for the WHOLE request (measured 2026-11-07)."""
    seen = {}

    def capture(symbol, start, end):
        seen.update(start=start, end=end)
        return [], None

    monkeypatch.setattr(oc, "alpaca_daily_bars", capture)
    mdl.fetch_alpaca_daily_bars("SPY", 30)
    end = datetime.fromisoformat(seen["end"])
    start = datetime.fromisoformat(seen["start"])
    assert datetime.now(timezone.utc) - end >= timedelta(minutes=mdl._sip_delay_minutes() - 1)
    assert (end - start).days == 30


def test_provider_exception_is_empty(monkeypatch):
    def boom(s, a, b):
        raise RuntimeError("no keys")

    monkeypatch.setattr(oc, "alpaca_daily_bars", boom)
    assert mdl.fetch_alpaca_daily_bars("SPY", 30) == []


def test_blank_symbol_never_calls_a_provider(monkeypatch):
    called = []
    monkeypatch.setattr(oc, "alpaca_daily_bars", lambda s, a, b: called.append(s) or ([], None))
    assert mdl.fetch_alpaca_daily_bars("  ", 30) == []
    assert called == []


class _FakeMdl:
    TIMEFRAME_MAP: dict = {}

    def __init__(self):
        self.calls = []

    def fetch_alpaca_daily_bars(self, symbol, days):
        self.calls.append(("alpaca", symbol, days))
        return [{"symbol": symbol, "timeframe": "daily", "bar_time": datetime.now(ET) - timedelta(days=2),
                 "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "source": "alpaca"}]

    def fetch_yfinance_bars(self, symbol, timeframe, days):
        self.calls.append(("yfinance", symbol, timeframe))
        return []

    def store_bars(self, conn, bars):
        self.calls.append(("store", len(bars)))
        return len(bars)


class _Cur:
    """First read: no stored bars. Second read (after the fetch): the bar the fetch just stored."""

    def __init__(self, row):
        self.row = row
        self.reads = 0

    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith("SELECT")

    def fetchall(self):
        self.reads += 1
        return [] if self.reads == 1 else [self.row]


class _Conn:
    def __init__(self, row):
        self.cur = _Cur(row)

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass


def test_technical_intelligence_daily_fetch_uses_alpaca(monkeypatch):
    import technical_intelligence as ti

    fake = _FakeMdl()
    monkeypatch.setitem(sys.modules, "market_data_snapshot_loader", fake)
    monkeypatch.setattr(ti, "_freshness_cfg", lambda: {})
    ts = datetime.now(ET) - timedelta(days=2)
    conn = _Conn((ts, 1.0, 2.0, 0.5, 1.5, 10.0, "alpaca"))
    out = ti.load_bars("SPY", "daily", conn, allow_fetch=True)
    assert [c[0] for c in fake.calls] == ["alpaca", "store"]
    assert fake.calls[0][1] == "SPY" and fake.calls[0][2] == 730  # weekly/monthly resample depth
    assert out["meta"]["bars"] == 1
