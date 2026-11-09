"""ANCHOR: lq1409_batch3_exit_empty — LQ-20261107-1409 batch3 (+ REWORK).

hermes-deep-research-local: provider_rate_limited-only → exit 0 (systemd oneshot;
exit 75 fails the unit the same as 1). Mixed reasons still exit 1 via _execute.
update-lockup-earnings-dates: produced=0 → empty_reason=nothing_due.
research-intelligence-queue: drain with explicit processed=0/still_queued=0 →
empty_reason=no_new_input; a missing processed must not coerce to a clean empty.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
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
RIQ = _load("lq1409_riq", "scripts/research_intelligence_queue.py")


def _hermes_execute_with_run_one(monkeypatch, tmp_path, run_one):
    """Drive _execute to the target loop with stubs (no DB/network/provider)."""
    lock = tmp_path / "hermes_deep_research_local.lock"
    kill = tmp_path / "HERMES_DISABLED"
    monkeypatch.setattr(HERMES, "LOCK", lock)
    monkeypatch.setattr(HERMES, "KILL", kill)
    monkeypatch.setenv("TRADEAI_ALLOW_DAYTIME", "1")

    class _Conn:
        def close(self):
            return None

    monkeypatch.setattr(HERMES, "db", lambda: _Conn())
    monkeypatch.setattr(HERMES, "pick_targets", lambda _c, _n: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(HERMES, "run_one", run_one)

    argv = [
        "hermes_deep_research_local.py",
        "--apply",
        "--max-rows",
        "3",
        "--allow-daytime",
        "--allow-peak",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    fake_failover = MagicMock()
    fake_failover.primary_provider.return_value = "bridge_flash"
    fake_failover.is_deepseek_offpeak.return_value = True
    fake_failover.allow_deepseek_peak.return_value = True
    fake_failover.deepseek_window_label.return_value = "offpeak"
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
        HERMES._FAILURE_REASONS.clear()
        HERMES._LAST_RUN.clear()
        return HERMES._execute()


def test_hermes_rate_limited_reason_constant():
    assert HERMES._RATE_LIMITED_REASON == "provider_rate_limited"
    assert not hasattr(HERMES, "EX_TEMPFAIL")


def test_hermes_execute_rate_limited_returns_0(monkeypatch, tmp_path):
    """REWORK: rate-limit-only → exit 0 (systemd); reasons stay on _LAST_RUN."""

    def _run_one(_conn, sym, _model, _apply):
        return HERMES._failed(sym, "provider_rate_limited", "429")

    rc = _hermes_execute_with_run_one(monkeypatch, tmp_path, _run_one)
    assert rc == 0
    assert HERMES._LAST_RUN.get("rate_limited_only") is True
    assert HERMES._LAST_RUN.get("status") == "RATE_LIMITED"
    assert HERMES._LAST_RUN.get("failure_reasons")
    assert all(r == "provider_rate_limited" for r in HERMES._LAST_RUN["failure_reasons"].values())


def test_hermes_execute_mixed_reasons_returns_1(monkeypatch, tmp_path):
    """REWORK: mixed failure reasons still exit 1 through _execute."""

    def _run_one(_conn, sym, _model, _apply):
        if sym == "AAA":
            return HERMES._failed(sym, "provider_rate_limited", "429")
        return HERMES._failed(sym, "forbidden_model", "nope")

    rc = _hermes_execute_with_run_one(monkeypatch, tmp_path, _run_one)
    assert rc == 1
    assert not HERMES._LAST_RUN.get("rate_limited_only")
    reasons = HERMES._LAST_RUN.get("failure_reasons") or {}
    assert "provider_rate_limited" in reasons.values()
    assert "forbidden_model" in reasons.values()


def test_lockup_receipt_declares_nothing_due_when_unchanged(monkeypatch, tmp_path):
    """changed=[] → write_lane_receipt(..., produced_count=0, empty_reason='nothing_due')."""
    calls: list[dict] = []

    def _capture(*_a, **kw):
        calls.append(kw)
        return tmp_path / "receipt.json"

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
        lambda dry_run=False: {"changed": [{"symbol": "X"}], "alert_errors": 0},
    )

    rc = LOCKUP.main([])
    assert rc == 0
    kw = calls[-1]
    assert kw.get("produced_count") == 1
    assert kw.get("empty_reason") is None


def test_riq_drain_idle_writes_no_new_input(monkeypatch, tmp_path):
    """REWORK: drain {ok, processed:0, still_queued:0} → produced_count=0, empty_reason=no_new_input."""
    calls: list[dict] = []

    def _capture(*_a, **kw):
        calls.append(kw)
        return tmp_path / "receipt.json"

    import lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", _capture)
    monkeypatch.setattr(R, "now_iso", lambda: "2026-11-09T00:00:00+00:00")
    monkeypatch.setattr(
        RIQ,
        "_run",
        lambda _args: {"ok": True, "processed": 0, "still_queued": 0, "settled_stale": []},
    )

    monkeypatch.setattr(sys, "argv", ["research_intelligence_queue.py", "--drain"])
    rc = RIQ.main()
    assert rc == 0
    assert calls, "write_lane_receipt was not called"
    kw = calls[-1]
    assert kw.get("produced_count") == 0
    assert kw.get("empty_reason") == "no_new_input"
    assert kw.get("ok") is True


def test_riq_drain_missing_processed_does_not_look_idle(monkeypatch, tmp_path):
    """REWORK: missing processed must not coerce to empty_reason=no_new_input."""
    calls: list[dict] = []

    def _capture(*_a, **kw):
        calls.append(kw)
        return tmp_path / "receipt.json"

    import lib.lane_last_receipt as R

    monkeypatch.setattr(R, "write_lane_receipt", _capture)
    monkeypatch.setattr(R, "now_iso", lambda: "2026-11-09T00:00:00+00:00")
    monkeypatch.setattr(
        RIQ,
        "_run",
        lambda _args: {"ok": True, "still_queued": 0, "settled_stale": []},  # no processed
    )
    monkeypatch.setattr(sys, "argv", ["research_intelligence_queue.py", "--drain"])
    rc = RIQ.main()
    assert rc == 0
    assert calls
    kw = calls[-1]
    assert kw.get("empty_reason") is None
    assert kw.get("produced_count") is None
