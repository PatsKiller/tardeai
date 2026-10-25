"""2026-10-24 supersedes the Sept tier rule: WATCH is research-only.

The advisory queue keeps confirmed triggers and records withdrawal reasons.
"""
from __future__ import annotations

import importlib.util
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _stub_missing(*names):
    """CI's source-only runner has no numpy/pandas; _reconcile_proposals uses neither.

    Returns the names it stubbed so the caller can remove them again: a bare stub left in
    sys.modules breaks later tests in the same session (pytest.approx probes numpy.isscalar).
    """
    import types
    stubbed = []
    for name in names:
        try:
            __import__(name)
        except ImportError:
            sys.modules[name] = types.ModuleType(name)
            stubbed.append(name)
    return stubbed


def _load():
    stubbed = _stub_missing("numpy", "pandas")
    try:
        spec = importlib.util.spec_from_file_location("pullback_macd_screener_t", ROOT / "scripts" / "pullback_macd_screener.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for name in stubbed:
            sys.modules.pop(name, None)
    return mod


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def __call__(self, sql, params=None, fetch=None):
        if sql.lstrip().upper().startswith("SELECT"):
            return self.rows
        self.updates.append(params)
        return [{"id": params[-1]}]


def _cand(sym, tier, price=10.0):
    return {"sym": sym, "tier": tier, "price": price}


def _rows(*syms):
    return [{"id": i + 1, "symbol": s, "proposed_stop": 8.0, "proposed_target1": 14.0} for i, s in enumerate(syms)]


def test_watch_tier_is_withdrawn_even_when_old_config_allows_watch(monkeypatch, capsys):
    mod = _load()
    db = FakeDb(_rows("AES", "RTX"))
    monkeypatch.setattr(mod, "_db", db)
    retired = mod._reconcile_proposals([_cand("AES", "watch"), _cand("RTX", "trigger")], ["trigger", "watch"])
    assert retired == 1
    assert db.updates[0][1] == 1
    assert "WATCH tier withdrawn" in db.updates[0][0]
    assert "symbol=AES" in capsys.readouterr().out


def test_symbol_that_left_every_proposal_tier_is_expired(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES"))
    monkeypatch.setattr(mod, "_db", db)
    retired = mod._reconcile_proposals([_cand("RTX", "trigger")], ["trigger", "watch"])
    assert retired == 1
    reason, pid = db.updates[0]
    assert pid == 1 and "no longer a confirmed trigger" in reason


def test_default_tiers_stay_trigger_only(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES"))
    monkeypatch.setattr(mod, "_db", db)
    assert mod._reconcile_proposals([_cand("AES", "watch")]) == 1


def test_stop_break_still_expires_a_trigger_proposal(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES"))
    monkeypatch.setattr(mod, "_db", db)
    assert mod._reconcile_proposals([_cand("AES", "trigger", price=7.5)], ["trigger", "watch"]) == 1
    assert "plan broken" in db.updates[0][0]


def test_monitor_pass_uses_trigger_only_reconciliation():
    src = (ROOT / "scripts" / "pullback_macd_screener.py").read_text(encoding="utf-8")
    assert '_reconcile_proposals(cands, watch_only=not cfg.get("reconcile_proposals", True))' in src


def test_watch_only_scan_returns_before_routing_or_sizing(monkeypatch):
    mod = _load()
    monkeypatch.setitem(sys.modules, "proposal_routing_lanes", None)
    monkeypatch.setattr(mod, "_db", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no queue reads")))
    assert mod._emit_proposals([_cand("AES", "watch")], {"proposal_tiers": ["trigger", "watch"]}) == 0


def test_trigger_only_config_cannot_be_widened_by_db_settings(monkeypatch):
    import types
    mod = _load()
    fake = types.ModuleType("proposal_routing_lanes")
    fake.entry_routing_lanes = lambda: []
    fake.risk_gate_for_lane = lambda *a: None
    monkeypatch.setitem(sys.modules, "proposal_routing_lanes", fake)
    plans = []
    monkeypatch.setattr(mod, "_write_trade_plan", lambda c, *a: plans.append(c["sym"]))
    monkeypatch.setattr(mod, "_db", lambda *a, **kw: [])
    trigger = {**_cand("RTX", "trigger"), "entry": 10, "stop": 9, "score": 90}
    watch = {**_cand("AES", "watch"), "entry": 10, "stop": 9, "score": 99}
    assert mod._emit_proposals([watch, trigger], {"proposal_tiers": ["watch", "trigger"]}) == 0
    assert plans == ["RTX"]


def test_watch_withdrawal_still_runs_with_ordinary_plan_reconciliation_disabled(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES", "RTX"))
    monkeypatch.setattr(mod, "_db", db)
    assert mod._reconcile_proposals([_cand("AES", "watch"), _cand("RTX", "trigger", 7)], watch_only=True) == 1
    assert db.updates[0][1] == 1


def test_row_that_filled_after_selection_is_not_counted_or_logged_as_withdrawn(monkeypatch, capsys):
    mod = _load()
    def racing_db(sql, params=None, fetch=None):
        return _rows("AES") if sql.lstrip().startswith("SELECT") else []
    monkeypatch.setattr(mod, "_db", racing_db)
    assert mod._reconcile_proposals([_cand("AES", "watch")]) == 0
    assert "proposal withdrawal" not in capsys.readouterr().out


def test_failed_withdrawal_is_a_failed_lane_not_a_successful_noop(monkeypatch):
    mod = _load()
    def failed_write(sql, params=None, fetch=None):
        return _rows("AES") if sql.lstrip().startswith("SELECT") else None
    monkeypatch.setattr(mod, "_db", failed_write)
    with pytest.raises(RuntimeError, match="withdrawal write failed"):
        mod._reconcile_proposals([_cand("AES", "watch")])
