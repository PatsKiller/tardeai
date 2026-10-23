"""Trade AI scalp-window cadence (operator 2026-10-23, P1).

"These are supposed to be running like every 5 minutes … we can't have that long of a period on micro
scalps." Pins:

* continuous_runner cycles every 5 minutes across 06:00-12:00 ET and hard-stops at 12:00 (was 15/10/15
  minutes and an 11:30 stop);
* after each scalp-window cycle it starts a non-blocking ``warm_caches.py --only trade_ai`` under the shared
  warm lock, so the page does not wait for the */8 warm; outside the window it starts nothing;
* ``warm_caches --only trade_ai`` recomputes only the scanner cache and writes the trade-ai-rewarm receipt,
  never the three-step warm-caches lane receipt;
* the scanner payload carries ``latest_scan_at`` and a per-serve ``scan_freshness`` (FRESH / STALE after
  10 min in the window / OFF_WINDOW / UNKNOWN), also on /trade-ai/summary for the header.

Hermetic: no DB, no network, no process is started (Popen is injected), api_v2 is a fake module.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
ET = ZoneInfo("America/New_York")


def _et(h, m, day=23):  # 2026-10-23 is a Friday
    return datetime(2026, 10, day, h, m, tzinfo=ET).astimezone(timezone.utc)


# ── continuous_runner cadence ──────────────────────────────────────────────


def _cr():
    sys.modules.pop("continuous_runner", None)
    return importlib.import_module("continuous_runner")


@pytest.mark.parametrize("hm", ["06:00", "07:10", "08:55", "09:00", "09:45", "10:30", "11:00", "11:55"])
def test_scalp_window_is_five_minute_grid(hm, monkeypatch):
    cr = _cr()
    monkeypatch.setattr(cr, "_now_min", lambda: cr._hm_to_min(hm))
    assert cr._current_interval() == 5


def test_hard_cutoff_is_end_of_scalp_window():
    cr = _cr()
    assert cr.SCALP_WINDOW == ("06:00", "12:00") and cr.HARD_CUTOFF_HM == "12:00"
    src = (ROOT / "scripts" / "continuous_runner.py").read_text(encoding="utf-8")
    assert 'if now_min >= _hm_to_min("11:30"):' not in src
    assert "if now_min >= _hm_to_min(HARD_CUTOFF_HM):" in src


def test_rewarm_started_in_window_with_shared_lock(tmp_path):
    cr = _cr()
    (tmp_path / "logs").mkdir()
    seen = []
    cmd = cr._rewarm_trade_ai_cache(tmp_path, now_min=cr._hm_to_min("08:40"), popen=lambda c, **k: seen.append((c, k)))
    assert cmd and seen and seen[0][0] == cmd
    assert cmd[:3] == ["flock", "-n", "/tmp/warm_caches.lock"]
    assert cmd[-3:] == [str(tmp_path / "scripts" / "warm_caches.py"), "--only", "trade_ai"][-3:]
    assert seen[0][1]["cwd"] == str(tmp_path)


@pytest.mark.parametrize("hm", ["05:59", "12:00", "13:00"])
def test_rewarm_skipped_outside_window(hm, tmp_path):
    cr = _cr()
    seen = []
    assert cr._rewarm_trade_ai_cache(tmp_path, now_min=cr._hm_to_min(hm), popen=lambda c, **k: seen.append(c)) is None
    assert seen == []


def test_rewarm_failure_never_breaks_the_loop(tmp_path):
    cr = _cr()
    (tmp_path / "logs").mkdir()

    def boom(*a, **k):
        raise OSError("no flock")

    assert cr._rewarm_trade_ai_cache(tmp_path, now_min=cr._hm_to_min("09:00"), popen=boom) is None


def test_main_loop_calls_rewarm_after_each_cycle():
    src = (ROOT / "scripts" / "continuous_runner.py").read_text(encoding="utf-8")
    loop = src[src.index("def main() -> int:") :]
    assert (
        loop.index("run_live_cycle(root, run_label, date_str, state, time_str)")
        < loop.index("_rewarm_trade_ai_cache(root)")
        < loop.index("# Digest triggers")
    )


# ── warm_caches --only trade_ai ────────────────────────────────────────────


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    return root


def _receipt(state, lane):
    p = state / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


def _fake_api(monkeypatch, exc=None):
    calls = []
    api = types.ModuleType("api_v2")

    def trade_ai(force=False):
        calls.append(("trade_ai", force))
        if exc:
            raise exc

    def rot(*a, **k):
        calls.append(("rotation_summary",))

    api.trade_ai = trade_ai
    api._rotation_summary = rot
    monkeypatch.setitem(sys.modules, "api_v2", api)
    ra = types.ModuleType("rotation_autopilot")
    ra.run_autopilot_tick = lambda **k: calls.append(("autopilot",)) or {}
    monkeypatch.setitem(sys.modules, "rotation_autopilot", ra)
    return calls


def _wc():
    sys.modules.pop("warm_caches", None)
    return importlib.import_module("warm_caches")


def test_only_trade_ai_runs_one_step_and_its_own_receipt(state, monkeypatch):
    calls = _fake_api(monkeypatch)
    assert _wc().main(["--only", "trade_ai"]) == 0
    assert calls == [("trade_ai", True)]
    rec = _receipt(state, "trade-ai-rewarm")
    assert rec["status"] == "ok" and set(rec["summary"]["steps_s"]) == {"trade_ai"}
    assert _receipt(state, "warm-caches") is None  # a one-step run never stamps the three-step lane


def test_only_trade_ai_failure_exits_1(state, monkeypatch):
    _fake_api(monkeypatch, exc=RuntimeError("db down"))
    assert _wc().main(["--only", "trade_ai"]) == 1
    rec = _receipt(state, "trade-ai-rewarm")
    assert rec["status"] != "ok" and rec["summary"]["failed"] == ["trade_ai"]


def test_only_dry_run_lists_just_that_step(state, monkeypatch, capsys):
    calls = _fake_api(monkeypatch)
    assert _wc().main(["--dry-run", "--only", "trade_ai"]) == 0
    out = capsys.readouterr().out
    assert "would run trade_ai" in out and "rotation_summary" not in out
    assert calls == [] and _receipt(state, "trade-ai-rewarm") is None


# ── scan freshness ─────────────────────────────────────────────────────────


def test_latest_scan_at_picks_newest_zoned_stamp():
    from lib.scan_freshness import latest_scan_at

    rows = [
        {"persisted_at": "2026-10-23T08:40:10-04:00"},
        {"persisted_at": "2026-10-23T12:52:23+00:00"},
        {"persisted_at": "2026-10-23T08:59:00"},  # unzoned: dropped, not guessed
        {"persisted_at": None},
        "junk",
    ]
    assert latest_scan_at(rows) == "2026-10-23T12:52:23+00:00"
    assert latest_scan_at([]) is None and latest_scan_at(None) is None


@pytest.mark.parametrize(
    "now,latest,status,age",
    [
        (_et(8, 54), "2026-10-23T08:50:00-04:00", "FRESH", 240),
        (_et(8, 54), "2026-10-23T08:43:59-04:00", "STALE", 601),
        (_et(8, 54), "2026-10-23T07:00:00-04:00", "STALE", 6840),
        (_et(13, 0), "2026-10-23T11:59:00-04:00", "OFF_WINDOW", 3660),
        (_et(8, 54, day=24), "2026-10-23T11:59:00-04:00", "OFF_WINDOW", None),  # Saturday
        (_et(8, 54), None, "UNKNOWN", None),
    ],
)
def test_scan_freshness_status(now, latest, status, age):
    from lib.scan_freshness import scan_freshness

    f = scan_freshness(latest, now)
    assert f["status"] == status and f["contract"] == "ScanFreshness@v1"
    if age is not None:
        assert f["age_sec"] == age
    assert f["stale_after_sec"] == 600 and f["expected_cadence_sec"] == 300


def test_api_publishes_freshness_on_scanner_and_summary():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name: ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert '"latest_scan_at": _scan_latest_at(tickers)' in fns["_compute_trade_ai"]
    assert 'data["scan_freshness"] = scan_freshness(data.get("latest_scan_at"))' in fns["_refresh_trade_ai_cache_age"]
    summary = fns["trade_ai_summary"]
    assert '"latest_scan_at"' in summary and '"scan_freshness"' in summary
