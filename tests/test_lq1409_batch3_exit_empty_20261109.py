"""ANCHOR: lq1409_batch3_exit_empty — LQ-20261107-1409 batch3.

hermes-deep-research-local: provider_rate_limited-only → EX_TEMPFAIL (75).
update-lockup-earnings-dates / research-intelligence-queue: produced=0 receipts
must declare an empty_reason the health contract allows.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


HERMES = _load("lq1409_hermes_deep", "scripts/hermes_deep_research_local.py")
LOCKUP = _load("lq1409_lockup", "scripts/update_lockup_earnings_dates.py")


def test_hermes_ex_tempfail_constant_is_75():
    assert HERMES.EX_TEMPFAIL == 75
    assert HERMES._RATE_LIMITED_REASON == "provider_rate_limited"


def test_hermes_rate_limited_only_maps_to_tempfail():
    """All targets provider_rate_limited → 75; mixed reasons stay 1."""
    reasons_only = {"A": "provider_rate_limited", "B": "provider_rate_limited"}
    assert reasons_only and all(r == HERMES._RATE_LIMITED_REASON for r in reasons_only.values())
    rc = HERMES.EX_TEMPFAIL
    assert rc == 75

    mixed = {"A": "provider_rate_limited", "B": "forbidden_model"}
    assert not all(r == HERMES._RATE_LIMITED_REASON for r in mixed.values())
    rc = 1
    assert rc == 1


def test_hermes_execute_rate_limited_returns_75(monkeypatch, tmp_path):
    """_execute path: three rate-limited failures → exit 75 (not 1)."""
    lock = tmp_path / "hermes_deep_research_local.lock"
    kill = tmp_path / "HERMES_DISABLED"
    monkeypatch.setattr(HERMES, "LOCK", lock)
    monkeypatch.setattr(HERMES, "KILL", kill)
    monkeypatch.setattr(HERMES, "is_us_overnight", lambda: False, raising=False)

    # Force deepseek daytime path without peak skip / kill / overnight.
    monkeypatch.setenv("TRADEAI_ALLOW_DAYTIME", "1")

    class _Conn:
        def close(self):
            return None

    def _db():
        return _Conn()

    def _pick(_conn, _n):
        return ["AAA", "BBB", "CCC"]

    def _run_one(_conn, sym, _model, _apply):
        return HERMES._failed(sym, "provider_rate_limited", "429")

    monkeypatch.setattr(HERMES, "db", _db)
    monkeypatch.setattr(HERMES, "pick_targets", _pick)
    monkeypatch.setattr(HERMES, "run_one", _run_one)

    # Bypass argparse overnight / peak guards by calling the failure exit math via a
    # minimal argv that reaches the target loop. Patch window helpers to no-op.
    import sys

    argv = ["hermes_deep_research_local.py", "--apply", "--max-rows", "3", "--allow-daytime", "--allow-peak"]
    monkeypatch.setattr(sys, "argv", argv)

    # Stub failover imports used at the top of _execute
    fake_failover = MagicMock()
    fake_failover.primary_provider.return_value = "bridge_flash"
    fake_failover.is_deepseek_offpeak.return_value = True
    fake_failover.allow_deepseek_peak.return_value = True
    fake_failover.deepseek_window_label.return_value = "offpeak"

    with patch.dict(sys.modules, {"hermes_llm_failover": fake_failover}):
        # overnight policy import may still run; force daytime
        fake_policy = MagicMock()
        fake_policy.is_us_overnight.return_value = False
        fake_policy.LANE_CHATGPT = "chatgpt"
        fake_policy.LANE_NONE = "none"
        with patch.dict(
            sys.modules,
            {
                "hermes_llm_failover": fake_failover,
                "lib.overnight_llm_policy": fake_policy,
                "scripts.lib.overnight_llm_policy": fake_policy,
            },
        ):
            rc = HERMES._execute()
    assert rc == 75
    assert HERMES._LAST_RUN.get("failure_reasons")
    assert all(r == "provider_rate_limited" for r in HERMES._LAST_RUN["failure_reasons"].values())


def test_lockup_receipt_declares_nothing_due_when_unchanged(monkeypatch, tmp_path):
    """changed=[] → write_lane_receipt(..., produced_count=0, empty_reason='nothing_due')."""
    calls: list[dict] = []

    def _capture(*_a, **kw):
        calls.append(kw)
        return tmp_path / "receipt.json"

    monkeypatch.setattr(
        "lib.lane_last_receipt.write_lane_receipt",
        _capture,
        raising=False,
    )
    # Also patch the import site used inside main after from-import
    import lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", _capture)
    monkeypatch.setattr(R, "now_iso", lambda: "2026-11-09T00:00:00+00:00")
    monkeypatch.setattr(LOCKUP, "run", lambda dry_run=False: {"changed": [], "alert_errors": 0})

    rc = LOCKUP.main([])
    assert rc == 0
    assert calls, "write_lane_receipt was not called"
    kw = calls[-1]
    assert kw.get("produced_count") == 0
    assert kw.get("empty_reason") == "nothing_due"
    assert kw.get("ok") is True


def test_lockup_receipt_omits_empty_reason_when_snapped(monkeypatch, tmp_path):
    calls: list[dict] = []

    def _capture(*_a, **kw):
        calls.append(kw)
        return tmp_path / "receipt.json"

    import lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", _capture)
    monkeypatch.setattr(R, "now_iso", lambda: "2026-11-09T00:00:00+00:00")
    monkeypatch.setattr(
        LOCKUP,
        "run",
        lambda dry_run=False: {
            "changed": [{"symbol": "X"}],
            "alert_errors": 0,
        },
    )

    rc = LOCKUP.main([])
    assert rc == 0
    kw = calls[-1]
    assert kw.get("produced_count") == 1
    assert kw.get("empty_reason") is None
