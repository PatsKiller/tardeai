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
    assert out["verdict"] in ("Invalidated", "Still falling")
    # a new low resets the swing low to it; the verdict is never "Early setup" after a close below the old low
    assert out["verdict"] != "Early setup"


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
    closes = [("ZZZ", "acct_taxable", "2026-10-28", True, 146.0), ("ZZZ", "acct_ira", "2026-10-30", True, 137.0)]
    buys = [("ZZZ", "acct_taxable", "2026-10-28", 144.0, "12:44")]
    sells = [("ZZZ", "acct_taxable", "2026-10-28", "09:30")]
    out = bp.per_account_exits(closes, buys, held={("acct_taxable", "ZZZ")}, wash_days=30, sells=sells)
    e = out["ZZZ"]
    assert e["exit_date"] == "2026-10-30" and e["exit_account_type"] == "ira" and e["exit_price"] == 137.0
    assert e["wash_sale"]["state"] == "occurred" and e["wash_sale"]["rebuy_price"] == 144.0
    assert e["taxable_loss_date"] is None  # no forward "re-buy before ..." warning once the re-buy happened
    assert e["held_elsewhere"]


def test_buy_then_sell_day_trade_stays_an_exit():
    closes = [("DTR", "acct_ira", "2026-10-05", False, 4.5)]
    buys = [("DTR", "acct_ira", "2026-10-05", 4.4, "10:07")]
    sells = [("DTR", "acct_ira", "2026-10-05", "10:08")]
    out = bp.per_account_exits(closes, buys, held=set(), wash_days=30, sells=sells)
    assert "DTR" in out


def test_rebuy_in_every_exited_account_means_no_exit():
    closes = [("RRR", "acct_taxable", "2026-10-28", True, 10.0)]
    buys = [("RRR", "acct_taxable", "2026-10-29", 9.5, None)]
    assert bp.per_account_exits(closes, buys, held=set(), wash_days=30, sells=[]) == {}


def test_taxable_loss_without_rebuy_opens_the_window():
    closes = [("WWW", "acct_taxable", "2026-10-28", True, 10.0)]
    out = bp.per_account_exits(closes, [], held=set(), wash_days=30, sells=[])
    assert out["WWW"]["wash_sale"] == {"state": "window_open", "account_scope": out["WWW"]["wash_sale"]["account_scope"],
                                       "loss_sale_date": "2026-10-28", "until": "2026-11-27"}


def test_ira_loss_has_no_wash_sale():
    out = bp.per_account_exits([("III", "acct_ira", "2026-10-28", True, 10.0)], [], held=set(), wash_days=30, sells=[])
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
