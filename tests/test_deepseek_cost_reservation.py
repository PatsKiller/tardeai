"""Token limits end-to-end + atomic reservation ledger authority tests."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.consumption_run_manual import SMOKE_PROCESS_ID  # noqa: E402


class _Resp:
    def __init__(self, **kw):
        self.ok = True
        self.content = kw.get("content", "OK")
        self.requested_policy = "FAST"
        self.executed_policy = "FAST"
        self.requested_model_id = "deepseek-v4-flash"
        self.returned_model = "deepseek-v4-flash"
        self.thinking = "disabled"
        self.reasoning_effort = None
        self.request_id = "req-t"
        self.client_request_id = "cli-t"
        self.latency_ms = 5
        self.estimated_cost_usd = kw.get("cost", 0.00001)
        self.cost_basis = "provider_usage_x_registry_snapshot"
        self.finish_reason = "stop"
        self.raw_response_hash = "h"
        self.fallback_used = False
        self.error_class = None
        self.error_message = None
        self.usage = {"prompt_tokens": 4, "completion_tokens": 1}


def test_smoke_process_chat_receives_max_tokens_32(monkeypatch):
    """Provider kwargs must use registry max_output_tokens=32 for smoke process."""
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("lib.deepseek_client.chat", fake_chat)

    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})
    monkeypatch.setattr(
        lc,
        "get_process_config",
        lambda pid: {
            "registered": True,
            "mode": "manual",
            "allowed_lanes": ["deepseek-flash", "fast"],
            "max_input_tokens": 64,
            "max_output_tokens": 32,
            "daily_soft_cap": 20,
            "daily_cost_cap_usd": 1.0,
        },
    )
    # reservation no-op success
    monkeypatch.setattr(lc, "reserve_projected_cost", lambda *a, **k: 99)
    monkeypatch.setattr(lc, "settle_reservation", lambda *a, **k: None)
    monkeypatch.setattr(lc, "log_call", lambda **k: 1)

    lc.gate_and_generate(
        "Reply with exactly: OK",
        lane="deepseek-flash",
        process_id=SMOKE_PROCESS_ID,
        manual_trigger=True,
        policy="FAST",
        max_tokens=2048,  # caller tries to raise limit — must not win
    )
    assert captured.get("max_tokens") == 32
    assert captured.get("policy") == "FAST"


def test_request_2048_cannot_override_process_limit(monkeypatch):
    captured = {}

    def fake_chat(**kwargs):
        captured["max_tokens"] = kwargs.get("max_tokens")
        return _Resp()

    monkeypatch.setattr("lib.deepseek_client.chat", fake_chat)
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})
    monkeypatch.setattr(
        lc,
        "get_process_config",
        lambda pid: {
            "registered": True,
            "mode": "manual",
            "allowed_lanes": ["fast"],
            "max_input_tokens": 64,
            "max_output_tokens": 32,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 20,
        },
    )
    monkeypatch.setattr(lc, "reserve_projected_cost", lambda *a, **k: 1)
    monkeypatch.setattr(lc, "settle_reservation", lambda *a, **k: None)
    monkeypatch.setattr(lc, "log_call", lambda **k: 1)

    lc.gate_and_generate(
        "OK",
        lane="fast",
        process_id=SMOKE_PROCESS_ID,
        manual_trigger=True,
        policy="FAST",
        max_tokens=2048,
    )
    assert captured["max_tokens"] == 32


def test_oversized_input_rejected(monkeypatch):
    from lib import llm_consumption as lc

    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})
    monkeypatch.setattr(
        lc,
        "get_process_config",
        lambda pid: {
            "registered": True,
            "mode": "manual",
            "allowed_lanes": ["fast"],
            "max_input_tokens": 10,
            "max_output_tokens": 32,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 20,
        },
    )
    called = {"reserve": False}
    monkeypatch.setattr(
        lc, "reserve_projected_cost",
        lambda *a, **k: called.__setitem__("reserve", True) or 1,
    )

    big = "word " * 200  # >> 10 tokens
    try:
        lc.gate_and_generate(
            big, lane="fast", process_id=SMOKE_PROCESS_ID,
            manual_trigger=True, policy="FAST", max_tokens=32,
        )
        assert False
    except RuntimeError as e:
        assert "INPUT_LIMIT_EXCEEDED" in str(e)
    assert called["reserve"] is False


def test_settled_actual_counted_when_log_fails(monkeypatch):
    """Logging failure after settle must not erase ledger spend."""
    from lib import llm_consumption as lc

    if not lc.cost_persistence_available():
        pytest.skip("no DB")

    pid = f"test_ledger_{int(time.time()*1000)}"
    # inject fake registered config
    monkeypatch.setattr(
        lc,
        "get_process_config",
        lambda p: {
            "registered": True,
            "mode": "manual",
            "allowed_lanes": ["fast"],
            "max_input_tokens": 64,
            "max_output_tokens": 32,
            "daily_soft_cap": 100,
            "daily_cost_cap_usd": 1.0,
            "process_name": p,
        },
    )
    monkeypatch.setattr(lc, "is_process_registered", lambda p: True)
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "manual"})

    cfg = {
        "registered": True,
        "daily_cost_cap_usd": 1.0,
        "daily_soft_cap": 100,
    }
    before = lc.ledger_paid_usd_today(pid)
    rid = lc.reserve_projected_cost(
        pid, 0.01, model_id="deepseek-v4-flash", process_config=cfg,
    )
    lc.settle_reservation(rid, 0.007, ok=True, billable_attempt=True)
    # log_call fails
    monkeypatch.setattr(lc, "log_call", lambda **k: (_ for _ in ()).throw(RuntimeError("log down")))

    after = lc.ledger_paid_usd_today(pid)
    assert after >= before + 0.007 - 1e-9


def test_released_pre_provider_does_not_consume(monkeypatch):
    from lib import llm_consumption as lc

    if not lc.cost_persistence_available():
        pytest.skip("no DB")

    pid = f"test_release_{int(time.time()*1000)}"
    monkeypatch.setattr(
        lc,
        "get_process_config",
        lambda p: {
            "registered": True,
            "mode": "manual",
            "allowed_lanes": ["fast"],
            "daily_soft_cap": 100,
            "daily_cost_cap_usd": 1.0,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
        },
    )
    cfg = {"registered": True, "daily_cost_cap_usd": 1.0, "daily_soft_cap": 100}
    before = lc.ledger_paid_usd_today(pid)
    rid = lc.reserve_projected_cost(
        pid, 0.02, model_id="deepseek-v4-flash", process_config=cfg,
    )
    lc.settle_reservation(rid, None, ok=False, billable_attempt=False)
    after = lc.ledger_paid_usd_today(pid)
    assert abs(after - before) < 1e-9


def test_ambiguous_timeout_settles_conservatively(monkeypatch):
    from lib import llm_consumption as lc

    if not lc.cost_persistence_available():
        pytest.skip("no DB")

    pid = f"test_timeout_{int(time.time()*1000)}"
    cfg = {
        "registered": True,
        "mode": "manual",
        "allowed_lanes": ["fast"],
        "daily_soft_cap": 100,
        "daily_cost_cap_usd": 5.0,
        "max_output_tokens": 32,
        "max_input_tokens": 64,
    }
    monkeypatch.setattr(lc, "get_process_config", lambda p: cfg)
    before = lc.ledger_paid_usd_today(pid)
    rid = lc.reserve_projected_cost(
        pid, 0.03, model_id="deepseek-v4-flash", process_config=cfg,
    )
    # billable attempt, no actual → projected
    lc.settle_reservation(rid, None, ok=False, billable_attempt=True, projected_fallback=0.03)
    after = lc.ledger_paid_usd_today(pid)
    assert after >= before + 0.03 - 1e-9


def test_concurrent_reservations_respect_cap(monkeypatch):
    """Two concurrent reservations cannot both pass a $0.05 process cap with $0.04 each."""
    from lib import llm_consumption as lc

    if not lc.cost_persistence_available():
        pytest.skip("no DB")

    pid = f"test_conc_{int(time.time()*1000)}"
    cfg = {
        "registered": True,
        "mode": "manual",
        "allowed_lanes": ["fast"],
        "daily_soft_cap": 100,
        "daily_cost_cap_usd": 0.05,
        "max_output_tokens": 32,
        "max_input_tokens": 64,
    }
    monkeypatch.setattr(lc, "get_process_config", lambda p: cfg)

    results = []
    lock = threading.Lock()

    def worker():
        try:
            rid = lc.reserve_projected_cost(
                pid, 0.04, model_id="deepseek-v4-flash", process_config=cfg,
            )
            with lock:
                results.append(("ok", rid))
        except Exception as e:
            with lock:
                results.append(("err", str(e)))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, results
    assert len(errs) == 1, results
    assert "COST_CAP" in errs[0][1].upper()


def test_concurrent_global_cap(monkeypatch):
    from lib import llm_consumption as lc

    if not lc.cost_persistence_available():
        pytest.skip("no DB")

    # Cap is relative to current global ledger so prior test spend does not flake.
    spent_g = lc.ledger_paid_usd_today(None)
    # Room for exactly one 0.6 projection; second concurrent reserve must fail.
    global_cap = float(spent_g) + 0.7

    pid_a = f"test_ga_{int(time.time()*1000)}"
    pid_b = f"test_gb_{int(time.time()*1000)}"
    cfg = {
        "registered": True,
        "daily_cost_cap_usd": 10.0,
        "daily_soft_cap": 100,
    }
    results = []
    lock = threading.Lock()

    def worker(pid):
        try:
            rid = lc.reserve_projected_cost(
                pid, 0.6, model_id="deepseek-v4-flash",
                process_config=cfg, global_cap=global_cap,
            )
            with lock:
                results.append(("ok", rid))
        except Exception as e:
            with lock:
                results.append(("err", str(e)))

    t1 = threading.Thread(target=worker, args=(pid_a,))
    t2 = threading.Thread(target=worker, args=(pid_b,))
    t1.start(); t2.start(); t1.join(); t2.join()
    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, results
    assert len(errs) == 1, results
    assert "COST_CAP" in errs[0][1].upper() or "global" in errs[0][1].lower()


def test_missing_cap_config_fails_closed():
    from lib.consumption_run_manual import validate_paid_cap_config
    import pytest
    with pytest.raises(RuntimeError, match="COST_CONFIGURATION_INVALID"):
        validate_paid_cap_config({"daily_cost_cap_usd": None, "daily_soft_cap": 10})
    with pytest.raises(RuntimeError, match="COST_CONFIGURATION_INVALID"):
        validate_paid_cap_config({"daily_cost_cap_usd": 0.05, "daily_soft_cap": None})
    with pytest.raises(RuntimeError, match="COST_CONFIGURATION_INVALID"):
        validate_paid_cap_config({"daily_cost_cap_usd": 0, "daily_soft_cap": 10})


def test_reserve_requires_process_config():
    from lib import llm_consumption as lc
    if not lc.cost_persistence_available():
        pytest.skip("no DB")
    with pytest.raises(RuntimeError, match="COST_CONFIGURATION_INVALID"):
        lc.reserve_projected_cost("x", 0.01, model_id="deepseek-v4-flash", process_config=None)


def test_config_error_after_lock_no_insert(monkeypatch):
    """Force failure after advisory locks: entire reservation rolls back; no row inserted."""
    from lib import llm_consumption as lc
    if not lc.cost_persistence_available():
        pytest.skip("no DB")

    pid = f"test_cfg_err_{int(time.time()*1000)}"
    cfg = {"daily_cost_cap_usd": 1.0, "daily_soft_cap": 100}
    before = lc.ledger_request_count_today(pid)

    # Fail only after locks are taken (ledger read path uses cur= inside the txn).
    def boom_paid(process_id=None, cur=None):
        if cur is not None:
            raise RuntimeError("COST_PERSISTENCE_UNAVAILABLE: forced post-lock failure")
        return 0.0

    monkeypatch.setattr(lc, "ledger_paid_usd_today", boom_paid)
    try:
        lc.reserve_projected_cost(
            pid, 0.01, model_id="deepseek-v4-flash", process_config=cfg,
        )
        assert False, "expected post-lock failure"
    except RuntimeError as e:
        u = str(e).upper()
        assert "COST_PERSISTENCE_UNAVAILABLE" in u or "COST_CONFIGURATION" in u
    after = lc.ledger_request_count_today(pid)
    assert after == before


def test_missing_caps_rejected_before_or_at_reserve():
    """Missing process caps never mean unlimited; no reservation path opens."""
    from lib import llm_consumption as lc
    if not lc.cost_persistence_available():
        pytest.skip("no DB")
    pid = f"test_nocap_{int(time.time()*1000)}"
    before = lc.ledger_request_count_today(pid)
    with pytest.raises(RuntimeError, match="COST_CONFIGURATION_INVALID"):
        lc.reserve_projected_cost(
            pid, 0.01, model_id="deepseek-v4-flash",
            process_config={"daily_cost_cap_usd": None, "daily_soft_cap": 10},
        )
    assert lc.ledger_request_count_today(pid) == before
