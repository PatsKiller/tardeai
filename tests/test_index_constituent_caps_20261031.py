"""Index-constituent caps for the engine's event category (scripts/index_constituent_caps.py). Hermetic."""

from __future__ import annotations

import scripts.index_constituent_caps as icc

FAKE = {
    "AAPL": {"marketCap": 5_000e9, "currentPrice": 340.0},
    "MSFT": {"marketCap": 3_900e9, "regularMarketPrice": 520.0},
    "BRK.B": {"marketCap": 1_000e9, "currentPrice": 480.0},
    "ZERO": {"marketCap": 0, "currentPrice": 10.0},
}


def _info(s):
    if s == "BOOM":
        raise TimeoutError("yahoo timed out")
    return FAKE.get(s, {})


def test_rows_and_missing_are_reported_not_swallowed(capsys):
    rows, missing = icc.fetch(["AAPL", "MSFT", "BRK.B", "ZERO", "BOOM", "NONE"], info_of=_info)
    assert [r["symbol"] for r in rows] == ["AAPL", "MSFT", "BRK.B"]
    assert missing == ["ZERO", "BOOM", "NONE"]
    assert "BOOM: TimeoutError" in capsys.readouterr().err


def test_yahoo_symbol_mapping():
    assert icc._yf_symbol("BRK.B") == "BRK-B"


def test_dry_run_writes_nothing_and_reports_weights():
    out = icc.run(apply=False, symbols=["AAPL", "MSFT", "BRK.B"], info_of=_info)
    assert out["written"] == 0 and out["coverage"] == 1.0
    assert round(sum(t["weight"] for t in out["top"]), 6) == 1.0 and out["top"][0]["symbol"] == "AAPL"


def test_apply_writes_through_the_single_writer(monkeypatch):
    seen = {}

    def fake_write(cur, rows, *, source):
        seen["rows"], seen["source"] = rows, source

        class R:
            rows_accepted = len(rows)

        return R()

    class C:
        committed = False

        def cursor(self):
            return object()

        def commit(self):
            C.committed = True

    monkeypatch.setattr("lib.writers.market_quotes_writer.write_market_quotes", fake_write)
    out = icc.run(apply=True, symbols=["AAPL", "MSFT"], info_of=_info, conn=C())
    assert out["written"] == 2 and seen["source"] == "yfinance:index_caps" and C.committed
    assert set(seen["rows"][0]) == {"symbol", "price", "market_cap"}


def test_universe_is_the_policy_list():
    u = icc.universe()
    assert len(u) == 35 and "BRK.B" in u and "NVDA" in u
