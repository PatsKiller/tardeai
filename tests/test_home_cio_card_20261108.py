"""LQ-20261107-1352: the Home CIO card + Market Risk panel projection (HomeCioCard@v1, design cio-card v5).

Synthetic fixtures only (public repo): symbols DEMOA/DEMOB/DEMOC, account labels "Example IRA" / "Example Taxable",
round dollar figures. Asserts shape, provenance on every value, untraceable values dropped, stale input → no advice,
and that the sector engines are shown side by side, never blended."""
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


def _bars(sym, start, step, n=25):
    return [{"symbol": sym, "session": f"2031-02-{d:02d}", "close": round(start + step * i, 2)}
            for i, d in enumerate(range(1, n + 1))]


MR = {
    "tier": "RED", "score": 59.584, "as_of": MR_AT, "stale": False, "age_hours": 0.2,
    "confirming": {"n": 2, "of": 4},
    "deescalates_if": "RED -> ORANGE if score below 75. RED is held by the completed-session rule: 2 of 3 completed "
                      "trading sessions below this tier recorded; current readings support YELLOW.",
    "contributors": [{"name": "Technical", "points": 33.6, "detail": "breakdown", "as_of": "2031-03-07"},
                     {"name": "Options flow", "points": 26.0, "detail": "put/call high", "as_of": "2031-03-07"},
                     {"name": "Breadth", "points": 0.0, "detail": "ok"}],
    "categories": [{"name": "Technical", "state": "STRESS", "detail": "x"},
                   {"name": "Options flow", "state": "STRESS", "detail": "y"},
                   {"name": "Breadth", "state": "CALM", "detail": "fine"},
                   {"name": "Extended hours", "state": "CALM", "detail": "/ES level-only (no dated close)"}],
    "sectors": {"as_of": "2031-03-07", "stressed": ["Technology"], "resilient": ["Healthcare", "Staples"],
                "sectors_hit": 1, "sectors_measured": 11, "sectors_down": 8,
                "groups": [{"key": "tech", "label": "Technology", "kind": "sector", "symbols": ["XLK"], "state": "STRESS", "rs20": -11.0},
                           {"key": "comm", "label": "Communications", "kind": "sector", "symbols": ["XLC"], "state": "RESILIENT", "rs20": 0.5},
                           {"key": "healthcare", "label": "Healthcare", "kind": "sector", "symbols": ["XLV"], "state": "RESILIENT", "rs20": 13.8, "dd20": -2.6},
                           {"key": "staples", "label": "Staples", "kind": "sector", "symbols": ["XLP"], "state": "RESILIENT", "rs20": 13.5, "dd20": -2.0},
                           {"key": "utilities", "label": "Utilities", "kind": "sector", "symbols": ["XLU"], "state": "NEUTRAL", "rs20": 9.7}]},
    "heatmap": [{"key": "healthcare", "state": "RESILIENT"}, {"key": "staples", "state": "RESILIENT"},
                {"key": "utilities", "state": "NEUTRAL"}],
    "leadership": {"groups": {"healthcare": {"class": "LEADERSHIP_CONFIRMED"}, "staples": {"class": "UNKNOWN"}}},
    "episode": {"id": "mre-demo", "opened_at": "2031-03-03T21:30:00+00:00", "acknowledged_at": None, "current_tier": "RED"},
    "hedge": {"verdict": "WATCH", "candidates": ["SH", "PSQ"], "as_of": "2031-03-07T22:00:00+00:00",
              "thresholds": {"trigger_book_pct": 10.0, "index_trigger_lagging_sectors": 4, "materiality_exposure_pct": 8.0},
              "lagging_count": 1, "stressed_usd": 7000.0, "stressed_pct_book": 7.0,
              "stressed_breakdown": [{"key": "tech", "label": "Technology", "usd": 7000.0}]},
    "book_exposure": {"as_of": "2031-03-10", "total_usd": 100000.0, "cash_usd": 76000.0, "cash_pct_book": 76.0,
                      "stressed_usd": 7000.0, "stressed_pct_book": 7.0, "stops_known": True,
                      "largest_contributor": {"symbol": "DEMOA", "account_label": "Example IRA", "group": "tech", "share": 0.5},
                      "rows": [{"symbol": "DEMOA", "account_label": "Example IRA", "value_usd": 8000.0, "pct_account": 8.0,
                                "stressed_share": 0.5, "usd_exposed": 4000.0, "stop_distance_pct": 10.0, "stance": "exit review"},
                               {"symbol": "DEMOB", "account_label": "Example IRA", "value_usd": 3000.0, "pct_account": 3.0,
                                "stressed_share": 1.0, "usd_exposed": 3000.0, "stop_distance_pct": 3.8, "stance": "exit review"},
                               {"symbol": "DEMOC", "account_label": "Example Taxable", "value_usd": 2000.0, "pct_account": 2.0,
                                "stressed_share": 0.0, "usd_exposed": 0.0, "stop_distance_pct": 3.5, "stance": "hold"}],
                      "more": {"count": 1, "usd": 9.0}, "zero_exposure_symbols": ["DEMOC", "DEMOE"]},
    "reentry_watch": {"_stages_contract": "doc", "DEMOD": {"exit_date": "2031-03-07", "exit_price": 100.0, "exit_basis": "stop (matched by price)",
                                                           "status": "RE_ENTER_IF", "stages": {"last_close": 102.0, "last_date": "2031-03-07", "pct_vs_exit": 2.0,
                                                                                                 "verdict": "Confirmed", "invalidation_level": 99.5,
                                                                                                 "stage1": {"met": 1, "of": 5, "conditions": [{"text": "higher low", "met": False}]}}},
                      "DEMOOLD": {"exit_date": "2031-01-02", "exit_price": 5.0}},
    "reentry_detail": {"DEMOD": {"exit_account_label": "Example Roth", "held_elsewhere_labels": ["Example IRA"]}},
    "reentry_card": {"recent_sessions": 5, "max_rows": 5},
}

