"""LQ-20261107-1784 (P0) — the Home CIO rotate column must not rank false positives.

The operator: "this is not clear what to do and formatting not actionable." The rank under each defensive
ETF named penny/microcap data accidents because ``rotation_stocks.read`` had no price, liquidity, split or
RS-sanity floor.

This file pins D1: a name must clear the operator's floors before it may be RANKED.

* penny — a sub-$5 close is never a candidate;
* illiquid — a 20-session dollar volume under the floor is never a candidate (measured from market_ohlcv_bars,
  the only volume owner); an UNMEASURED dollar volume is counted and NOT ranked (an unmeasured floor is not a
  passed floor), never called illiquid, and a held name is still listed;
* split artifact — ticker_prices and market_ohlcv_bars disagree by more than the tolerance for the same
  session inside the RS window, so the stored close is not trustworthy;
* data error — |RS20| over the sanity cap is unadjusted history, dropped and counted in the group note.

A HELD name is a fact about the book and is still listed; it carries a plain flag and, when its price is
unreliable, no RS20 fact.

Synthetic fixtures only (public repo): the sector ETFs the product already ranks, DEMO constituent names, round
prices, no operator holding, no operator share count, no operator dollar amount, no database. Fail-before: at the
livefold revision the module has no bars read and no floors, so every name below
is ranked (and the ``excluded`` / ``unmeasured_liquidity`` keys do not exist) — the assertions fail on absence.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import home_cio_card as hc  # noqa: E402
from lib import rotation_stocks as rs  # noqa: E402
from lib.cio_buys_gate import buys_block  # noqa: E402

ANCHOR = "ROTATE_NO_FALSE_POSITIVES_1784_20261110"
COVERS = ["scripts/lib/rotation_stocks.py", "config/market_risk_policy.yaml",
          "scripts/lib/home_cio_card.py", "scripts/lib/cio_buys_gate.py"]
ET = ZoneInfo("America/New_York")

DATES = [f"2031-02-{d:02d}" for d in range(1, 29)]
LAST = DATES[-1]
#: A 20-session window needs 21 sessions; 28 gives every fixture room and keeps RS20 measurable.
VOL = 1_000_000.0


def _closes(symbol, start, per_session):
    return [{"symbol": symbol, "session": d, "close": round(start * (1 + per_session) ** i, 4)}
            for i, d in enumerate(DATES)]


def _bars(prices, volume=VOL):
    return [{"symbol": p["symbol"], "session": p["session"], "close": p["close"], "volume": volume}
            for p in prices]


PROFILES = [
    {"symbol": "DEMOSANE", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOPENNY", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOLIQ", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOSPLIT", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMODATA", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOUNMEAS", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOHOLD", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOHOLDSPLIT", "sector": "Health Care", "instrument_type": "stock"},
    {"symbol": "DEMOSTPL", "sector": "Consumer Staples", "instrument_type": "stock"},
    {"symbol": "XLV", "sector": "Health Care", "instrument_type": "etf"},
]

# SPY +0.1%/session. DEMOSANE +2%/session (a clean, tradeable rank); DEMODATA +5%/session (|RS20| > 100).
PRICES = (
    _closes("SPY", 400.0, 0.001)
    + _closes("DEMOSANE", 50.0, 0.02)
    + _closes("DEMOPENNY", 3.00, 0.0)
    + _closes("DEMOLIQ", 20.0, 0.01)
    + _closes("DEMOSPLIT", 50.0, 0.01)
    + _closes("DEMODATA", 10.0, 0.05)
    + _closes("DEMOUNMEAS", 60.0, 0.015)
    + _closes("DEMOHOLD", 2.00, 0.0)
    + _closes("DEMOHOLDSPLIT", 40.0, 0.01)
    + _closes("DEMOSTPL", 85.0, 0.001)
)


def _fixture_bars():
    """Bars for every name, then the deliberate artifacts. DEMOUNMEAS has no bars at all (unmeasured)."""
    rows = _bars([p for p in PRICES if p["symbol"] != "DEMOUNMEAS"])
    ours = []
    for b in rows:
        sym = b["symbol"]
        if sym == "DEMOLIQ":
            b = {**b, "volume": 100_000.0}          # $2M/day: under the $10M floor
        elif sym == "DEMOSPLIT" and b["session"] == DATES[-3]:
            b = {**b, "close": round(b["close"] * 1.10, 4)}  # ticker_prices and bars disagree by 9%
        elif sym == "DEMOHOLDSPLIT" and b["session"] == DATES[-2]:
            b = {**b, "close": round(b["close"] * 0.80, 4)}  # a 25% artifact on a HELD name
        ours.append(b)
    return ours


class DB:
    """The module's three reads, faked; a name absent from ``bars`` has no row (unmeasured volume)."""

    def __init__(self, bars=None):
        self.bars = _fixture_bars() if bars is None else bars
        self.calls = []

    def __call__(self, sql, params=None):
        self.calls.append({"sql": sql, "params": params})
        if "symbol_profiles" in sql:
            return PROFILES
        if "ticker_prices" in sql:
            return PRICES
        if "market_ohlcv_bars" in sql:
            return self.bars
        raise AssertionError(f"unexpected read: {sql}")  # pragma: no cover


