"""P1-T2 vol complex in the regime collector and P1-T3 FRED window. No DB, no network."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as emi  # noqa: E402
import market_regime_collector as mrc  # noqa: E402


def test_vol_complex_records_values_and_term_structure(monkeypatch):
    prices = {"^VVIX": 106.4, "^VIX9D": 21.0, "^VIX3M": 20.0, "^VXN": 28.5, "^SKEW": 150.0}
    monkeypatch.setattr(mrc, "_yahoo_last", lambda s: (prices[s], None, None))
    inds, missing = mrc.collect_vol_complex("SNAP_T", None, 20.0)
    got = {i["indicator_key"]: (i["value"], i["signal"]) for i in inds}
    assert got["vvix_close"] == (106.4, "observed")
    assert got["vix9d_vix_ratio"] == (1.05, "inverted")  # 9-day above spot: front-end stress
    assert got["vix_vix3m_ratio"] == (1.0, "contango")
    assert missing == []


def test_vol_complex_names_every_failure(monkeypatch):
    def boom(sym):
        raise TimeoutError(sym)

    monkeypatch.setattr(mrc, "_yahoo_last", boom)
    inds, missing = mrc.collect_vol_complex("SNAP_T", None, 20.0)
    assert inds == []
    assert sorted(missing) == sorted(f"{k}_unavailable:TimeoutError" for k in mrc.VOL_COMPLEX.values())


def test_vix_missing_uses_labelled_etf_proxy(monkeypatch):
    monkeypatch.setattr(mrc, "_yahoo_last", lambda s: (1.0, None, None))

    class Cur:
        def execute(self, sql, params):
            self.params = params

        def fetchall(self):
            return [("UVXY", 9.5, "2026-10-30 16:09")]

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

    inds, missing = mrc.collect_vol_complex("SNAP_T", Conn(), None)
    assert "vix_close_unavailable" in missing
    proxy = [i for i in inds if i["indicator_key"] == "vol_proxy_uvxy_change_pct"]
    assert proxy and proxy[0]["signal"] == "proxy" and proxy[0]["value"] == 9.5


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
