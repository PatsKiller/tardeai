"""'Everything BLOCKED' repair (2026-09-26).

Three defects made every surface read BLOCKED:
- Options: the generator built ideas the liquidity gate always refuses (fixed-%
  strikes, proximity-only picks, no premium floor, a $1.84 name with no chain).
- Aegis: the worker's claim SQL returned a column the live table never had, so
  nothing ran after 2026-07-08, and the health check counted the wrong status.
- Watch: the scheduler SIGKILLed the refresh workers it had just spawned, so
  decision packets stopped being rebuilt on 2026-09-13.

No DB, broker, network or LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import options_income_quality as q  # noqa: E402

CFG = {
    "min_open_interest": 50,
    "max_bid_ask_spread_pct": 12.0,
    "require_chain_for_live": True,
    "min_underlying_price": 5.0,
    "min_premium_per_share": 0.10,
    "min_annualized_roc_pct": 6.0,
    "picker_strike_slack_pct": 8.0,
    "csp_target_abs_delta": 0.25,
    "cc_target_delta": 0.25,
    "edge_roc_full_credit_ann_pct": 25.0,
}


def _c(**kw):
    base = {"strike": 50.0, "bid": 0.95, "ask": 1.05, "mid": 1.0, "oi": 500, "volume": 40, "dte": 30}
    base.update(kw)
    return base


# ── income screen ────────────────────────────────────────────────────────────
def test_pcsa_class_penny_stock_is_refused_before_a_card():
    est = _c(strike=1.7, bid=0.01, ask=0.01, mid=0.01, oi=None, volume=0)
    assert q.income_drop_reason("cash_secured_put", est, "bs_estimate", 1.84, CFG) == "PRICE_BELOW_FLOOR"


def test_black_scholes_estimate_is_not_a_chain():
    assert q.income_drop_reason("cash_secured_put", _c(), "bs_estimate", 55.0, CFG) == "NO_CHAIN"


def test_ajg_class_zero_oi_wide_spread_is_no_liquid_contract():
    ajg = _c(strike=210, bid=0.95, ask=1.65, mid=1.30, oi=0, volume=0, dte=20)
    assert q.income_drop_reason("cash_secured_put", ajg, "schwab_chain", 231.1, CFG) == "NO_LIQUID_CONTRACT"


def test_missing_oi_is_never_liquid():
    assert q.is_liquid(_c(oi=None), CFG) is False


def test_penny_premium_on_liquid_contract_is_below_floor():
    thin = _c(bid=0.04, ask=0.045, mid=0.0425)
    assert q.income_drop_reason("cash_secured_put", thin, "schwab_chain", 55.0, CFG) == "PREMIUM_BELOW_FLOOR"


def test_low_annualized_return_is_below_floor():
    # $0.15 on a $200 strike for 60 days is ~0.46% annualized
    low = _c(strike=200, bid=0.145, ask=0.155, mid=0.15, dte=60)
    assert q.income_drop_reason("cash_secured_put", low, "schwab_chain", 220.0, CFG) == "PREMIUM_BELOW_FLOOR"


def test_a_real_income_contract_passes():
    good = _c(strike=50, bid=0.95, ask=1.05, mid=1.0, oi=800, dte=30)
    assert q.income_drop_reason("cash_secured_put", good, "schwab_chain", 55.0, CFG) is None


def test_roc_score_needs_the_configured_yield_for_full_credit():
    assert q.roc_score(6.2, CFG, 28.0) < 8.0          # used to max out at ~6% annualized
    assert q.roc_score(25.0, CFG, 28.0) == 28.0
    assert q.roc_score(80.0, CFG, 28.0) == 28.0


def test_thresholds_live_in_portfolio_intent_yaml():
    text = (ROOT / "assets" / "portfolio_intent.yaml").read_text(encoding="utf-8")
    for key in ("min_underlying_price", "min_premium_per_share", "min_annualized_roc_pct",
                "picker_strike_slack_pct", "csp_target_abs_delta", "cc_target_delta",
                "edge_roc_full_credit_ann_pct"):
        assert f"  {key}:" in text, key


# ── engine picker / IV / gate ────────────────────────────────────────────────
@pytest.fixture()
def oe(monkeypatch):
    import options_engine as mod
    monkeypatch.setattr(mod, "_DESK_CFG", dict(CFG))
    return mod


def _chain(rows, dte=30):
    return {"status": "ok", "expirations": [{"exp": "2026-10-30", "dte": dte, "strikes": rows}]}


def test_picker_takes_a_liquid_contract_over_the_nearest_illiquid_one(oe):
    rows = [
        {"side": "put", "strike": 210, "bid": 0.95, "ask": 1.65, "oi": 0, "volume": 0, "delta": -0.13},
        {"side": "put", "strike": 215, "bid": 2.00, "ask": 2.10, "oi": 900, "volume": 60, "delta": -0.2},
    ]
    got = oe._pick_chain_contract(_chain(rows), "put", 210, 30)
    assert got["strike"] == 215 and got["oi"] == 900


def test_picker_targets_delta_when_the_chain_has_it(oe):
    rows = [
        {"side": "put", "strike": s, "bid": b, "ask": b + 0.08, "oi": 800, "volume": 50, "delta": d}
        for s, b, d in ((200, 0.9, -0.10), (210, 1.9, -0.18), (215, 2.9, -0.25), (220, 4.2, -0.35))
    ]
    got = oe._pick_chain_contract(_chain(rows), "put", 200, 30, target_abs_delta=0.25)
    assert got["strike"] == 215


def test_picker_keeps_missing_oi_missing(oe):
    rows = [{"side": "put", "strike": 50, "bid": 1.0, "ask": 1.1, "volume": 3}]
    got = oe._pick_chain_contract(_chain(rows), "put", 50, 30)
    assert got["oi"] is None


def test_iv_rank_with_no_data_is_zero_not_a_placeholder(oe, monkeypatch):
    monkeypatch.setattr(oe, "_iv_rank_from_history", lambda *a, **k: None)
    assert oe._iv_rank_proxy("PCSA", {}) == 0.0
    assert oe._iv_rank_proxy("V", {"iv": 22, "high52": 400, "low52": 300, "price": 367}) > 0


def test_income_screen_records_named_drops(oe):
    oe.INCOME_SCREEN_DROPS.clear()
    assert oe._income_screen("cash_secured_put", "AJG", _c(oi=0), "schwab_chain", 231.1) == "NO_LIQUID_CONTRACT"
    summary = oe._income_screen_summary()
    assert summary["reasons"]["NO_LIQUID_CONTRACT"] == {"count": 1, "symbols": ["AJG"]}
    oe.INCOME_SCREEN_DROPS.clear()


def test_liquidity_gate_names_missing_oi():
    import options_desk_enterprise as ent
    out = ent.liquidity_gate({"bid": 1.0, "ask": 1.05, "mid": 1.025, "oi": None, "volume": 10}, cfg=CFG)
    assert out["pass"] is False
    assert "OI unknown (chain field missing)" in out["issues"]
    assert not any(i.startswith("OI 0") for i in out["issues"])


# ── Aegis ensemble ───────────────────────────────────────────────────────────
def test_worker_writes_a_heartbeat_when_the_claim_raises(monkeypatch, tmp_path):
    import importlib.util
    import json
    # Load from THIS tree: another suite can leave a different copy in sys.modules.
    spec = importlib.util.spec_from_file_location(
        "inference_ensemble_worker_under_test", ROOT / "scripts" / "inference_ensemble_worker.py")
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    hb = tmp_path / "hb.json"
    monkeypatch.setenv("ENSEMBLE_WORKER_HEARTBEAT", str(hb))
    monkeypatch.setattr(w, "_load_env", lambda: None)

    def boom(limit):
        raise RuntimeError('column "lanes" does not exist')
    monkeypatch.setattr(w, "process", boom)
    monkeypatch.setattr(sys, "argv", ["w", "--run"])
    assert w.main() == 1
    beat = json.loads(hb.read_text())
    assert beat["claimed"] == 0 and "lanes" in beat["last_error"]


def test_repair_is_a_dry_run_by_default_and_never_deletes(monkeypatch, capsys):
    import types
    import repair_ensemble_jobs as r
    writes = []

    def fake_exec(sql, params=None, fetch="one"):
        if sql.lstrip().upper().startswith(("ALTER", "UPDATE", "DELETE")):
            writes.append(sql)
            return None
        if "information_schema" in sql:
            return [{"column_name": "id"}]
        return [{"id": 1, "status": "queued", "target_type": "x", "requested_at": None, "started_at": None}]

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=fake_exec))
    monkeypatch.setattr(r, "_load_env", lambda: None)
    assert r.main([]) == 0
    assert writes == []
    assert "DELETE" not in r.expire_sql().upper() and "DELETE" not in r.ADD_LANES.upper()
    assert "dry_run" in capsys.readouterr().out


def test_health_check_counts_error_status_and_flags_a_stall():
    src = (ROOT / "scripts" / "health_agent.py").read_text(encoding="utf-8")
    assert "status IN ('failed','error')" in src
    assert "ensemble_worker_stalled" in src


# ── Watch refresh workers ────────────────────────────────────────────────────
def test_refresh_workers_run_outside_the_scheduler_cgroup(monkeypatch):
    import watch_decision_refresh as wdr
    calls = []
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setenv("DB_PASSWORD", "secret-value")
    monkeypatch.setattr(wdr.shutil, "which", lambda name: "/usr/bin/systemd-run")
    monkeypatch.setattr(wdr.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(wdr.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("fell back to an in-cgroup Popen"))
    assert wdr._spawn_workers(2) == 2
    assert len(calls) == 2
    for argv in calls:
        assert argv[:2] == ["systemd-run", "--user"]
        assert any(a.startswith("--unit=tradeai-watch-refresh-worker-") for a in argv)
        assert any(a.startswith("--property=RuntimeMaxSec=") for a in argv)
        assert argv[-1] == "--worker"
        assert not any("secret-value" in a for a in argv)


def test_refresh_workers_fall_back_without_systemd(monkeypatch):
    import watch_decision_refresh as wdr
    started = []
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.setattr(wdr.subprocess, "Popen", lambda argv, **k: started.append(argv))
    assert wdr._spawn_workers(1) == 1
    assert started and started[0][-1] == "--worker"


def test_scheduler_rechecks_old_quarantine():
    src = (ROOT / "scripts" / "watch_decision_scheduler.py").read_text(encoding="utf-8")
    assert "WATCH_QUARANTINE_RECHECK_DAYS" in src and "QUARANTINE_RECHECK" in src