HELD = [
    {"symbol": "DEMOHOLD", "sector": "Health Care", "value_usd": 5000.0},
    {"symbol": "DEMOHOLDSPLIT", "sector": "Health Care", "value_usd": 4000.0},
]


def _health():
    return rs.read(DB(), held=HELD)["healthcare"]


def _by(block):
    return {r["symbol"]: r for r in block["rows"]}


# ── the rank ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_penny_illiquid_and_split_names_are_not_ranked():
    block = _health()
    ranked = [r for r in block["rows"] if not r["held"]]
    symbols = {r["symbol"] for r in ranked}
    assert "DEMOPENNY" not in symbols, "a sub-$5 name was ranked"
    assert "DEMOLIQ" not in symbols, "a name under the dollar-volume floor was ranked"
    assert "DEMOSPLIT" not in symbols, "a split artifact was ranked"
    # the clean name still leads the rank, so the card is not empty
    assert ranked and ranked[0]["symbol"] == "DEMOSANE"


def test_a_split_artifact_is_dropped_even_when_price_and_liquidity_pass():
    # its only failure is the two-source disagreement: that alone must stop a rank
    block = _health()
    assert "DEMOSPLIT" not in _by(block)
    assert block["excluded"].get("split_mismatch") == 1


def test_the_rs_sanity_cap_counts_a_data_error_in_the_group_note():
    block = _health()
    assert "DEMODATA" not in _by(block), "an |RS20| over the cap was ranked"
    assert block["excluded"].get("rs_sanity") == 1
    assert block["filter_note"] and "data error" in block["filter_note"]
    # and the count names itself where the operator sees it
    assert "|RS20| > 100" in block["filter_note"]


def test_an_unmeasured_name_is_counted_but_never_ranked_and_never_called_illiquid():
    """LQ-1784 r2 (grok-a review): an unmeasured dollar volume cannot take a top-N slot under a liquid caption."""
    block = _health()
    assert "DEMOUNMEAS" not in _by(block), "a name the liquidity floor could not measure was ranked"
    assert block["unmeasured_liquidity"] >= 1, "the unmeasured name vanished from the group note"
    assert "not ranked: dollar volume unmeasured" in (block["filter_note"] or "")
    assert "illiquid" not in (block["filter_note"] or "").lower(), "an unmeasured name was called illiquid"


# ── held names are facts about the book ─────────────────────────────────────────────────────────────────────────

def test_a_held_penny_is_still_listed_with_a_plain_flag():
    block = _health()
    row = _by(block)["DEMOHOLD"]
    assert row["held"] is True and row["close"] == 2.0
    assert row["flag"] == "below $5.00 — review"
    # held names lead the sector, before the ranked names
    held = [r["symbol"] for r in block["rows"] if r["held"]]
    assert set(held) == {"DEMOHOLD", "DEMOHOLDSPLIT"}
    assert all(not r["held"] for r in block["rows"][len(held):])


def test_a_held_split_artifact_shows_no_rank_it_cannot_trust():
    row = _by(_health())["DEMOHOLDSPLIT"]
    assert row["held"] is True
    assert row["flag"] == "no reliable price — review"
    assert row["rs20"] is None and row["rs20_as_of"] is None


# ── the floors are the operator's, not the code's ───────────────────────────────────────────────────────────────

