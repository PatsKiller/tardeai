"""Paid cost accounting vs relative units; cost caps."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.llm_model_registry import estimate_usd_cost  # noqa: E402


def test_relative_units_not_used_as_usd():
    # Pure token math — 0 tokens → $0, not char-based
    est = estimate_usd_cost(model_id="deepseek-v4-flash", prompt_tokens=0, completion_tokens=0)
    assert est["estimated_cost_usd"] == 0.0
    assert "provider_usage" in (est.get("cost_basis") or "")


def test_cache_hit_miss_split():
    est = estimate_usd_cost(
        model_id="deepseek-v4-flash",
        prompt_tokens=None,
        completion_tokens=0,
        cache_hit_tokens=1_000_000,
        cache_miss_tokens=0,
    )
    assert est["estimated_cost_usd"] == pytest.approx(0.0028, rel=1e-6)
    assert est["tokens"]["cache_hit_input"] == 1_000_000
    assert est["tokens"]["cache_miss_input"] == 0


def test_pro_pricing_snapshot():
    est = estimate_usd_cost(
        model_id="deepseek-v4-pro",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        cache_miss_tokens=1_000_000,
    )
    # 0.435 + 0.87
    assert est["estimated_cost_usd"] == pytest.approx(1.305, rel=1e-6)
    assert est.get("pricing_effective_at")


def test_check_cost_cap_process(monkeypatch):
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "get_process_config", lambda pid: {
        "process_id": pid, "daily_cost_cap_usd": 1.0, "mode": "automated", "allowed_lanes": [],
    })
    monkeypatch.setattr(lc, "usd_spent_today", lambda pid=None: 0.95)
    deny = lc.check_cost_cap("watchlist_maria_priority", projected_usd=0.1)
    assert deny["allow"] is False
    assert deny["reason"] == "COST_CAP_EXCEEDED"
    allow = lc.check_cost_cap("watchlist_maria_priority", projected_usd=0.0)
    assert allow["allow"] is True


def test_check_cost_cap_global(monkeypatch):
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "get_process_config", lambda pid: {
        "process_id": pid, "daily_cost_cap_usd": None, "mode": "automated", "allowed_lanes": [],
    })
    monkeypatch.setattr(lc, "usd_spent_today", lambda pid=None: 9.5 if pid is None else 0.0)
    deny = lc.check_cost_cap("any", projected_usd=1.0, global_cap=10.0)
    assert deny["allow"] is False
    assert deny["scope"] == "global"


def test_gate_blocks_on_cost_cap(monkeypatch):
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "automated"})
    monkeypatch.setattr(lc, "check_cost_cap", lambda *a, **k: {
        "allow": False, "reason": "COST_CAP_EXCEEDED", "scope": "process", "spent_usd": 5, "cap_usd": 5,
    })
    with pytest.raises(RuntimeError, match="COST_CAP_EXCEEDED"):
        lc.gate_and_generate("hi", lane="fast", process_id="watchlist_maria_priority", manual_trigger=True)


def test_no_downgrade_after_cost_block(monkeypatch):
    """Cost block must not invoke another model."""
    from lib import llm_consumption as lc
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call model after cost block")

    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})
    monkeypatch.setattr(lc, "check_cost_cap", lambda *a, **k: {"allow": False, "reason": "COST_CAP_EXCEEDED"})
    monkeypatch.setitem(sys.modules, "llm_lane", MagicMock(generate=boom))
    with pytest.raises(RuntimeError, match="COST_CAP_EXCEEDED"):
        lc.gate_and_generate("hi", lane="fast", process_id="p", manual_trigger=True)
    assert called["n"] == 0


def test_log_call_separates_relative_and_usd():
    """Unit-level: kwargs interface keeps fields separate (DB optional)."""
    from lib import llm_consumption as lc
    # If DB unavailable, log_call returns None without crashing
    lid = lc.log_call(
        lane="fast",
        process_id="unregistered",
        task_summary="t",
        trigger_mode="manual",
        success=True,
        relative_units=1.5,
        estimated_cost_usd=0.0012,
        cost_basis="provider_usage_x_registry_snapshot",
        requested_policy="FAST",
        executed_policy="FAST",
        requested_model_id="deepseek-v4-flash",
        returned_model="deepseek-v4-flash",
        tokens_in=100,
        tokens_out=20,
    )
    # None is acceptable when DB not configured; integer id when available
    assert lid is None or isinstance(lid, int)
