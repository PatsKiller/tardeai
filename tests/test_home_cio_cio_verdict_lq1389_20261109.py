"""ANCHOR: HOME_CIO_CIO_VERDICT_LQ1389_20261109 — Home renders ONE verdict, and it is the CIO's.

LQ-20261107-1389, operator 2026-11-08 23:06 ET, two conflicts on the same page:

* (a) the rotation column proposed "tranche 1 XLV/XLP ($26,224)" while the CIO's own verdict, four lines above it,
  read "Buys NONE until CPI Tue". Two answers, and the operator left to pick — a dollar amount the verdict forbids
  acting on. The fix withholds the tranche (not to zero: to absent) under a no-buys gate and states the gate and
  the named release the tranche is waiting for;
* (b) the stressed-holdings table printed the market-risk projection's stance — "exit review" — for names the CIO
  had answered: SPCX "RAISE the stop", ANET "hold". The table now carries the CIO's answer ("CIO: raise stop",
  "CIO: hold") and keeps the projection's label beside it as ``stance_engine``, so the override is traceable rather
  than a reading that vanished.

Everything here is synthetic (the repository is PUBLIC): symbols DEMO*, round dollars, no state root, no broker,
no database and no host clock. The SPA half (the row's "after CPI Tue" and the "TRANCHE 1 AFTER CPI TUE" pill) is a
guarded read of the same two fields; it is not pinned by a rendered test because repo_preflight refuses any new SPA
test file (the stale ``ui_build_command`` registration check, documented on LQ-20261107-1388).

COVERS = ["scripts/lib/home_cio_card.py"]
"""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import home_cio_card as h  # noqa: E402

NOW = datetime(2031, 3, 10, 2, 10, tzinfo=timezone.utc)
MR_AT = "2031-03-10T02:00:00+00:00"
SYN_AT = "2031-03-10T01:05:00+00:00"
BUYS_NONE = {"line": "No new buys before CPI Tue 03-11 08:30 ET; protect gains with stops",
             "gate": "NONE", "until": "CPI Tue 03-11 08:30 ET", "until_short": "CPI Tue"}


def _bars(sym, start, step, n=25):
    return [{"symbol": sym, "session": f"2031-02-{d:02d}", "close": round(start + step * i, 2)}
            for i, d in enumerate(range(1, n + 1))]


MR = {
    "tier": "RED", "score": 59.6, "as_of": MR_AT, "stale": False, "age_hours": 0.2,
    "sectors": {"as_of": "2031-03-07", "stressed": ["Technology"], "resilient": ["Healthcare", "Staples"],
                "sectors_hit": 1, "sectors_measured": 11, "sectors_down": 8,
                "groups": [{"key": "tech", "label": "Technology", "kind": "sector", "symbols": ["DEMOT"], "state": "STRESS"},
                           {"key": "healthcare", "label": "Healthcare", "kind": "sector", "symbols": ["DEMOX"], "state": "RESILIENT", "rs20": 13.8},
                           {"key": "staples", "label": "Staples", "kind": "sector", "symbols": ["DEMOY"], "state": "RESILIENT", "rs20": 13.5},
                           {"key": "utilities", "label": "Utilities", "kind": "sector", "symbols": ["DEMOZ"], "state": "NEUTRAL"}]},
    "heatmap": [{"key": "healthcare", "state": "RESILIENT"}, {"key": "staples", "state": "RESILIENT"},
                {"key": "utilities", "state": "NEUTRAL"}],
    "leadership": {"groups": {"healthcare": {"class": "LEADERSHIP_CONFIRMED"}, "staples": {"class": "UNKNOWN"}}},
    "book_exposure": {"as_of": "2031-03-10", "total_usd": 100000.0, "cash_usd": 76000.0, "cash_pct_book": 76.0,
                      "stressed_usd": 9000.0, "stressed_pct_book": 9.0, "stops_known": True,
                      "rows": [{"symbol": "DEMOA", "account_label": "Example IRA", "value_usd": 8000.0, "pct_account": 8.0,
                                "stressed_share": 0.5, "usd_exposed": 4000.0, "stop_distance_pct": 10.0, "stance": "exit review"},
                               {"symbol": "DEMOB", "account_label": "Example IRA", "value_usd": 3000.0, "pct_account": 3.0,
                                "stressed_share": 1.0, "usd_exposed": 3000.0, "stop_distance_pct": 3.8, "stance": "exit review"},
                               {"symbol": "DEMOC", "account_label": "Example Taxable", "value_usd": 2000.0, "pct_account": 2.0,
                                "stressed_share": 0.5, "usd_exposed": 1000.0, "stop_distance_pct": 4.5, "stance": "exit review"},
                               {"symbol": "DEMOD", "account_label": "Example Taxable", "value_usd": 1000.0, "pct_account": 1.0,
                                "stressed_share": 1.0, "usd_exposed": 1000.0, "stop_distance_pct": 6.0, "stance": "exit review"}]},
}