SC = {
    "freshness": {"stale": False, "window_current": True},
    "cio_brief": {
        "generated_at": SYN_AT,
        "synopsis": {
            "posture": "DEFENSIVE — HOLD CASH", "as_of": SYN_AT,
            "buys": {"line": "No new buys before CPI", "gate": "NONE", "until": "CPI Tue 03-11 08:30 ET", "until_short": "CPI Tue"},
            "book": {"positions": 5, "accounts": 2, "cash": 76000.0, "as_of": SYN_AT,
                     "largest_unprotected_risk": {"symbol": "DEMOA", "account": "example_taxable", "shares": 10.0,
                                                  "price": 100.0, "value": 1000.0, "source_id": "stop_last_known:DEMOA"}},
            "market": {"shock_class": "SECTOR"},
            "reentry": {"stage2": 3, "stage3": 0, "tracked": 20, "line": "3 near entry", "as_of": SYN_AT},
            "this_week": {"macro": [{"date": "2031-03-11", "event": "Consumer Price Index", "time_et": "08:30"},
                                    {"date": "2031-03-01", "event": "Old print", "time_et": "08:30"}],
                          "earnings": [{"symbol": "DEMOC", "date": "2031-03-10"}, {"symbol": "OTHER", "date": "2031-03-12"}]},
            "do_now": {"stop_advice_count": 4, "actionable_count": 2},
        },
        "stop_advice": [
            {"symbol": "DEMOA", "account": "example_ira", "answer": "RAISE", "stop_now": 90.0, "stop_qty": 80, "held_qty": 80,
             "suggested_stop": 95.0, "reason": "gain to lock", "as_of": SYN_AT},
            {"symbol": "DEMOA", "account": "example_taxable", "answer": "ADD_STOP", "stop_now": None, "stop_qty": 0, "held_qty": 10,
             "suggested_stop": 95.0, "reason": "no stop", "as_of": SYN_AT},
            {"symbol": "DEMOC", "account": "example_taxable", "answer": "HOLD", "as_of": SYN_AT},
        ],
    },
}

BARS = _bars("XLV", 170.0, 0.6) + _bars("XLP", 85.0, 0.2) + _bars("XLU", 41.0, 0.08, n=10)
DEFENSE = {"mode": "SHADOW", "generated_at": "2031-03-07T22:50:00+00:00",
           "account_equities": {"example_ira": 50000, "example_taxable": 5000},
           "groups": {"get_into": [{"title": "ROTATE-IN · Staples (LEADING)", "instruments": [{"symbol": "XLP", "kind": "sector ETF", "price": 99.99}]}],
                      "short_side": [{"title": "HEDGE · PSQ", "size_band": "2–5% of account equity"}]}}
MOMENTUM = {"generated_at": "2031-03-07T22:26:00+00:00",
            "rows": [{"etf": "XLC", "state": "LAGGING"}, {"etf": "XLK", "state": "LAGGING"}, {"etf": "XLV", "state": "LEADING"}]}