def test_a_contract_change_changes_the_rank_without_a_code_change(monkeypatch):
    # raise the price floor above every non-held fixture and they all go; nothing in the module changes
    monkeypatch.setattr(rs, "_policy_constituents",
                        lambda: ({"min_price": 100.0, "top_n": 5}, None))
    block = _health()
    assert "DEMOSANE" not in _by(block)
    assert block["excluded"].get("below_price", 0) >= 1


def test_an_absent_floor_falls_back_to_the_module_constant(monkeypatch):
    monkeypatch.setattr(rs, "_policy_constituents", lambda: ({"min_price": 0}, None))
    d = rs.defaults()
    assert d["min_price"] == rs.MIN_PRICE == 5.00, "a 0 floor silently disabled the check"


# ── no advice, no order ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_flagged_held_name_never_becomes_an_instruction():
    text = " ".join(str(v) for r in _health()["rows"] for v in r.values()).lower()
    for word in ("buy", "sell", "place order", "stop loss"):
        assert word not in text


# ── D2: the column says what to do, once ────────────────────────────────────────────────────────────────────────
#
# The operator's second complaint: "not clear what to do and formatting not actionable". The stock line repeated the
# RS pair and compared two closes; the event line could not tell that an 08:30 ET print had already happened; a
# filled tranche had no next step. These pin the reading, not a new verdict: the CIO owns the verdict, and every
# phrase below is drawn from a fact the projection already carries. Round synthetic figures only.

def _fact(value, as_of="2031-03-10T02:00:00+00:00", source_id="synthetic"):
    return {"value": value, "source_id": source_id, "as_of": as_of}


NOW_BEFORE = datetime(2031, 3, 11, 8, 29, tzinfo=ET)   # CPI at 08:30 ET is still ahead
NOW_AFTER = datetime(2031, 3, 11, 8, 31, tzinfo=ET)    # it has printed

MACRO = [
    {"date": "2031-03-11", "event": "Consumer Price Index", "time_et": "08:30"},
    {"date": "2031-03-14", "event": "Producer Price Index", "time_et": "08:30"},
]


def test_a_passed_release_is_not_the_next_event():
    syn = {"as_of": "2031-03-11T08:00:00+00:00", "this_week": {"macro": MACRO},
           "buys": {"until": "CPI Tue 03-11 08:30 ET"}}
    assert hc._catalyst(syn, NOW_BEFORE)["event"] == "Consumer Price Index"
    after = hc._catalyst(syn, NOW_AFTER)
    assert after["event"] == "Producer Price Index", "the card still named a release that had printed"
    # with nothing ahead the card carries no stale event; the buys line states the gate's current state instead
    assert hc._catalyst({"as_of": syn["as_of"], "this_week": {"macro": MACRO[:1]}}, NOW_AFTER) is None


def test_the_buys_gate_stops_naming_a_release_that_already_printed():
    before = buys_block("YELLOW", MACRO, NOW_BEFORE)
    assert before["gate"] == "SMALL_ONLY" and before["until"].startswith("CPI")
    after = buys_block("YELLOW", MACRO, NOW_AFTER)
    assert after["until"].startswith("PPI"), "the gate waited for a print that was already out"
    # once the last event is behind us the gate says its own state, never a passed-release clause
    last = buys_block("RED", MACRO[:1], NOW_AFTER)
    assert last["line"] == "No new buys while the tier is RED; protect gains with stops"


def test_the_stock_line_is_one_relational_phrase():
    one = {"close": {"value": 50.0}}
    cand = {"symbol": "XLV", "rs20": 10.0, "close": {"value": 100.0}}
    assert hc._stock_line(one, cand, {"value": 7.0}) == "weaker than XLV by 3.0 pts"
    assert hc._stock_line(one, cand, {"value": 20.0}) == "stronger than XLV by 10.0 pts"
    assert hc._stock_line(one, cand, {"value": 10.0}) == "matches XLV"
    assert hc._stock_line(one, cand, None) is None
    assert hc._stock_line(one, {"symbol": "XLV"}, {"value": 7.3}) is None
    # the duplicated RS sentence and the meaningless two-close comparison are gone
    line = hc._stock_line(one, cand, {"value": 7.0})
    for gone in ("RS", "close", "100.0", "vs SPY", "+"):
        assert gone not in line


