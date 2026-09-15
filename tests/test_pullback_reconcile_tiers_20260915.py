"""2026-09-15: pullback reconcile keeps every proposal tier the screener emits.

Checking only `trigger` while `proposal_tiers: [trigger, watch]` expired each watch-tier
proposal in the same pass that created it (1,075 of 1,156 auto proposals in 30 days).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("pullback_macd_screener_t", ROOT / "scripts" / "pullback_macd_screener.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def __call__(self, sql, params=None, fetch=None):
        if sql.lstrip().upper().startswith("SELECT"):
            return self.rows
        self.updates.append(params)
        return None


def _cand(sym, tier, price=10.0):
    return {"sym": sym, "tier": tier, "price": price}


def _rows(*syms):
    return [{"id": i + 1, "symbol": s, "proposed_stop": 8.0, "proposed_target1": 14.0} for i, s in enumerate(syms)]


def test_watch_tier_proposal_survives_when_watch_is_a_proposal_tier(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES", "RTX"))
    monkeypatch.setattr(mod, "_db", db)
    retired = mod._reconcile_proposals([_cand("AES", "watch"), _cand("RTX", "trigger")], ["trigger", "watch"])
    assert retired == 0
    assert db.updates == []


def test_symbol_that_left_every_proposal_tier_is_expired(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES"))
    monkeypatch.setattr(mod, "_db", db)
    retired = mod._reconcile_proposals([_cand("RTX", "trigger")], ["trigger", "watch"])
    assert retired == 1
    reason, pid = db.updates[0]
    assert pid == 1 and "no longer a confirmed trigger or watch setup" in reason


def test_default_tiers_stay_trigger_only(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES"))
    monkeypatch.setattr(mod, "_db", db)
    assert mod._reconcile_proposals([_cand("AES", "watch")]) == 1


def test_stop_break_still_expires_a_watch_proposal(monkeypatch):
    mod = _load()
    db = FakeDb(_rows("AES"))
    monkeypatch.setattr(mod, "_db", db)
    assert mod._reconcile_proposals([_cand("AES", "watch", price=7.5)], ["trigger", "watch"]) == 1
    assert "plan broken" in db.updates[0][0]


def test_monitor_pass_passes_configured_tiers():
    src = (ROOT / "scripts" / "pullback_macd_screener.py").read_text(encoding="utf-8")
    assert '_reconcile_proposals(cands, cfg.get("proposal_tiers") or ["trigger"])' in src
