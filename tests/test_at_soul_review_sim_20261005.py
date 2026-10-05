"""Active Trader soul: "should have been" session review + automated mode as SIMULATION ONLY.

Operator 2026-10-05: "This is the exact type of methodology I need you to build into this as a soul and
its foundation … both the option for manual and automated … it would have got in and got out safely
according to the volume and what was happening in the Level 2."

Pins (docs/active_trader/ACTIVE_TRADER_SOUL.md):
- the review reproduces the operator's XNDU 2026-10-05 table from real bars + journal + fills;
- one exit rule serves review and simulator; the simulator sizes to the supply near the ask;
- there is no live mode and neither module can reach a broker, an order or a market-data provider.
Fixture: tests/fixtures/active_trader/xndu_session_20261005.json (real data). Fakes only.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import auto_trader_sim as sim  # noqa: E402
from active_trader import momentum_alerts_api as api  # noqa: E402
from active_trader import session_review as sr  # noqa: E402

FX = json.loads((ROOT / "tests" / "fixtures" / "active_trader" / "xndu_session_20261005.json").read_text())
CFG = sr.ReviewConfig()


@pytest.fixture(autouse=True)
def _journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    return tmp_path / "at"


def _trips():
    return api.attribute_fills(FX["fills"], [api._compact(r, None) for r in FX["journal"]])


def _review():
    return sr.review_symbol("XNDU", bars=FX["bars"], journal=FX["journal"], trips=_trips(), cfg=CFG)


def _row(rv, time):
    return [r for r in rv["table"] if r["time"] == time]


# ── should have been ──────────────────────────────────────────────────────────

def test_ideal_entries_match_the_operator_table():
    ideal = sr.ideal_trades(FX["bars"], CFG)
    t1, t2 = ideal["trades"][0], ideal["trades"][1]
    assert (t1["kind"], sr.et(t1["ts"], False), t1["price"]) == ("breakout", "09:51", 4.35)
    assert (t2["kind"], sr.et(t2["ts"], False), t2["price"]) == ("pullback", "09:59", 4.38)
    assert tuple(round(z, 2) for z in t2["zone"]) == (4.38, 4.40)
    assert (sr.et(ideal["top"]["ts"], False), ideal["top"]["price"]) == ("10:06", 4.5)
    assert any(sr.et(h["ts"], False) == "10:05" for h in ideal["holding_breaks"])
    assert t1["pnl_per_share"] > 0 and t2["pnl_per_share"] > 0


def test_review_reproduces_the_xndu_table():
    rv = _review()
    assert _row(rv, "09:50:13")[0]["should"].startswith("✅ Correct")
    e1 = _row(rv, "09:51")[0]
    assert "alert held" in e1["engine"] and "best entry #1" in e1["should"]
    chase = _row(rv, "09:55:11")[0]
    assert "Time to buy" in chase["engine"] and "Extended, don't chase; buy zone 4.38–4.40" in chase["should"]
    missed = _row(rv, "10:00:22")[0]
    assert "COOLDOWN" in missed["engine"] and "best entry #2" in missed["should"] and "missed" in missed["should"]
    assert "Second breakout already underway" in _row(rv, "10:05:16")[0]["should"]
    assert _row(rv, "10:06")[0]["should"] == "Top of the move"
    buy = _row(rv, "10:07:09")[0]
    assert buy["engine"].startswith("Your buy, 1m53s after the 10:05 heads-up") and buy["should"] == "After the top"
    assert _row(rv, "10:08:15")[0]["engine"].startswith("Your sell, +$1.00")
    m = rv["metrics"]
    assert m["latency_s"] == [252] and m["correct_heads_up"] == 1
    assert m["missed"][0]["reasons"] == ["COOLDOWN"] and m["chases"][0]["ext_r"] >= 1
    assert m["you"][0]["after_top"] is True


def test_vetoes_with_no_ideal_entry_are_graded_correct():
    rv = _review()
    assert _row(rv, "10:10:15")[0]["should"].startswith("✅ Correct to stay out")


def test_exit_evidence_rules():
    bars = sr.norm_bars([
        {"t": "2026-10-05T14:00:00Z", "o": 10, "h": 10.1, "l": 9.9, "c": 10.0, "v": 100},
        {"t": "2026-10-05T14:01:00Z", "o": 10, "h": 10.2, "l": 9.95, "c": 10.1, "v": 100},
        {"t": "2026-10-05T14:02:00Z", "o": 10.1, "h": 10.9, "l": 10.05, "c": 10.2, "v": 900},
    ])
    vw = sr.vwap_series(bars)
    assert sr.exit_evidence(bars, 1, stop=9.97, entry_idx=0, vwap=vw, cfg=CFG)[0] == "stop hit"
    assert sr.exit_evidence(bars, 2, stop=9.0, entry_idx=0, vwap=vw, cfg=CFG)[0] == "volume climax with a long upper wick"
    assert sr.exit_evidence(bars, 1, stop=9.0, entry_idx=0, vwap=vw, cfg=CFG) is None


# ── automated mode: simulation only ───────────────────────────────────────────

def _sim(size):
    review = sr.build_review("2026-10-05", journal=FX["journal"], trips=_trips(), bars_fn=lambda s: FX["bars"], cfg=CFG)
    return sim.simulate_day(review, journal=FX["journal"], bars_fn=lambda s: FX["bars"],
                            cfg_raw={"active_trader_mode": "auto_sim", "active_trader_auto_sim": {"size_shares": size}})


def test_sim_engine_timing_loses_and_improved_timing_wins():
    res = _sim(500)
    eng, imp = res["sources"]["engine"], res["sources"]["improved_timing"]
    assert eng["trades"][0]["status"] == "FILLED" and eng["metrics"]["net_pnl"] < 0          # bought the 09:55 chase
    assert imp["metrics"]["filled"] >= 2 and imp["metrics"]["net_pnl"] > 0 and imp["metrics"]["win_rate"] == 1.0
    first = imp["trades"][0]
    assert sr.et(first["entry_ts"], False) == "09:51" and first["fill"] > first["ref_price"]  # pays the spread
    assert res["compare"]["should_have_been_pnl"] >= res["compare"]["improved_sim_pnl"] > res["compare"]["manual_pnl"]


def test_sim_sizes_to_the_supply_near_the_ask():
    res = _sim(2000)
    refused = [t for t in res["sources"]["improved_timing"]["trades"] if t["status"] == "REFUSED"]
    assert refused and "near the ask" in refused[0]["reason"]
    assert res["sources"]["improved_timing"]["metrics"]["fill_feasibility"] < 1


def test_there_is_no_live_mode():
    assert sim.mode({}) == "manual" and sim.mode({"active_trader_mode": "auto_sim"}) == "auto_sim"
    with pytest.raises(ValueError):
        sim.mode({"active_trader_mode": "auto_live"})


def test_ledger_appends_each_trade_once(_journal_dir):
    res = _sim(500)
    n = sim.append_ledger(res)
    assert n == res["sources"]["engine"]["metrics"]["attempted"] + res["sources"]["improved_timing"]["metrics"]["attempted"]
    assert sim.append_ledger(res) == 0


def test_review_and_sim_cannot_reach_a_broker_or_provider():
    forbidden = ("futu", "moomoo", "alpaca", "schwab", "brokers", "requests", "httpx", "urllib.request",
                 "execution_guard", "canary_gate", "place_order", "telegram_alert")
    for name in ("session_review.py", "auto_trader_sim.py"):
        tree = ast.parse((ROOT / "scripts" / "active_trader" / name).read_text())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
        for m in mods - {"__future__"}:
            assert not any(f in seg for seg in m.lower().split(".") for f in forbidden), (name, m)
        src = (ROOT / "scripts" / "active_trader" / name).read_text()
        assert "place_order" not in src and "submit_order" not in src


# ── persistence, Telegram (shadow by default), API ────────────────────────────

def test_run_day_persists_and_sends_only_in_send_mode(monkeypatch, _journal_dir):
    from active_trader import trade_replay as tr
    monkeypatch.setattr(tr, "_journal_day", lambda day: FX["journal"])
    monkeypatch.setattr(api, "operator_fills", lambda day, syms, conn=None: FX["fills"])
    sent = []
    raw = {"active_trader_mode": "manual", "active_trader_review": {"mode": "shadow"}}
    res = sr.run_day("2026-10-05", apply=True, bars_fn=lambda s: FX["bars"], cfg_raw=raw,
                     send_fn=lambda **k: sent.append(k) or {"sent": True})
    assert Path(res["path"]).exists() and res["learning_appended"] == 1 and not sent
    assert "auto_sim_ledger" not in res                                   # manual: comparison only
    raw = {"active_trader_mode": "auto_sim", "active_trader_review": {"mode": "send"}}
    res = sr.run_day("2026-10-05", apply=True, bars_fn=lambda s: FX["bars"], cfg_raw=raw,
                     send_fn=lambda **k: sent.append(k) or {"sent": True})
    assert sent and res["auto_sim_ledger"] > 0
    body = sent[0]["title"] + "\n" + sent[0]["body"]
    assert body.startswith("ACTIVE TRADER · SCALP ALERT") and "NOT AN ORDER" in body
    assert "XNDU: ideal" in body and "COOLDOWN" in body and len(body.splitlines()) < 15


def test_session_review_route_is_a_pure_read(monkeypatch, _journal_dir):
    review = sr.build_review("2026-10-05", journal=FX["journal"], trips=_trips(), bars_fn=lambda s: FX["bars"], cfg=CFG)
    sr.write_review(review)
    from active_trader import read_http
    status, body = read_http.dispatch(None, "GET", "/api/v3/active-trader/session-review", {"day": ["2026-10-05"]})
    assert status == 200 and body["read_only"] is True and body["review"]["day"] == "2026-10-05"
    assert body["days"] == ["2026-10-05"]
    assert read_http.dispatch(None, "POST", "/api/v3/active-trader/session-review", {})[0] == 405


def test_config_sections_parse():
    import yaml
    raw = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8"))
    assert sim.mode(raw) == "manual"
    rc = sr.ReviewConfig.from_mapping(raw["active_trader_review"])
    assert rc.mode == "shadow" and rc.chase_r == 1.0
    assert sim.SimConfig.from_mapping(raw["active_trader_auto_sim"]).size_shares == 500