MR = {
    "as_of": "2031-03-10T02:00:00+00:00",
    "sectors": {"as_of": "2031-03-07", "groups": [
        {"key": "healthcare", "label": "Healthcare", "symbols": ["XLV"], "state": "RESILIENT", "rs20": 10.0, "dd20": -2.0},
        {"key": "staples", "label": "Staples", "symbols": ["XLP"], "state": "NEUTRAL", "rs20": 4.0},
        {"key": "utilities", "label": "Utilities", "symbols": ["XLU"], "state": "NEUTRAL", "rs20": 2.0},
    ]},
    "heatmap": [{"key": "healthcare", "state": "RESILIENT"}, {"key": "staples", "state": "NEUTRAL"},
                {"key": "utilities", "state": "NEUTRAL"}],
    "leadership": {"groups": {"healthcare": {"class": "LEADERSHIP_CONFIRMED"}}},
    # a round $1M synthetic book: the 4% healthcare target is $40K, so tranche 1 and 2 are $12K each
    "book_exposure": {"as_of": "2031-03-10", "total_usd": 1_000_000.0, "cash_usd": 400_000.0},
}
BARS = ([{"symbol": "XLV", "session": f"2031-02-{d:02d}", "close": 100.0 + 1.0 * i}
         for i, d in enumerate(range(1, 26))]
        + [{"symbol": "XLP", "session": f"2031-02-{d:02d}", "close": 100.0 + 0.5 * i}
           for i, d in enumerate(range(1, 26))]
        + [{"symbol": "XLU", "session": f"2031-02-{d:02d}", "close": 50.0 + 0.25 * i}
           for i, d in enumerate(range(1, 26))])
QUOTES = {"XLV": {"price": 100.00, "as_of": "2031-03-10T02:09:00+00:00", "source": "synthetic_quote"},
          "XLP": {"price": 100.00, "as_of": "2031-03-10T02:09:00+00:00", "source": "synthetic_quote"}}
D2_HELD = {"XLV": {"shares": 120.0, "avg_cost": 100.00, "as_of": "2031-03-09T20:00:00+00:00",
                "source_id": "synthetic_book:fixture_1"}}
BUYS = {"gate": _fact("SMALL_ONLY"), "until": _fact("CPI Tue 03-11 08:30 ET"),
        "until_short": _fact("CPI Tue"),
        "line": _fact("Small sizes only, and nothing new before CPI Tue 03-11 08:30 ET")}


def _rotate(stocks=None, buys=BUYS):
    return hc._rotate(MR, BARS, True, None, QUOTES, D2_HELD, stocks, buys)


def _cand(rot, sym):
    return {c["symbol"]: c for c in rot["candidates"]}[sym]


def test_a_filled_tranche_states_the_next_one_even_under_the_gate():
    rot = _rotate()
    c = _cand(rot, "XLV")
    assert c["held"]["filled"] is True and c["held"]["shares"] == 120
    # the next step: tranche 2's size at the CURRENT price, and the event it waits on
    assert c["next_tranche"]["usd"] == 12_000.0 and c["next_tranche"]["shares"] == 120
    # the gate withholds tranche 1's dollars, not the fact of the fill
    assert c["proposed"]["tranche1_usd"] is None and rot["gated"]
    # and the CIO's own line rides out so the column can state TODAY without a second read
    assert rot["buys"]["line"]["value"].startswith("Small sizes only") and rot["buys"]["gate"]["value"] == "SMALL_ONLY"


def test_a_watch_group_owes_a_target_and_no_tranche():
    rot = _rotate()
    xlp = _cand(rot, "XLP")
    assert xlp["qualifies"] is False and "held" not in xlp and "next_tranche" not in xlp
    assert xlp["proposed"]["target_pct"] == 2.0 and xlp["proposed"]["target_usd"] == 20_000.0


def test_a_held_flag_and_the_drop_count_reach_the_column():
    stocks = {"healthcare": {"as_of": "2031-03-07", "rows": [
        {"symbol": "DEMOH", "held": True, "close": 2.0, "flag": "below $5.00 — review",
         "source_id": "ticker_prices:daily:DEMOH", "close_as_of": "2031-03-07", "held_value_usd": 500.0},
    ], "filter_note": "2 dropped: 1 under $5.00, 1 under $10.0M/day"}}
    c = _cand(_rotate(stocks=stocks), "XLV")
    row = c["stocks"][0]
    assert row["held"] is True and row["flag"] == "below $5.00 — review"
    assert c["stocks_note"] == "2 dropped: 1 under $5.00, 1 under $10.0M/day"
