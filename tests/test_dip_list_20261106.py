"""Dip list with valuation (PKG-SELLOFF-INTEL-20261106 E), and the deep brief's analyst facts.

Synthetic fixtures only: invented symbols, prices and estimates, dated 2030. Nothing here reads a database or a file
outside the test's temp directory.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.lib.market_risk import contract
from scripts.lib.market_risk import deep_brief_facts as dbf
from scripts.lib.market_risk import dip_list as dl

TODAY = date(2030, 2, 6)  # a Wednesday


def weekdays(n: int, end: date = date(2030, 2, 5)) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


SESSIONS = weekdays(22)
GROUPS = [
    {"key": "tech", "label": "Technology", "kind": "sector", "symbols": ["XLK"]},
    {"key": "semis", "label": "Semis", "kind": "theme", "symbols": ["SMH"]},
]
SECTORS = {
    "groups": [
        {"key": "tech", "label": "Technology", "kind": "sector", "state": "STRESS", "r5": -6.0, "rs5": -4.0},
        {"key": "semis", "label": "Semis", "kind": "theme", "state": "WEAK", "r5": -5.0, "rs5": -3.0},
        {"key": "staples", "label": "Staples", "kind": "sector", "state": "LEADING", "r5": 1.0, "rs5": 2.0},
    ]
}


def path(peak: float, low: float, peak_at: int = 5, n: int = 22) -> list[dict]:
    """Closes rising to ``peak`` on session ``peak_at``, then a straight decline to ``low`` on the last session."""
    closes = []
    for i in range(n):
        if i <= peak_at:
            closes.append(peak * (0.9 + 0.1 * i / max(peak_at, 1)))
        else:
            closes.append(peak + (low - peak) * (i - peak_at) / (n - 1 - peak_at))
    return [{"date": d.isoformat(), "close": round(c, 4)} for d, c in zip(SESSIONS[-n:], closes)]


def trend(cur: float, d7=None, d30=None, d60=None, d90=None) -> list[dict]:
    return [
        {"index": "0q", "current": 1.0},
        {"index": "+1y", "current": cur, "7daysAgo": d7, "30daysAgo": d30, "60daysAgo": d60, "90daysAgo": d90},
    ]


def yrow(sym, snap, *, price=999.0, target=150.0, rating=1.8, analysts=20, eps=None, revs=(5, 1), earn=None):
    ext = {"eps_trend": eps or trend(10.0, 10.0, 10.0, 10.0, 10.0)}
    if revs is not None:
        ext["eps_revisions"] = [{"index": "+1y", "upLast30days": revs[0], "downLast30days": revs[1]}]
    if earn:
        ext["earnings_dates"] = [{"index": f"{earn}T20:00:00", "EPS Estimate": 1.0, "Reported EPS": None}]
    return {
        "symbol": sym,
        "snapshot_date": snap.isoformat() if isinstance(snap, date) else snap,
        "current_price": price,
        "target_mean_price": target,
        "recommendation_mean": rating,
        "recommendation_key": "buy",
        "number_of_analyst_opinions": analysts,
        "data": {"extended": ext},
    }


def cand(sym, sector="Technology", industry="Software", conviction=60):
    return {"symbol": sym, "sector": sector, "industry": industry, "conviction": conviction, "type": "stock"}


def build(cands, rows, bars, **kw):
    return dl.build(
        sectors_block=kw.pop("sectors", SECTORS),
        policy_groups=GROUPS,
        candidates=cands,
        analyst_rows=rows,
        bars=bars,
        today=TODAY,
        **kw,
    )


def by_symbol(p):
    return {r["symbol"]: r for r in p["rows"]}


# -- prices come from the daily closes, not the sparse Yahoo capture ------------------------------------------------


def test_price_high_and_drawdown_come_from_daily_closes_not_the_yahoo_price():
    # One Yahoo record in six weeks (the sparse case that wrongly dropped 79 names) and a nonsense Yahoo price.
    p = build([cand("AAA")], [yrow("AAA", TODAY, price=1.0)], {"AAA": path(100.0, 80.0)})
    r = by_symbol(p)["AAA"]
    assert r["price"] == 80.0 and r["high_20"] == 100.0
    assert r["high_session"] == SESSIONS[5].isoformat()
    assert r["drawdown_pct"] == -20.0
    assert r["price_session"] == SESSIONS[-1].isoformat()
    assert "daily closes" in p["price_basis"] and SESSIONS[-1].isoformat() in p["price_basis"]


def test_the_high_is_taken_over_the_last_20_sessions_only():
    bars = path(100.0, 80.0, peak_at=5)
    bars[0]["close"] = 500.0  # 22 sessions back: outside the 20-session window
    r = by_symbol(build([cand("AAA")], [yrow("AAA", TODAY)], {"AAA": bars}))["AAA"]
    assert r["high_20"] == 100.0 and r["sessions"] == 20


def test_one_close_per_session_and_the_first_given_wins():
    bars = path(100.0, 80.0) + [{"date": SESSIONS[-1].isoformat(), "close": 1.0}]
    r = by_symbol(build([cand("AAA")], [yrow("AAA", TODAY)], {"AAA": bars}))["AAA"]
    assert r["price"] == 80.0


# -- forward P/E now vs at the high, only where the history reaches it --------------------------------------------


def _high_capture(bars):
    hi = max(bars[-20:], key=lambda b: b["close"])
    return dl.next_weekday(date.fromisoformat(hi["date"]))


def test_pe_at_the_high_uses_the_own_record_captured_after_the_high_session():
    bars = path(100.0, 80.0)
    cap = _high_capture(bars)
    rows = [yrow("AAA", cap, eps=trend(8.0)), yrow("AAA", TODAY, eps=trend(10.0, d30=9.0))]
    r = by_symbol(build([cand("AAA")], rows, {"AAA": bars}))["AAA"]
    assert r["fpe_pre"] == 12.5 and r["fpe_now"] == 8.0  # 100/8 at the high; 80/10 now
    assert r["fpe_pre_basis"] == f"own record {cap.isoformat()}"
    assert r["fpe_change_pct"] == -36.0


def test_pe_at_the_high_falls_back_to_the_nearest_lookback_column_within_tolerance():
    bars = path(100.0, 80.0, peak_at=2)  # the high is about a month before today
    rows = [yrow("AAA", TODAY, eps=trend(10.0, d7=9.9, d30=5.0))]
    r = by_symbol(build([cand("AAA")], rows, {"AAA": bars}))["AAA"]
    assert r["fpe_pre"] == 20.0 and r["fpe_pre_basis"].startswith("today's record, estimate 30 days ago")


def test_no_pe_at_the_high_when_the_history_does_not_reach_it_and_the_row_says_why():
    bars = path(100.0, 80.0, peak_at=5)
    rows = [yrow("AAA", TODAY, eps=trend(10.0))]  # no lookback columns, no own record near the high
    r = by_symbol(build([cand("AAA")], rows, {"AAA": bars}))["AAA"]
    assert r["fpe_pre"] is None and r["fpe_change_pct"] is None
    assert "EPS history does not reach it" in r["fpe_pre_missing"]
    assert "at the high: n/a (no estimate within" in dl.line(r)


def test_no_pe_now_without_an_eps_trend_says_why():
    rows = [yrow("AAA", TODAY)]
    rows[0]["data"]["extended"]["eps_trend"] = []
    r = by_symbol(build([cand("AAA")], rows, {"AAA": path(100.0, 80.0)}))["AAA"]
    assert r["fpe_now"] is None and r["fpe_now_missing"] == "no EPS trend in the analyst record"
    assert "fwd P/E n/a now (no EPS trend in the analyst record)" in dl.line(r)


def test_history_depth_is_measured_from_the_rows():
    rows = [yrow("AAA", d) for d in SESSIONS[-5:]] + [yrow("BBB", SESSIONS[-1])]
    rows[0]["data"]["extended"]["eps_trend"] = []
    h = build([cand("AAA"), cand("BBB")], rows, {})["history"]
    assert h["snapshot_days"] == 5 and h["eps_trend_days"] == 4 and h["symbols"] == 2
    assert h["first_snapshot"] == SESSIONS[-5].isoformat()


# -- the quality filter: stated, every exclusion counted with its reason ------------------------------------------


def test_quality_filter_counts_every_exclusion_with_its_reason():
    cands = [cand(s) for s in ("CHEAP", "THIN", "NOBARS", "NOHIST", "FLAT", "SPLIT", "SHORT", "OK")]
    rows = [yrow(s, TODAY) for s in ("CHEAP", "NOBARS", "FLAT", "SPLIT", "SHORT", "OK")] + [
        yrow("THIN", TODAY, analysts=3)
    ]
    split = path(100.0, 80.0)
    split[10]["close"] = split[9]["close"] / 3
    bars = {
        "CHEAP": path(6.0, 4.0),
        "THIN": path(100.0, 80.0),
        "NOHIST": path(100.0, 80.0),
        "FLAT": path(100.0, 98.0),
        "SPLIT": split,
        "SHORT": path(100.0, 80.0, peak_at=2, n=8),
        "OK": path(100.0, 80.0),
    }
    p = build(cands, rows, bars)
    ex = p["excluded"]
    assert ex["price under $5"] == ["CHEAP"]
    assert ex["fewer than 8 analysts"] == ["THIN"]
    assert ex["no daily closes"] == ["NOBARS"]
    assert ex["not in the analyst history"] == ["NOHIST"]
    assert ex["drawdown shallower than -5%"] == ["FLAT"]
    assert ex["fewer than 10 daily closes"] == ["SHORT"]
    assert any(k.startswith("price history break") and v == ["SPLIT"] for k, v in ex.items())
    assert [r["symbol"] for r in p["rows"]] == ["OK"] and p["members"] == 8
    text = dl.render(p)
    assert "Quality filter: price at least $5; at least 8 analysts" in text
    assert "- price under $5 (1): CHEAP" in text


def test_only_members_of_stressed_groups_and_never_etfs():
    cands = [
        cand("TECH1"),
        cand("CHIP", sector="Industrials", industry="Semiconductor Equipment"),
        cand("FOOD", sector="Consumer Staples"),
        {**cand("XLK"), "type": "etf"},
    ]
    rows = [yrow(s, TODAY) for s in ("TECH1", "CHIP", "FOOD", "XLK")]
    bars = {s: path(100.0, 80.0) for s in ("TECH1", "CHIP", "FOOD", "XLK")}
    p = build(cands, rows, bars)
    got = by_symbol(p)
    assert set(got) == {"TECH1", "CHIP"} and got["CHIP"]["groups"] == ["semis"] and p["members"] == 2


def test_no_stressed_group_means_no_list_and_the_text_says_so():
    calm = {"groups": [dict(g, state="NEUTRAL") for g in SECTORS["groups"]]}
    p = build([cand("AAA")], [yrow("AAA", TODAY)], {"AAA": path(100.0, 80.0)}, sectors=calm)
    assert p["rows"] == [] and p["members"] == 0
    assert "No group is STRESS or WEAK, so there is no dip list today." in dl.render(p)


# -- own-news falls ----------------------------------------------------------------------------------------------


def _group(n=6):
    cands = [cand(f"G{i}") for i in range(n)]
    rows = [yrow(f"G{i}", TODAY) for i in range(n)]
    bars = {f"G{i}": path(100.0 + i, 80.0 + i) for i in range(n)}
    return cands, rows, bars


def test_a_one_session_fall_far_worse_than_the_group_is_flagged_and_held_back():
    cands, rows, bars = _group()
    news = path(100.0, 70.0)
    news[-3]["close"] = news[-4]["close"] * 0.78  # -22% on one session while the group drifts about -1%
    cands.append(cand("NEWS"))
    rows.append(yrow("NEWS", TODAY))
    bars["NEWS"] = news
    p = build(cands, rows, bars)
    ev = by_symbol(p)["NEWS"]["own_news_day"]
    assert ev and ev["session"] == SESSIONS[-3].isoformat() and ev["pct"] == pytest.approx(-22.0, abs=0.01)
    assert ev["group"] == "tech" and ev["group_median_pct"] > -3
    assert "NEWS" in p["screen_held_back"]["fell far more than its group on one session (own news, likely)"]
    assert "likely its own news" in dl.line(by_symbol(p)["NEWS"])
    assert all(by_symbol(p)[f"G{i}"]["own_news_day"] is None for i in range(6))


def test_a_fall_across_a_gap_in_the_closes_is_not_a_one_session_fall():
    cands, rows, bars = _group()
    gap = path(100.0, 90.0)
    gap[-3]["close"] = gap[-5]["close"] * 0.78
    del gap[-4]  # one missing session: the -22% spans two sessions
    cands.append(cand("GAP"))
    rows.append(yrow("GAP", TODAY))
    bars["GAP"] = gap
    assert by_symbol(build(cands, rows, bars))["GAP"]["own_news_day"] is None


def test_no_flag_without_enough_group_members_for_a_median():
    cands, rows, bars = _group(3)
    news = path(100.0, 90.0)
    news[-3]["close"] = news[-4]["close"] * 0.78
    cands.append(cand("NEWS"))
    rows.append(yrow("NEWS", TODAY))
    bars["NEWS"] = news
    assert by_symbol(build(cands, rows, bars))["NEWS"]["own_news_day"] is None


# -- the narrower screen ------------------------------------------------------------------------------------------


def test_screen_states_each_hold_back_reason_and_ranks_by_upside():
    names = {
        "UP1": dict(target=160.0),
        "UP2": dict(target=200.0),
        "SHALLOW": dict(),
        "FEW": dict(analysts=9),
        "HOLDR": dict(rating=2.6),
        "CUT": dict(eps=trend(9.0, d30=10.0)),
        "NOTREND": dict(eps=[{"index": "0q", "current": 1.0}]),
        "REVDN": dict(revs=(1, 4)),
        "SOON": dict(earn=(TODAY + timedelta(days=3)).isoformat()),
        "NOREV": dict(revs=None),  # unknown revision counts must not pass "up at least down"
    }
    cands = [cand(s) for s in names]
    rows = [yrow(s, TODAY, **kw) for s, kw in names.items()]
    bars = {s: path(100.0, 80.0) for s in names}
    bars["SHALLOW"] = path(100.0, 92.0)
    p = build(cands, rows, bars)
    held = p["screen_held_back"]
    assert p["shortlist"] == ["UP2", "UP1"]  # +150% before +100%
    assert held["drawdown shallower than -12%"] == ["SHALLOW"]
    assert held["fewer than 10 analysts"] == ["FEW"]
    assert held["consensus rating weaker than 2.0"] == ["HOLDR"]
    assert held["next-year EPS estimate lowered in 30 days"] == ["CUT"]
    assert held["no next-year EPS trend in the analyst record"] == ["NOTREND"]
    assert held["more EPS revisions down than up in 30 days"] == ["REVDN"]
    assert held["earnings within 7 days"] == ["SOON"]
    assert held["EPS revision counts unknown"] == ["NOREV"]
    text = dl.render(p)
    assert "Narrower screen (stated; ranked by distance to the consensus target)" in text
    assert text.index("**UP2**", text.index("Narrower screen")) < text.index("**UP1**", text.index("Narrower screen"))


def test_earnings_fallback_fills_only_a_missing_date():
    rows = [yrow("AAA", TODAY, earn="2030-03-01"), yrow("BBB", TODAY)]
    bars = {"AAA": path(100.0, 80.0), "BBB": path(100.0, 80.0)}
    p = build([cand("AAA"), cand("BBB")], rows, bars, earnings={"AAA": "2030-02-07", "BBB": "2030-02-20"})
    assert by_symbol(p)["AAA"]["next_earnings"] == "2030-03-01"
    assert by_symbol(p)["BBB"]["next_earnings"] == "2030-02-20"


# -- summary: earnings or the multiple? ---------------------------------------------------------------------------


def test_summary_counts_eps_targets_revisions_and_the_median_pe_change_with_n():
    bars = path(100.0, 80.0)
    cap = _high_capture(bars)
    rows = [
        yrow("AAA", cap, target=150.0, eps=trend(8.0)),
        yrow("AAA", TODAY, target=140.0, eps=trend(10.0, d30=9.0), revs=(3, 1)),
        yrow("BBB", cap, target=150.0, eps=trend(10.0)),
        yrow("BBB", TODAY, target=160.0, eps=trend(9.0, d30=10.0), revs=(0, 2)),
    ]
    s = build([cand("AAA"), cand("BBB")], rows, {"AAA": bars, "BBB": bars})["summary"]
    assert (s["eps_estimate_raised"], s["eps_estimate_cut"], s["eps_estimate_n"]) == (1, 1, 2)
    assert (s["targets_raised"], s["targets_cut"], s["targets_n"]) == (1, 1, 2)
    assert (s["revisions_up"], s["revisions_down"], s["revisions_n"]) == (3, 3, 2)
    # AAA 12.5 -> 8.0 (-36%), BBB 10.0 -> 8.9 (-11%, P/E rounded first): median -23.5
    assert s["median_fpe_change_pct"] == -23.5 and s["fpe_pairs_n"] == 2


def test_percent_text_never_prints_minus_zero():
    assert dl._p(-0.04) == "0.0%" and dl._p(-0.4, 0) == "0%" and dl._p(-0.6, 0) == "-1%" and dl._p(None) == "n/a"


# -- advisory only ------------------------------------------------------------------------------------------------


def test_payload_has_no_behaviour_fields_and_the_text_no_sizing():
    p = build([cand("AAA")], [yrow("AAA", TODAY)], {"AAA": path(100.0, 80.0)})
    contract.assert_no_behavior_fields(p)
    text = dl.render(p)
    assert "Advisory screen, not a recommendation: no orders, sizes or stop levels." in text
    from scripts.lib.buy_ready_cio_review import _SIZING_TEXT

    assert not _SIZING_TEXT.search(text)


def test_render_refuses_sizing_text(monkeypatch):
    p = build([cand("AAA")], [yrow("AAA", TODAY)], {"AAA": path(100.0, 80.0)})
    p["rows"][0]["rating_key"] = "buy 100 shares"
    with pytest.raises(ValueError, match="sizing text"):
        dl.render(p)


# -- the CLI: read-only collection --------------------------------------------------------------------------------


class FakeReader:
    def __init__(self, rows, bars):
        self.rows, self.bars, self.calls = rows, bars, []

    def analyst_history(self, *, start, end, symbols=None):
        self.calls.append(("analyst_history", sorted(symbols or [])))
        return [r for r in self.rows if r["symbol"] in set(symbols or [])]

    def daily_bars(self, symbols, *, sessions, end):
        self.calls.append(("daily_bars", sessions))
        return [dict(b, symbol=s) for s in symbols for b in self.bars.get(s, [])]

    def earnings_calendar(self, *, start, end, now=None):
        self.calls.append(("earnings_calendar",))
        return [{"symbol": "AAA", "date": "2030-02-20", "kind": "next"}]


def test_cli_collect_reads_members_closes_and_history_and_writes_nothing(tmp_path):
    from scripts import market_risk_dip_list as cli
    from scripts.lib.market_risk_projection import SNAPSHOT_REL

    snap = tmp_path / SNAPSHOT_REL
    snap.parent.mkdir(parents=True)
    snap.write_text(json.dumps({"sectors": SECTORS}))
    proj = tmp_path / "data" / "cio" / "cio_opportunity_projection.json"
    proj.parent.mkdir(parents=True)
    proj.write_text(json.dumps({"items": {"AAA": cand("AAA"), "FOOD": cand("FOOD", sector="Consumer Staples")}}))
    before = sorted(p for p in tmp_path.rglob("*"))
    reader = FakeReader([yrow("AAA", TODAY, revs=None)], {"AAA": path(100.0, 80.0)})
    now = datetime(2030, 2, 6, 15, 0, tzinfo=timezone.utc)
    p = cli.collect(now, reader, {"sectors": {"groups": GROUPS}}, tmp_path, days=45)
    assert ("analyst_history", ["AAA"]) in reader.calls and ("daily_bars", 25) in reader.calls
    assert [r["symbol"] for r in p["rows"]] == ["AAA"] and p["rows"][0]["next_earnings"] == "2030-02-20"
    assert sorted(p for p in tmp_path.rglob("*")) == before


# -- the deep brief's analyst facts read the Yahoo history --------------------------------------------------------


NOW = datetime(2030, 2, 6, 15, 0, tzinfo=timezone.utc)


def test_deep_brief_analyst_source_reads_the_yahoo_history_read_only():
    seen = []

    class Reader:
        def _rows(self, sql, params):
            seen.append((sql, params))
            if "tgt_now" in sql:
                return [
                    {"symbol": "AAA", "tgt_now": 110.0, "as_of": date(2030, 2, 6), "eps_trend": trend(10.5, d30=10.0)},
                    {"symbol": "BBB", "tgt_now": 90.0, "as_of": date(2030, 2, 5), "eps_trend": None},
                ]
            return [{"symbol": "AAA", "tgt_then": 100.0}]

    rows = dbf.PgSources(Reader()).analyst_revisions(["AAA", "BBB"], NOW)
    assert rows[0] == {
        "symbol": "AAA",
        "tgt_now": 110.0,
        "tgt_then": 100.0,
        "eps_next_fy": 10.5,
        "eps_next_fy_30d_ago": 10.0,
        "as_of": "2030-02-06",
    }
    assert rows[1]["tgt_then"] is None and rows[1]["eps_next_fy"] is None
    for sql, params in seen:
        assert sql.lstrip().upper().startswith("SELECT") and "yahoo_analyst_targets_history" in sql
        assert "analyst_consensus_history" not in sql and "created_at <= %s" in sql and NOW in params
        assert " target_price" not in sql  # the old store's column: NULL on every row there, absent here
    assert "target_mean_price AS tgt_now" in seen[0][0] and "target_mean_price AS tgt_then" in seen[1][0]


class _CalReader:
    def earnings_calendar(self, *, start, end, now=None):
        return []


def _catalyst_facts(rev):
    class Src(dbf.NullSources):
        def analyst_revisions(self, symbols, end):
            return rev

    p = dbf.Pack(NOW)
    out = dbf._catalysts(p, _CalReader(), NOW, ["AAA", "BBB", "CCC"], Src(), {}, {})
    return p, out


def test_deep_brief_states_target_and_eps_estimate_direction_with_counts_and_source():
    rev = [
        {
            "symbol": "AAA",
            "tgt_now": 130.0,
            "tgt_then": 100.0,
            "eps_next_fy": 10.5,
            "eps_next_fy_30d_ago": 10.0,
            "as_of": "2030-02-06",
        },
        {
            "symbol": "BBB",
            "tgt_now": 90.0,
            "tgt_then": 100.0,
            "eps_next_fy": 9.0,
            "eps_next_fy_30d_ago": 10.0,
            "as_of": "2030-02-05",
        },
        {
            "symbol": "CCC",
            "tgt_now": 100.0,
            "tgt_then": 100.0,
            "eps_next_fy": 5.0,
            "eps_next_fy_30d_ago": 5.0,
            "as_of": "2030-02-05",
        },
    ]
    p, out = _catalyst_facts(rev)
    f = {x["label"]: x for x in p.facts}
    assert f["analyst revisions"]["source"] == "yahoo_analyst_targets_history"
    assert "across 3 names: mean change +6.7%; raised on 1, cut on 1" in f["analyst revisions"]["text"]
    assert f["eps estimates"]["source"] == "yahoo_analyst_targets_history"
    assert (
        f["eps estimates"]["text"]
        == "Next-year EPS estimates over 30 days across 3 names: raised on 1, cut on 1, unchanged on 1"
    )
    assert f["eps estimates"]["as_of"] == "2030-02-06"
    assert (out["eps_estimate_raised"], out["eps_estimate_cut"]) == (1, 1)


def test_deep_brief_says_unknown_rather_than_zero_when_the_history_is_missing():
    p, out = _catalyst_facts(
        [{"symbol": "AAA", "tgt_now": 110.0, "tgt_then": None, "eps_next_fy": None, "eps_next_fy_30d_ago": None}]
    )
    labels = {x["label"] for x in p.facts}
    assert "analyst revisions" not in labels and "eps estimates" not in labels
    missing = {u["what"] for u in p.unknown}
    assert {"analyst revisions", "eps estimates"} <= missing
    assert "analyst_change" not in out and "eps_estimate_raised" not in out


def test_an_unknown_analyst_count_is_excluded_as_unknown_never_read_as_zero():
    p = build([cand("NOCOUNT")], [yrow("NOCOUNT", TODAY, analysts=None)], {"NOCOUNT": path(100.0, 80.0)})
    assert p["excluded"] == {"analyst count unknown": ["NOCOUNT"]} and p["rows"] == []
