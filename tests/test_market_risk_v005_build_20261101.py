"""Design home/v005 build: re-entry Stage 1/2, per-account exits (a same-account re-buy is a holding), value-weighted
book exposure, issuer segments, projection pass-through and the API-side dollar join. Synthetic data only."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from scripts.lib import market_risk_book_dollars as bd
from scripts.lib import market_risk_projection as proj
from scripts.lib.market_risk import book_precision as bp
from scripts.lib.market_risk import lookthrough as lt
from scripts.lib.market_risk import reentry_stages as rs

POLICY = {
    "reentry_watch": {
        "stage1": {"volume_ratio_min": 1.0, "volume_avg_sessions": 5, "group_rs_sessions": 3, "hedging_peak_sessions": 3,
                   "hedging_ease_pct": 10, "blocked_tiers": ["ORANGE", "RED"]},
        "stage2": {"confirm_ma_sessions": [10, 20], "confirm_above_exit": True},
        "short_history_anchor": "swing_low_vwap",
        "verdict": {"basing_min_sessions": 3, "basing_band_pct": 3.0, "invalidation_sessions": 10, "trend_sessions": 5},
    },
    "home_review": {"max_items": 5, "max_position_rows": 5, "stop_near_pct": 5.0, "stressed_min_usd": 1000},
    "positions": {"materiality": {"min_shares": 1.0, "min_market_value": 1000.0}},
}


def _bars(rows, start=date(2026, 9, 1)):
    out = []
    for i, (o, h, lo, c, v) in enumerate(rows):
        out.append({"date": (start + timedelta(days=i)).isoformat(), "open": o, "high": h, "low": lo, "close": c, "volume": v})
    return out


def _history(n=25, px=100.0):
    return [(px, px + 1, px - 1, px, 1000) for _ in range(n)]


# ── Stage 1 / Stage 2 ─────────────────────────────────────────────────────────────────────────────────────────────


def test_no_session_since_exit_is_still_falling():
    bars = _bars(_history(25))
    out = rs.evaluate(symbol="AAA", exit_date="2099-01-01", exit_price=100.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["verdict"] == "Still falling"


def test_follow_through_with_volume_is_early_setup_and_swing_low_is_the_invalidation():
    hist = _history(25)
    # exit day 25, sells off to a low of 88 on day 26, higher low, then two green closes, second above first's high
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89, 91, 89.5, 90.5, 1000),
            (90.6, 92.0, 90.4, 91.8, 1000), (91.9, 93.5, 91.7, 93.2, 1500)]
    bars = _bars(hist + tail)
    exit_date = bars[25]["date"]
    ratio = [1.0, 0.98, 0.96, 0.95, 0.955, 0.96, 0.97]  # the low is before the last 3 sessions
    out = rs.evaluate(symbol="AAA", exit_date=exit_date, exit_price=95.0, bars=bars, group_ratio=ratio,
                      hedging_series=[3.8, 3.9, 3.2], market_tier="YELLOW", policy=POLICY)
    assert out["swing_low"] == 88 and out["invalidation_level"] == 88
    assert out["stage1"]["met"] == 5, out["stage1"]
    assert out["verdict"] == "Early setup"
    assert out["stage2"]["met"] is False  # below the exit and both averages


def test_low_volume_follow_through_is_not_met():
    hist = _history(25)
    # day 3 is red, so the follow-through is days 4-5 and the second green day (day 5) has thin volume
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (90.5, 91, 89.5, 90.0, 1000),
            (90.6, 92.0, 90.4, 91.8, 1000), (91.9, 93.5, 91.7, 93.2, 400)]
    bars = _bars(hist + tail)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    keys = {c["key"]: c["met"] for c in out["stage1"]["conditions"]}
    assert keys["follow_through"] is True and keys["volume"] is False


def test_close_below_swing_low_after_a_setup_is_invalidated():
    hist = _history(25)
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89, 91, 89.5, 90.5, 1000),
            (90.6, 92.0, 90.4, 91.8, 1000), (91.9, 93.5, 91.7, 93.2, 1500), (93, 93, 86, 87, 2000)]
    bars = _bars(hist + tail)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    # the swing low (88) is frozen at the setup bar; the later close (87) below it cancels the setup
    assert out["verdict"] == "Invalidated"
    assert out["invalidated"]["level"] == 88


def test_close_above_exit_is_confirmed():
    hist = _history(25)
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (90, 97, 89.5, 96.5, 1000)]
    bars = _bars(hist + tail)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["verdict"] == "Confirmed"


def test_short_history_uses_anchored_vwap():
    bars = _bars([(100, 101, 99, 100, 1000)] * 6 + [(99, 99, 90, 91, 3000), (91, 95, 90.5, 94, 2000)])
    out = rs.evaluate(symbol="NEW", exit_date=bars[5]["date"], exit_price=100.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["anchored_vwap"] is not None
    assert any(c["key"] == "above_anchored_vwap" for c in out["stage2"]["conditions"])


def test_hedging_needs_history_and_tier_gate():
    ok, txt = rs.hedging_easing([3.9], 3, 10)
    assert ok is False and "history 1 of 3" in txt
    assert rs.hedging_easing([3.0, 4.0, 3.5], 3, 10)[0] is True
    hist = _history(25)
    bars = _bars(hist + [(95, 96, 90, 91, 1000)])
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="ORANGE", policy=POLICY)
    assert {c["key"]: c["met"] for c in out["stage1"]["conditions"]}["tier_ok"] is False


def test_stage_output_carries_no_behaviour_fields():
    bars = _bars(_history(30))
    out = rs.evaluate(symbol="AAA", exit_date=bars[20]["date"], exit_price=100.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    for k in ("size_usd", "shares", "qty", "order", "stop", "limit"):
        assert k not in out


# ── Per-account exits: a same-account re-buy is a holding; its wash sale has occurred ──────────────────────────────


def test_same_day_rebuy_after_the_sale_is_held_and_wash_sale_occurred():
    closes = [("SYNA", "acct_taxable", "2031-05-12", True, 60.0), ("SYNA", "acct_ira", "2031-05-14", True, 55.0)]
    buys = [("SYNA", "acct_taxable", "2031-05-12", 58.0, "14:20")]
    sells = [("SYNA", "acct_taxable", "2031-05-12", "10:15")]
    out = bp.per_account_exits(closes, buys, held={("acct_taxable", "SYNA")}, wash_days=30, sells=sells)
    e = out["SYNA"]
    assert e["exit_date"] == "2031-05-14" and e["exit_account_type"] == "ira" and e["exit_price"] == 55.0
    assert e["wash_sale"]["state"] == "occurred" and e["wash_sale"]["rebuy_price"] == 58.0
    assert e["taxable_loss_date"] is None  # no forward "re-buy before ..." warning once the re-buy happened
    assert e["held_elsewhere"]


def test_buy_then_sell_day_trade_stays_an_exit():
    closes = [("SYNB", "acct_ira", "2031-05-05", False, 7.0)]
    buys = [("SYNB", "acct_ira", "2031-05-05", 6.9, "11:01")]
    sells = [("SYNB", "acct_ira", "2031-05-05", "11:02")]
    out = bp.per_account_exits(closes, buys, held=set(), wash_days=30, sells=sells)
    assert "SYNB" in out


def test_rebuy_in_every_exited_account_means_no_exit():
    closes = [("RRR", "acct_taxable", "2031-05-12", True, 10.0)]
    buys = [("RRR", "acct_taxable", "2031-05-13", 9.5, None)]
    assert bp.per_account_exits(closes, buys, held=set(), wash_days=30, sells=[]) == {}


def test_taxable_loss_without_rebuy_opens_the_window():
    closes = [("WWW", "acct_taxable", "2031-05-12", True, 10.0)]
    out = bp.per_account_exits(closes, [], held=set(), wash_days=30, sells=[])
    assert out["WWW"]["wash_sale"] == {"state": "window_open", "account_scope": out["WWW"]["wash_sale"]["account_scope"],
                                       "loss_sale_date": "2031-05-12", "until": "2031-06-11"}


def test_ira_loss_has_no_wash_sale():
    out = bp.per_account_exits([("III", "acct_ira", "2031-05-12", True, 10.0)], [], held=set(), wash_days=30, sells=[])
    assert out["III"]["wash_sale"] is None


# ── Look-through ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_book_group_exposure_is_value_weighted():
    per = [{"symbol": "BIG", "groups": {"tech": 0.1, "financials": 0.9}}, {"symbol": "TINY", "groups": {"comm": 1.0}}]
    eq = lt.book_group_exposure(per)
    vw = lt.book_group_exposure(per, weights={"BIG": 99_000.0, "TINY": 1_000.0})
    assert eq["comm"] == 0.5  # the legacy equal weighting the operator saw
    assert vw["comm"] == pytest.approx(0.01) and vw["financials"] == pytest.approx(0.891)


def test_issuer_segments_only_approved_and_partition_checked():
    seg = {"SEG": {"status": "APPROVED", "segments": [{"group": "industrials", "weight": 0.3}, {"group": "comm", "weight": 0.7},
                                                      {"group": "ai_basket", "weight": 0.05}], "source": "filing", "as_of": "2026-06-01"}}
    got = lt.issuer_segments_for("SEG", seg)
    assert got["groups"] == {"industrials": 0.3, "comm": 0.7, "ai_basket": 0.05}
    assert lt.issuer_segments_for("SEG", {"SEG": {**seg["SEG"], "status": "PROPOSED"}}) is None
    bad = {"SEG": {**seg["SEG"], "segments": [{"group": "industrials", "weight": 0.5}]}}
    assert lt.issuer_segments_for("SEG", bad) is None
    ex = lt.exposure_for("SEG", ai_basket=[], profiles={"SEG": {"sector": "Industrials"}}, fund_cfg={}, ipos={}, segments_cfg=seg)
    assert ex["groups"]["comm"] == 0.7 and ex["basis"].startswith("segments")


def test_shipped_issuer_segments_config_is_empty():
    import json
    from pathlib import Path

    cfg = json.loads((Path(__file__).resolve().parents[1] / "config" / "issuer_segments.json").read_text())
    assert cfg["issuers"] == {}


# ── Projection pass-through ───────────────────────────────────────────────────────────────────────────────────────


def test_projection_keeps_budget_names_only_and_adds_heatmap_rs1():
    """Budget numbers stay out of the snapshot the CIO reads (review of #2383, M3); the API join reads them from the
    engine's own assessment file. The heat map gains rs1 / reason_unknown from sectors.groups."""
    doc = {
        "schema": proj.ASSESSMENT_SCHEMA, "tier": "YELLOW", "score": 60, "as_of": "2026-11-01T16:00:00+00:00",
        "portfolio": {"vulnerability": 8, "budget_breaches": [{"scope": "acct-x", "budget": "unprotected_pct", "limit": 10.0,
                                                              "actual": 46.6, "unit": "%", "ratio": 4.66, "drivers": ["A", "B"]}]},
        "heatmap": [{"key": "tech", "kind": "sector", "state": "STRESS"}],
        "sectors": {"groups": [{"key": "tech", "rs1": -3.1, "reason_unknown": None}]},
    }
    s = proj.snapshot_from_assessment(doc)
    assert set(s["book"]["budgets"][0]) == {"budget", "scope", "breached"}
    assert s["heatmap"][0]["rs1"] == -3.1


def test_join_reads_budget_numbers_only_from_the_same_evaluation(tmp_path, monkeypatch):
    import json

    from scripts.lib import market_risk_book_join as bj

    d = tmp_path / "data" / "runtime" / "market_risk"
    d.mkdir(parents=True)
    (d / "shadow_latest.json").write_text(json.dumps({"as_of": "T1", "portfolio": {"budget_breaches": [
        {"scope": "acct-x", "budget": "unprotected_pct", "actual": 46.6, "limit": 10.0, "breached": True}]}}))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert bj._assessment_budgets({"mode": "shadow", "as_of": "T1"})[0]["actual"] == 46.6
    assert bj._assessment_budgets({"mode": "shadow", "as_of": "T2"}) == []


# ── API-side dollar join ──────────────────────────────────────────────────────────────────────────────────────────


def _store():
    return {
        "data_as_of": "2026-10-30",
        "portfolio_totals": {"total_value": 300_000.0},
        "holdings": [
            {"symbol": "CASH", "account": "a1", "is_cash": True, "market_value": 100_000.0},
            {"symbol": "FND", "account": "a1", "market_value": 150_000.0, "shares": 1000, "price": 150.0},
            {"symbol": "STK", "account": "a2", "market_value": 40_000.0, "shares": 100, "price": 400.0},
            {"symbol": "UNK", "account": "a2", "market_value": 10_000.0, "shares": 100, "price": 100.0},
        ],
    }


def _projection():
    return {
        "heatmap": [{"key": "tech", "kind": "sector", "state": "STRESS"}, {"key": "semis", "kind": "theme", "state": "STRESS"},
                    {"key": "financials", "kind": "sector", "state": "RESILIENT"}],
        "positions": {
            "FND": {"label": "hold", "look_through": {"groups": {"tech": 0.09, "semis": 0.05, "financials": 0.86}, "basis": "factsheet"}},
            "STK": {"label": "hold", "look_through": {"groups": {"financials": 1.0}, "basis": "stock"}},
            "UNK": {"label": "hold", "look_through": {"groups": {}, "basis": "stock_unknown", "note": "no sector profile"}},
        },
        "book": {"budgets": [{"scope_id": bd.opaque_account("a2"), "budget": "unprotected_pct", "limit": 10.0, "actual": 20.0,
                              "unit": "%", "drivers": ["UNK"]}]},
        "reentry_watch": {"XIT": {"exit_account_scope": bd.opaque_account("a1"), "held_elsewhere": [bd.opaque_account("a2")],
                                  "wash_sale": {"state": "occurred", "account_scope": bd.opaque_account("a2"), "loss_sale_date": "2026-10-28"}}},
    }


def _join(**kw):
    return bd.build(_projection(), _store(), stops=kw.get("stops", [{"account": "a2", "symbol": "STK", "stop_price": 386.0}]),
                    policy=POLICY, label_fn=lambda k: {"a1": "Acct One", "a2": "Acct Two"}.get(k, k), canon_fn=lambda k: k,
                    deferred_loss=lambda s, sc, d: 123.45)


def test_dollar_join_reconciles_and_never_double_counts_themes():
    out = _join()["book_exposure"]
    assert out["reconciles"] is True and out["total_usd"] == 300_000.0 and out["cash_usd"] == 100_000.0
    # 9% tech with 5% semis inside it is 9%, not 14%
    assert out["stressed_usd"] == pytest.approx(150_000 * 0.09)
    assert out["rows"][0]["symbol"] == "FND" and out["rows"][0]["stressed_share"] == 0.09
    assert out["groups"]["financials"]["usd"] == pytest.approx(150_000 * 0.86 + 40_000)
    assert [u["symbol"] for u in out["unmapped"]] == ["UNK"]


def test_book_total_mismatch_is_flagged():
    st = _store()
    st["portfolio_totals"]["total_value"] = 999.0
    out = bd.build(_projection(), st, stops=[], policy=POLICY, label_fn=str, canon_fn=str)
    assert out["book_exposure"]["reconciles"] is False


def test_review_ranked_by_dollars_with_merged_reasons():
    rv = _join()["review"]
    assert [i["symbol"] for i in rv][:2] == ["FND", "STK"]
    fnd = rv[0]
    assert "no stop" in fnd["text"] and "stressed" in fnd["text"] and fnd["usd"] == 150_000.0
    stk = rv[1]
    assert stk["text"].startswith("stop 3.5% below last") and stk["to"].startswith("/risk?tab=exposure")
    unk = next(i for i in rv if i["symbol"] == "UNK")
    assert "no look-through" in unk["text"]
    for i in rv:
        assert not any(w in i["text"].lower() for w in ("buy ", "sell ", "shares", "set stop"))


def test_budget_drivers_sorted_by_dollars_with_labels():
    b = _join()["budgets"][0]
    assert b["account_label"] == "Acct Two" and b["actual_usd"] == pytest.approx(0.20 * 50_000)
    assert b["drivers"][0]["name"] == "UNK"


def test_reentry_labels_and_deferred_loss():
    r = _join()["reentry"]["XIT"]
    assert r["exit_account_label"] == "Acct One" and r["held_elsewhere_labels"] == ["Acct Two"]
    assert r["wash_sale"]["deferred_loss_usd"] == 123.45 and r["wash_sale"]["account_label"] == "Acct Two"


# ── review of #2447: B1 invalidation, follow-through, held set, per-account wash, weights, stops, DB bounds ──────────


def test_follow_through_needs_the_second_close_above_the_first_green_high():
    hist = _history(25)
    # two green closes after a higher low, but the second (91.0) does not close above the first's high (91.5)
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89.5, 91.5, 89.2, 90.5, 1000), (90.6, 91.2, 90.4, 91.0, 2000)]
    bars = _bars(hist + tail)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert {c["key"]: c["met"] for c in out["stage1"]["conditions"]}["follow_through"] is False


