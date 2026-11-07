"""LQ-20261107-333: market-event WP3 plan + MarketEvent@v1 API. Synthetic fixtures only (SYNTH_* symbols,
generic account labels, invented cash). Spec SPEC_MARKET_EVENT_REENTRY_20261107 §4.3/§4.4."""

from __future__ import annotations

import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import market_event_api as api
from scripts.lib import market_event_plan as mep

ROOT = Path(__file__).resolve().parents[1]
POL = mep._merge(mep.DEFAULT_POLICY, {})
NOW = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)


def _bars(closes, vols=None, start=date(2026, 8, 1), lows=None):
    out = []
    for i, c in enumerate(closes):
        lo = lows[i] if lows else c * 0.99
        out.append({"date": (start + timedelta(days=i)).isoformat(), "open": c, "high": c * 1.01, "low": lo,
                    "close": c, "volume": (vols[i] if vols else 1_000_000)})
    return out


def _falling(n=40, start=100.0, step=1.0):
    return [start - step * i for i in range(n)]


def _based():
    """A fall to a low, then a higher-low base with a turn up on rising volume (READY shape)."""
    closes = _falling(32, 100.0, 1.5)              # 100 -> 53.5
    closes += [54.0, 54.5, 55.5, 56.5, 58.0]        # 5 sessions without a new low, closes rising
    vols = [1_000_000] * 32 + [1_500_000] * 5
    lows = [c * 0.99 for c in closes]
    return _bars(closes, vols, lows=lows)


def _snapshot(scores=(70.0, 66.0, 62.0), tiers=("RED", "RED", "ORANGE"), states=("CALM", "WARN", "CALM")):
    hist = [{"as_of": f"2026-11-0{6 + i}T15:00:00+00:00", "score": s, "tier": t}
            for i, (s, t) in enumerate(zip(scores, tiers))]
    cats = [{"category": k, "state": st} for k, st in zip(("options_flow", "breadth", "extended_hours"), states)]
    return {"schema": "MarketRiskSnapshot@v1", "as_of": "2026-11-08T14:00:00+00:00", "tier": tiers[-1],
            "score": scores[-1], "mode": "live", "history": hist, "categories": cats}


# ------------------------------------------------------------------ market gate


def test_market_gate_passes_on_falling_score_and_two_confirmations():
    g = mep.market_gate(_snapshot(), POL)
    assert g["passed"] is True
    assert g["primary"]["score_falling"] is True
    assert g["confirming"] == {"n": 3, "need": 2}


def test_market_gate_flat_weekend_scores_are_not_a_fall():
    g = mep.market_gate(_snapshot(scores=(64.9, 64.9, 64.9), tiers=("RED",) * 3), POL)
    assert g["passed"] is False and g["primary"]["score_falling"] is False
    assert any("not fallen" in r for r in g["reasons"])


def test_market_gate_tier_step_down_counts_without_a_score_fall():
    g = mep.market_gate(_snapshot(scores=(60.0, 61.0, 61.0), tiers=("RED", "RED", "ORANGE")), POL)
    assert g["primary"]["tier_stepped_down"] is True and g["passed"] is True


def test_market_gate_needs_confirmations_and_unknown_does_not_confirm():
    g = mep.market_gate(_snapshot(states=("STRESS", "UNKNOWN", "CALM")), POL)
    assert g["passed"] is False and g["confirming"]["n"] == 1


def test_market_gate_missing_snapshot_is_not_evaluated():
    for snap in (None, {"schema": "MarketRiskSnapshotUnreadable@v1"}):
        g = mep.market_gate(snap, POL)
        assert g["evaluated"] is False and g["passed"] is False


# ------------------------------------------------------------------ name gate + state machine


def test_name_gate_short_history_is_not_evaluated():
    g = mep.name_gate(_bars(_falling(10)), POL)
    assert g["evaluated"] is False and "need 30" in g["reasons"][0]


def test_falling_name_is_watch():
    ev = mep.evaluate_candidate({"symbol": "SYNTH_A"}, _bars(_falling()), mep.market_gate(_snapshot(), POL), POL)
    assert ev["state"] == "WATCH" and ev["tranches_ready"] == 0


def test_based_name_is_ready_and_tranches_follow_gates():
    bars = _based()
    sig = mep.name_gate(bars, POL)["signals"]
    assert sig["no_new_low"] and sig["rsi_turning_up"] and sig["accumulation"]
    passed, failed = mep.market_gate(_snapshot(), POL), {"passed": False}
    ev_fail = mep.evaluate_candidate({"symbol": "SYNTH_B"}, bars, failed, POL)
    ev_pass = mep.evaluate_candidate({"symbol": "SYNTH_B"}, bars, passed, POL)
    assert ev_fail["state"] == "READY" and ev_fail["tranches_ready"] == 1
    assert ev_pass["tranches_ready"] == (3 if sig["sma20_reclaim"] else 2)