def _build(mr=MR, sc=SC, **kw):
    kw.setdefault("defense", DEFENSE)
    kw.setdefault("momentum", MOMENTUM)
    kw.setdefault("bars", BARS)
    return h.build(copy.deepcopy(mr), copy.deepcopy(sc), now=NOW, **kw)


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def test_shape():
    out = _build()
    assert out["schema"] == "HomeCioCard@v1" and out["advisory_only"] is True
    assert out["advice"] == {"ok": True, "reason": None}
    c, p = out["card"], out["panel"]
    assert c["tier"]["value"] == "RED" and c["score"]["value"] == 59.6
    assert c["held"]["readings_support"] == "YELLOW" and c["held"]["sessions_recorded"] == 2
    assert [d["name"] for d in c["drivers"]] == ["Technical", "Options flow"]
    assert c["score_sum"]["value"] == 59.6
    assert c["calm"]["n"] == 2 and c["calm"]["of"] == 4
    assert [g["name"] for g in c["gaps"]] == ["Extended hours"]
    assert c["catalyst"]["event"] == "Consumer Price Index"
    assert [a["symbol"] + ":" + a["answer"] for a in c["actions"]] == ["DEMOA:RAISE", "DEMOA:ADD_STOP"]
    assert c["do_now"]["n"] == 1 and c["do_now"]["of"] == 2
    # past events dropped; held earnings flagged
    tw = {x["label"]: x for x in c["this_week"]}
    assert "Old print" not in tw and tw["DEMOC earnings"]["held"] is True and tw["OTHER earnings"]["held"] is False
    assert set(p) == {"header", "exposure", "protect", "hedge", "rotate", "positions", "stopped_out"}
    # protect: the same stop actions first, then the two closest other stops
    assert [x["kind"] for x in p["protect"]] == ["action", "action", "watch", "watch"]
    assert [x["symbol"] for x in p["protect"][2:]] == ["DEMOC", "DEMOB"]
    # hedge on % of book; gap to the 8% consider line
    trig = {t["key"]: t for t in p["hedge"]["triggers"]}
    assert trig["stressed_pct_book"]["value"] == 7.0 and trig["stressed_pct_book"]["act"] == 10.0
    assert p["hedge"]["gap_to_consider_usd"] == 1000.0
    assert p["hedge"]["if_triggered"]["symbol"] == "PSQ" and p["hedge"]["if_triggered"]["proposed"] is True
    # positions: stressed only, by $ exposed
    assert [r["symbol"] for r in p["positions"]["rows"]] == ["DEMOA", "DEMOB"]
    assert [s["symbol"] for s in p["stopped_out"]] == ["DEMOD"]


