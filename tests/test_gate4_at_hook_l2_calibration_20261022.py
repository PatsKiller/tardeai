"""Gate 4 under execution-engineering grant e88bf21e (2026-10-22): Active Trader shadow hook, L2 book signals in
SignalConfig and the served payload, and the signal_calibration unit fix. Hermetic (A1/A2: fixtures only).

(a) momentum_alerts.evaluate_pass logs the unified message BESIDE the legacy alert and never suppresses or
    replaces it: off = no unified build, shadow = SHADOW_LOGGED row, live = refused and recorded
    ("live replacement pending operator decision"), the legacy send identical in every mode.
(b) microstructure_signals.SignalConfig carries spread_bps_max / imbalance_min / ask_heavy_max / imbalance_levels
    (parity with lib/l2_book_signals and the committed priors); entry_signals has tight_spread and
    bid_ask_imbalance; exit_signals is unchanged (exit_watch counts it); the served AT payload carries
    l2_book_signals.
(c) signal_calibration proposes min_stop.pct_of_price in knob units (a fraction) with proposed_feature_value
    beside it; the harness freezes the feature-unit value and its declared current values equal AlertConfig.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import microstructure_signals as msig  # noqa: E402
from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import momentum_alerts_api as api  # noqa: E402
from active_trader import signal_calibration as sc  # noqa: E402
from lib import l2_book_signals as L2  # noqa: E402
from lib import unified_momentum_alert as U  # noqa: E402

import calibration_shadow_harness as H  # noqa: E402

NOW = 1_792_680_000.0  # 2026-10-22 10:40 ET
CFG = ma.AlertConfig(mode="send")


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(tmp_path / "unified.jsonl"))
    monkeypatch.setattr(U, "catalyst_from_hermes", lambda s, d, lookup=None: {})

    def no_send(*a, **k):
        raise AssertionError("the AT hook never sends a unified message")

    monkeypatch.setattr(U, "gateway_send", no_send)
    return tmp_path


def _book(at=NOW):
    return {"bids": [(5.00 - i * 0.01, 5000) for i in range(10)], "asks": [(5.01 + i * 0.01, 2000) for i in range(10)],
            "ts_epoch": at - 2, "ts_source": "opend_server"}


def _tape(at=NOW):
    return [{"ts_epoch": at - 3 - (30 - i), "price": 5.0, "volume": 100, "direction": "BUY" if i < 24 else "SELL"}
            for i in range(30)]


def _cand():
    return ma.Candidate(symbol="ABCD", lane="BELOW", ign=40.0, fsm_state="IDLE", entry_ref=5.01, stop_ref=4.90,
                        rvol=8.0, float_mm=6.0, last=5.01, quote_ts_epoch=NOW - 2, fire_ts_epoch=NOW - 30,
                        session_date="2026-10-22")


def _pass(mode, monkeypatch, tmp):
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_MODE", mode)
    calls = []
    rows = ma.evaluate_pass([_cand()], cfg=CFG, now=NOW, fetch_primary_book=lambda s: _book(),
                            fetch_primary_tape=lambda s: _tape(), fetch_compare_book=lambda s: None,
                            send_fn=lambda **kw: calls.append(kw) or {"sent": True}, persist=True)
    return rows, calls


# ── (a) shadow-only hook ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
def test_legacy_alert_is_sent_identically_in_every_mode(mode, monkeypatch, _hermetic):
    rows, calls = _pass(mode, monkeypatch, _hermetic)
    assert rows[0]["verdict"] == ma.ALERT and rows[0]["sent"] is True
    assert len(calls) == 1 and calls[0]["alert_type"] == "at_scalp_triggered"
    assert calls[0]["title"] == rows[0]["message"]["title"] and calls[0]["body"] == rows[0]["message"]["body"]


def test_off_builds_nothing(monkeypatch, _hermetic):
    rows, _ = _pass("off", monkeypatch, _hermetic)
    assert rows[0]["unified"] is None and not (_hermetic / "unified.jsonl").exists()


def test_shadow_logs_the_unified_message_beside_the_legacy_alert(monkeypatch, _hermetic):
    rows, _ = _pass("shadow", monkeypatch, _hermetic)
    u = rows[0]["unified"]
    assert u["action"] == "SHADOW_LOGGED" and u["state"] == "TRIGGERED" and u["is_root"] is True
    led = [json.loads(x) for x in (_hermetic / "unified.jsonl").read_text().splitlines()]
    assert len(led) == 1 and led[0]["legacy_alert"] == "active_trader.momentum_alerts"
    assert led[0]["mode"] == "shadow" and U.ADVISORY_LINE in led[0]["text"]
    journal = [json.loads(x) for x in (_hermetic / "at" / "momentum_alerts.jsonl").read_text().splitlines()]
    assert journal[0]["unified"]["row_id"] == led[0]["row_id"]


def test_live_is_refused_and_recorded_never_replacing(monkeypatch, _hermetic):
    rows, calls = _pass("live", monkeypatch, _hermetic)
    assert rows[0]["unified"] == {"action": "LIVE_REFUSED", "mode": "live",
                                  "note": "live replacement pending operator decision"}
    assert len(calls) == 1 and not (_hermetic / "unified.jsonl").exists()


def test_vetoes_and_dry_passes_build_nothing(monkeypatch, _hermetic):
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_MODE", "shadow")
    rows = ma.evaluate_pass([_cand()], cfg=CFG, now=NOW, fetch_primary_book=lambda s: None,
                            fetch_primary_tape=lambda s: _tape(), send_fn=None, persist=True)
    assert rows[0]["verdict"] == ma.VETO and "unified" not in rows[0]
    ma.evaluate_pass([_cand()], cfg=CFG, now=NOW + 5000, fetch_primary_book=lambda s: _book(NOW + 5000),
                     fetch_primary_tape=lambda s: _tape(NOW + 5000), send_fn=None, persist=False)
    assert not (_hermetic / "unified.jsonl").exists()


def test_hook_failure_is_recorded_and_the_alert_still_goes(monkeypatch, _hermetic):
    def boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(U, "emit", boom)
    rows, calls = _pass("shadow", monkeypatch, _hermetic)
    assert rows[0]["unified"]["action"] == "ERROR" and "ledger down" in rows[0]["unified"]["error"]
    assert len(calls) == 1 and rows[0]["sent"] is True


def test_hook_adds_no_router_bypass_site():
    tree = ast.parse((ROOT / "scripts/active_trader/momentum_alerts.py").read_text())
    bypass = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "bypass_router"]
    assert len(bypass) == 1, "only the legacy telegram_send site (allowlisted) may bypass the router"


# ── (b) L2 book signals ───────────────────────────────────────────────────────────────────────────────────────

def test_signal_config_priors_match_the_lib_and_the_committed_config():
    import yaml

    raw = yaml.safe_load((ROOT / "config/scalp_signal_engine.yaml").read_text())["microstructure_signals"]
    sc_ = msig.SignalConfig.from_mapping(raw)
    lib = L2.load_config()
    assert (sc_.spread_bps_max, sc_.imbalance_min, sc_.ask_heavy_max, sc_.imbalance_levels) == \
        (lib.spread_bps_max, lib.imbalance_min, lib.ask_heavy_max, lib.levels) == (50.0, 1.5, 0.67, 5)
    assert msig.SignalConfig() == msig.SignalConfig.from_mapping(raw), "committed priors equal the code defaults"


def _snap(t, bids, asks):
    return {"t": t, "b": bids, "a": asks, "l": asks[0][0], "k": []}


def test_entry_signals_carry_tight_spread_and_imbalance_with_lib_parity():
    cfg = msig.SignalConfig()
    snaps = [_snap(NOW - 30, [[2.70, 900], [2.69, 900]], [[2.72, 1000], [2.73, 1000]]),
             _snap(NOW - 5, [[2.70, 2800], [2.69, 2800]], [[2.71, 1000], [2.72, 1000]])]
    sig = msig.entry_signals(snaps, [], now=NOW, cfg=cfg)
    assert sig["tight_spread"]["on"] is True and sig["tight_spread"]["value"] == pytest.approx(37.0, abs=0.05)
    assert sig["bid_ask_imbalance"]["on"] is True and sig["bid_ask_imbalance"]["value"] == 2.8
    lib = L2.from_snapshot(snaps[-1])
    assert lib["spread_bps"] == sig["tight_spread"]["value"] and lib["imbalance"] == sig["bid_ask_imbalance"]["value"]
    heavy = msig.ask_heavy([_snap(NOW - 5, [[2.70, 500]], [[2.71, 1000]])], NOW, cfg)
    assert heavy["on"] is True and heavy["value"] == 0.5


@pytest.mark.parametrize("snaps", [[], [_snap(NOW - 5, [], [[2.71, 100]])], [_snap(NOW - 5, [[2.8, 1]], [[2.7, 1]])]])
def test_missing_one_sided_or_crossed_book_is_none(snaps):
    cfg = msig.SignalConfig()
    assert msig.tight_spread(snaps, NOW, cfg)["on"] is None
    if snaps and snaps[0]["b"] and snaps[0]["b"][0][0] > snaps[0]["a"][0][0]:
        return  # crossed: imbalance of sizes is still defined; spread is the guard
    assert msig.bid_ask_imbalance(snaps, NOW, cfg)["on"] is None


def test_exit_signals_are_unchanged():
    out = msig.exit_signals([], [], now=NOW, cfg=msig.SignalConfig())
    assert set(out) == {"tape_flip", "volume_climax", "ask_wall", "close_below_prior_low", "vwap_loss"}


def test_served_payload_carries_l2_book_signals():
    row = {"candidate": {"symbol": "ABCD"}, "kind": "ARMED", "verdict": "ALERT", "ts_epoch": NOW,
           "l2": {"ok": True, "best_bid": 2.85, "best_ask": 2.86, "bid_depth": 20165.0, "ask_depth": 54906.0,
                  "levels": 10, "source": "moomoo", "spread_bps": 35.0},
           "unified": {"action": "SHADOW_LOGGED"}}
    out = api._compact(row, None)
    v = out["l2_book_signals"]
    assert v["status"] == "OK" and v["imbalance"] == 0.37
    assert v["signals"]["ask_heavy"]["on"] is True and v["signals"]["tight_spread"]["on"] is True
    assert out["unified"] == {"action": "SHADOW_LOGGED"}
    assert api._compact({**row, "l2": {}}, None)["l2_book_signals"] is None


# ── (c) unit fix + harness defaults ───────────────────────────────────────────────────────────────────────────

def _dec(i, risk, result):
    return {"type": "decision", "session_date": "2026-10-2%d" % (i % 3), "features": {"risk_pct": risk},
            "signals": {}, "outcome": {"result": result, "rule_exit_pct": 0.0}}


def test_min_stop_proposal_is_a_fraction_with_the_feature_value_beside_it():
    recs = [_dec(i, 2.4, "WORKED") for i in range(10)] + [_dec(i, 1.1, "STOPPED") for i in range(10)]
    rep = sc.calibrate(recs, sessions=20, min_sample=10, min_bucket=8, min_edge=0.15)
    p = next(x for x in rep["proposals"] if x.get("knob") == "min_stop.pct_of_price")
    assert p["proposed_feature_value"] == pytest.approx(1.75)
    assert p["proposed_value"] == pytest.approx(0.0175) and p["knob_unit_scale"] == 0.01
    assert p["proposed_value"] < 1, "a fraction of price, never 175 %"


def test_other_knobs_are_unscaled():
    recs = [{"type": "decision", "session_date": "2026-10-21", "features": {"spread_bps": 40.0}, "signals": {},
             "outcome": {"result": "WORKED"}} for _ in range(10)]
    recs += [{"type": "decision", "session_date": "2026-10-21", "features": {"spread_bps": 70.0}, "signals": {},
              "outcome": {"result": "STOPPED"}} for _ in range(10)]
    rep = sc.calibrate(recs, sessions=20, min_sample=10, min_bucket=8, min_edge=0.15)
    p = next(x for x in rep["proposals"] if x.get("knob") == "active_trader_alerts.max_spread_bps")
    assert p["proposed_value"] == p["proposed_feature_value"] == 55.0 and p["knob_unit_scale"] == 1.0


def test_harness_freezes_the_feature_unit_value():
    cal = {"status": "ok", "sessions": ["2026-10-21"], "proposals": [
        {"type": "threshold", "knob": "min_stop.pct_of_price", "feature": "risk_pct", "proposed_value": 0.0175,
         "proposed_feature_value": 1.75, "status": "PROPOSED — operator ratifies"},
        {"type": "threshold", "knob": "x.max_y", "feature": "y", "proposed_value": 3.0,
         "status": "PROPOSED — operator ratifies"}]}
    trials, _ = H.update_trials(None, cal, H.load_config())
    assert {t["knob"]: t["frozen_value"] for t in trials} == {"min_stop.pct_of_price": 1.75, "x.max_y": 3.0}


def test_harness_declared_current_values_equal_alert_config_defaults():
    declared = H.load_config()["current_values"]
    d = ma.AlertConfig()
    assert declared == {"active_trader_alerts.max_spread_bps": d.max_spread_bps,
                        "active_trader_alerts.min_buy_ratio": d.min_buy_ratio,
                        "active_trader_alerts.min_depth_ratio_armed": d.min_depth_ratio_armed}
    v, prov = H.current_value("min_stop.pct_of_price", H.load_config())
    assert v == pytest.approx(1.0) and "×100" in prov


def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = json.loads((ROOT / "config/ci_gates/gate4_at_hook_l2_calibration_20261022.json").read_text())
    assert ci_gates.validate(doc, stem="gate4_at_hook_l2_calibration_20261022")
    assert doc["files"] == ["tests/test_gate4_at_hook_l2_calibration_20261022.py"]