def test_find_setup_freezes_the_swing_low_at_the_setup_bar():
    bars = _bars([(95, 96, 90, 91, 1), (91, 92, 88, 89, 1), (89, 91, 89.5, 90.5, 1), (90.6, 92.0, 90.4, 91.8, 1)])
    st = rs.find_setup(bars, 0)
    assert st == {"index": 3, "swing_low": 88, "low_index": 1}


def test_a_new_setup_after_an_invalidation_starts_a_new_count():
    hist = _history(25)
    tail = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89, 91, 89.5, 90.5, 1000), (90.6, 92.0, 90.4, 91.8, 1000),
            (93, 93, 86, 87, 2000),                                   # invalidates (87 < 88)
            (87, 88, 85, 85.5, 1000), (85.6, 87, 85.8, 86.8, 1000), (86.9, 88.5, 86.7, 88.2, 3000)]  # new setup, low 85
    bars = _bars(hist + tail)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[0.9, 0.9, 0.91, 0.92, 0.93, 0.94],
                      hedging_series=[4.0, 3.9, 3.0], market_tier="YELLOW", policy=POLICY)
    assert out["swing_low"] == 85 and out["verdict"] == "Early setup"


def test_held_set_alone_makes_an_account_not_exited():
    closes = [("HHH", "acct_ira", "2031-05-12", False, 10.0)]
    assert bp.per_account_exits(closes, [], held={("acct_ira", "HHH")}, wash_days=30, sells=[]) == {}
    assert "HHH" in bp.per_account_exits(closes, [], held=set(), wash_days=30, sells=[])