SC = {
    "freshness": {"stale": False, "window_current": True},
    "cio_brief": {
        "generated_at": SYN_AT,
        "synopsis": {"posture": "DEFENSIVE — HOLD CASH", "as_of": SYN_AT, "buys": dict(BUYS_NONE),
                     "this_week": {"macro": [{"date": "2031-03-11", "event": "Consumer Price Index", "time_et": "08:30"}]}},
        "stop_advice": [
            # the CIO answers three of the four stressed names; DEMOD it never mentions
            {"symbol": "DEMOA", "account": "example_ira", "answer": "RAISE", "stop_now": 90.0, "stop_qty": 80,
             "held_qty": 80, "suggested_stop": 95.0, "reason": "gain to lock", "as_of": SYN_AT},
            {"symbol": "DEMOB", "account": "example_ira", "answer": "HOLD", "as_of": SYN_AT},
            # DEMOC's ask is already satisfied by the broker: not a verdict about the name any more (LQ-1672)
            {"symbol": "DEMOC", "account": "example_taxable", "answer": "RAISE", "state": "done", "as_of": SYN_AT},
            # a name the CIO turned down for action is not answered either
            {"symbol": "DEMOD", "account": "example_taxable", "answer": "NO_ACTION", "as_of": SYN_AT},
        ],
    },
}

BARS = _bars("DEMOX", 170.0, 0.6) + _bars("DEMOY", 85.0, 0.2) + _bars("DEMOZ", 41.0, 0.08, n=10)


def _build(mr=None, sc=None, **kw):
    kw.setdefault("bars", BARS)
    return h.build(copy.deepcopy(MR if mr is None else mr), copy.deepcopy(SC if sc is None else sc), now=NOW, **kw)


def _rotate(out):
    return out["panel"]["rotate"]


# ── (a) a no-buys verdict withholds the tranche ────────────────────────────────────────────────────────────────

def test_no_buys_gate_suppresses_every_tranche_and_the_plan():
    out = _build()
    rot = _rotate(out)
    assert out["advice"] == {"ok": True, "reason": None}
    assert out["card"]["buys_gate"]["value"] == "NONE"
    # nothing carries money or a share count...
    for c in rot["candidates"]:
        assert c["proposed"]["tranche1_usd"] is None, c["symbol"]
        assert c["proposed"]["shares"] is None, c["symbol"]
        assert c["proposed"]["tranches"] == [], c["symbol"]
    # ...and the plan the operator was asked to approve is gone, not zeroed
    assert rot.get("plan") is None
    assert "$26,224" not in str(rot)


def test_the_gate_travels_with_the_column_and_names_the_release():
    rot = _rotate(_build())
    gated = rot["gated"]
    assert gated["gate"]["value"] == "NONE"
    assert gated["until_short"]["value"] == "CPI Tue"          # the row reads "after CPI Tue"
    assert gated["until"]["value"] == "CPI Tue 03-11 08:30 ET"
    assert gated["line"]["value"].startswith("No new buys before CPI")
    # every fact is traceable: a gate with no source or no time is not a fact
    for k in ("gate", "until", "until_short", "line"):
        assert gated[k]["source_id"] and gated[k]["as_of"]


