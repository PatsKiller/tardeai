"""Stage 5 harness — scheduler renderer + live authorization marker tests.
Proves the renderer never schedules and the live path refuses without an owner marker."""
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader import premarket_observation_schedule as sched  # noqa: E402
from active_trader import market_calendar as cal  # noqa: E402

TZ = ZoneInfo("America/New_York")


def test_schedule_plan_next_valid_session_after_cutoff():
    # 2026-07-23 08:52 ET is past the 07:10 cutoff -> next trading day
    plan = sched.schedule_plan(dt.datetime(2026, 7, 23, 8, 52, tzinfo=TZ))
    assert plan["disposition"] == "SCHEDULE_NEXT_TRADING_DAY"
    assert plan["target_trading_date"] == "2026-07-24"
    assert plan["timezone"] == "America/New_York"


def test_schedule_plan_start_now_in_window():
    plan = sched.schedule_plan(dt.datetime(2026, 7, 24, 6, 58, tzinfo=TZ))
    assert plan["disposition"] == "START_NOW"


def test_schedule_plan_schedule_today_before_preflight():
    plan = sched.schedule_plan(dt.datetime(2026, 7, 24, 5, 0, tzinfo=TZ))
    assert plan["disposition"] == "SCHEDULE_TODAY"


def test_render_transient_unit_no_secret_absolute_paths_oneshot():
    r = sched.render_transient_unit(
        now=dt.datetime(2026, 7, 23, 8, 52, tzinfo=TZ),
        launcher_path="/abs/run_active_trader_premarket_observation.py",
        worktree="/home/johnclaw/worktrees/active-trader-next",
        state_dir="/home/johnclaw/.local/state/lab/obs", log_dir="/home/johnclaw/.local/state/lab/logs",
        session_number=1)
    assert r["argv_contains_secret"] is False
    assert r["user_level"] and r["transient"] and r["one_shot"]
    assert r["linger_change"] is False and r["boot_persistence"] is False
    assert r["unit_properties"]["WorkingDirectory"].startswith("/")
    assert r["argv"][0].startswith("/")
    # no secret-like token anywhere in the rendered blob
    blob = " ".join(str(v) for v in r.values()).lower()
    for bad in ("password", "token", "secret", "pwd", "md5", "sms"):
        assert bad not in blob


def test_execute_schedule_blocked_and_no_systemd():
    r = sched.execute_schedule()
    assert r["status"] == sched.NOT_AUTHORIZED == "NOT_AUTHORIZED_BY_BUILD_TRANSACTION"
    assert r["systemd_run_called"] is False


def _marker(**over):
    base = dict(run_id="20260722-01", session_number=1,
                expected_git_sha="abc123", target_market_date="2026-07-24",
                target_window="07:00-10:05", symbols_policy="AAPL+<=1 representative",
                created_at="2026-07-23T20:00:00-04:00", expires_at="2026-07-25T00:00:00-04:00",
                owner_authorization_version="obs-auth-1")
    base.update(over)
    return sched.ObservationAuthorizationMarker.from_dict(base)


def test_live_authorization_blocked_without_marker():
    chk = sched.verify_live_authorization(
        None, current_git_sha="abc123", worktree_clean=True, session_number=1,
        now=dt.datetime(2026, 7, 24, 7, 0, tzinfo=TZ), smoke_pass=True,
        credential_green=True, trade_scan_pass=True)
    assert not chk.authorized and chk.status == sched.BLOCKED_OWNER


def test_live_authorization_pass_with_valid_marker():
    chk = sched.verify_live_authorization(
        _marker(), current_git_sha="abc123", worktree_clean=True, session_number=1,
        now=dt.datetime(2026, 7, 24, 7, 0, tzinfo=TZ), smoke_pass=True,
        credential_green=True, trade_scan_pass=True)
    assert chk.authorized and chk.status == "AUTHORIZED"