def test_third_tranche_needs_sma20_reclaim():
    bars = _based()
    # pin the last close under SMA20: the base is far below the 20-day mean of the fall
    assert mep.name_gate(bars, POL)["signals"]["sma20_reclaim"] is False
    ev = mep.evaluate_candidate({"symbol": "SYNTH_B"}, bars, mep.market_gate(_snapshot(), POL), POL)
    assert ev["tranches_ready"] == 2


def test_stabilizing_without_rsi_turn():
    closes = _falling(32, 100.0, 1.5) + [53.4, 53.3, 53.2, 53.1, 53.0]
    lows = [c * 0.99 for c in closes[:32]] + [53.6 * 0.99] * 5   # no new low, but closes keep sagging
    lows[31] = 50.0
    ev = mep.evaluate_candidate({"symbol": "SYNTH_C"}, _bars(closes, lows=lows), {"passed": True}, POL)
    assert ev["state"] == "STABILIZING"


def test_new_low_under_recorded_invalidation_invalidates_and_sticks():
    bars = _based()
    row = {"symbol": "SYNTH_D", "state": "READY", "plan": {"invalidation": bars[-1]["low"] + 1.0}}
    ev = mep.evaluate_candidate(row, bars, {"passed": True}, POL)
    assert ev["state"] == "INVALIDATED"
    again = mep.evaluate_candidate({"symbol": "SYNTH_D", "state": "INVALIDATED"}, bars, {"passed": True}, POL)
    assert again["state"] == "INVALIDATED"


def test_entered_is_carried_never_inferred():
    bars = _based()
    ev = mep.evaluate_candidate({"symbol": "SYNTH_E", "state": "ENTERED"}, bars, {"passed": False}, POL)
    assert ev["state"] == "ENTERED"
    fresh = mep.evaluate_candidate({"symbol": "SYNTH_E"}, bars, {"passed": True}, POL)
    assert fresh["state"] != "ENTERED"


# ------------------------------------------------------------------ sizing


def _ready(sym, sector, price=50.0, inv=45.0, sma=55.0, q=1.0, d=1.0, rank=1, state="READY", t=2):
    return {"symbol": sym, "sector": sector, "last_price": price, "state": state, "tranches_ready": t, "rank": rank,
            "quality_score": q, "discount_score": d,
            "name_gate": {"last_close": price, "invalidation": inv, "sma20": sma}}


ACCTS = [
    {"account_key": "SYNTHKEY-123456789", "account_label": "Brokerage A", "account_type": "taxable",
     "cash_usd": 30_000.0, "account_value_usd": 200_000.0},
    {"account_key": "SYNTHKEY-987654321", "account_label": "IRA B", "account_type": "rollover_ira",
     "cash_usd": 5_000.0, "account_value_usd": 100_000.0},
    {"account_label": "Paper C", "account_type": "paper", "cash_usd": 99_000.0, "account_value_usd": 99_000.0},
]