def test_same_day_rebuy_without_times_counts_when_held_and_wash_occurred():
    closes = [("S", "acct_taxable", "2031-05-12", True, 60.0), ("S", "acct_ira", "2031-05-14", True, 55.0)]
    buys = [("S", "acct_taxable", "2031-05-12", 58.0, None)]
    out = bp.per_account_exits(closes, buys, held={("acct_taxable", "S")}, wash_days=30, sells=[])
    assert out["S"]["wash_sale"]["state"] == "occurred"


def test_wash_is_tested_from_the_loss_sale_not_a_later_gain_sale():
    closes = [("W", "acct_taxable", "2031-05-01", True, 10.0), ("W", "acct_taxable", "2031-05-20", False, 12.0)]
    buys = [("W", "acct_taxable", "2031-05-05", 9.0, None)]
    assert bp.per_account_exits(closes, buys, held=set(), wash_days=30, sells=[])["W"]["wash_sale"]["state"] == "occurred"


def test_engine_book_shares_are_value_weighted():
    expo = {"BIG": {"symbol": "BIG", "groups": {"financials": 1.0}}, "TINY": {"symbol": "TINY", "groups": {"comm": 1.0}}}
    material = [{"symbol": "BIG", "shares": 100, "mark": 990.0}, {"symbol": "TINY", "shares": 10, "mark": 100.0}]
    got = bp.book_shares(expo, material)
    assert got["comm"] == pytest.approx(0.01) and got["financials"] == pytest.approx(0.99)


