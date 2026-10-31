"""Rotation advisor: durable leadership detector, advisory stances, card, CIO facts and backtest (operator 2026-10-31:
"if stuff is turning for the long term, I should have advisement of what I should be getting into").

Hermetic: synthetic series and the public bars fixture; telegram_alert stubbed. No DB, no network, no model.
"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta

import pytest

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import leadership as L
from scripts.lib.market_risk import rotation_advice as R
from scripts.lib.market_risk.policy import load_policy

COVERS = ["scripts/lib/market_risk/rotation_advice.py"]

POLICY = load_policy()
CFG = POLICY["leadership"]
GROUPS = [
    {"key": "energy", "label": "Energy", "kind": "sector", "symbols": ["XLE"]},
    {"key": "tech", "label": "Technology", "kind": "sector", "symbols": ["XLK"]},
]
POL = {"leadership": CFG, "sectors": {"groups": GROUPS}}


def _dates(n: int) -> list[str]:
    d0 = date(2020, 1, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _series(dates, fn, vol=1000.0):
    return [(d, fn(i), vol) for i, d in enumerate(dates)]


def _panel(spy_fn, grp_fn, n=420, grp="XLE"):
    ds = _dates(n)
    bars = {"SPY": _series(ds, spy_fn), grp: _series(ds, grp_fn)}
    return L.build_panel(bars, [g for g in GROUPS if g["symbols"][0] == grp], "SPY"), n - 1


def _cls(spy_fn, grp_fn, key="energy", grp="XLE"):
    panel, i = _panel(spy_fn, grp_fn, grp=grp)
    f = L.features_at(panel, key, i, CFG)
    return L.classify_features(f, CFG)[0]


def flat(i):
    return 100.0


def test_steady_outperformer_is_confirmed():
    assert _cls(flat, lambda i: 100.0 * (1.001**i)) == "LEADERSHIP_CONFIRMED"


def test_recent_rally_after_long_lag_is_bounce_only():
    def g(i):
        return 100.0 * (0.998**i) if i < 410 else 100.0 * (0.998**410) * (1.005 ** (i - 410))

    assert _cls(flat, g) == "BOUNCE_ONLY"


def test_long_leader_rolling_over_is_fading():
    def g(i):
        return 100.0 * (1.002**i) if i < 395 else 100.0 * (1.002**395) * (0.996 ** (i - 395))

    assert _cls(flat, g) == "LEADERSHIP_FADING"


def test_new_leader_is_emerging_not_confirmed():
    def g(i):  # lagged across the 120-session window, then led for the last ~40 sessions
        return 100.0 * (0.998**i) if i < 380 else 100.0 * (0.998**380) * (1.003 ** (i - 380))

    assert _cls(flat, g) == "LEADERSHIP_EMERGING"


def test_short_history_is_unknown_never_zero():
    ds = _dates(100)
    panel = L.build_panel({"SPY": _series(ds, flat), "XLE": _series(ds, lambda i: 100 + i)}, GROUPS[:1], "SPY")
    cls, conf, reasons = L.classify_features(L.features_at(panel, "energy", 99, CFG), CFG)
    assert cls == "UNKNOWN" and conf == 0.0 and reasons


def test_strategic_needs_macro_alignment():
    assert L.horizon_label("LEADERSHIP_CONFIRMED", True, CFG) == "strategic"
    assert L.horizon_label("LEADERSHIP_CONFIRMED", False, CFG) == "tactical"
    assert L.horizon_label("BOUNCE_ONLY", True, CFG) is None


def _block(cls_by_key):
    return {
        "state": "evaluated",
        "as_of": "2026-10-30",
        "macro": {},
        "groups": {
            k: {
                "key": k,
                "label": k.title(),
                "kind": "sector",
                "symbols": ["XLE" if k == "energy" else "XLK"],
                "class": cls,
                "confidence": 0.9,
                "horizon": "tactical",
                "evidence": ["relative to SPY: +5.0% over 20"],
            }
            for k, cls in cls_by_key.items()
        },
    }


CANDS = [
    {"symbol": "AAA", "sector": "Energy", "conviction": 80, "stance": "WATCH", "rankable": True},
    {"symbol": "BBB", "sector": "Energy", "conviction": 40, "stance": "WATCH", "rankable": True},
    {"symbol": "CCC", "sector": "Technology", "conviction": 90, "stance": "WATCH", "rankable": True},
]


def test_confirmed_group_is_add_with_ranked_names_above_floor():
    p = R.advise(_block({"energy": "LEADERSHIP_CONFIRMED"}), policy=POL, tier="YELLOW", candidates=CANDS, holdings=[])
    g = p["groups"]["energy"]
    assert g["stance"] == "ADD"
    assert [n["symbol"] for n in g["names"]] == ["AAA"]  # BBB below the CIO's conviction floor


def test_entry_gate_holds_at_orange():
    p = R.advise(_block({"energy": "LEADERSHIP_CONFIRMED"}), policy=POL, tier="ORANGE", candidates=CANDS, holdings=[])
    assert p["groups"]["energy"]["stance"] == "HOLD_CASH_FOR"
    assert any("market_risk_gate" in r for r in p["groups"]["energy"]["reasons"])


def test_fading_with_overlap_is_watch_closely_and_residual_ignored():
    holds = [{"symbol": "XLK", "sector": "Technology", "market_value": 50_000}]
    p = R.advise(_block({"tech": "LEADERSHIP_FADING"}), policy=POL, tier=None, candidates=CANDS, holdings=holds)
    assert p["groups"]["tech"]["stance"] == "WATCH_CLOSELY"
    resid = [{"symbol": "XLK", "sector": "Technology", "market_value": 12.0}]
    p2 = R.advise(_block({"tech": "LEADERSHIP_FADING"}), policy=POL, tier=None, candidates=CANDS, holdings=resid)
    assert p2["groups"]["tech"]["stance"] == "AVOID"  # a fractional residual is not "exposure"


def test_payload_and_card_carry_no_behaviour():
    p = R.advise(_block({"energy": "LEADERSHIP_CONFIRMED"}), policy=POL, tier="YELLOW", candidates=CANDS, holdings=[])
    c.assert_no_behavior_fields(p)
    card = R.render_card(p)
    assert "no order, size, weight or price" in card
    from scripts.lib import buy_ready_cio_review as br

    assert not br._SIZING_TEXT.search(card)  # noqa: SLF001


def test_behaviour_field_in_candidate_is_refused():
    bad = [dict(CANDS[0], shares=100)]
    p = R.advise(_block({"energy": "LEADERSHIP_CONFIRMED"}), policy=POL, tier=None, candidates=bad, holdings=[])
    assert "shares" not in str(p)  # only whitelisted fields are copied from candidates


def test_send_card_goes_through_the_chokepoint(monkeypatch):
    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **kw: sent.append((msg, kw)) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    p = R.advise(_block({"energy": "LEADERSHIP_CONFIRMED"}), policy=POL, tier=None, candidates=CANDS, holdings=[])
    assert R.send_card(p, POL) is True
    msg, kw = sent[0]
    assert kw["priority"] == "P2" and kw["message_class"] == "market_risk" and kw["producer"] == "market_risk_rotation"
    assert "WHERE LEADERSHIP IS MOVING" in msg


def test_send_failure_propagates(monkeypatch):
    tg = types.ModuleType("telegram_alert")

    def boom(*a, **k):
        raise RuntimeError("transport down")

    tg.send_telegram = boom
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    p = R.advise(_block({"energy": "LEADERSHIP_CONFIRMED"}), policy=POL, tier=None, candidates=CANDS, holdings=[])
    with pytest.raises(RuntimeError):
        R.send_card(p, POL)


def test_card_is_off_by_default_until_an_edge_is_shown():
    assert CFG.get("card_enabled") is False


def test_cio_facts_exclude_neutral_and_unknown():
    from scripts.lib.market_risk import cio_context

    blk = _block({"energy": "LEADERSHIP_CONFIRMED", "tech": "NEUTRAL"})
    facts = cio_context._leadership_facts(blk)  # noqa: SLF001
    assert set(facts["groups"]) == {"energy"}
    assert cio_context._leadership_facts({"state": "UNKNOWN"}) is None  # noqa: SLF001


def test_backtest_holds_out_2026_and_reports_baseline():
    import importlib.util
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "scripts" / "market_risk_leadership_backtest.py"
    spec = importlib.util.spec_from_file_location("lb", p)
    lb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lb)
    rep = lb.run(step=60)
    ins, hold = rep["periods"]["in_sample"], rep["periods"]["holdout_2026"]
    assert ins["detector"][60]["n"] > 0 and ins["baseline_top3_rs60"][60]["n"] > 0
    assert hold["class_counts"]  # 2026 is evaluated separately, never pooled with in-sample


def test_measure_unknown_without_benchmark_bars():
    class R0:
        def daily_bars(self, *a, **k):
            return []

    from datetime import datetime, timezone

    blk = L.measure(c.EvalContext(now=datetime(2026, 10, 30, tzinfo=timezone.utc), reader=R0(), policy=POLICY))
    assert blk["state"] == "UNKNOWN" and "SPY" in blk["reason_unknown"]


def test_least_bad_in_a_falling_market_is_not_confirmed():
    """Relative strength alone is not leadership: a group falling slower than SPY, below its own 200-day, is not a
    durable leader (the stated rule requires the group's own uptrend)."""
    cls = _cls(lambda i: 100.0 * (0.998**i), lambda i: 100.0 * (0.999**i))
    assert cls != "LEADERSHIP_CONFIRMED"
