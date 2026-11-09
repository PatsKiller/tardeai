"""ANCHOR: SINCE_CLOSE_ATR_STOP_BAND_LQ1386_20261108 — "at its stop" is a measurement, not a row count.

2026-11-08, ~23:00 ET. The Home since-close feed said **"SKYD at its stop"**, **"V at its stop"** and
**"PFE at its stop"** on rows the CIO brief itself answered **HOLD** — the names sat 1.8x, 1.6x and 3.6x their
daily ATR above the stop. ``_at_risk()`` returned every ``stop_advice`` row whose answer was not ``NO_ACTION``,
and almost every held name gets a HOLD row, so the ranking's second tier was "the whole book". One name,
ANET at 0.62x ATR, really was at its stop.

The tier is now the house band: room to a **working** stop of less than one daily ATR — the brief's own ``tight``
band (``cio_overnight_brief.cushion``: ``(price - stop) / atr < 1.0``). Price and ATR come from the move; the stop
comes from the brief's ``stop_now`` (never a *suggested* stop, which is a proposal, not a resting order). A name
with no ATR, no working stop or no readable price is not at its stop and the feed keeps its since-close move text.
Synthetic fixtures, shaped on the 2026-11-09T01:06:53Z brief; no DB, no network, no live snapshot is read.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import since_close_card as c  # noqa: E402

ET = ZoneInfo("America/New_York")


def _t(price, pct, atr=None, mv=0.0, sh=0.0, wk=1.0):
    rec = {
        "quote": {"price": price, "change_pct": pct},
        "performance": {"perf_week": wk},
        "holdings_context": {"shares_total": sh, "market_value_total": mv} if sh else {},
    }
    if atr is not None:
        rec["technicals"] = {"atr": atr}
    else:
        rec["technicals"] = {}  # the 2026-11-08 ticker snapshot carries an empty technicals block for MU
    return rec


#: The four labelled names and ANET, with the live 2026-11-08 numbers (price, move, ATR in dollars, market value).
BOOK = {
    "ANET": _t(170.80, 0.13, 10.53, 34_490.00, 1_000),
    "SKYD": _t(8.01, 3.20, 0.52, 8_080.00, 1_000),
    "V": _t(422.65, -0.40, 9.27, 43_202.23, 100),
    "PFE": _t(29.39, -1.00, 0.76, 29_460.00, 1_000),
    "MU": _t(101.00, 2.00, None, 10_100.00, 100),
}

#: The brief's ``stop_advice[]`` for those names (per account, so V appears twice; the roth row has no working stop).
BRIEF = {"stop_advice": [
    {"symbol": "SKYD", "account": "rollover", "answer": "HOLD", "stop_now": 7.07, "suggested_stop": None},
    {"symbol": "PFE", "account": "rollover", "answer": "HOLD", "stop_now": 26.68, "suggested_stop": None},
    {"symbol": "ANET", "account": "rollover", "answer": "HOLD", "stop_now": 164.27, "suggested_stop": None},
    {"symbol": "V", "account": "rollover", "answer": "HOLD", "stop_now": 407.72, "suggested_stop": None},
    {"symbol": "V", "account": "roth", "answer": "NO_ACTION", "stop_now": None, "suggested_stop": None},
    {"symbol": "MU", "account": "rollover", "answer": "HOLD", "stop_now": 97.00, "suggested_stop": None},
]}


def _moves(book=None):
    return c.build_moves({"tickers": book or BOOK}, close_tag="Fri close")


def _news(*symbols):
    return [
        {"symbol": s, "title": f"{s} makes a real announcement", "source": "wire",
         "published_at": datetime(2026, 11, 9, 20, i, tzinfo=ET), "relevance_score": 0.9}
        for i, s in enumerate(symbols)
    ]


def _feed(brief=None, book=None, symbols=("ANET", "SKYD", "V", "PFE", "MU")):
    """(feed, moves) as the producer builds them: the band derived from the brief and the moves themselves."""
    moves = c.attach_news(_moves(book), _news(*symbols))
    return c.build_feed(moves, {}, at_risk=c._at_risk(brief if brief is not None else BRIEF, moves)), moves


# ---- the measurement -------------------------------------------------------------------------------------------
def test_the_1108_label_was_true_for_exactly_one_name():
    """ANET 0.62x ATR really was at its stop; SKYD 1.81x, V 1.61x and PFE 3.57x were not. The old "wider tier"
    (every row that is not NO_ACTION) named all four."""
    moves = _moves()
    at_risk = c._at_risk(BRIEF, moves)
    assert at_risk == ["ANET"], "brief order, one entry per symbol"
    legacy = [r["symbol"] for r in BRIEF["stop_advice"] if str(r.get("answer") or "").upper() != "NO_ACTION"]
    assert set(legacy) == {"SKYD", "PFE", "ANET", "V", "MU"}, "every held name had a row, which is why all of them were labelled"
    stops = {"ANET": 164.27, "SKYD": 7.07, "V": 407.72, "PFE": 26.68, "MU": 97.0}
    multiple = {m["symbol"]: (m["price"] - stops[m["symbol"]]) / m["atr"] for m in moves if m["atr"]}
    assert round(multiple["ANET"], 2) == 0.62 and round(multiple["SKYD"], 2) == 1.81
    assert round(multiple["V"], 2) == 1.61 and round(multiple["PFE"], 2) == 3.57


def test_moves_carry_the_atr_in_dollars():
    by = {m["symbol"]: m for m in _moves()}
    assert by["ANET"]["atr"] == 10.53 and by["V"]["atr"] == 9.27, "the daily ATR, read from technicals.atr"
    assert by["MU"]["atr"] is None, "an empty technicals block is unmeasured, not an ATR of zero"


def test_a_name_without_an_atr_is_not_at_its_stop():
    """MU has a HOLD row and a working stop, but the 2026-11-08 snapshot carried no ATR for it: nothing is
    measured, so nothing is claimed (the same rule as ``stop_distance_unmeasured``)."""
    moves = [m for m in _moves() if m["symbol"] == "MU"]
    assert moves and moves[0]["atr"] is None
    assert c._at_risk(BRIEF, moves) == []


def test_a_row_without_a_working_stop_is_not_at_its_stop():
    brief = {"stop_advice": [{"symbol": "V", "account": "roth", "answer": "NO_ACTION", "stop_now": None}]}
    assert c._at_risk(brief, _moves()) == []


def test_a_suggested_stop_is_not_a_working_stop():
    """``suggested_stop`` is what the brief proposes, not a resting order: a name whose only stop is suggested is
    not at its stop."""
    brief = {"stop_advice": [{"symbol": "PFE", "answer": "HOLD", "stop_now": None, "suggested_stop": 29.30}]}
    assert c._at_risk(brief, _moves()) == []


def test_the_nearest_account_stop_decides():
    """Two accounts on one name: the tighter stop is the one that fires first, so it decides. V at 422.65 with
    stops 407.72 and 420.00 is 0.29x its 9.27 ATR from the nearer stop — at its stop."""
    moves = [m for m in _moves() if m["symbol"] == "V"]
    brief = {"stop_advice": [{"symbol": "V", "answer": "HOLD", "stop_now": 407.72},
                             {"symbol": "V", "answer": "HOLD", "stop_now": 420.00}]}
    assert c._at_risk(brief, moves) == ["V"]
    assert c._at_risk({"stop_advice": [{"symbol": "V", "answer": "HOLD", "stop_now": 407.72}]}, moves) == []


def test_the_band_boundary_is_the_briefs_tight_band():
    """The house band is ``cushion``'s ``tight``: room / ATR < 1.0. Exactly one ATR away is ``moderate``, so it
    is not labelled; a hair inside the band is."""
    book = {"AAA": _t(10.00, 1.0, 0.50, 1_000.0, 100)}
    moves = _moves(book)
    assert c._at_risk({"stop_advice": [{"symbol": "AAA", "answer": "HOLD", "stop_now": 9.50}]}, moves) == [], "room == 1.00 ATR"
    assert c._at_risk({"stop_advice": [{"symbol": "AAA", "answer": "HOLD", "stop_now": 9.51}]}, moves) == ["AAA"], "room == 0.98 ATR"


def test_a_breached_stop_is_at_its_stop():
    book = {"AAA": _t(9.00, -4.0, 0.50, 900.0, 100)}
    assert c._at_risk({"stop_advice": [{"symbol": "AAA", "answer": "HOLD", "stop_now": 9.50}]}, _moves(book)) == ["AAA"]


def test_no_brief_means_no_risk_tier():
    assert c._at_risk(None, _moves()) == []
    assert c._at_risk({}, _moves()) == []


# ---- what the operator reads -----------------------------------------------------------------------------------
def test_the_feed_says_at_its_stop_only_for_the_band_name():
    feed, _ = _feed()
    why = {i["title"].split()[0]: i["why"] for i in feed}
    assert why["ANET"] == "$45 moved · ANET at its stop", "the one measured name, and the producer's exact string"
    assert why["SKYD"] == "$259 moved · SKYD +3.2% since the close"
    assert why["PFE"] == "$295 moved · PFE -1.0% since the close"
    assert why["V"] == "$173 moved · V -0.4% since the close"
    assert why["MU"] == "$202 moved · MU +2.0% since the close"
    for sym in ("SKYD", "V", "PFE", "MU"):
        assert "at its stop" not in why[sym], f"{sym} is not at its stop and the feed must not say it is"


def test_the_risk_tier_is_worth_fifteen_points_and_only_inside_the_band():
    book = {
        "AAA": _t(100.00, 1.0, 2.0, 1_000.00, 100),   # 1.00 above its stop: 0.50x ATR
        "BBB": _t(100.00, 1.0, 2.0, 1_000.00, 100),   # 10.00 above its stop: 5.00x ATR
    }
    brief = {"stop_advice": [{"symbol": "AAA", "answer": "HOLD", "stop_now": 99.00},
                             {"symbol": "BBB", "answer": "HOLD", "stop_now": 90.00}]}
    feed, _ = _feed(brief, book=book, symbols=("AAA", "BBB"))
    scored = {i["title"].split()[0]: i["score"] for i in feed}
    quiet = {i["title"].split()[0]: i["score"] for i in c.build_feed(c.attach_news(_moves(book), _news("AAA", "BBB")), {})}
    legacy = ["AAA", "BBB"]
    old = {i["title"].split()[0]: i["score"]
           for i in c.build_feed(c.attach_news(_moves(book), _news("AAA", "BBB")), {}, at_risk=legacy)}
    assert scored["AAA"] - quiet["AAA"] == 15, "inside the band: +15"
    assert scored["BBB"] == quiet["BBB"], "five ATRs away: nothing"
    assert old["BBB"] - quiet["BBB"] == 15, "the old tier would have paid BBB, which is the defect"


def test_the_stored_rank_rule_names_the_band():
    assert "within 1 ATR of its stop" in c.RANK_RULE
    assert "at-risk name" not in c.RANK_RULE


def test_build_snapshot_threads_the_band_into_the_feed():
    """The producer's own call site: the snapshot the API serves names only the measured name."""
    now = datetime(2026, 11, 10, 5, 55, tzinfo=ET)
    snap = c.build_snapshot(now=now, ticker_snapshot={"tickers": BOOK, "_meta": {"generated_at": "2026-11-09T17:00:00"}},
                            articles=_news("ANET", "SKYD", "V", "PFE", "MU"), futures=None, llm=None, cio_brief=BRIEF)
    why = {i["title"].split()[0]: i["why"] for i in snap["feed"]}
    assert "ANET at its stop" in why["ANET"]
    assert not any("at its stop" in w for s, w in why.items() if s != "ANET")
    assert snap["feed_rule"]["score"] == c.RANK_RULE