def test_unread_stops_are_not_no_stop():
    out = bd.build(_projection(), _store(), stops=None, policy=POLICY, label_fn=str, canon_fn=str)
    kinds = [k for i in out["review"] for k in i["kinds"]]
    assert "no_stop" not in kinds and out["book_exposure"]["stops_known"] is False
    assert all(b["drivers"] == [{"name": "UNK", "usd": 10_000.0}] for b in out["budgets"])  # no inferred unprotected drivers


def test_partial_sale_after_the_build_is_not_a_conflict_but_a_full_one_is():
    proj = _projection()
    st = _store()
    part = bd.build(proj, st, stops=[], policy=POLICY, label_fn=str, canon_fn=str,
                    ledger_sells=[{"symbol": "STK", "account": "a2", "date": "2031-05-12", "quantity": 40}])
    assert "data_conflict" not in [k for i in part["review"] for k in i["kinds"]]
    full = bd.build(proj, st, stops=[], policy=POLICY, label_fn=str, canon_fn=str,
                    ledger_sells=[{"symbol": "STK", "account": "a2", "date": "2031-05-12", "quantity": 100}])
    assert "data_conflict" in [k for i in full["review"] for k in i["kinds"]]
    none = bd.build(proj, st, stops=[], policy=POLICY, label_fn=str, canon_fn=str,
                    ledger_sells=[{"symbol": "STK", "account": "a2", "date": "2031-05-12"}])
    assert "data_conflict" not in [k for i in none["review"] for k in i["kinds"]]


