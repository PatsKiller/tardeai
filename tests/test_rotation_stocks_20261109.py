"""LQ-20261107-1655: the individual names under a defensive rotation group (``lib.rotation_stocks.read``).

ANCHOR: ROTATION_INDIVIDUAL_STOCKS_1655_20261109

Synthetic fixtures only (public repo): symbols DEMOA / DEMOB / DEMOH / DEMOUT / DEMOST, round prices, no live
symbol, no live dollar amount, no database. The three reads the module makes (``symbol_profiles``,
``ticker_prices`` then ``market_ohlcv_bars`` for the LQ-1784 liquidity/split guard) are faked; every assertion is
about the rule the operator set — held names in that sector first, then the group's best constituents by RS vs SPY
over exactly 20 sessions — and about the drop rule: a symbol with no dated close, or no complete SPY-session
window, is never ranked and never filled in.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import rotation_stocks as rs  # noqa: E402

ANCHOR = "ROTATION_INDIVIDUAL_STOCKS_1655_20261109"
COVERS = ["scripts/lib/rotation_stocks.py", "scripts/lib/home_cio_card.py"]

# 28 consecutive sessions: more than the 21 (20 + start) a complete RS20 window needs.
DATES = [f"2031-02-{d:02d}" for d in range(1, 29)]
LAST = DATES[-1]


def _prices(symbol, start, per_session, dates=DATES):
    return [{"symbol": symbol, "session": d, "close": round(start * (1 + per_session) ** i, 4)}
            for i, d in enumerate(dates)]


def _profile(symbol, sector, kind="stock"):
    return {"symbol": symbol, "sector": sector, "instrument_type": kind}


PROFILES = [
    _profile("DEMOA", "Health Care"),
    _profile("DEMOB", "healthcare"),
    _profile("DEMOH", "Health Care"),
    _profile("DEMOX", "Health Care"),           # member, no price rows at all
    _profile("DEMOUT", "Utilities"),
    _profile("DEMOST", "Consumer Staples"),
    _profile("DEMDD", "Information Technology"),  # not defensive: out of every group
    _profile("XLV", "Health Care", kind="etf"),   # the ETF row itself, never a constituent
]
PRICES = (
    _prices("SPY", 400.0, 0.001)
    + _prices("DEMOA", 100.0, 0.005)     # strongest
    + _prices("DEMOB", 12.5, 0.003)
    + _prices("DEMOH", 30.0, 0.0)        # weakest, but held
    + _prices("DEMOUT", 41.0, 0.002)
    + _prices("DEMOST", 85.0, 0.0015)
)


class DB:
    """The module's three reads, faked. An exception instance in ``profiles``/``prices``/``bars`` is raised; the
    string ``"none"`` is the db helper's own failure shape (no rows, no exception).

    ``bars`` (market_ohlcv_bars, LQ-1784) defaults to a synthetic daily bar per ticker_prices row with a large
    volume and the same close, so a fixture written for the rank alone is not changed by the floors: its names
    pass the price, dollar-volume, RS-sanity and split checks. A test that wants a floor to fail sets ``bars``.
    """

    def __init__(self, profiles=None, prices=None, bars=None):
        self.profiles = PROFILES if profiles is None else profiles
        self.prices = PRICES if prices is None else prices
        self.bars = bars
        self.calls = []

    def __call__(self, sql, params=None):
        self.calls.append({"sql": sql, "params": params})
        if "symbol_profiles" in sql:
            out = self.profiles
        elif "ticker_prices" in sql:
            out = self.prices
        elif "market_ohlcv_bars" in sql:
            out = self.bars if self.bars is not None else _bars_from(self.prices)
        else:  # pragma: no cover - the module makes exactly these three reads
            raise AssertionError(f"unexpected read: {sql}")
        if isinstance(out, Exception):
            raise out
        return None if out == "none" else out


def _bars_from(prices, volume=1_000_000.0):
    """A daily bar per stored row, same close and a large volume: the floors pass unless a test says otherwise.

    A failure shape (Exception / ``"none"``) is mirrored, so a test that fails the price read fails the volume
    read the same way and the gap it asserts on is the one the module saw first.
    """
    if isinstance(prices, Exception) or prices == "none":
        return prices
    return [{"symbol": p["symbol"], "session": p["session"], "close": p["close"], "volume": volume}
            for p in prices]


def test_groups_and_labels_come_from_the_lookthrough_owner():
    by_group = rs.sectors_by_group()
    assert set(by_group) == set(rs.GROUPS) == {"healthcare", "staples", "utilities"}
    assert by_group["healthcare"] == ("health care", "healthcare")
    assert by_group["staples"] == ("consumer defensive", "consumer staples")
    assert rs.group_of("Health Care") == "healthcare" and rs.group_of("  UTILITIES ") == "utilities"
    assert rs.group_of("Information Technology") is None and rs.group_of(None) is None


def test_held_first_then_best_rs20():
    held = [{"symbol": "demoh", "sector": "Health Care", "market_value": 5000.0}]
    out = rs.read(DB(), held=held, exclude=["XLV"], limit=2)
    block = out["healthcare"]
    symbols = [r["symbol"] for r in block["rows"]]
    # the held name leads on the strength of the holding, not its RS; then the two best ranked names
    assert symbols == ["DEMOH", "DEMOA", "DEMOB"]
    assert block["rows"][0]["held"] is True and block["rows"][0]["held_value_usd"] == 5000.0
    assert [r["held"] for r in block["rows"][1:]] == [False, False]
    # ranked by RS20, strictly descending
    ranked = [r["rs20"] for r in block["rows"][1:]]
    assert ranked == sorted(ranked, reverse=True)
    assert block["rows"][1]["rs20"] > 0 > block["rows"][0]["rs20"]


def test_limit_counts_constituents_not_held_names():
    held = [{"symbol": "DEMOH", "sector": "Health Care", "value_usd": 1000.0}]
    block = rs.read(DB(), held=held, limit=1)["healthcare"]
    assert [r["symbol"] for r in block["rows"]] == ["DEMOH", "DEMOA"]


def test_a_symbol_without_a_dated_close_is_dropped():
    block = rs.read(DB())["healthcare"]
    assert "DEMOX" in {p["symbol"] for p in PROFILES}, "fixture check: DEMOX is a member"
    assert "DEMOX" not in {r["symbol"] for r in block["rows"]}
    assert block["gap"] is None and block["measured"] >= 3


def test_an_incomplete_window_is_not_a_rank():
    short = _prices("DEMOB", 12.5, 0.003, dates=DATES[:10])  # 10 sessions: no 20-session window
    prices = [p for p in PRICES if p["symbol"] != "DEMOB"] + short
    block = rs.read(DB(prices=prices))["healthcare"]
    by = {r["symbol"]: r for r in block["rows"]}
    assert "DEMOB" not in by, "a name with no measurable RS20 is not ranked among constituents"
    # but a held name still appears on the strength of the holding, with its dated close and no RS
    held_block = rs.read(DB(prices=prices), held=[{"symbol": "DEMOB", "sector": "Health Care", "value_usd": 1.0}])["healthcare"]
    row = {r["symbol"]: r for r in held_block["rows"]}["DEMOB"]
    assert row["held"] is True and row["rs20"] is None and row["close_as_of"] == DATES[9]


def test_spy_is_the_benchmark_and_never_a_row():
    db = DB()
    out = rs.read(db, held=[{"symbol": "SPY", "sector": "Health Care", "value_usd": 9.0}])
    assert "SPY" not in {r["symbol"] for block in out.values() for r in block["rows"]}
    read = [c for c in db.calls if "ticker_prices" in c["sql"]][0]
    assert "SPY" in read["params"][0], "the benchmark must be read even though it is not a candidate"


def test_group_etfs_are_not_constituents():
    # a held ETF in the group is excluded the same way the ETF row itself is
    out = rs.read(DB(), held=[{"symbol": "XLV", "sector": "Health Care", "value_usd": 9.0}], exclude=["xlv"])
    assert "XLV" not in {r["symbol"] for r in out["healthcare"]["rows"]}


def test_every_row_carries_its_own_provenance():
    block = rs.read(DB())["healthcare"]
    assert block["as_of"] == LAST and block["source_id"] == rs.PRICE_SOURCE
    for r in block["rows"]:
        assert r["close_as_of"] == LAST, r["symbol"]
        assert r["source_id"] == f"{rs.PRICE_SOURCE}:{r['symbol']}"
        assert r["rs_source_id"] == f"ticker_prices:rs20_vs_spy:{r['symbol']}"
        assert r["rs20_as_of"] == LAST and r["close"] > 0
        assert str(r["sector"]).strip().lower() in block["sector"]


def test_a_sub_cent_print_is_not_a_close():
    prices = [p for p in PRICES if p["symbol"] != "DEMOST"] + _prices("DEMOST", 0.0, 0.0)
    prices = [p for p in prices if p["symbol"] != "DEMOST"] + [
        {"symbol": "DEMOST", "session": d, "close": 0.001} for d in DATES]
    block = rs.read(DB(prices=prices))["staples"]
    assert block["rows"] == [] and block["gap"] == "no constituent with a measured close"


def test_every_group_is_present_and_an_empty_one_says_why():
    out = rs.read(DB())
    assert set(out) == set(rs.GROUPS)
    assert out["utilities"]["rows"] and out["staples"]["rows"]
    empty = rs.read(DB(profiles=[], prices=[]))
    for block in empty.values():
        assert block["rows"] == [] and block["gap"] == "no constituent with a measured close"


def test_a_failed_read_is_a_named_gap_never_a_raise():
    out = rs.read(DB(prices=RuntimeError("boom")))
    for block in out.values():
        assert block["rows"] == [] and block["gap"] == "price history unavailable (RuntimeError)"
    out = rs.read(DB(profiles=RuntimeError("boom")))
    for block in out.values():
        assert block["gap"] == "sector membership unavailable (RuntimeError)"
    # a read that returns None (the db helper's failure shape) is the same gap, without an exception name
    out = rs.read(DB(profiles="none", prices="none"))
    for block in out.values():
        assert block["gap"] == "price history unavailable"
    out = rs.read(DB(profiles="none"))
    for block in out.values():
        assert block["gap"] == "sector membership unavailable"


def test_no_order_vocabulary_in_the_rows():
    out = rs.read(DB(), held=[{"symbol": "DEMOH", "sector": "Health Care", "value_usd": 1.0}])
    keys = {k for block in out.values() for r in block["rows"] for k in r} | {k for b in out.values() for k in b}
    assert not keys & {"order_id", "place_order", "account_number", "order", "qty", "side", "target_usd"}


def _contract_block():
    path = Path(rs.__file__).resolve().parents[2] / "config" / "market_risk_policy.yaml"
    import yaml

    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert policy["schema"] == "MarketRiskPolicy@v1"
    return policy["sectors"]["constituents"]


def test_the_numbers_live_in_the_operators_contract_and_the_reader_agrees():
    block = _contract_block()
    assert block["groups"] == ["healthcare", "staples", "utilities"]
    assert block["top_n"] == rs.TOP_N == 5
    assert block["rs_window_sessions"] == rs.RS_WINDOW_SESSIONS == 20
    assert block["bar_lookback_days"] == rs.BAR_LOOKBACK_DAYS == 70
    assert block["held_first"] is True and block["drop_untraceable"] is True
    # LQ-20261107-1784: the NO-FALSE-POSITIVES floors are the operator's, not the module's.
    assert block["min_price"] == rs.MIN_PRICE == 5.00
    assert block["min_avg_dollar_volume_usd"] == rs.MIN_AVG_DOLLAR_VOLUME_USD == 10_000_000
    assert block["max_abs_rs20"] == rs.MAX_ABS_RS20 == 100
    assert block["max_split_diff_pct"] == rs.MAX_SPLIT_DIFF_PCT == 5.0
    d = rs.defaults()
    assert d["groups"] == tuple(block["groups"]) and d["top_n"] == 5 and d["bar_lookback_days"] == 70
    assert d["rs_window_sessions"] == 20 and d["policy_gap"] is None, "a readable policy reports no gap"
    assert (d["min_price"], d["min_avg_dollar_volume_usd"], d["max_abs_rs20"], d["max_split_diff_pct"]) == (
        5.00, 10_000_000, 100, 5.0)


def test_a_contract_change_changes_the_list_without_a_code_change(monkeypatch):
    monkeypatch.setattr(rs, "_policy_constituents", lambda: ({"groups": ["healthcare"], "top_n": 1}, None))
    out = rs.read(DB())
    assert set(out) == {"healthcare"}, "a group the contract does not name was listed"
    assert len(out["healthcare"]["rows"]) == 1, "the contract's top_n did not reach the rank"
    # an explicit argument still wins over the operator's file
    assert len(rs.read(DB(), limit=2)["healthcare"]["rows"]) == 2


def test_an_unreadable_policy_is_the_module_defaults_not_a_blank_card(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("policy file unavailable")

    # the real boundary: the loader the reader calls, so the fallback inside _policy_constituents is what runs
    monkeypatch.setattr("lib.market_risk.policy.load_policy", _boom)
    d = rs.defaults()
    assert d["groups"] == rs.GROUPS and d["top_n"] == rs.TOP_N and d["bar_lookback_days"] == rs.BAR_LOOKBACK_DAYS
    # the fallback is a stated unknown, never a confident "the policy says nothing"
    assert d["policy_gap"] == "policy unreadable (OSError)"
    assert set(rs.read(DB())) == set(rs.GROUPS)
    # and a policy that reads but has no block is the other, distinguishable gap
    monkeypatch.setattr(rs, "_policy_constituents", lambda: ({}, "policy has no sectors.constituents block"))
    assert rs.defaults()["policy_gap"] == "policy has no sectors.constituents block"


def test_the_contracts_rs_window_is_the_owners_window():
    """``rs_window_sessions: 20`` is only true if the RS owner needs 21 SPY sessions for rs20 (the window + its start)."""
    from lib.sector_signals import relative_strength

    window = rs.RS_WINDOW_SESSIONS
    spy = [(d, 100.0 + i) for i, d in enumerate(DATES[: window + 1])]
    name = [(d, 50.0 + i) for i, d in enumerate(DATES[: window + 1])]
    assert relative_strength(name, spy)["rs20"] is not None
    short_name = name[:window]
    assert relative_strength(short_name, spy)["rs20"] is None, "a partial window was ranked"
    assert relative_strength(name, spy[:-1])["rs20"] is None, "a short benchmark window was ranked"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