def test_deployable_is_cash_minus_reserve_and_tranches_are_30_30_40():
    pol = mep._merge(POL, {"per_name_cap_pct_of_deployable": 100.0, "per_sector_cap_pct_of_deployable": 100.0,
                           "risk_budget_pct_of_account": 100.0})
    out = mep.plan_accounts(ACCTS[:1], [_ready("SYNTH_A", "Tech")], pol)
    a = out[0]
    assert a["reserve_usd"] == 10_000.0 and a["deployable_usd"] == 20_000.0
    usd = [t["usd"] for t in a["names"][0]["tranches"]]
    assert usd == [6_000.0, 6_000.0, 8_000.0]
    assert [t["ready"] for t in a["names"][0]["tranches"]] == [True, True, False]
    t3 = a["names"][0]["tranches"][2]
    assert t3["entry_zone"][0] == 55.0 and t3["shares"] == int(8_000 // 55.0)


def test_cash_under_reserve_deploys_nothing_with_a_reason():
    out = mep.plan_accounts([{"account_label": "Low", "account_type": "taxable", "cash_usd": 1_000.0,
                              "account_value_usd": 100_000.0}], [_ready("SYNTH_A", "Tech")], POL)
    assert out[0]["deployable_usd"] == 0.0 and out[0]["notes"]
    assert out[0]["names"][0]["tranches"][0]["shares"] == 0


def test_per_name_and_sector_caps():
    cands = [_ready(f"SYNTH_{i}", "Tech", rank=i) for i in range(5)] + [_ready("SYNTH_X", "Energy", rank=9)]
    pol = mep._merge(POL, {"risk_budget_pct_of_account": 100.0})
    a = mep.plan_accounts(ACCTS[:1], cands, pol)[0]
    tech = sum(n["target_usd"] for n in a["names"] if n["sector"] == "Tech")
    assert tech <= 0.30 * 20_000 + 0.01
    assert all(n["target_usd"] <= 0.10 * 20_000 + 0.01 for n in a["names"])
    assert any("sector cap" in x for n in a["names"] for x in n["annotations"])


def test_risk_budget_cuts_the_position():
    pol = mep._merge(POL, {"per_name_cap_pct_of_deployable": 100.0, "per_sector_cap_pct_of_deployable": 100.0,
                           "risk_budget_pct_of_account": 0.5})   # $1,000 on a $200k account
    a = mep.plan_accounts(ACCTS[:1], [_ready("SYNTH_A", "Tech", price=50.0, inv=40.0)], pol)[0]
    n = a["names"][0]
    assert n["loss_at_invalidation_usd"] <= 1_000.0 + 1e-6
    assert any("risk budget" in x for x in n["annotations"])


def test_wash_sale_and_account_type_are_annotated_never_dropped():
    wash = {"SYNTH_A": {"kind": "WASH_SALE_RISK_LOSS", "hold_until": "2026-11-30", "label": "loss sale"}}
    out = mep.plan_accounts(ACCTS, [_ready("SYNTH_A", "Tech")], POL, wash=wash)
    taxable, ira, paper = out
    assert taxable["names"][0]["wash_sale"]["kind"] == "WASH_SALE_RISK_LOSS"
    assert taxable["names"][0]["tranches"]           # still planned, annotated
    assert any("disallows the loss permanently" in x for x in ira["names"][0]["annotations"])
    assert ira["tax_class"] == "tax_advantaged" and paper["deployable_usd"] == 0.0 and not paper["names"]


def test_no_price_and_invalidated_carry_reasons():
    c1 = _ready("SYNTH_P", "Tech", price=None)
    c1["name_gate"]["last_close"] = None
    c2 = _ready("SYNTH_Q", "Tech", state="INVALIDATED")
    names = mep.plan_accounts(ACCTS[:1], [c1, c2], POL)[0]["names"]
    by = {n["symbol"]: n["annotations"] for n in names}
    assert "no price: no sizing" in by["SYNTH_P"] and "invalidated: no plan" in by["SYNTH_Q"]


def test_output_carries_labels_never_account_keys():
    blob = json.dumps(mep.plan_accounts(ACCTS, [_ready("SYNTH_A", "Tech")], POL))
    assert "SYNTHKEY" not in blob and "account_key" not in blob
    assert "Brokerage A" in blob


# ------------------------------------------------------------------ policy


def test_policy_file_block_overrides_defaults(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"policy_version": "v-test", "plan": {"cash_reserve_pct": 7.5,
                                                                   "name_gate": {"rsi_low": 30}}}))
    pol = mep.load_policy(p)
    assert pol["policy_source"] == "file" and pol["cash_reserve_pct"] == 7.5
    assert pol["name_gate"]["rsi_low"] == 30 and pol["name_gate"]["min_bars"] == 30
    assert mep.load_policy(tmp_path / "absent.json")["policy_source"] == "defaults"
    (tmp_path / "bad.json").write_text("{torn")
    assert mep.load_policy(tmp_path / "bad.json")["policy_source"].startswith("defaults (unreadable")


# ------------------------------------------------------------------ API


class FakeDB:
    def __init__(self, tables):
        self.t = tables
        self.sql = []

    def __call__(self, sql, params=None):
        self.sql.append(sql)
        s = sql.lower()
        for name, rows in self.t.items():
            if f"from {name}" in s:
                if rows is None:
                    return None
                if "group by" in s:
                    return [{"episode_id": "E1", "state": "READY", "n": 1}]
                return rows
        return []


HOLD = [
    {"account": "SYNTHKEY-123456789", "is_cash": True, "market_value": 30_000.0},
    {"account": "SYNTHKEY-123456789", "symbol": "SYNTH_H", "market_value": 170_000.0},
]


def _active(db, snap=None):
    return api.build_active(db_query=db, snapshot=snap if snap is not None else _snapshot(), holdings_rows=HOLD,
                            label=lambda k: "Brokerage A", facts=lambda r: {"account_type": "taxable"},
                            taxable=lambda a: True, policy=POL, now=NOW)