def test_reconcile_tolerance_comes_from_config():
    st = _store()
    st["portfolio_totals"]["total_value"] = 300_004.0
    loose = {**POLICY, "home_review": {**POLICY["home_review"], "reconcile_tolerance_usd": 10.0}}
    assert bd.build(_projection(), st, stops=[], policy=loose, label_fn=str, canon_fn=str)["book_exposure"]["reconciles"] is True
    tight = {**POLICY, "home_review": {**POLICY["home_review"], "reconcile_tolerance_usd": 1.0}}
    assert bd.build(_projection(), st, stops=[], policy=tight, label_fn=str, canon_fn=str)["book_exposure"]["reconciles"] is False


def test_join_connection_is_dedicated_bounded_and_read_only():
    from scripts.lib import market_risk_book_join as bj

    seen = {}

    class Conn:
        def set_session(self, readonly=False):
            seen["readonly"] = readonly

        def close(self):
            seen["closed"] = True

    def get_conn(**kw):
        seen.update(kw)
        return Conn()

    pol = {"home_review": {"db": {"connect_timeout_s": 60, "statement_timeout_ms": 999_999, "lock_timeout_ms": 2_000}}}
    bj._ro_conn(bj.db_bounds(pol), get_conn)
    assert seen["readonly"] is True
    assert seen["connect_timeout"] == 10  # never looser than the shared connection's 10 s
    assert "statement_timeout=180000" in seen["options"] and "lock_timeout=2000" in seen["options"]


