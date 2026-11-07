"""OHLC_BARS_SARGABLE
LQ-20261107-416: ohlc_bars SQL must be index-sargable (upper(symbol) forced a 127 ms seq scan per symbol)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.data_broker import ohlc_bars  # noqa: E402


def test_sql_does_not_wrap_symbol_in_a_function():
    for sql in (ohlc_bars.BARS_SQL, ohlc_bars.CLOSES_SQL):
        assert "upper(symbol)" not in sql.lower()
        assert "symbol = %s" in sql


def test_lowercase_input_is_uppercased_before_the_query():
    seen = []

    def fake(sql, params):
        seen.append(params[0])
        return []

    ohlc_bars.get_daily_ohlc(fake, " aapl ")
    assert seen and all(s == "AAPL" for s in seen)