def test_active_without_tables_is_stale_and_episode_null():
    doc = _active(FakeDB({"market_event_episodes": None}))
    assert doc["schema"] == "MarketEvent@v1" and doc["episode"] is None and doc["stale"] is True
    assert any("unreadable" in r for r in doc["stale_reasons"])
    assert doc["accounts"][0]["deployable_usd"] == 20_000.0 and doc["accounts"][0]["names"] == []
    assert doc["advisory_only"] is True


def test_active_full_shape_labels_only():
    bars = [{"symbol": "SYNTH_B", "bar_time": b["date"], **{k: b[k] for k in ("open", "high", "low", "close",
                                                                                "volume")}} for b in _based()]
    # move the bars to end yesterday so they are fresh
    shift = (NOW.date() - timedelta(days=1)) - date.fromisoformat(bars[-1]["bar_time"])
    for b in bars:
        b["bar_time"] = (date.fromisoformat(b["bar_time"]) + shift).isoformat()
    db = FakeDB({
        "market_event_episodes": [{"episode_id": "E1", "state": "OPEN", "opened_at": "2026-11-05T14:00:00+00:00"}],
        "market_event_candidates": [{"episode_id": "E1", "symbol": "SYNTH_B", "rank": 1, "state": "WATCH",
                                     "last_price": 58.0, "quality_score": 0.7, "discount_score": 0.4,
                                     "reason_evidence": {"sector": "Technology"},
                                     "updated_at": "2026-11-08T13:00:00+00:00"}],
        "market_ohlcv_bars": bars,
        "trade_transactions": [],
    })
    doc = _active(db)
    assert doc["episode"]["episode_id"] == "E1" and doc["market_gate"]["passed"] is True
    c = doc["candidates"][0]
    assert c["symbol"] == "SYNTH_B" and c["state"] == "READY" and c["sector"] == "Technology"
    acct = doc["accounts"][0]
    assert acct["account_label"] == "Brokerage A" and acct["deployable_usd"] == 20_000.0
    assert doc["stale"] is False, doc["stale_reasons"]
    blob = json.dumps(doc, default=str)
    assert "SYNTHKEY" not in blob
    assert all("insert " not in s.lower() and "update " not in s.lower() and "delete " not in s.lower()
               for s in db.sql)


def test_wash_reader_flags_a_recent_taxable_loss_sale():
    today = NOW.date()
    rows = [
        {"trade_date": (today - timedelta(days=60)).isoformat(), "action": "Buy", "symbol": "SYNTH_W",
         "quantity": 10, "price": 100.0, "amount": -1000.0, "fees": 0, "account": "SYNTHKEY-1"},
        {"trade_date": (today - timedelta(days=5)).isoformat(), "action": "Sell", "symbol": "SYNTH_W",
         "quantity": 10, "price": 80.0, "amount": 800.0, "fees": 0, "account": "SYNTHKEY-1"},
    ]
    w = api.read_wash(FakeDB({"trade_transactions": rows}), ["SYNTH_W"], today, lambda a: True)
    assert w["SYNTH_W"]["kind"] == "WASH_SALE_RISK_LOSS"
    assert api.read_wash(FakeDB({"trade_transactions": rows}), ["SYNTH_W"], today, lambda a: False) == {}


def test_history_counts_states():
    doc = api.build_history(db_query=FakeDB({"market_event_episodes": [{"episode_id": "E1", "state": "CLOSED"}],
                                             "market_event_candidates": []}), now=NOW)
    assert doc["episodes"][0]["candidate_states"] == {"READY": 1} and doc["stale"] is False
    bad = api.build_history(db_query=FakeDB({"market_event_episodes": None}), now=NOW)
    assert bad["stale"] is True and bad["episodes"] == []


# ------------------------------------------------------------------ rail


@pytest.mark.parametrize("rel", ["scripts/lib/market_event_plan.py", "scripts/lib/market_event_api.py"])
def test_no_broker_order_or_write_path(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(any(b in m for b in ("broker", "schwab", "alpaca", "moomoo", "requests", "urllib", "order"))
                   for m in mods), mods
    low = src.lower()
    for bad in ("place_order", "insert into", "update market_event", "delete from"):
        assert bad not in low


def test_routes_registered():
    src = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/market-event/active": lambda q=None: _market_event_active_api(q)' in src
    assert '"/api/v2/market-event/history": lambda q=None: _market_event_history_api(q)' in src
