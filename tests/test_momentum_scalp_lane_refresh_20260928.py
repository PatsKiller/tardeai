"""Momentum-scalp lane refresh (2026-09-28) — fail→pass.

Before: the */15 cron line meant to refresh Finviz ran `timeout 150` around a 240 s stage and
shared the */5 line's lock, so it was killed silently every quarter-hour (no log line, no
receipt) and the lane had not refreshed Finviz since 2026-09-18. Now the Finviz stage clamps to
an outer deadline, writes STARTED/DONE receipts, refreshes only the scalp screeners, and the */5
wrapper refreshes itself when the last DONE receipt is older than N minutes.

COVERS = ["scripts/momentum_scalp_early_lane_runner.py", "scripts/run_finviz_momentum_scalp_scan.py",
          "config/finviz_momentum_scalp_screen.yaml"]
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import momentum_scalp_early_lane_runner as lane  # noqa: E402

COVERS = ["scripts/momentum_scalp_early_lane_runner.py", "scripts/run_finviz_momentum_scalp_scan.py",
          "config/finviz_momentum_scalp_screen.yaml"]


def test_config_lists_scalp_screeners_and_cadence():
    cfg = yaml.safe_load((ROOT / "config/finviz_momentum_scalp_screen.yaml").read_text())
    r = cfg["momentum_scalp_finviz_screen"]["refresh"]
    assert r["screener_ids"] == ["prime_setups", "watchlist_setups"]
    assert r["if_older_min"] == 15
    assert lane.refresh_screener_ids() == ["prime_setups", "watchlist_setups"]


def test_stage_timeout_clamps_to_outer_deadline(monkeypatch):
    assert lane.stage_timeout(240, None, None) == 240
    # 260 s deadline, nothing elapsed: 260 - 15 headroom = 245 > 240 → stage default
    assert lane.stage_timeout(240, 260.0, None) == 240
    # 150 s deadline (the killed cron line's `timeout`): clamp to 135
    assert lane.stage_timeout(240, 150.0, None) == 135
    # deadline nearly spent → never below 1
    t0 = lane.time.monotonic() - 300
    assert lane.stage_timeout(240, 150.0, t0) == 1


def test_outer_deadline_from_cli_or_env(monkeypatch):
    monkeypatch.delenv(lane.OUTER_DEADLINE_ENV, raising=False)
    assert lane.outer_deadline_s(None) is None
    assert lane.outer_deadline_s(260) == 260.0
    monkeypatch.setenv(lane.OUTER_DEADLINE_ENV, "200")
    assert lane.outer_deadline_s(None) == 200.0
    monkeypatch.setenv(lane.OUTER_DEADLINE_ENV, "garbage")
    assert lane.outer_deadline_s(None) is None


def test_started_receipt_survives_a_killed_stage(tmp_path, monkeypatch):
    """The failure mode that was invisible: the subprocess is killed → a STARTED receipt remains."""
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv(lane.REFRESH_RECEIPT_ENV, str(receipt))

    def _killed(cmd, timeout=None):
        # mimic _run's TimeoutExpired branch: rc 124-ish, no stdout
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(lane, "_run", _killed)
    try:
        lane.stage_finviz_scan(dry_run=False, deadline_s=150.0, screener_ids=["prime_setups"])
    except subprocess.TimeoutExpired:
        pass
    rec = json.loads(receipt.read_text())
    assert rec["state"] == "STARTED" and rec["screener_ids"] == ["prime_setups"] and rec["pid"]


def test_done_receipt_and_per_screener_calls(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv(lane.REFRESH_RECEIPT_ENV, str(receipt))
    calls = []

    def _ok(cmd, timeout=None):
        calls.append((cmd[-2:], timeout))
        return {"rc": 0, "stdout_tail": "wrote 7 rows", "stderr_tail": "", "latency_ms": 5}

    monkeypatch.setattr(lane, "_run", _ok)
    st = lane.stage_finviz_scan(dry_run=False, deadline_s=260.0, screener_ids=["prime_setups", "watchlist_setups"])
    assert st["ok"] and st["rows"] == 14 and len(st["calls"]) == 2
    assert [c[0] for c in calls] == [["--screener", "prime_setups"], ["--screener", "watchlist_setups"]]
    assert all(c[1] <= 240 for c in calls)
    rec = json.loads(receipt.read_text())
    assert rec["state"] == "DONE" and rec["rc"] == 0 and rec["rows"] == 14


def test_failed_receipt_when_runner_fails(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv(lane.REFRESH_RECEIPT_ENV, str(receipt))
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=None: {"rc": 1, "stdout_tail": "", "stderr_tail": "boom", "latency_ms": 1})
    st = lane.stage_finviz_scan(dry_run=False, screener_ids=["prime_setups"])
    assert not st["ok"]
    assert json.loads(receipt.read_text())["state"] == "FAILED"


def test_refresh_age_only_counts_done_receipts():
    now = datetime(2026, 9, 28, 7, 30, tzinfo=timezone.utc)
    done16 = {"state": "DONE", "at": (now - timedelta(minutes=16)).isoformat()}
    done4 = {"state": "DONE", "at": (now - timedelta(minutes=4)).isoformat()}
    started = {"state": "STARTED", "at": (now - timedelta(minutes=1)).isoformat()}
    assert round(lane.refresh_age_min(now, done16)) == 16
    assert round(lane.refresh_age_min(now, done4)) == 4
    assert lane.refresh_age_min(now, started) is None
    assert lane.refresh_age_min(now, None) is None


def test_wrapper_refreshes_at_16_min_and_skips_at_4_min(tmp_path, monkeypatch):
    """Drive the wrapper's decision branch through its real main() with the stages stubbed."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rfms", ROOT / "scripts" / "run_finviz_momentum_scalp_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = []
    monkeypatch.setattr(mod.lane, "stage_finviz_scan", lambda **kw: (seen.append(kw) or {"stage": "finviz_scan", "ran": True, "ok": True}))
    monkeypatch.setattr(mod.lane, "scan_counts", lambda *a, **k: {"rows": 0})
    monkeypatch.setattr(mod.lane, "is_trading_day", lambda t: True)
    monkeypatch.setattr(mod.lane, "in_window", lambda t, w=None: True)

    def run(age):
        monkeypatch.setattr(mod.lane, "refresh_age_min", lambda *a, **k: age)
        out = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(a[0] if a else ""))
        monkeypatch.setattr(sys, "argv", ["x", "--apply", "--refresh-if-older-min", "15", "--deadline-s", "260"])
        rc = mod.main()
        return rc, json.loads(out[-1])

    seen.clear(); rc, rep = run(16.0)
    assert rc == 0 and seen and seen[0]["deadline_s"] == 260.0 and rep["deadline_s"] == 260.0
    seen.clear(); rc, rep = run(4.0)
    assert rc == 0 and not seen
    assert rep["stages"][0]["reason"].startswith("skipped_finviz_refresh_fresh (age=4.0m")
    seen.clear(); rc, rep = run(None)   # no receipt ever → refresh
    assert seen


def test_receipt_path_never_hardcodes_a_host(monkeypatch, tmp_path):
    monkeypatch.delenv(lane.REFRESH_RECEIPT_ENV, raising=False)
    p = lane.refresh_receipt_path()
    assert p.name == lane.REFRESH_RECEIPT_NAME and p.parent.name == "runtime"
    src = (ROOT / "scripts/momentum_scalp_early_lane_runner.py").read_text()
    assert "/home/" + "johnclaw" not in src