def test_live_authorization_fails_on_sha_expiry_session_and_evidence():
    good_now = dt.datetime(2026, 7, 24, 7, 0, tzinfo=TZ)
    # sha mismatch
    assert not sched.verify_live_authorization(_marker(), current_git_sha="ZZZ", worktree_clean=True,
        session_number=1, now=good_now, smoke_pass=True, credential_green=True, trade_scan_pass=True).authorized
    # expired
    assert not sched.verify_live_authorization(_marker(expires_at="2026-07-24T06:00:00-04:00"),
        current_git_sha="abc123", worktree_clean=True, session_number=1, now=good_now,
        smoke_pass=True, credential_green=True, trade_scan_pass=True).authorized
    # smoke evidence missing
    assert not sched.verify_live_authorization(_marker(), current_git_sha="abc123", worktree_clean=True,
        session_number=1, now=good_now, smoke_pass=False, credential_green=True, trade_scan_pass=True).authorized
    # dirty worktree
    assert not sched.verify_live_authorization(_marker(), current_git_sha="abc123", worktree_clean=False,
        session_number=1, now=good_now, smoke_pass=True, credential_green=True, trade_scan_pass=True).authorized


def test_marker_rejects_secret_fields():
    with pytest.raises(ValueError):
        sched.ObservationAuthorizationMarker.from_dict({
            "run_id": "r", "session_number": 1, "expected_git_sha": "s",
            "target_market_date": "2026-07-24", "target_window": "07:00-10:05",
            "symbols_policy": "password=hunter2", "created_at": "x", "expires_at": "y",
            "owner_authorization_version": "v"})


def test_no_scheduler_invocation_in_module():
    # The module NAMES systemd-run/systemctl in docstrings + rendered text (to prove it refuses),
    # but must never IMPORT or CALL a process/scheduler API.
    src = (Path(__file__).resolve().parents[1] / "scripts" / "active_trader"
           / "premarket_observation_schedule.py").read_text()
    for banned in ("import subprocess", "import os\n", "os.system", "Popen", "subprocess.run",
                   "check_output", "check_call"):
        assert banned not in src


def test_run_live_authorized_path_executes(tmp_path, monkeypatch):
    """Regression: run_live's authorized path must execute end-to-end (mocked capture) without a
    NameError. Guards the dt/_dt typo that crashed the live Session 1 capture on 2026-07-24 —
    that line was never exercised by the module tests until the real timer fired."""
    import importlib.util, argparse
    import json as _json
    root = Path(__file__).resolve().parents[1] / "scripts" / "run_active_trader_premarket_observation.py"
    spec = importlib.util.spec_from_file_location("runroot_under_test", root)
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)

    # force authorization + stub the live capture so no OpenD/broker is touched
    monkeypatch.setattr(rr.sched, "verify_live_authorization",
                        lambda *a, **k: rr.sched.LiveAuthorizationCheck(True, "AUTHORIZED", []))
    monkeypatch.setattr(rr, "worktree_clean", lambda: True)
    monkeypatch.setattr(rr, "current_git_sha", lambda: "deadbeef")
    import active_trader.premarket_observation_live as live

    class _Cap:
        result = "CAPTURE_OK"; counts = {"ORDER_BOOK": 3}; event_count = 3
        parquet_verified = True; parquet_row_count = 3; safety = {"trade_context": False}
        wal_path = str(tmp_path / "seg.wal")
    monkeypatch.setattr(live, "capture", lambda **k: _Cap())
    monkeypatch.setattr(live, "events_from_wal", lambda p: [])

    marker = tmp_path / "m.json"
    marker.write_text(_json.dumps({
        "run_id": "20260722-01", "session_number": 1, "expected_git_sha": "deadbeef",
        "target_market_date": "2026-07-27", "target_window": "07:00-10:05",
        "symbols_policy": "AAPL baseline", "created_at": "2026-07-24T20:00:00-04:00",
        "expires_at": "2026-07-28T00:00:00-04:00", "owner_authorization_version": "v"}))
    args = argparse.Namespace(
        mode="live", fixture=None, out=str(tmp_path), session_index=1,
        authorization_marker=str(marker), execute_schedule=False, smoke_pass=True,
        credential_green=True, trade_scan_pass=True, max_capture_seconds=1.0)

    res = rr.run_live(args)
    assert res["result"] == "CAPTURE_OK" and res["opend_started"] is True
    # these fields exist only if end_et computed + evaluate() ran — i.e. the dt/_dt line is correct
    for k in ("premarket_transport", "rth_continuous_capture", "session_counted"):
        assert k in res