def test_join_fails_soft_and_fast_when_the_db_is_unreachable():
    import time

    from scripts.lib import market_risk_book_join as bj

    def stalled(**kw):
        assert kw["connect_timeout"] <= 10
        raise TimeoutError("connect timeout expired")

    proj = {**_projection(), "state": "evaluated", "as_of": "T", "mode": "shadow"}
    t0 = time.monotonic()
    out = bj.join(proj, get_conn=stalled, store=_store(), policy=POLICY, budgets=[])
    assert time.monotonic() - t0 < 5
    be = out["book_exposure"]
    assert be["stops_known"] is False and "TimeoutError" in be["ledger_error"]
    assert "no_stop" not in [k for i in out["review"] for k in i["kinds"]]


# ── review of PR 2447, round 2 ───────────────────────────────────────────────────────────────────────────────────


def test_a_break_after_the_badge_window_still_cancels_the_setup():
    """Q1: 11 quiet sessions after the setup, then a close below the frozen low: never "Early setup ... invalidates
    below 88" while the price is 81."""
    hist = _history(25)
    setup = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89, 91, 89.5, 90.5, 1000),
             (90.6, 92.0, 90.4, 91.8, 1000), (91.9, 93.5, 91.7, 93.2, 1500)]
    drift = [(93, 94, 92, 93, 1000)] * 11
    crash = [(93, 93, 80, 81, 3000)]
    bars = _bars(hist + setup + drift + crash)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    ft = {c["key"]: c["met"] for c in out["stage1"]["conditions"]}["follow_through"]
    assert ft is False and out["verdict"] == "Invalidated" and out["invalidated"]["level"] == 88
    assert out["last_close"] >= out["invalidation_level"]  # the shown level is the new count's low (80), not 88


