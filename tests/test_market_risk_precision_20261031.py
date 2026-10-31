"""Precision layer: sector attribution, shock type, look-through, position stances, protection playbook.

Operator 2026-10-31: "aware of which sectors got hit", "whether it's a pandemic or ... a certain sector", "advise me
... when to get back in", "the percentages recommendation for each trail and stop". Public-data fixtures and synthetic
books only (§2A). Advisory only: every payload passes the behaviour-field guard and the sizing-text guard.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import lookthrough as lt
from scripts.lib.market_risk import position_stances as ps
from scripts.lib.market_risk import protection_playbook as pp
from scripts.lib.market_risk import sectors, shock_type
from scripts.lib.market_risk import policy as P
from scripts.lib.market_risk.fixture_reader import FixtureReader, close_instant

POLICY = P.load_policy()
READER = FixtureReader()


def _block(day: str) -> dict:
    ctx = c.EvalContext(now=close_instant(date.fromisoformat(day)), reader=READER, policy=POLICY)
    return sectors.measure(ctx)


@pytest.fixture(scope="module")
def oct30():
    return _block("2026-10-30")


def test_oct30_tech_semis_ai_hit_defensives_hold(oct30):
    assert {"Technology", "Semis", "AI basket"} <= set(oct30["stressed"])
    assert {"Staples", "Healthcare", "Utilities"} <= set(oct30["resilient"])
    assert oct30["rotating"], "defensive rotation not detected"
    line = sectors.card_line(oct30)
    assert line.startswith("Hit: ") and "Holding: " in line


def test_shock_type_oct30_is_sector_not_systemic(oct30):
    st = shock_type.classify(oct30, [], POLICY)
    assert st["class"] == "SECTOR"
    assert st["headline"].startswith("Type: SECTOR") and "not systemic" in st["headline"]
    c.assert_no_behavior_fields(st)


def test_shock_type_covid_is_systemic():
    st = shock_type.classify(_block("2020-03-12"), [], POLICY)
    assert st["class"] == "SYSTEMIC"


def test_unknown_when_no_history():
    class Empty:
        def daily_bars(self, *a, **k):
            return []

    ctx = c.EvalContext(now=close_instant(date(2026, 10, 30)), reader=Empty(), policy=POLICY)
    b = sectors.measure(ctx)
    assert all(g["state"] == "UNKNOWN" for g in b["groups"])
    assert shock_type.classify(b, [], POLICY)["class"] == "UNKNOWN"


def test_heatmap_carries_exposure_only_when_given(oct30):
    rows = sectors.heatmap(oct30)
    assert rows and all("book_exposure_share" not in r for r in rows)
    rows2 = sectors.heatmap(oct30, {"tech": 0.5})
    assert any(r.get("book_exposure_share") == 0.5 for r in rows2)


EXPO = {
    "GROWTH": {"groups": {"tech": 0.46, "semis": 0.2, "ai_basket": 0.44}},
    "STAPLE": {"groups": {"staples": 1.0}},
    "HEALTH": {"groups": {"healthcare": 1.0}},
}


def _stances(tier, shock_class, block, prior=None, reentry=None):
    return ps.stances(
        positions=list(EXPO),
        exposures=EXPO,
        tier=tier,
        shock={"class": shock_class, "headline": f"Type: {shock_class}"},
        sectors_block=block,
        prior=prior,
        reentry=reentry or [],
        stop_distance_pct={"GROWTH": 4.1},
        policy=POLICY,
        as_of="2026-10-30T20:00:00+00:00",
    )


def test_sector_shock_flags_only_exposed_positions(oct30):
    st = _stances("ORANGE", "SECTOR", oct30)
    assert st["GROWTH"]["stance"] == "TRIM" and st["GROWTH"]["label"] == "trim review"
    assert st["STAPLE"]["stance"] == "HOLD" and "defensive group holding up" in st["STAPLE"]["reasons"]
    assert st["HEALTH"]["stance"] == "HOLD"
    assert _stances("RED", "SECTOR", oct30)["GROWTH"]["stance"] == "EXIT"
    assert _stances("YELLOW", "SECTOR", oct30)["GROWTH"]["stance"] == "WATCH_CLOSELY"


def test_systemic_shock_flags_whole_book(oct30):
    st = _stances("RED", "SYSTEMIC", oct30)
    assert {s["stance"] for s in st.values()} == {"EXIT"}


def _re(**met):
    keys = ["group_recovered", "market_below_yellow", "index_reclaimed_50d", "vix_below_20d", "engine_green"]
    return [{"key": k, "met": bool(met.get(k)), "text": k} for k in keys]


def test_reentry_needs_all_required_conditions(oct30):
    prior = {"GROWTH": {"stance": "EXIT", "flagged_groups": ["tech"]}}
    calm = {**oct30, "stressed": [], "weak": []}
    partial = _stances("NONE", "SECTOR", calm, prior, _re(group_recovered=True, index_reclaimed_50d=True))
    assert partial["GROWTH"]["stance"] == "RE_ENTER_IF"
    full = _stances(
        "NONE", "SECTOR", calm, prior, _re(group_recovered=True, index_reclaimed_50d=True, vix_below_20d=True)
    )
    assert full["GROWTH"]["stance"] == "RE_ENTER"
    assert ps.reentry_card(full["GROWTH"]).startswith("🟢 RE-ENTRY CONDITIONS MET")
    green = _stances("GREEN", "SECTOR", calm, prior, _re(engine_green=True))
    assert green["GROWTH"]["stance"] == "RE_ENTER"


def test_stance_payload_has_no_behaviour_fields(oct30):
    for rec in _stances("RED", "SECTOR", oct30).values():
        c.assert_no_behavior_fields(rec)
    with pytest.raises(ValueError):
        c.assert_no_behavior_fields({"GROWTH": {"stance": "EXIT", "stop_price": 1.0}})


def test_lookthrough_ipo_overrides_stale_fund_entry_and_goog_alias():
    funds = {
        "ZZIPO": {"name": "old fund", "lookthrough": "none"},
        "GROWTH_ETF": {"weights": {"Technology": 0.5}, "industries": {"Semiconductors": 0.2}},
    }
    ipos = {"lockups": {"ZZIPO": {}}}
    ex = lt.exposure_for(
        "ZZIPO", ai_basket=["NVDA"], fund_cfg=funds, ipos=ipos, profiles={"ZZIPO": {"sector": "Industrials"}}
    )
    assert ex["groups"] == {"industrials": 1.0} and "stale" in ex["note"]
    hs = {
        "GROWTH_ETF": [
            {"holding": "NVDA", "weight": 0.12},
            {"holding": "GOOG", "weight": 0.04},
            {"holding": "XOM", "weight": 0.01},
        ]
    }
    g = lt.exposure_for("GROWTH_ETF", ai_basket=["NVDA", "GOOGL"], fund_cfg=funds, ipos=ipos, holdings=hs)
    assert g["ai_share"] == pytest.approx(0.16) and g["groups"]["semis"] == 0.2
    none = lt.exposure_for("ZZIPO", ai_basket=[], fund_cfg=funds, ipos={})
    assert none["groups"] == {} and none["basis"] == "fund_unknown"


def _bars(gaps):
    rows, px = [], 100.0
    for g in gaps:
        rows.append({"open": px * (1 + g / 100), "close": px * (1 + g / 100)})
        px = rows[-1]["close"]
    return [{"open": 100.0, "close": 100.0}] + rows


def test_playbook_band_comes_from_house_policy_not_literals(oct30):
    import holding_family as hf

    cfg = POLICY["positions"]["playbook"]
    band = pp.house_band("SYNTH", "ORANGE", cfg)
    fam, _ = hf.classify_family("SYNTH")
    expect = hf.protection_bounds(fam, regime=cfg["tier_posture"]["ORANGE"])
    assert band["stop_band_pct"] == [expect["stop_min_pct"], expect["stop_max_pct"]]
    assert band["posture_source"] and "OPERATOR-SET" in band["posture_source"]


def test_playbook_gap_implied_open_wash_sale_and_guards():
    stance = {"stance": "TRIM", "re_enter_if": [{"key": "vix_below_20d", "met": False, "text": "VIX below its 20-day"}]}
    bars = _bars([0.1] * 100 + [-5.0, 0.2, -4.5] + [0.1] * 50)
    hold = [
        {"holding": "AMZN", "weight": 0.05},
        {"holding": "GOOG", "weight": 0.04},
        {"holding": "NVDA", "weight": 0.12},
    ]
    band = {
        "family": "f",
        "family_label": "Growth",
        "stop_band_pct": [10.0, 12.0],
        "trail_band_pct": [10.0, 12.0],
        "posture_applied": None,
        "posture_source": None,
    }
    kw = dict(
        symbol="GROWTH",
        tier="ORANGE",
        stance=stance,
        stop_distance_pct=4.1,
        bars=bars,
        holdings=hold,
        after_hours_moves={"AMZN": -6.0, "GOOGL": -2.0, "NVDA": -1.0},
        hedge={"symbol": "PSQ", "state": "GREEN"},
        cluster=["GROWTH", "SEMIS_FUND"],
        policy=POLICY,
        as_of=None,
        band=band,
    )
    ira = pp.build(account_types=["ira"], **kw)
    assert ira["gap_risk"]["gapped_through"] == 2
    assert ira["implied_open"]["implied_open_pct"] == pytest.approx(-0.5)
    assert ira["wash_sale_note"] is None and ira["moves_with"] == ["SEMIS_FUND"]
    taxable = pp.build(account_types=["taxable"], **kw)
    assert taxable["wash_sale_note"] and "wash sale" in taxable["wash_sale_note"]
    lines = pp.render_lines(taxable)
    assert any("stop orders are not eligible" in x for x in lines)
    assert lines[-1].startswith("Advisory.")
    with pytest.raises(ValueError):
        pp._sizing_guard(["sell 500 shares of GROWTH"])


def test_book_clusters_same_ai_bet():
    r = [0.01 * ((i % 7) - 3) for i in range(60)]
    cl = pp.book_clusters(
        {"A": r, "B": [x * 1.1 for x in r], "C": [((i * 37) % 11 - 5) / 100 for i in range(60)]},
        {"A": ["ai_basket"], "D": ["ai_basket"]},
        0.8,
    )
    assert ["A", "B", "D"] in cl


def test_card_leads_with_shock_type_and_sectors(oct30):
    from scripts.lib.market_risk import alerts

    st = shock_type.classify(oct30, [], POLICY)
    text = alerts.render(
        {
            "tier": "ORANGE",
            "score": 61,
            "confirming": 3,
            "contributors": [],
            "sectors": oct30,
            "shock_type": st,
            "positions": _stances("ORANGE", "SECTOR", oct30),
        }
    )
    lines = text.splitlines()
    assert lines[1].startswith("Type: SECTOR") and lines[2].startswith("Hit: ")
    assert any(x.startswith("GROWTH: CIO trim review") for x in lines)


def test_projection_and_cio_facts_carry_precision(oct30):
    from scripts.lib import market_risk_projection as mp
    from scripts.lib.market_risk import cio_context

    st = shock_type.classify(oct30, [], POLICY)
    doc = {
        "schema": c.SCHEMA_ASSESSMENT,
        "as_of": "2026-10-30T20:00:00+00:00",
        "tier": "ORANGE",
        "market_tier": "ORANGE",
        "score": 61.0,
        "confirming": 3,
        "observations": [],
        "contributors": [],
        "sectors": oct30,
        "shock_type": st,
        "heatmap": sectors.heatmap(oct30),
        "positions": {},
    }
    snap = mp.snapshot_from_assessment(doc)
    assert snap["shock_type"]["class"] == "SECTOR" and snap["heatmap"]
    facts = cio_context.ask_facts({**snap, "state": "evaluated"})
    assert facts["shock_type"]["class"] == "SECTOR" and "Technology" in facts["sectors"]["stressed"]


def test_weak_groups_count_only_from_orange():
    block = {
        "groups": [{"key": "ai_basket", "label": "AI basket", "state": "WEAK"}],
        "stressed": [],
        "weak": ["AI basket"],
        "resilient": [],
    }
    ex = {"GROWTH": {"groups": {"ai_basket": 0.44}}}
    kw = dict(
        positions=["GROWTH"],
        exposures=ex,
        shock={"class": "SECTOR"},
        sectors_block=block,
        prior=None,
        reentry=[],
        stop_distance_pct=None,
        policy=POLICY,
        as_of=None,
    )
    assert ps.stances(tier="YELLOW", **kw)["GROWTH"]["stance"] == "HOLD"
    assert ps.stances(tier="RED", **kw)["GROWTH"]["stance"] == "EXIT"


def test_moves_with_is_direct_not_transitive():
    a = [0.01 * ((i % 7) - 3) for i in range(60)]
    b = [x * 1.2 for x in a]
    c2 = [0.5 * x + 0.01 * ((i * 13) % 5 - 2) for i, x in enumerate(b)]
    got = pp.moves_with("A", {"A": a, "B": b, "C": c2}, {"A": ["ai_basket"], "D": ["ai_basket"], "C": []}, 0.95)
    assert "B" in got and "D" in got and "C" not in got


def test_no_broker_stop_is_said():
    pb = {
        "symbol": "X",
        "stance": "TRIM",
        "house": {"family_label": "f", "stop_band_pct": [5, 8], "trail_band_pct": [6, 8], "posture_applied": None},
        "broker_stop_distance_pct": None,
        "gap_risk": {},
        "implied_open": {},
        "session_facts": [],
        "moves_with": [],
        "hedge": None,
        "wash_sale_note": None,
    }
    assert "No broker stop is observed on this position." in pp.render_lines(pb)