def test_rotate_uses_bars_and_proposed_rule():
    rot = _build()["panel"]["rotate"]
    by = {c["symbol"]: c for c in rot["candidates"]}
    assert list(by) == ["XLV", "XLP", "XLU"]
    xlv = by["XLV"]
    assert xlv["close"]["value"] == round(170.0 + 0.6 * 24, 2)
    assert xlv["close"]["source_id"].startswith("market_ohlcv_bars:daily:XLV")
    assert xlv["avg20"]["value"] == round(sum(170.0 + 0.6 * i for i in range(5, 25)) / 20, 2)
    assert xlv["proposed"] == {"target_pct": 4.0, "target_usd": 4000.0, "tranche1_usd": 1200.0,
                               "shares": int(1200.0 // xlv["close"]["value"]), "proposed": True}
    assert by["XLP"]["proposed"]["target_pct"] == 3.0
    # neutral: a target only, no tranche until it turns resilient; fewer than 20 bars → no 20-day average
    assert by["XLU"]["qualifies"] is False and by["XLU"]["proposed"]["tranche1_usd"] is None
    assert "avg20" not in by["XLU"]
    assert rot["plan"]["proposed"] is True and rot["plan"]["tranche1_usd"] == 1200.0 + 900.0


def test_every_value_has_provenance():
    out = _build()
    for path, node in _walk({"card": out["card"], "panel": out["panel"], "notes": out["notes"]}):
        if "value" in node:
            assert node.get("source_id") and node.get("as_of"), path
    # every grouped record / list item carries its own provenance (hedge triggers and proposals are inside one)
    for key in ("drivers", "gaps", "actions", "this_week"):
        for x in out["card"][key]:
            assert x["source_id"] and x["as_of"], key
    for key in ("protect", "stopped_out"):
        for x in out["panel"][key]:
            assert x["source_id"] and x["as_of"], key
    for c in out["panel"]["rotate"]["candidates"]:
        assert c["source_id"] and c["as_of"]
    for n in out["notes"]:
        assert n["source_id"] and n["as_of"]


def test_untraceable_values_dropped():
    sc = copy.deepcopy(SC)
    sc["cio_brief"]["synopsis"]["book"]["largest_unprotected_risk"]["source_id"] = None
    sc["cio_brief"]["stop_advice"][0]["as_of"] = None
    sc["cio_brief"]["generated_at"] = None
    mr = copy.deepcopy(MR)
    mr["book_exposure"]["as_of"] = None
    mr["book_exposure"]["cash_pct_book"] = None
    out = _build(mr=mr, sc=sc)
    assert out["card"]["largest_unprotected"] is None
    assert [a["account"] for a in out["card"]["actions"]] == ["example_taxable"]
    # the book join falls back to the record time; a missing number is dropped, not zero
    assert out["panel"]["exposure"]["cash_pct_book"] is None
    assert out["panel"]["exposure"]["book_usd"]["as_of"] == MR_AT
    assert h.fact(1.0, None, "t") is None and h.fact(1.0, "s", None) is None and h.fact(None, "s", "t") is None
    assert h.item(None, "t", a=1) is None


def test_no_bars_no_prices_no_shares():
    rot = _build(bars=[])["panel"]["rotate"]
    for c in rot["candidates"]:
        assert "close" not in c and "avg20" not in c
        assert c["proposed"]["shares"] is None


@pytest.mark.parametrize("mutate,reason", [
    (lambda mr, sc: mr.update(stale=True, age_hours=5.0), "stale"),
    (lambda mr, sc: sc["freshness"].update(stale=True), "CIO synopsis"),
    (lambda mr, sc: sc["freshness"].update(window_current=False), "CIO synopsis"),
    (lambda mr, sc: sc["cio_brief"].pop("synopsis"), "no CIO synopsis"),
])
def test_stale_input_no_advice(mutate, reason):
    mr, sc = copy.deepcopy(MR), copy.deepcopy(SC)
    mutate(mr, sc)
    out = _build(mr=mr, sc=sc)
    assert out["advice"]["ok"] is False and reason in out["advice"]["reason"]
    assert out["card"]["actions"] == [] and out["card"]["do_now"] is None
    assert out["panel"]["protect"] == []
    assert out["panel"]["hedge"].get("if_triggered") is None
    assert all("proposed" not in c for c in out["panel"]["rotate"]["candidates"])
    assert out["panel"]["rotate"].get("plan") is None
    # facts still show
    assert out["card"]["tier"]["value"] == "RED"


def test_not_evaluated_renders_nothing():
    out = h.build({"state": "not_evaluated", "reason": "x"}, SC, now=NOW)
    assert out["card"] is None and out["panel"] is None and out["advice"]["ok"] is False


def test_held_only_when_readings_differ():
    mr = copy.deepcopy(MR)
    mr["deescalates_if"] = "no hold clause"
    assert _build(mr=mr)["card"]["held"] is None


def test_engines_shown_not_blended():
    out = _build()
    topics = {n["topic"]: n for n in out["notes"]}
    # sector state stays the market-risk record's; the other engine appears only in the notes
    assert "Communications: market risk RESILIENT, sector momentum LAGGING" in topics["Sector state"]["text"]
    assert "Technology" not in topics["Sector state"]["text"]  # STRESS vs LAGGING mean the same thing
    assert "Healthcare" not in topics["Sector state"]["text"]  # RESILIENT vs LEADING mean the same thing
    assert "XLP: defense desk 99.99" in topics["Prices"]["text"]
    assert topics["Freshness"]["text"].startswith("Defense record mode SHADOW")
    assert "$55,000" in topics["Sizing base"]["text"] and "$100,000" in topics["Sizing base"]["text"]
    xlp = {c["symbol"]: c for c in out["panel"]["rotate"]["candidates"]}["XLP"]
    assert xlp["close"]["value"] != 99.99 and xlp["state"] == "RESILIENT"


def test_no_order_vocabulary_leaks_into_shape():
    out = _build()
    keys = {k for _, node in _walk(out) for k in node}
    assert not keys & {"order_id", "place_order", "account_number", "order"}
