"""Precision round 2: no false trims on defensives or a proxy, the evening exit review, operator theme overrides.

Operator 2026-10-31: staples / healthcare held up and must not be trimmed; "warn me the night before".
Public-data fixtures and synthetic books only (§2A).
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import lookthrough as lt
from scripts.lib.market_risk import position_stances as ps
from scripts.lib.market_risk import policy as P
from scripts.lib.market_risk import sectors, shock_type
from scripts.lib.market_risk.fixture_reader import FixtureReader, close_instant

POLICY = P.load_policy()
READER = FixtureReader()
BOOK = {
    "GROWTH": {"groups": {"tech": 0.46, "semis": 0.2, "comm": 0.12, "ai_basket": 0.44}},
    "PROXY": {"groups": {"industrials": 1.0}},
    "STAPLE": {"groups": {"staples": 1.0}},
    "HEALTH": {"groups": {"healthcare": 1.0}},
}


def _block(day: str) -> dict:
    return sectors.measure(c.EvalContext(now=close_instant(date.fromisoformat(day)), reader=READER, policy=POLICY))


def _st(day: str, tier: str, evening=None, book=BOOK):
    b = _block(day)
    return ps.stances(
        positions=list(book),
        exposures=book,
        tier=tier,
        shock=shock_type.classify(b, [], POLICY),
        sectors_block=b,
        prior=None,
        reentry=[],
        stop_distance_pct=None,
        policy=POLICY,
        as_of=day,
        evening_risk=evening,
    )


@pytest.mark.parametrize(
    "day,tier", [("2026-10-23", "ORANGE"), ("2026-10-29", "YELLOW"), ("2026-10-29", "RED"), ("2026-10-30", "RED")]
)
def test_defensives_hold_with_reason(day, tier):
    st = _st(day, tier)
    for sym in ("STAPLE", "HEALTH"):
        assert st[sym]["stance"] == "HOLD", (day, sym, st[sym])
        assert "defensive group holding up" in st[sym]["reasons"]


def test_one_bad_day_does_not_stress_a_group_near_its_high():
    staples = {g["key"]: g for g in _block("2026-10-23")["groups"]}["staples"]
    assert staples["r1"] < -1.5 and staples["dd20"] > -3.0
    assert staples["state"] not in ("STRESS", "WEAK")


def test_proxy_not_trimmed_on_a_weak_non_theme_group_in_a_sector_shock():
    st = _st("2026-10-23", "ORANGE")
    assert st["PROXY"]["stance"] == "HOLD"


def test_evening_exit_review_when_implied_open_reaches_the_stop():
    ev = {"GROWTH": {"room_to_stop_pct": 1.2, "text": "implied open -0.93% from 10 after-hours movers"}}
    st = _st("2026-10-29", "YELLOW", evening=ev)
    assert st["GROWTH"]["stance"] == "EXIT" and st["GROWTH"]["reasons"][0].startswith("after hours:")
    far = _st("2026-10-29", "YELLOW", evening={"GROWTH": {"room_to_stop_pct": 2.6, "text": "x"}})
    assert far["GROWTH"]["stance"] != "EXIT"
    quiet = _st("2026-10-29", "BLUE", evening=ev)
    assert quiet["GROWTH"]["stance"] == "HOLD"


def test_theme_override_is_operator_owned_and_additive():
    ex = lt.exposure_for(
        "XYZ",
        ai_basket=[],
        fund_cfg={},
        ipos={},
        profiles={"XYZ": {"sector": "Industrials"}},
        themes={"XYZ": ["ai_basket"]},
    )
    assert ex["groups"] == {"industrials": 1.0, "ai_basket": 1.0} and "operator theme override" in ex["basis"]
    assert POLICY["positions"]["theme_overrides"] == {}


def _holdings_doc():
    return {
        "as_of": "2026-10-22",  # stale legacy top-level field: never used for freshness
        "data_as_of": "2026-10-30",
        "aggregate_published_at": "2026-10-30T20:45:22+00:00",
        "holdings": [
            {"symbol": "GROWTH_ETF", "account": "acct_taxable_a", "shares": 0.5, "market_value": 10.0, "price": 20.0},
            {"symbol": "AI_STOCK", "account": "acct_taxable_b", "shares": 0.25, "market_value": 25.0, "price": 100.0},
            {
                "symbol": "CORE_FUND",
                "account": "acct_ira_rollover",
                "shares": 1000,
                "market_value": 60000,
                "price": 60.0,
            },
            {"symbol": "TINY", "account": "acct_ira_roth", "shares": 3, "market_value": 30.0, "price": 10.0},
            {
                "symbol": "SOLD_TODAY",
                "account": "acct_ira_rollover",
                "shares": 0.3,
                "market_value": 6.0,
                "price": 20.0,
            },
            {"symbol": "CASH", "account": "acct_ira_rollover", "is_cash": True, "market_value": 100000},
        ],
        "closed_today": {"acct_ira_rollover": [{"symbol": "SOLD_TODAY", "sold_qty": 10.0}]},
    }


def test_current_book_drops_residuals_and_closed_today():
    from scripts.lib.market_risk import book_precision as bp

    book = bp.current_book(POLICY, doc=_holdings_doc())
    assert [p["symbol"] for p in book["material"]] == ["CORE_FUND"]
    assert book["material"][0]["account_type"] == "ira"
    assert book["residuals"] == ["AI_STOCK", "GROWTH_ETF", "TINY"]
    assert book["closed_today_excluded"] == ["SOLD_TODAY"]
    assert book["data_as_of"] == "2026-10-30" and book["published_at"].startswith("2026-10-30")


def test_canonical_store_is_the_one_home_reads():
    from scripts.lib import canonical_store_registry as reg
    from scripts.lib.market_risk import book_precision as bp

    assert (
        reg.resolve_store(bp.HOLDINGS_STORE_ID, root="/nonexistent")["spec"]["path"]
        == "data/portfolios/state/holdings.json"
    )


def test_card_counts_residuals_and_skips_meta():
    from scripts.lib.market_risk import alerts

    text = alerts.render(
        {
            "tier": "ORANGE",
            "score": 61,
            "contributors": [],
            "positions": {
                "_book": {"residuals_ignored": 3},
                "CORE_FUND": {"symbol": "CORE_FUND", "stance": "TRIM", "label": "trim review", "reasons": ["exposed"]},
            },
        }
    )
    assert "residuals ignored: 3" in text and "CORE_FUND: CIO trim review" in text and "_book" not in text


def test_defensive_guard_holds_even_if_a_state_says_stress():
    block = {
        "groups": [{"key": "staples", "label": "Staples", "state": "STRESS", "r5": 0.5}],
        "stressed": ["Staples"],
        "weak": [],
        "resilient": [],
    }
    st = ps.stances(
        positions=["STAPLE"],
        exposures={"STAPLE": {"groups": {"staples": 1.0}}},
        tier="RED",
        shock={"class": "SECTOR"},
        sectors_block=block,
        prior=None,
        reentry=[],
        stop_distance_pct=None,
        policy=POLICY,
        as_of=None,
    )
    assert st["STAPLE"]["stance"] == "HOLD" and st["STAPLE"]["reasons"] == ["defensive group holding up"]


def _flagged_block():
    return {
        "groups": [{"key": "tech", "label": "Technology", "state": "STRESS", "r5": -4.0}],
        "stressed": ["Technology"],
        "weak": [],
        "resilient": [],
    }


def _re2(**met):
    keys = ["group_recovered", "market_below_yellow", "index_reclaimed_50d", "vix_below_20d", "engine_green"]
    return [{"key": k, "met": bool(met.get(k)), "text": k} for k in keys]


def _one(tier, prior, reentry=(), block=None):
    return ps.stances(
        positions=["G"],
        exposures={"G": {"groups": {"tech": 0.5}}},
        tier=tier,
        shock={"class": "SECTOR"},
        sectors_block=block or _flagged_block(),
        prior=prior,
        reentry=list(reentry),
        stop_distance_pct=None,
        policy=POLICY,
        as_of="t",
    )["G"]


def test_milder_tier_never_erases_an_exit():
    out = _one("YELLOW", {"G": {"stance": "EXIT"}})
    assert out["stance"] == "RE_ENTER_IF"
    assert _one("RED", {"G": {"stance": "TRIM"}})["stance"] == "EXIT"


def test_reentry_fires_before_the_tier_flag_but_never_at_red():
    allmet = _re2(group_recovered=True, index_reclaimed_50d=True, vix_below_20d=True)
    assert _one("YELLOW", {"G": {"stance": "EXIT"}}, allmet)["stance"] == "RE_ENTER"
    assert _one("RED", {"G": {"stance": "EXIT"}}, allmet)["stance"] == "EXIT"


def test_after_reentry_flag_again_only_on_escalation():
    back = {"G": {"stance": "RE_ENTER", "reentered_tier": "YELLOW", "since": "t0"}}
    assert _one("YELLOW", back)["stance"] == "RE_ENTER"
    assert _one("ORANGE", back)["stance"] == "TRIM"


def _watch(**over):
    from scripts.lib.market_risk import reentry_watch as rw

    closes = [100.0] * 30 + [90.0, 88.0, 86.0] + [92.0 + i * 0.5 for i in range(25)]
    kw = dict(
        symbol="PROXY",
        exit_date="2026-10-30",
        breakdown_close=95.0,
        closes=closes,
        last_date="2026-11-30",
        group_label="Industrials",
        group_history=["NEUTRAL", "RESILIENT"],
        earnings_next=None,
        earnings_last=None,
        sessions_since_earnings=None,
        sessions_to_earnings=None,
        market_tier="YELLOW",
        options_flow_state="CALM",
        account_types=["ira"],
        loss=True,
        days_since_exit=10,
        policy=POLICY,
    )
    kw.update(over)
    return rw.card(**kw), rw


def test_reentry_watch_all_met_and_counts():
    rec, rw = _watch()
    assert rec["status"] == "RE_ENTER" and rec["met"] == 5 and rec["stance"] == "RE_ENTER"
    rec2, _ = _watch(market_tier="ORANGE", options_flow_state="STRESS")
    assert rec2["status"] == "RE_ENTER_IF" and rec2["headline"] == "3 of 5 conditions met"
    assert "RE-ENTRY WATCH" in rw.render(rec2) and "no order, size or price" in rw.render(rec2)


def test_reentry_watch_pending_earnings_blocks_evaluation():
    rec, _ = _watch(earnings_next="2026-11-03", sessions_to_earnings=2)
    assert rec["status"] == "PENDING_EARNINGS"
    assert (
        rec["headline"]
        == "earnings 2026-11-03 pending: re-entry not evaluated until the post-earnings reaction settles"
    )


def test_reentry_watch_wash_sale_only_taxable_loss_within_30_days():
    assert _watch()[0]["wash_sale_note"] is None
    assert _watch(account_types=["taxable"])[0]["wash_sale_note"]
    assert _watch(account_types=["taxable"], loss=False)[0]["wash_sale_note"] is None
    assert _watch(account_types=["taxable"], days_since_exit=31)[0]["wash_sale_note"] is None


def test_reentry_base_rate_on_own_history():
    from scripts.lib.market_risk import reentry_watch as rw

    cfg = POLICY["reentry_watch"]
    up = [100.0] * 25 + [91.0, 90.0] + [101.0 + i for i in range(40)]
    assert rw.base_rate(up, cfg) == {"n": 1, "beat_waiting": 1, "rate": 1.0, "horizon_sessions": 20}
    fade = [100.0] * 25 + [91.0, 90.0] + [101.0] + [100.5 - 0.1 * i for i in range(40)]
    assert rw.base_rate(fade, cfg)["rate"] == 0.0


def test_reentry_flip_sends_one_p2_card_dry_run(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from scripts import market_risk_evaluate as mre

    def fake_eval(now, reader, policy, prior, portfolio=None):
        a = c.RiskAssessment(
            as_of=now.isoformat(),
            score=30.0,
            market_score=30.0,
            tier="BLUE",
            market_tier="BLUE",
            confirming=0,
            observations=[],
        )
        rec, _ = _watch()
        a.reentry_watch = {"PROXY": rec}
        return a

    monkeypatch.setattr(mre, "evaluate", fake_eval)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    now = datetime(2026, 11, 30, 21, 0, tzinfo=timezone.utc)
    out = mre.run_cycle(
        now,
        None,
        POLICY,
        {"reentry_watch": {"PROXY": {"status": "RE_ENTER_IF"}}},
        apply=False,
        episodes_path=tmp_path / "ep.json",
        ledger_path=tmp_path / "led.json",
    )
    re = [x for x in out["sends"] if x.get("kind") == "reentry"]
    assert len(re) == 1 and "RE-ENTRY WATCH · PROXY" in re[0]["text"]
    again = mre.run_cycle(
        now,
        None,
        POLICY,
        {"reentry_watch": {"PROXY": {"status": "RE_ENTER"}}},
        apply=False,
        episodes_path=tmp_path / "ep.json",
        ledger_path=tmp_path / "led.json",
    )
    assert not [x for x in again["sends"] if x.get("kind") == "reentry"]