def test_the_target_survives_because_it_is_not_a_purchase():
    """Withholding the buy must not withhold the plan's target: the group still goes to 4% once the gate lifts."""
    x = {c["symbol"]: c for c in _rotate(_build())["candidates"]}
    assert x["DEMOX"]["qualifies"] is True and x["DEMOX"]["proposed"]["target_pct"] == 4.0
    assert x["DEMOX"]["proposed"]["target_usd"] == 4000.0
    assert x["DEMOY"]["proposed"]["target_pct"] == 3.0


#: LQ-20261107-1655's per-name rows under the healthcare ETF, in the shape the endpoint hands the projection.
STOCKS = {"healthcare": {"source_id": "ticker_prices:daily", "as_of": "2031-03-07", "gap": None, "rows": [
    {"symbol": "DEMON", "sector": "Health Care", "held": False, "close": 40.0, "close_as_of": "2031-03-07",
     "rs20": 11.0, "rs20_as_of": "2031-03-07", "source_id": "ticker_prices:daily:DEMON",
     "rs_source_id": "ticker_prices:rs20_vs_spy:DEMON"}]}}


def test_the_names_under_a_gated_etf_keep_their_readings_and_lose_their_share_count():
    """The per-name rows are the same tranche 1 as the ETF row: under a no-buys gate they carry the readings and
    no money, no share count and no proposed flag — otherwise the page shows the same buy one level down."""
    assert _rotate(_build(stocks=STOCKS)).get("plan") is None
    for c in _rotate(_build(stocks=STOCKS))["candidates"]:
        for r in c.get("stocks") or []:
            assert "tranche1_usd" not in r and "tranche1_shares" not in r and "proposed" not in r, r["symbol"]
    x = {c["symbol"]: c for c in _rotate(_build(stocks=STOCKS))["candidates"]}["DEMOX"]
    assert [r["symbol"] for r in x["stocks"]] == ["DEMON"]      # the readings the operator wanted stay
    assert x["stocks"][0]["close"]["value"] == 40.0 and x["stocks"][0]["rs20"]["value"] == 11.0
    # and the gate is a gate, not a deletion: the same row sizes again once the buys line allows one
    sc = copy.deepcopy(SC)
    sc["cio_brief"]["synopsis"]["buys"] = {"line": "Buys open, slowly", "gate": "OPEN"}
    open_row = {c["symbol"]: c for c in _rotate(_build(sc=sc, stocks=STOCKS))["candidates"]}["DEMOX"]["stocks"][0]
    assert open_row["tranche1_usd"] == 1200.0 and open_row["tranche1_shares"] == int(1200.0 // 40.0)
    assert open_row["proposed"] is True


@pytest.mark.parametrize("buys,gated", [
    ({"gate": "OPEN", "until": "CPI Tue 03-11 08:30 ET", "until_short": "CPI Tue", "line": "Buys open, slowly"}, False),
    ({"gate": "SMALL_ONLY", "until": "CPI Tue 03-11 08:30 ET", "until_short": "CPI Tue", "line": "Small sizes only, and nothing new before CPI Tue"}, True),
    ({"gate": "SMALL_ONLY", "line": "Small sizes only"}, False),
    ({"gate": "NONE", "line": "No new buys while the tier is RED"}, True),   # no event named: still no buys
    (None, False),                                                          # no gate fact at all: nothing to obey
])
def test_the_gate_is_read_from_the_verdict_and_only_no_buys_withholds(buys, gated):
    sc = copy.deepcopy(SC)
    if buys is None:
        sc["cio_brief"]["synopsis"].pop("buys")
    else:
        sc["cio_brief"]["synopsis"]["buys"] = buys
    rot = _rotate(_build(sc=sc))
    assert bool(rot.get("gated")) is gated
    # an open line proposes again — this fix is a gate, not a ban on the rotation column
    assert bool(rot.get("plan")) is (not gated)


def test_an_open_gate_sizes_the_same_tranches_as_before():
    sc = copy.deepcopy(SC)
    sc["cio_brief"]["synopsis"]["buys"] = {"line": "Buys open, slowly", "gate": "OPEN"}
    rot = _rotate(_build(sc=sc))
    x = {c["symbol"]: c for c in rot["candidates"]}
    assert x["DEMOX"]["proposed"]["tranche1_usd"] == 1200.0
    assert rot["plan"]["tranche1_usd"] == 1200.0 + 900.0


def test_a_stale_synopsis_is_not_a_verdict():
    """advice.ok False turns the actions off; a stale gate must not be obeyed either, and none is carried."""
    sc = copy.deepcopy(SC)
    sc["freshness"]["stale"] = True
    out = _build(sc=sc)
    assert out["advice"]["ok"] is False
    rot = _rotate(out)
    assert "gated" not in rot
    assert all("proposed" not in c for c in rot["candidates"])


# ── (b) the stressed table renders the CIO's answer ────────────────────────────────────────────────────────────

def test_a_name_the_cio_answers_is_labelled_with_the_cio_answer():
    rows = {r["symbol"]: r for r in _build()["panel"]["positions"]["rows"]}
    assert rows["DEMOA"]["stance"] == "CIO: raise stop"
    assert rows["DEMOA"]["stance_engine"] == "exit review"     # the projection's label, kept and attributed
    assert rows["DEMOB"]["stance"] == "CIO: hold"
    assert rows["DEMOB"]["stance_engine"] == "exit review"


def test_a_name_the_cio_does_not_answer_keeps_the_projections_stance():
    rows = {r["symbol"]: r for r in _build()["panel"]["positions"]["rows"]}
    # DEMOD: NO_ACTION is not a verdict; DEMOC: the ask is already satisfied in the broker (state done)
    for sym in ("DEMOD", "DEMOC"):
        assert rows[sym]["stance"] == "exit review", sym
        assert "stance_engine" not in rows[sym], sym


def test_two_verdicts_never_reach_the_operator_for_one_name():
    rows = {r["symbol"]: r for r in _build()["panel"]["positions"]["rows"]}
    # DEMOA and DEMOB get the CIO's answer in the Stance column; the projection's word is NOT what the operator
    # reads there — it is attributed to the engine beside it.
    for sym in ("DEMOA", "DEMOB"):
        assert rows[sym]["stance"].startswith("CIO: "), sym
        assert rows[sym]["stance"] != rows[sym]["stance_engine"], sym
    # the names the CIO never answered keep the projection's label as their stance, and nothing claims otherwise
    assert rows["DEMOD"]["stance"] == "exit review" and "stance_engine" not in rows["DEMOD"]


def test_a_stale_synopsis_leaves_the_tables_own_stance():
    sc = copy.deepcopy(SC)
    sc["freshness"]["stale"] = True
    rows = {r["symbol"]: r for r in _build(sc=sc)["panel"]["positions"]["rows"]}
    assert rows["DEMOA"]["stance"] == "exit review" and "stance_engine" not in rows["DEMOA"]


def test_an_actionable_answer_outranks_a_hold_across_accounts():
    v = h._cio_verdicts({"cio_brief": {"stop_advice": [
        {"symbol": "DEMOA", "account": "a", "answer": "HOLD"},
        {"symbol": "DEMOA", "account": "b", "answer": "RAISE"}]}})
    assert v == {"DEMOA": "CIO: raise stop"}
    # and the reverse order is the same answer, not whichever row came last
    v = h._cio_verdicts({"cio_brief": {"stop_advice": [
        {"symbol": "DEMOA", "account": "b", "answer": "RAISE"},
        {"symbol": "DEMOA", "account": "a", "answer": "HOLD"}]}})
    assert v == {"DEMOA": "CIO: raise stop"}


def test_the_buys_gate_helper_reads_facts_it_can_trace():
    assert h._buy_hold({}) is None and h._buy_hold(None) is None
    assert h._buy_hold({"gate": {"value": "OPEN", "source_id": "s", "as_of": "t"}}) is None
    gated = h._buy_hold({"gate": {"value": "NONE", "source_id": "s", "as_of": "t"},
                         "line": {"value": "No new buys", "source_id": "s", "as_of": "t"}})
    assert gated == {"gate": {"value": "NONE", "source_id": "s", "as_of": "t"},
                     "line": {"value": "No new buys", "source_id": "s", "as_of": "t"}}
