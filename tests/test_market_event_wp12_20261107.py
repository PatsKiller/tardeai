"""LQ-20261107-332 (WP1+WP2): market-event detector, store and ranker. Synthetic fixtures only: SYNTH_* symbols,
no real holdings, cash or account ids. No DB: the DB readers are exercised through fakes."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import market_event_detect as det
from lib import market_event_rank as rank
from lib import market_event_store as store

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc)  # a Saturday


@pytest.fixture()
def policy():
    return copy.deepcopy(rank.load_policy(ROOT / "config" / "market_event_policy.json"))


def fund(sector="Technology", industry="Software", **kw):
    base = {"sector": sector, "industry": industry, "forward_pe": 20.0, "pe": 25.0, "peg": 1.5, "roic_pct": 15.0,
            "oper_margin_pct": 20.0, "total_debt_equity": 0.5, "analyst_recom": 2.0, "inst_trans_pct": 0.5,
            "insider_trans_pct": -1.0, "beta": 1.0, "market_cap_usd": 5e10, "avg_vol_m": 5000.0}
    base.update(kw)
    return base


def mre(tier="RED", groups=None, as_of="2026-11-07T22:00:00+00:00"):
    return {"tier": tier, "score": 60.0, "as_of": as_of, "reentry_watch": {},
            "sectors": {"groups": groups if groups is not None else [
                {"key": "tech", "kind": "sector", "state": "STRESS", "rs5": -5.5, "symbols": ["SYNTH_XLK"]},
                {"key": "semis", "kind": "sector", "state": "STRESS", "rs5": -9.6, "symbols": ["SYNTH_SMH"]},
                {"key": "staples", "kind": "sector", "state": "RESILIENT", "rs5": 3.0, "symbols": []},
                {"key": "ai_basket", "kind": "theme", "state": "NEUTRAL", "rs5": -1.0, "symbols": ["SYNTH_AI"]},
            ]}}


# ------------------------------------------------------------------------------------------------ policy
def test_policy_weights_and_plan_block(policy):
    w = {k: v["weight"] for k, v in policy["ranking"]["quality_factors"].items() if not k.startswith("_")}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert policy["plan"]["tranche_pcts"] == [30, 30, 40]  # WP3's block, verbatim
    assert policy["plan"]["name_gate"]["min_bars"] == 30
    assert "yfinance" not in policy["data"]["quote_sources_allowed"]
    seed = policy["detector"]["seed_episodes"][0]
    assert (seed["kind"], seed["scope"], seed["baseline_date"]) == ("broad_selloff", "market", "2026-11-04")


# ------------------------------------------------------------------------------------------------ pure scoring
def test_split_guard_flags_split_ratio_not_a_real_drop(policy):
    g = policy["data"]["split_guard"]
    assert rank.split_suspect(300.0, 92.0, g)        # ~3.26:1 with a real drop on top: split break
    assert rank.split_suspect(50.0, 100.0, g)        # reverse 2:1
    assert not rank.split_suspect(100.0, 80.0, g)    # -20%: a real move
    assert not rank.split_suspect(100.0, 62.0, g)    # -38%: below min_abs_move_pct, never a split
    assert not rank.split_suspect(100.0, 16.0, g)    # ratio 6.25: outside 15% of 5 and of 8


def test_absent_is_not_negative(policy):
    f = policy["ranking"]["quality_factors"]
    full, cov_full, _ = rank.quality_score(rank.quality_inputs(fund(), 25.0, None), f)
    sparse, cov_sparse, detail = rank.quality_score({"roic_pct": 15.0}, f)
    assert sparse == pytest.approx(75.0)             # one factor, renormalised: not dragged to zero
    assert cov_sparse < 0.2 < cov_full
    assert detail["orders_backlog"]["value"] is None
    assert rank.quality_score({}, f)[0] is None


def test_quality_prefers_cheaper_better_business(policy):
    f = policy["ranking"]["quality_factors"]
    good = rank.quality_score(rank.quality_inputs(fund(forward_pe=12.0, roic_pct=30.0), 25.0, 25.0), f)[0]
    bad = rank.quality_score(rank.quality_inputs(fund(forward_pe=60.0, roic_pct=1.0, total_debt_equity=3.0),
                                                 25.0, -20.0), f)[0]
    assert good > 80 > 30 > bad


def test_discount_is_drawdown_beyond_beta(policy):
    d = policy["ranking"]["discount"]
    s_hi, ev = rank.discount_score(-20.0, 1.0, -4.0, d)   # fell 16 pts more than beta implies
    assert ev["excess_drawdown_pct"] == pytest.approx(-16.0) and s_hi == pytest.approx(80.0)
    s_beta, _ = rank.discount_score(-8.0, 2.0, -4.0, d)   # fell exactly what beta 2 implies
    assert s_beta == 0.0
    assert rank.discount_score(-8.0, None, -4.0, d)[1]["beta_used"] == 1.0


def test_group_most_specific_first(policy):
    g = policy["universe"]["group_map"]
    groups = {x["key"]: x for x in mre()["sectors"]["groups"]}
    assert rank.group_for(fund(industry="Semiconductors"), "SYNTH_A", g, groups) == "semis"
    assert rank.group_for(fund(), "SYNTH_B", g, groups) == "tech"
    assert rank.group_for(fund(), "SYNTH_AI", g, groups) == "ai_basket"
    assert rank.group_for(fund(sector="Utilities"), "SYNTH_C", g, groups) == "utilities"


def test_fell_for_reason(policy):
    cfg = policy["ranking"]["fell_for_reason"]
    assert rank.fell_for_reason("SYNTH_A", [{"catalyst_type": "guidance_lower"}], -1.0, cfg)[0]
    assert not rank.fell_for_reason("SYNTH_A", [{"catalyst_type": "contract_win"}], -20.0, cfg)[0]
    assert rank.fell_for_reason("SYNTH_A", [{"catalyst_type": "earnings_beat"}], -12.0, cfg)[0]   # reaction
    assert not rank.fell_for_reason("SYNTH_A", [{"catalyst_type": "earnings_beat"}], -2.0, cfg)[0]


def test_rpo_growth_yoy_only():
    from datetime import date
    rows = [(date(2026, 9, 30), 120.0), (date(2026, 6, 30), 110.0), (date(2025, 9, 30), 100.0)]
    assert rank.rpo_growth(rows) == pytest.approx(20.0)
    assert rank.rpo_growth(rows[:2]) is None          # no year-ago quarter: absent, not zero


def _score(policy, universe, baseline, last, funds, catalysts=None, bench_dd=-4.0, affected=("tech", "semis")):
    return rank.score_candidates(universe=universe, baseline=baseline, last=last, funds=funds,
                                 catalysts=catalysts or {}, orders={}, bench_drawdown_pct=bench_dd,
                                 mre_groups={x["key"]: x for x in mre()["sectors"]["groups"]},
                                 affected_groups=affected, policy=policy)


def test_score_candidates_end_to_end(policy):
    universe = {"SYNTH_HELD": {"holding"}, "SYNTH_STOP": {"stop_out", "watchlist"}, "SYNTH_PEER": {"sector_peer"},
                "SYNTH_JUNK": {"sector_peer"}, "SYNTH_SPLIT": {"watchlist"}, "SYNTH_FLAT": {"holding"},
                "SYNTH_NEWS": {"watchlist"}, "SYNTH_NOPX": {"holding"}, "SYNTH_STAPLE": {"sector_peer"}}
    baseline = {"SYNTH_HELD": 100.0, "SYNTH_STOP": 50.0, "SYNTH_PEER": 80.0, "SYNTH_JUNK": 30.0,
                "SYNTH_SPLIT": 300.0, "SYNTH_FLAT": 40.0, "SYNTH_NEWS": 60.0, "SYNTH_STAPLE": 70.0}
    last = {"SYNTH_HELD": 90.0, "SYNTH_STOP": 40.0, "SYNTH_PEER": 68.0, "SYNTH_JUNK": 20.0,
            "SYNTH_SPLIT": 95.0, "SYNTH_FLAT": 39.5, "SYNTH_NEWS": 45.0, "SYNTH_STAPLE": 60.0}
    funds = {s: fund() for s in baseline}
    funds["SYNTH_JUNK"] = fund(roic_pct=-5.0)                  # fails the peer quality floor
    funds["SYNTH_STAPLE"] = fund(sector="Consumer Defensive")  # peer in an unaffected group
    cats = {"SYNTH_NEWS": [{"catalyst_type": "analyst_downgrade", "headline": "synthetic"}]}
    ranked, excluded = _score(policy, universe, baseline, last, funds, cats)
    syms = [c["symbol"] for c in ranked]
    assert set(syms) == {"SYNTH_HELD", "SYNTH_STOP", "SYNTH_PEER", "SYNTH_NEWS"}
    assert excluded["counts"] == {"no_price": 1, "split_suspect": 1, "peer_floor": 2, "drawdown_below_min": 1}
    assert syms[-1] == "SYNTH_NEWS" and ranked[-1]["fell_for_reason"]          # ranked after the clean names
    assert ranked[-1]["reason_evidence"]["rank_group"] == "fell_for_reason"
    assert [c["rank"] for c in ranked] == [1, 2, 3, 4]
    for c in ranked:
        ev = c["reason_evidence"]
        assert {"sector", "industry", "group"} <= set(ev) and c["state"] == "WATCH" and c["gates"] == {}
        assert c["plan"] is None
    stop = next(c for c in ranked if c["symbol"] == "SYNTH_STOP")
    assert stop["source"] == ["stop_out", "watchlist"] and stop["drawdown_pct"] == pytest.approx(-20.0)
    assert stop["reason_evidence"]["unexplained_excess_drop"]  # -20% vs beta-expected -4%, no catalyst


def test_peer_cap_applies_to_pure_peers_only(policy):
    policy["universe"]["sector_peers"]["per_group_cap"] = 2
    universe = {f"SYNTH_P{i}": {"sector_peer"} for i in range(5)} | {"SYNTH_W": {"watchlist", "sector_peer"}}
    baseline = {s: 100.0 for s in universe}
    last = {s: 80.0 + i for i, s in enumerate(sorted(universe))}
    ranked, excluded = _score(policy, universe, baseline, last, {s: fund() for s in universe})
    assert excluded["counts"]["peer_cap"] == 3
    assert "SYNTH_W" in {c["symbol"] for c in ranked} and len(ranked) == 3


# ------------------------------------------------------------------------------------------------ detector
def closes(spy=(100.0, 99.0, 98.0, 96.0, 95.5, 95.0), qqq=(100.0, 98.0, 97.0, 95.0, 94.0, 94.5)):
    days = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    return {"SPY": dict(zip(days, spy)), "QQQ": dict(zip(days, qqq))}


def test_triggers_and_seed_open_once(policy):
    trig = det.evaluate_triggers(mre(), closes(), "2026-11-06", policy, NOW)
    assert trig["mre"]["hit"] and {t["symbol"] for t in trig["index"]} == {"SPY", "QQQ"}
    assert trig["affected_groups"] == ["semis", "tech"]
    eps = det.plan_episodes([], trig, policy, NOW)
    assert [e["episode_id"] for e in eps] == ["broad_selloff:market:2026-11-04"]   # seed; no duplicate broad
    again = det.plan_episodes([{**{k: v for k, v in eps[0].items() if k != "_new"}}], trig, policy, NOW)
    assert len(again) == 1 and not again[0].get("_new")


def test_stale_mre_does_not_trigger(policy):
    policy["detector"]["seed_episodes"] = []
    trig = det.evaluate_triggers(mre(as_of="2026-11-01T00:00:00+00:00"), closes(spy=(100,) * 6, qqq=(100,) * 6),
                                 "2026-11-06", policy, NOW)
    assert not trig["mre"]["hit"] and trig["index"] == [] and trig["sectors"] == []
    assert det.plan_episodes([], trig, policy, NOW) == []


def test_sector_rotation_only_without_broad(policy):
    policy["detector"]["seed_episodes"] = []
    trig = det.evaluate_triggers(mre(tier="YELLOW"), closes(spy=(100,) * 6, qqq=(100,) * 6), "2026-11-06",
                                 policy, NOW)
    eps = det.plan_episodes([], trig, policy, NOW)
    assert sorted(e["episode_id"] for e in eps) == ["sector_rotation:semis:2026-11-05",
                                                    "sector_rotation:tech:2026-11-05"]


def test_advance_state_closes_after_calm_and_recovery(policy):
    ep = {"episode_id": "broad_selloff:market:2026-11-04", "kind": "broad_selloff", "scope": "market",
          "state": "OPEN", "closed_at": None, "last_eval": {}}
    c = [{"symbol": "SYNTH_A", "baseline_price": 100.0, "last_price": 80.0, "drawdown_pct": -20.0}]
    red = det.evaluate_triggers(mre(), closes(), "2026-11-06", policy, NOW)
    ep = det.advance_state(ep, c, red, policy, NOW)
    assert ep["state"] == "OPEN" and ep["last_eval"]["troughs"]["SYNTH_A"] == 80.0
    for day, px in (("2026-11-09", 92.0), ("2026-11-10", 93.0), ("2026-11-11", 95.0)):
        calm = det.evaluate_triggers(mre(tier="YELLOW"), closes(), day, policy, NOW)
        ep = det.advance_state(ep, [{**c[0], "last_price": px, "drawdown_pct": px - 100.0}], calm, policy, NOW)
    assert ep["state"] == "CLOSED" and ep["closed_at"] and len(ep["last_eval"]["calm_sessions"]) == 3


# ------------------------------------------------------------------------------------------------ store + lane
def test_upsert_never_resets_wp3_fields():
    src = Path(store.__file__).read_text()
    conflict = src.split("ON CONFLICT (episode_id, symbol) DO UPDATE SET", 1)[1].split('"""', 1)[0]
    for col in ("gates", "state", "plan"):
        assert f"{col} = EXCLUDED" not in conflict


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_dry_run_writes_nothing(monkeypatch, tmp_path, policy, capsys):
    calls = []
    monkeypatch.setattr(det, "connect", lambda read_only: (calls.append(("connect", read_only)), FakeConn())[1])
    monkeypatch.setattr(det, "index_closes", lambda conn, p, d: closes())
    monkeypatch.setattr(store, "tables_exist", lambda conn: False)
    for fn in ("upsert_episode", "upsert_candidates", "unrank_missing"):
        monkeypatch.setattr(store, fn, lambda *a, **k: calls.append("WRITE"))
    cand = {"symbol": "SYNTH_A", "source": ["holding"], "baseline_price": 100.0, "last_price": 85.0,
            "drawdown_pct": -15.0, "quality_score": 70.0, "discount_score": 50.0, "combined_score": 62.0,
            "rank": 1, "fell_for_reason": False, "gates": {}, "state": "WATCH", "plan": None,
            "reason_evidence": {"group": "tech", "quality_coverage": 0.8}}
    monkeypatch.setattr(rank, "build_candidates", lambda *a, **k: {"candidates": [cand], "excluded": {},
                                                                   "inputs": {"synthetic": True}})
    mre_file = tmp_path / "mre.json"
    mre_file.write_text(json.dumps(mre()))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rc = det.main(["--dry-run", "--mre", str(mre_file), "--now", NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 0 and "WRITE" not in calls and ("connect", True) in calls
    report = json.loads(out.split("DRY-RUN ", 1)[1])
    ep = report["summary"]["episodes"][0]
    assert ep["episode_id"] == "broad_selloff:market:2026-11-04" and ep["top"][0]["symbol"] == "SYNTH_A"
    assert not list(tmp_path.rglob("*_last.json"))   # no receipt in a dry run
