"""Market Risk Engine scoring, tiers, hysteresis, decay, uplift and explainability (builder A, P2-T1/T7/T10).

Synthetic observations only (public repo). The 10-30 shape tests reproduce the RCA timeline with made-up category
scores: ORANGE at a 10-28-close-like input, RED at a 10-29 18:15 ET-like input once the portfolio uplift applies.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import explain, registry, scoring
from scripts.lib.market_risk.policy import load_policy

POLICY_LIVE = load_policy()
# The arithmetic tests below pin tier boundaries, hysteresis, decay and attribution on the weighted-mean composite
# (composite.method: mean), where a score is easy to construct exactly. The shipped policy uses noisy_or; its own tests
# are at the end of this file (test_noisy_or_*).
POLICY = dict(POLICY_LIVE, composite={"method": "mean"})
NOW = datetime(2026, 10, 28, 20, 30, tzinfo=timezone.utc)  # 16:30 ET


def ob(cat, state, score, *, age_h=0.0, stale=None, now=NOW):
    if state == "UNKNOWN":
        return c.unknown(cat, now, "fixture")
    return c.CategoryObservation(
        category=cat,
        state=state,
        score=score,
        observed_at=(now - timedelta(hours=age_h)).isoformat(),
        headline=f"{cat} {state.lower()} {score}",
        stale_after_hours=stale,
    )


def obs(spec, now=NOW):
    """spec: {category: (state, score)}; missing categories are UNKNOWN."""
    return [ob(k, *spec[k], now=now) if k in spec else c.unknown(k, now, "fixture") for k in c.CATEGORIES]


OCT28_CLOSE = {
    "event": ("STRESS", 88),
    "volatility": ("WARN", 65),
    "technical": ("WARN", 62),
    "breadth": ("WARN", 58),
    "options_flow": ("CALM", 30),
    "cross_asset": ("CALM", 30),
    "macro_credit": ("WARN", 45),
    "seasonal": ("CALM", 20),
}
OCT29_1815_MARKET_ORANGE = {
    "event": ("STRESS", 92),
    "options_flow": ("STRESS", 85),
    "technical": ("STRESS", 72),
    "breadth": ("WARN", 70),
    "extended_hours": ("WARN", 70),
    "volatility": ("WARN", 60),
    "cross_asset": ("WARN", 55),
    "macro_credit": ("WARN", 45),
    "seasonal": ("CALM", 20),
}


def test_oct28_close_shape_is_orange():
    a = scoring.compose(obs(OCT28_CLOSE), POLICY, now=NOW)
    assert a.tier == "ORANGE", (a.score, a.hysteresis["why"])
    assert a.confirming == 5 and 50 <= a.score < 60  # orange by confirmation, not by score alone


def test_oct29_1815_shape_is_red_with_uplift():
    now = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)
    a = scoring.compose(obs(OCT29_1815_MARKET_ORANGE, now), POLICY, now=now)
    assert a.market_tier == "ORANGE"
    pc = c.PortfolioContext(vulnerability=78, drivers=({"symbol": "GROWTH_ETF", "stop_distance_pct": 4.1},))
    a = scoring.apply_uplift(a, pc, POLICY)
    assert a.tier == "RED" and a.uplift["from"] == "ORANGE" and a.score == a.market_score


def test_market_red_by_breadth_stress():
    spec = dict(OCT29_1815_MARKET_ORANGE, breadth=("STRESS", 75))
    assert scoring.compose(obs(spec), POLICY, now=NOW).tier == "RED"


def test_extended_hours_shock_red_bypasses_hysteresis():
    spec = dict(OCT29_1815_MARKET_ORANGE, extended_hours=("STRESS", 90))
    prior = {"tier": "ORANGE", "hysteresis": {}}
    a = scoring.compose(obs(spec), POLICY, prior=prior, now=NOW)
    assert a.tier == "RED" and a.hysteresis.get("immediate")


@pytest.mark.parametrize(
    "score,tier",
    [
        (24.9, "NONE"),
        (25, "BLUE"),
        (39.9, "BLUE"),
        (40, "YELLOW"),
        (59.9, "YELLOW"),
        (60, "ORANGE"),
        (74.9, "ORANGE"),
        (75, "RED"),
    ],
)
def test_score_boundaries(score, tier):
    # one CALM category -> composite == its score; no WARN confirmations, so only the score decides
    a = scoring.compose(
        [ob("technical", "CALM", score)] + [c.unknown(k, NOW, "x") for k in c.CATEGORIES[1:]], POLICY, now=NOW
    )
    assert a.tier == tier, a.score


def test_confirmation_without_required_stress_is_not_orange():
    spec = {k: ("WARN", 41) for k in ("technical", "breadth", "volatility", "macro_credit")}
    a = scoring.compose(obs(spec), POLICY, now=NOW)
    assert a.tier == "YELLOW"  # 4 WARN but none of options_flow/cross_asset/event at STRESS


def test_green():
    spec = {"technical": ("IMPROVING", 10), "breadth": ("CALM", 12), "volatility": ("CALM", 15)}
    assert scoring.compose(obs(spec), POLICY, now=NOW).tier == "GREEN"


def test_unknown_is_not_zero_and_coverage_drops():
    a = scoring.compose(obs({"event": ("STRESS", 90)}), POLICY, now=NOW)
    assert a.score == pytest.approx(90) and a.hysteresis["coverage"] < 0.2
    a0 = scoring.compose(obs({}), POLICY, now=NOW)
    assert a0.score is None and a0.tier == "NONE"


def test_hysteresis_escalation_needs_two():
    prior = {"tier": "YELLOW", "hysteresis": {}}
    a1 = scoring.compose(obs(OCT28_CLOSE), POLICY, prior=prior, now=NOW)
    assert a1.tier == "YELLOW" and a1.hysteresis["candidate"] == "ORANGE"
    a2 = scoring.compose(obs(OCT28_CLOSE), POLICY, prior=a1.to_dict(), now=NOW + timedelta(minutes=15))
    assert a2.tier == "ORANGE"


def test_hysteresis_deescalation_needs_three_sessions():
    calm = {"technical": ("CALM", 10)}
    prior = {"tier": "ORANGE", "hysteresis": {}}
    t = NOW
    for day in range(2):
        a = scoring.compose(obs(calm, t), POLICY, prior=prior, now=t)
        assert a.tier == "ORANGE"
        a2 = scoring.compose(obs(calm, t), POLICY, prior=a.to_dict(), now=t + timedelta(hours=1))  # same session
        assert a2.hysteresis["below_sessions"] == a.hysteresis["below_sessions"]
        prior, t = a2.to_dict(), t + timedelta(days=1)
    a = scoring.compose(obs(calm, t), POLICY, prior=prior, now=t)
    assert a.tier == "NONE"


def test_bootstrap_adopts_raw():
    a = scoring.compose(obs(OCT28_CLOSE), POLICY, prior=None, now=NOW)
    assert a.hysteresis["bootstrap"] is True and a.tier == "ORANGE"


def test_decay_steps_and_staleness():
    pol = POLICY
    w = [scoring.decay_weight(ob("event", "STRESS", 80, age_h=h), NOW, pol)[0] for h in (1, 20, 40, 70, 90, 100)]
    assert w == [1.0, 0.8, 0.6, 0.4, 0.4, 0.0]
    stale = scoring.compose(
        [ob("event", "STRESS", 80, age_h=100)] + [c.unknown(k, NOW, "x") for k in c.CATEGORIES if k != "event"],
        pol,
        now=NOW,
    )
    assert stale.observations[c.CATEGORIES.index("event")].state == "UNKNOWN" and stale.score is None


def test_unreconfirmed_orange_decays_below_orange_floor():
    a = scoring.compose(obs(OCT28_CLOSE), POLICY, now=NOW)
    b = scoring.compose(obs(OCT28_CLOSE, NOW), POLICY, prior=a.to_dict(), now=NOW + timedelta(hours=48))
    assert b.score < a.score and b.confirming == 0
    assert scoring.SEVERITY[b.hysteresis["raw_tier"]] < scoring.SEVERITY["ORANGE"]  # stale fear decays on its own
    assert b.tier == "ORANGE"  # the shown tier still waits out the 3-session de-escalation
    # a fresh STRESS observation reconfirms and resets the clock
    fresh = [
        o if o.category != "event" else ob("event", "STRESS", 88, now=NOW + timedelta(hours=48))
        for o in obs(OCT28_CLOSE, NOW)
    ]
    r = scoring.compose(fresh, POLICY, prior=b.to_dict(), now=NOW + timedelta(hours=48))
    assert r.score > b.score and "event" in r.hysteresis["why"]["confirming"]


def test_uplift_capped_at_one_tier_and_blue_never():
    a = scoring.compose(obs(OCT28_CLOSE), POLICY, now=NOW)
    pc = c.PortfolioContext(vulnerability=99, budget_breaches=({"budget": "growth", "ratio": 2.0},))
    assert scoring.apply_uplift(a, pc, POLICY).tier == "RED"
    blue = scoring.compose(
        [ob("technical", "CALM", 30)] + [c.unknown(k, NOW, "x") for k in c.CATEGORIES[1:]], POLICY, now=NOW
    )
    assert blue.tier == "BLUE"
    assert scoring.apply_uplift(blue, pc, POLICY).tier == "BLUE"


def test_yellow_budget_uplift():
    spec = {k: ("WARN", 41) for k in ("technical", "breadth", "volatility")}
    a = scoring.compose(obs(spec), POLICY, now=NOW)
    assert a.tier == "YELLOW"
    pc = c.PortfolioContext(vulnerability=10, budget_breaches=({"budget": "earnings_48h", "ratio": 1.3},))
    assert scoring.apply_uplift(a, pc, POLICY).tier == "ORANGE"


def test_attribution_sums_to_score_and_top_five():
    a = explain.explain(scoring.compose(obs(OCT28_CLOSE), POLICY, now=NOW), POLICY)
    named = [x for x in a.contributors if x.category != "other"]
    assert len(named) == 5 and named[0].category == "event"
    assert sum(x.points for x in a.contributors) == pytest.approx(a.score, abs=0.05)
    assert a.deescalates_if.startswith("ORANGE -> YELLOW if score below 60")


def test_behavior_field_guard_at_boundary():
    a = scoring.compose(obs(OCT28_CLOSE), POLICY, now=NOW)
    pc = c.PortfolioContext(vulnerability=78, drivers=({"symbol": "X", "stop_price": 1.0},))
    with pytest.raises(ValueError):
        scoring.apply_uplift(a, pc, POLICY)


def test_registry_unknown_on_missing_raising_and_bad_shape():
    ctx = c.EvalContext(now=NOW, reader=None, policy=POLICY)

    def boom(_):
        raise RuntimeError("db down")

    out = registry.evaluate_all(
        ctx, {"technical": boom, "breadth": lambda _: {"not": "obs"}, "event": lambda _: ob("event", "STRESS", 140)}
    )
    by = {o.category: o for o in out}
    assert by["technical"].state == "UNKNOWN" and "db down" in by["technical"].reason_unknown
    assert by["breadth"].state == "UNKNOWN" and "dict" in by["breadth"].reason_unknown
    assert by["event"].state == "UNKNOWN" and "outside" in by["event"].reason_unknown
    assert len(out) == 9


def test_cli_fixture_dry_run_and_apply(tmp_path, monkeypatch, capsys):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "mre_eval", Path(__file__).resolve().parents[1] / "scripts" / "market_risk_evaluate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "fred.json").write_text(json.dumps([]))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    assert mod.main(["--fixture", str(fx), "--as-of", "2026-10-29T22:15:00Z", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "dry_run" and len(doc["observations"]) == 9
    assert not (tmp_path / "state").exists()
    assert mod.main(["--fixture", str(fx), "--apply"]) == 0
    assert (tmp_path / "state" / "data" / "runtime" / "market_risk" / "latest.json").exists()
    monkeypatch.setitem(sys.modules, "scripts.lib.market_risk.reader", None)
    assert mod.main([]) == 2


def test_uplift_cap_binds_even_if_a_rule_asks_for_two_tiers():
    import copy

    pol = copy.deepcopy(POLICY)
    pol["tiers"]["uplift"]["vulnerability_rules"] = [{"from": "YELLOW", "min_vulnerability": 50, "to": "RED"}]
    spec = {k: ("WARN", 41) for k in ("technical", "breadth", "volatility")}
    a = scoring.compose(obs(spec), pol, now=NOW)
    assert scoring.apply_uplift(a, c.PortfolioContext(vulnerability=90), pol).tier == "ORANGE"


# ---- noisy_or (the shipped composite, config/market_risk_policy.yaml composite.method) -------------------------


def test_noisy_or_oct28_close_shape_is_orange_not_red():
    a = scoring.compose(obs(OCT28_CLOSE), POLICY_LIVE, now=NOW)
    assert a.tier == "ORANGE" and 60 <= a.score < 75, (a.score, a.hysteresis["why"])


def test_noisy_or_oct29_1815_shape_is_market_red():
    now = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)
    a = scoring.compose(obs(OCT29_1815_MARKET_ORANGE, now), POLICY_LIVE, now=now)
    assert a.market_tier == "RED" and a.score >= 75


def test_noisy_or_calm_categories_never_dilute_stress():
    stressed = {"technical": ("STRESS", 95), "volatility": ("STRESS", 80)}
    calm = dict(stressed, seasonal=("CALM", 20), event=("CALM", 10), macro_credit=("CALM", 15))
    a1 = scoring.compose(obs(stressed), POLICY_LIVE, now=NOW)
    a2 = scoring.compose(obs(calm), POLICY_LIVE, now=NOW)
    assert a2.score <= a1.score + 1e-9  # adding calm categories can only lower the extrapolation, never add risk
    assert a2.score >= 40


def test_noisy_or_warns_alone_never_reach_orange():
    five_warn = {k: ("WARN", 60) for k in ("technical", "volatility", "macro_credit", "seasonal", "event")}
    full = {k: ("CALM", 10) for k in c.CATEGORIES}
    full.update(five_warn)
    assert scoring.compose(obs(full), POLICY_LIVE, now=NOW).score < 60


def test_noisy_or_points_sum_to_score():
    a = explain.explain(scoring.compose(obs(OCT28_CLOSE), POLICY_LIVE, now=NOW), POLICY_LIVE)
    assert sum(x.points for x in a.contributors) == pytest.approx(a.score, abs=0.05)
    assert all(x.points == 0 for x in a.contributors if x.category in ("seasonal",))


def test_noisy_or_calm_market_is_unchanged_by_extrapolation():
    calm = {"technical": ("CALM", 10), "volatility": ("CALM", 10)}
    assert scoring.compose(obs(calm), POLICY_LIVE, now=NOW).score == 0


def test_deescalation_counts_a_session_only_after_its_close():
    calm = obs({"technical": ("CALM", 10)})
    prior = {"tier": "ORANGE", "market_tier": "ORANGE", "hysteresis": {"below_sessions": ["2026-10-27", "2026-10-28"]}}
    morning = datetime(2026, 10, 29, 14, 15, tzinfo=timezone.utc)  # 10:15 ET, session still open
    a = scoring.compose(calm, POLICY_LIVE, prior=prior, now=morning)
    assert a.tier == "ORANGE" and a.hysteresis["below_sessions"] == ["2026-10-27", "2026-10-28"]
    close = datetime(2026, 10, 29, 20, 30, tzinfo=timezone.utc)  # 16:30 ET
    assert scoring.compose(calm, POLICY_LIVE, prior=prior, now=close).tier != "ORANGE"
