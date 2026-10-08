"""Investment Command Center (operator 2026-10-08) — opportunity engine, CIO-memory store, API, Telegram line.

Risk/reward ladder (primary target, fallbacks, sanity flags), factor scores + conviction with re-weighting,
type/stance/condition rules, filters/presets, the CIO opportunity store (material-change versions, behaviour-key
refusal), price stats, positions context, entry ladders, the analyst-rollup list fix, and the Telegram opportunity
line. Fakes only: no database, no network, no real CIO memory.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import opportunity as op  # noqa: E402
from lib.data_broker.price_stats import compute as stats_compute  # noqa: E402
from scripts.lib import cio_opportunity_store as store_mod  # noqa: E402
from scripts.lib import opportunity_alert as oa  # noqa: E402


def ctx(**k):
    base = {
        "quote": {"price": 100.0, "day_change_pct": 1.0},
        "ladder": {"suggested_entry": 100.0, "entry_zone_low": 98, "entry_zone_high": 102, "invalidation_level": 90.0,
                   "plan_target": 130.0,
                   "targets": [{"label": "T1 (+1R)", "px": 110.0}, {"label": "T2 (plan target)", "px": 130.0},
                               {"label": "T3 (runner)", "px": 140.0}]},
        "analyst": {"target_mean": 135.0, "target_high": 160.0, "analyst_count": 20, "recommendation_mean": 1.8,
                    "recommendation_key": "buy"},
        "stats": {"change_1w_pct": 2.0, "change_1m_pct": 6.0, "relative_volume": 1.1, "sma_20": 98, "sma_50": 95,
                  "high_52w": 120},
        "indicators": {"rsi": 55, "alignment": "bullish", "atr": 3.0},
        "hermes": {"technical_momentum": {"score": 70}, "setup_quality": {"score": 80}},
        "profile": {"sector": "Technology", "market_cap_usd": 50e9},
        "position": {},
        "portfolio_known": True,
        "sector_weights": {"technology": 12.0},
    }
    base.update(k)
    return base


# ── risk / reward ───────────────────────────────────────────────────────────

def test_rr_uses_the_primary_plan_target_not_t1():
    rr = op.risk_reward(ctx())
    assert rr["entry_ref"] == 100 and rr["invalidation_level"] == 90 and rr["primary_target"] == 130
    assert rr["rr"] == 3.0 and rr["risk_pct"] == 10.0 and rr["reward_pct"] == 30.0       # operator's worked example
    assert [t["tier"] for t in rr["targets"]] == ["T1", "T2", "T3"]


def test_rr_fallbacks_strategy_then_atr_then_analyst_ladder():
    rr = op.risk_reward(ctx(ladder={}, strategy={"ideal_entry": 100, "stop_loss": 95, "target_price": 112}))
    assert rr["entry_source"] == "strategy_card.ideal_entry" and rr["invalidation_source"] == "strategy_card"
    rr = op.risk_reward(ctx(ladder={}, strategy={}))
    assert rr["entry_source"] == "current_price" and rr["invalidation_source"] == "atr" and rr["invalidation_level"] == 94
    assert rr["targets"][0]["source"] == "analyst"


def test_rr_too_tight_or_implausible_is_flagged_not_scored():
    tight = op.risk_reward(ctx(ladder={"suggested_entry": 100, "invalidation_level": 99.9, "plan_target": 130,
                                       "targets": []}))
    assert tight.get("rr") is None and tight["rr_flag"].startswith("invalidation too close")
    assert "risk_reward" not in op.factors(ctx(), tight)


def test_mechanical_levels_score_below_a_real_plan():
    plan = op.factors(ctx(), op.risk_reward(ctx()))["risk_reward"]["score"]
    card = ctx(ladder={}, strategy={"ideal_entry": 100, "stop_loss": 90, "target_price": 130})
    card_score = op.factors(card, op.risk_reward(card))["risk_reward"]["score"]
    assert card_score < plan


# ── factors, conviction, classification ─────────────────────────────────────

def test_missing_factors_are_dropped_and_coverage_says_so():
    c = ctx(analyst={}, hermes={}, indicators={}, stats={})
    fx = op.factors(c, op.risk_reward(c))
    conv, cov = op.conviction(fx)
    assert "analyst" not in fx and "momentum" not in fx and 0 < cov < 1 and conv is not None


def test_implausible_upside_is_not_scored_and_flagged():
    c = ctx(quote={"price": 1.0}, analyst={"target_mean": 9.0, "analyst_count": 5, "recommendation_mean": None})
    a = op.assess("PNY", c)
    assert a["upside_flag"].startswith("implausible") and "analyst" not in a["factors"]


@pytest.mark.parametrize("pos,kw,typ,stance", [
    ({"owned": True, "weight_pct": 3.0}, {}, "add_on", "ADD"),
    ({"owned": True, "weight_pct": 14.0}, {}, "exit_candidate", "TRIM"),
    ({}, {"reentry_state": "NEAR ENTRY"}, "re_entry", "RE_ENTER"),
    ({}, {}, "new_position", "WATCH"),
])
def test_type_and_stance(pos, kw, typ, stance):
    a = op.assess("ABC", ctx(position=pos, **kw))
    assert (a["type"], a["stance"]) == (typ, stance)


def test_exit_needs_strong_evidence():
    weak = ctx(position={"owned": True, "weight_pct": 3}, analyst={}, hermes={}, indicators={},
               stats={}, ladder={}, strategy={})
    assert op.assess("ETF", weak)["stance"] != "EXIT"   # thin evidence (an income ETF) never yields EXIT


def test_stance_prose_is_conditional_never_an_instruction():
    from scripts.lib.execution_language import find_imperative

    for s in op.STANCE_WHY.values():
        text = s.format(conv="70", rr="3.0", w="12.0")
        assert not find_imperative(text), text


@pytest.mark.parametrize("ind,st,cond", [
    ({"rsi": 75}, {}, "overbought"), ({"rsi": 25}, {}, "oversold"),
    ({"rsi": 60, "alignment": "bullish"}, {"high_52w": 101, "relative_volume": 1.5}, "breaking_out"),
    ({"rsi": 45, "alignment": "bullish"}, {"sma_20": 105, "sma_50": 95, "high_52w": 150}, "pullback"),
])
def test_technical_condition(ind, st, cond):
    assert op.technical_condition(ctx(indicators=ind, stats=st)) == cond


def test_rank_filters_presets_sorts():
    A = op.rank([op.assess(s, ctx(quote={"price": p})) for s, p in (("AAA", 100), ("BBB", 104), ("CCC", 96))])
    assert sorted(a["rank"] for a in A) == [1, 2, 3]
    q = op.apply_preset({"preset": "top5"})
    assert q["min_coverage"] == 0.8 and q["min_rr"] == 2.0
    assert all(op.passes(a, {"min_rr": "2"}) for a in A if (a["risk_reward"].get("rr") or 0) >= 2)
    for s in op.SORTS:
        assert len(op.sort_items(A, s)) == 3


# ── CIO memory store ────────────────────────────────────────────────────────

def test_store_versions_only_on_material_change(tmp_path):
    st = store_mod.CIOOpportunityStore(tmp_path / "e.jsonl", tmp_path / "p.json")
    a = op.rank([op.assess("AAA", ctx())])
    cfg = op.load_config()["material_change"]
    lines = st.plan(a, cfg)
    assert lines[0]["change_reasons"] == ["first_assessment"]
    st.append(lines, {"writer": "test"})
    assert st.plan(a, cfg) == []                                      # same facts → no new version
    moved = op.rank([op.assess("AAA", ctx(stats={"change_1m_pct": -30, "change_1w_pct": -10}))])
    again = st.plan(moved, cfg)
    assert again and again[0]["version"] == 2 and st.history("AAA")[0]["version"] == 1


def test_store_refuses_behaviour_fields(tmp_path):
    st = store_mod.CIOOpportunityStore(tmp_path / "e.jsonl", tmp_path / "p.json")
    bad = {"symbol": "X", "risk_reward": {"stop": 1.0}}
    with pytest.raises(store_mod.BehaviorFieldRefused):
        st.plan([bad], {})
    a = op.assess("AAA", ctx(position={"owned": True, "shares": 10}))
    store_mod.assert_no_behavior(a)                                   # a real assessment never carries one


def test_projection_round_trip(tmp_path):
    st = store_mod.CIOOpportunityStore(tmp_path / "e.jsonl", tmp_path / "p.json")
    st.write_projection(op.rank([op.assess("AAA", ctx())]), {"as_of": "2026-10-08T12:00:00+00:00"})
    assert st.read_projection()["items"]["AAA"]["conviction"] is not None


# ── readers ─────────────────────────────────────────────────────────────────

def test_price_stats_compute():
    closes = [100 + i * 0.1 for i in range(260)]
    s = stats_compute(closes, [])
    assert s["high_52w"] == max(closes[-252:]) and s["sma_200"] and s["ma_alignment"] == "bullish"
    assert s["change_1w_pct"] > 0 and "avg_volume_30d" not in s


def test_entry_ladder_keeps_prices_never_instructions():
    from lib.data_broker.entry_plan import get_entry_ladders

    plan = {"proposal": {"suggested_entry": 146.5},
            "exit_ladder": {"steps": [{"px": 154.5, "label": "T1 (+1R)", "action": "sell 1/3, move stop"}]}}
    rows = [{"symbol": "ALLE", "plan": json.dumps(plan), "stop_price": 138.5, "target_price": 178}]
    out = get_entry_ladders(lambda *a, **k: rows, ["ALLE"])["ALLE"]
    assert out["targets"] == [{"label": "T1 (+1R)", "px": 154.5}] and out["suggested_entry"] == 146.5
    assert "sell" not in json.dumps(out)


def test_positions_context_weight_and_pending_realized(tmp_path):
    from lib.data_broker.positions_context import get_positions_context

    h = tmp_path / "holdings.json"
    h.write_text(json.dumps({"as_of": "2026-10-08", "portfolio_totals": {"total_value": 1000.0}, "holdings": [
        {"symbol": "ABC", "shares": 2, "price": 40.0, "cost_basis": 80.0, "account": "a", "portfolio_pct": 99},
        {"symbol": "ABC", "shares": 1, "price": 40.0, "cost_basis": 45.0, "account": "b"}]}))
    q = lambda sql, params=None, fetch="all": [{"s": "XYZ", "last_sell": date(2026, 9, 1)}]  # noqa: E731
    # value comes from the read-time quote (50), never the stored mark (40) — lib/portfolio_positions
    out = get_positions_context(q, ["ABC", "XYZ"], holdings_path=h,
                                quotes={"ABC": {"price": 50.0, "as_of": datetime.now(timezone.utc).isoformat()}})
    assert out["ABC"]["market_value"] == 150.0 and out["ABC"]["weight_pct"] == 15.0
    assert out["ABC"]["avg_cost"] == round(125 / 3, 4) and out["ABC"]["unrealized_pl"] == 25.0
    assert out["ABC"]["realized_pl"] is None and "phase-3" in out["ABC"]["pending"]["realized_pl"]
    assert out["XYZ"]["owned"] is False and out["XYZ"]["last_sell_date"] == "2026-09-01"


def test_analyst_rollup_reads_the_list_shape(tmp_path, monkeypatch):
    from lib.data_broker import analyst_rollup as ar

    f = tmp_path / "pills.json"
    f.write_text(json.dumps({"updated_at": "x", "pills": [{"symbol": "NFLX", "recommendation_key": "buy",
                                                           "target_mean_price": 93.6, "target_high_price": 135,
                                                           "number_of_analyst_opinions": 45}]}))
    monkeypatch.setattr(ar, "_PILLS_PATH", f)
    r = ar.get_analyst_rollup(["NFLX"])["NFLX"]
    assert r["mean_target"] == 93.6 and r["target_high"] == 135 and r["analyst_count"] == 45


# ── Telegram opportunity line ───────────────────────────────────────────────

def _proj(tmp_path, as_of):
    a = op.rank([op.assess("NFLX", ctx())])[0]
    p = tmp_path / "proj.json"
    p.write_text(json.dumps({"as_of": as_of, "items": {"NFLX": a}}, default=str))
    return p


def test_telegram_line_on_opportunity_alerts_only(tmp_path):
    p = _proj(tmp_path, datetime.now(timezone.utc).isoformat())
    msg = "🟡 CIO ENTRY ALERT — NFLX · New position\nBUY READY · inside entry zone"
    out = oa.enrich(msg, projection_path=p)
    assert oa.MARK in out and "opp=NFLX" in out and "R:R 3.0x" in out
    assert oa.enrich(out, projection_path=p) == out                         # idempotent
    assert oa.enrich("🏥 Health Inspector [DEGRADED]", projection_path=p) == "🏥 Health Inspector [DEGRADED]"


def test_telegram_line_skipped_when_stale_or_broken(tmp_path):
    old = _proj(tmp_path, (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat())
    msg = "🟡 CIO ENTRY ALERT — NFLX · New position\nBUY READY"
    assert oa.enrich(msg, projection_path=old) == msg
    assert oa.enrich(msg, projection_path=tmp_path / "missing.json") == msg   # never raises


# ── wiring ──────────────────────────────────────────────────────────────────

def test_wiring():
    tg = (ROOT / "scripts" / "telegram_alert.py").read_text()
    assert "_opp_enrich(message" in tg
    api = (ROOT / "scripts" / "api_v2.py").read_text()
    assert '"/api/v3/opportunities"' in api and "api_v3_opportunities" in api
    app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text()
    assert "OpportunityModalProvider" in app
    for f in ("components/opportunity/OpportunityModal.tsx", "pages/OpportunitiesHub.tsx", "components/primitives/Modal.tsx"):
        assert (ROOT / "apps/command-center-v3/src" / f).exists()
