"""P1-T2 vol complex in the regime collector and P1-T3 FRED window. No DB, no network."""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as emi  # noqa: E402
import market_regime_collector as mrc  # noqa: E402


class _VolConn:
    """Fake connection for the store-backed vol complex: one dict of market_quotes_extended rows per symbol and
    one of fred_economic_series rows. It answers by table name, so a query against the wrong store finds nothing
    instead of silently passing."""

    def __init__(self, rows=(), fred=()):
        self.rows = list(rows)
        self.fred = list(fred)
        self.seen_params = []

    def cursor(self):
        conn = self

        class Cur:
            def execute(self, sql, params=None):
                conn.seen_params.append((sql, params))
                self._sql = str(sql)

            def fetchall(self):
                if "market_quotes_extended" in self._sql:
                    return conn.rows
                if "fred_economic_series" in self._sql:
                    return conn.fred
                return []

            def close(self):
                pass

        return Cur()

    def rollback(self):
        pass


_NOW = datetime(2026, 11, 6, 21, 5, tzinfo=timezone.utc)


def _row(sym, price, feed="schwab", hours_old=1.0, session="overnight"):
    return (sym, price, session, _NOW.date(), _NOW - timedelta(hours=hours_old),
            "schwab_point_quote", feed)


def _collect(rows, fred=()):
    conn = _VolConn(rows, fred)
    return mrc.collect_volatility_complex(conn, "SNAP_T", _NOW)


def test_vol_complex_records_values_and_term_structure():
    rows = [_row("$VIX", 20.0), _row("$VIX9D", 21.0), _row("$VIX3M", 20.0), _row("$VXN", 28.5),
            _row("$VVIX", 106.4), _row("$SKEW", 150.0)]
    inds, missing, summary = _collect(rows)
    got = {i["indicator_key"]: (i["value"], i["signal"]) for i in inds}
    assert got["vvix_close"] == (106.4, "observed")
    # 20.0 is not > the config's 20.0 'high' threshold, so it lands in 'normal' — the boundary is strict.
    assert got["vix_close"] == (20.0, "normal")
    assert got["vix9d_vix_ratio"] == (1.05, "inverted")  # 9-day above spot: front-end stress
    assert got["vix_vix3m_ratio"] == (1.0, "contango")
    assert missing == []
    by_key = {i["indicator_key"]: i for i in inds}
    # every real row names the store, feed and symbol it came from; the ratio rows name themselves 'derived'.
    assert by_key["vix_close"]["source_key"] == "market_quotes_extended:schwab:$VIX"
    assert by_key["vix_close"]["payload"]["source"] == "market_quotes_extended:schwab"
    assert by_key["vix9d_vix_ratio"]["source_key"] == "derived"
    assert "yahoo" not in json.dumps([i["payload"] for i in inds]).lower()
    assert summary["sources"] == {k: "schwab" for k in got if k.endswith("_close")}


def test_vol_complex_names_every_missing_key():
    inds, missing, _ = _collect([])
    assert inds == []
    for key in ("vix_close", "vix9d_close", "vix3m_close", "vvix_close", "skew_close", "vxn_close"):
        assert f"{key}_unavailable:no_row" in missing
    assert "vix9d_vix_ratio_unavailable:needs_vix9d_and_vix" in missing
    assert "vix_vix3m_ratio_unavailable:needs_vix_and_vix3m" in missing


def test_a_banned_source_row_is_refused_by_name_never_scored():
    """The whole point of LQ-20261107-940: a Yahoo row that is still in the store may not be used, and it must be
    visible on the receipt as a banned source rather than as an innocent 'no row'."""
    rows = [_row("$VIX", 20.0, feed="yahoo_finance"), _row("$VXN", 28.5, feed="yfinance")]
    inds, missing, summary = _collect(rows)
    assert inds == []
    assert "vix_close_banned_source:yahoo_finance" in missing
    assert "vxn_close_banned_source:yfinance" in missing
    assert len(summary["banned_feeds_refused"]) == 2


def test_a_stale_row_is_named_and_never_zeroed():
    rows = [_row("$VIX", 20.0, hours_old=24 * 10)]
    inds, missing, _ = _collect(rows)
    assert [i for i in inds if i["indicator_key"] == "vix_close"] == []
    assert any(m.startswith("vix_close_stale:") for m in missing)


def test_fred_fills_only_the_keys_schwab_did_not_supply():
    from datetime import date
    rows = [_row("$VIX", 20.0)]
    fred = [("VIXCLS", date(2026, 11, 5), 19.9), ("VXNCLS", date(2026, 11, 5), 27.5)]
    inds, missing, summary = _collect(rows, fred)
    got = {i["indicator_key"]: i for i in inds}
    # Schwab wins the key it has; FRED supplies the one it does not
    assert got["vix_close"]["value"] == 20.0 and got["vix_close"]["payload"]["source"] == "market_quotes_extended:schwab"
    assert got["vxn_close"]["value"] == 27.5
    assert got["vxn_close"]["payload"]["source"] == "fred_economic_series"
    assert summary["sources"]["vix_close"] == "schwab" and summary["sources"]["vxn_close"] == "fred"
    assert "vix_close_unavailable:no_row" not in missing  # Schwab had it
    assert "vxn_close_unavailable:no_row" not in missing  # FRED filled it


def test_a_stale_fred_observation_is_named_not_passed_off_as_today():
    from datetime import date
    fred = [("VIXCLS", date(2026, 9, 1), 19.9)]
    inds, missing, _ = _collect([], fred)
    assert inds == []
    assert any(m.startswith("vix_close_fred_stale:") for m in missing)


def test_fred_rows_skip_missing_marker():
    rows = emi._fred_rows(
        "DGS10", "10y", [{"date": "2026-10-29", "value": "4.1"}, {"date": "2026-10-28", "value": "."}]
    )
    assert rows == [("DGS10", "10y", 4.1, "2026-10-29")]


def test_fred_window_default_and_override(monkeypatch):
    monkeypatch.delenv("TRADEAI_FRED_WINDOW_OBS", raising=False)
    assert emi._fred_window() == emi.FRED_WINDOW_OBSERVATIONS == 400
    monkeypatch.setenv("TRADEAI_FRED_WINDOW_OBS", "1")
    assert emi._fred_window() == 1


def test_fred_dry_run_fetches_window_and_never_opens_the_db(monkeypatch):
    monkeypatch.delenv("TRADEAI_FRED_WINDOW_OBS", raising=False)
    monkeypatch.setattr(emi, "_env", lambda k: "test-key")
    monkeypatch.setattr(emi, "_get_conn", lambda: pytest.fail("dry run opened the database"))
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        seen.append(req.full_url)
        obs = [{"date": f"2026-10-{d:02d}", "value": "1.5"} for d in range(1, 30)]
        return Resp(json.dumps({"observations": obs}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = emi.ingest_fred(dry_run=True)
    assert out["mode"] == "dry_run" and out["window"] == 400
    assert out["fetched"] == len(emi.FRED_SERIES) and out["rows"] == 29 * len(emi.FRED_SERIES)
    assert all("limit=400" in u for u in seen) and "VXNCLS" in emi.FRED_SERIES