def test_the_invalidated_badge_expires_after_its_window():
    hist = _history(25)
    setup = [(95, 96, 90, 91, 1000), (91, 92, 88, 89, 1000), (89, 91, 89.5, 90.5, 1000),
             (90.6, 92.0, 90.4, 91.8, 1000), (93, 93, 86, 87, 2000)]
    quiet = [(87, 87.5, 86.5, 87, 1000)] * 11
    bars = _bars(hist + setup + quiet)
    out = rs.evaluate(symbol="AAA", exit_date=bars[25]["date"], exit_price=95.0, bars=bars, group_ratio=[],
                      hedging_series=[], market_tier="YELLOW", policy=POLICY)
    assert out["verdict"] != "Invalidated" and out["invalidated"] is None


def test_several_partial_sales_that_close_the_position_are_a_conflict():
    proj, st = _projection(), _store()
    sells = [{"symbol": "STK", "account": "a2", "date": "2031-05-12", "quantity": -60},
             {"symbol": "STK", "account": "a2", "date": "2031-05-13", "quantity": 40}]
    out = bd.build(proj, st, stops=[], policy=POLICY, label_fn=str, canon_fn=str, ledger_sells=sells)
    assert "data_conflict" in [k for i in out["review"] for k in i["kinds"]]


def test_carried_label_reads_the_sent_key_ledger(tmp_path, monkeypatch):
    import json

    from scripts.lib import market_risk_book_join as bj

    led = tmp_path / "sent_keys.json"
    led.write_text(json.dumps({"keys": {"market_risk:YELLOW:2031-05-12:carried_yellow": {
        "status": "sent", "intent": {"priority": "P3"}}}}))
    monkeypatch.setenv("MARKET_RISK_SENT_LEDGER", str(led))
    proj = {"carried_only": True, "mode": "live", "tier": "YELLOW", "as_of": "2031-05-12T18:00:00+00:00"}
    assert bj.run_alerts(proj) == {"sends": 1, "priorities": ["P3"]}
    assert bj.run_alerts({**proj, "as_of": "2031-05-13T18:00:00+00:00"}) == {"sends": 0, "priorities": []}
    assert bj.run_alerts({**proj, "carried_only": False}) is None
    led.write_text(json.dumps({"keys": {"market_risk:YELLOW:2031-05-12:carried_yellow": {
        "status": "pending", "intent": {"priority": "P3"}}}}))
    assert bj.run_alerts(proj) == {"sends": 0, "priorities": []}  # queued, not sent
    led.write_text("{torn")
    assert bj.run_alerts(proj) is None and led.read_text() == "{torn"  # read-only: never repaired or moved
