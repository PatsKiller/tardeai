"""Disk monitor — host-resident growth monitor (operator 2026-10-30 ENOSPC follow-on).

Pins the baseline seed/update contract, the pure band/growth/hotspot guards (including the mutation check that each
guard reads its configured threshold, not a constant), the transition-only dedupe (band changes alert once, same band
sends nothing, recovery sends once), the stable dedupe key, and that --dry-run writes nothing and sends nothing.

Hermetic: tmp home, tmp state root, tmp config, tmp alert-condition state, a fake df (measure_mount) and du
(du_bytes), and a fake Telegram notify. No live home, ledger, n8n, Telegram or production state.

COVERS = ["scripts/disk_monitor.py", "config/disk_monitor.json"]
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import disk_monitor as DMON  # noqa: E402

CONFIG = ROOT / "config"
GIB = 1024 ** 3
T0 = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _load() -> dict:
    return json.loads((CONFIG / "disk_monitor.json").read_text(encoding="utf-8"))


@pytest.fixture
def mon(tmp_path, monkeypatch):
    """A disk_monitor run harness: controllable df + du, a fake notifier, and a tmp config/state/alert path."""
    home = tmp_path / "home"
    home.mkdir()
    cfg = tmp_path / "disk_monitor.json"
    doc = _load()
    doc["home"] = str(home)
    doc["mounts"] = ["/"]
    doc["hotspots"] = []  # mount-focused tests; hotspot flags are pinned by the pure tests below
    doc["grow_warn_bytes"] = 10 ** 18  # growth effectively off for the used-band tests
    doc["grow_critical_bytes"] = 10 ** 18
    cfg.write_text(json.dumps(doc, indent=1))

    env = {"size": 500 * GIB, "used": int(500 * GIB * 0.5)}

    def fake_measure(mount):
        used = env["used"]
        return {"mount": mount, "used_pct": round(used / env["size"] * 100.0, 2),
                "used_bytes": used, "avail_bytes": env["size"] - used, "size_bytes": env["size"]}

    monkeypatch.setattr(DMON, "measure_mount", fake_measure)
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: 0)

    sends: list[tuple[str, str]] = []

    def fake_notify(text, priority):
        sends.append((text, priority))
        return "accepted"

    monkeypatch.setattr(DMON, "default_notify", fake_notify)
    clock = {"t": T0}

    return types.SimpleNamespace(
        home=home, cfg=cfg, state=tmp_path / "state", alert=tmp_path / "alert_state.json",
        env=env, sends=sends, clock=clock, doc=doc,
    )


def _run(m, apply: bool, used: float, hours: float = 0.0, *extra: str) -> int:
    m.clock["t"] = m.clock["t"] + timedelta(hours=hours)
    m.env["used"] = int(m.env["size"] * used / 100.0)
    args = (["--apply"] if apply else []) + list(extra)
    return DMON.main([*args, "--config", str(m.cfg), "--state-root", str(m.state),
                      "--now", m.clock["t"].isoformat(), "--alert-state", str(m.alert)])


def _baseline(m) -> dict:
    return json.loads((m.state / "data" / "runtime" / "disk_monitor_baseline.json").read_text())


# ── 1. baseline create / update ───────────────────────────────────────────────────────────────────────────────────


def test_baseline_seeds_on_first_apply_and_updates_on_the_second(mon):
    assert _run(mon, apply=True, used=50.0) == 0
    b = _baseline(mon)
    assert b["schema"] == DMON.BASELINE_SCHEMA
    assert b["mounts"]["/"]["used_bytes"] == int(500 * GIB * 0.5)
    assert b["samples"][0]["mounts"]["/"] == int(500 * GIB * 0.5)
    first_at = b["updated_at"]
    assert mon.sends == []  # the first run seeds and sends nothing

    assert _run(mon, apply=True, used=52.0, hours=1.0) == 0
    b2 = _baseline(mon)
    assert b2["baseline_at"] == b["baseline_at"]  # the reference is stable; only updated_at + samples advance
    assert b2["updated_at"] > first_at
    assert b2["mounts"]["/"]["used_bytes"] == int(500 * GIB * 0.52)
    assert len(b2["samples"]) == 2


def test_a_failed_measurement_keeps_the_prior_baseline_value(mon, monkeypatch):
    assert _run(mon, apply=True, used=50.0) == 0
    before = _baseline(mon)["mounts"]["/"]["used_bytes"]

    def boom(mount):
        return None

    monkeypatch.setattr(DMON, "measure_mount", boom)
    rc = _run(mon, apply=True, used=50.0, hours=1.0)
    # the run reports the unmeasurable mount (fail closed), but the prior value is never overwritten
    assert rc == 1
    assert _baseline(mon)["mounts"]["/"]["used_bytes"] == before


def test_an_unmeasured_hotspot_is_a_degradation_not_a_failure(mon, monkeypatch):
    mon.doc["hotspots"] = [{"id": "cache", "path": "~/.cache", "purge": "rule C"}]
    mon.cfg.write_text(json.dumps(mon.doc, indent=1))
    assert _run(mon, apply=True, used=50.0) == 0
    assert _baseline(mon)["hotspots"]["cache"]["bytes"] == 0
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: None)
    assert _run(mon, apply=True, used=52.0, hours=1.0) == 0  # soft: exit 0, not a run failure
    b = _baseline(mon)
    assert b["hotspots"]["cache"]["bytes"] == 0  # prior value kept (fail closed, never a zero or an error string)
    assert b["hotspots"]["cache"]["last_failure"] is not None  # the failure is recorded beside the value


# ── 2. the guards (pure), including the mutation check ────────────────────────────────────────────────────────────


def test_used_band_boundaries_and_the_guard_reads_the_threshold():
    m = {"warn_pct": 80.0, "critical_pct": 90.0}
    assert [DMON.band_of(p, m) for p in (79.99, 80.0, 89.99, 90.0, 99.0)] == \
        ["ok", "warn", "warn", "critical", "critical"]
    # mutation: the SAME reading flips when the threshold moves — the guard keys on the configured value, not a constant
    assert DMON.band_of(85.0, {"warn_pct": 90.0, "critical_pct": 95.0}) == "ok"
    assert DMON.band_of(85.0, {"warn_pct": 80.0, "critical_pct": 90.0}) == "warn"


def test_growth_band_boundaries_and_unknown():
    m = {"grow_warn_bytes": 10 * GIB, "grow_critical_bytes": 50 * GIB}
    assert DMON.growth_band(None, m) == "unknown"
    assert [DMON.growth_band(d, m) for d in (10 * GIB - 1, 10 * GIB, 50 * GIB, 50 * GIB + 1)] == \
        ["ok", "warn", "critical", "critical"]


def test_hotspot_flag_new_growing_and_ok():
    m = {"hotspot_growth_min_bytes": GIB, "hotspot_growth_ratio": 1.5}
    assert DMON.hotspot_flag(None, 0, m) == "unknown"
    assert DMON.hotspot_flag(100 * GIB, None, m) == "new"
    assert DMON.hotspot_flag(100 * GIB, 0, m) == "new"
    assert DMON.hotspot_flag(100 * GIB, 50 * GIB, m) == "growing"  # 2x, above min
    assert DMON.hotspot_flag(100 * GIB, 90 * GIB, m) == "ok"       # 1.11x, below ratio
    assert DMON.hotspot_flag(int(0.5 * GIB), 0, m) == "new"        # below min, but new is a new signal
    assert DMON.hotspot_flag(100 * GIB, 50 * GIB, {"hotspot_growth_min_bytes": 10 ** 18, "hotspot_growth_ratio": 1.5}) == "ok"


def test_growth_reference_prefers_the_window_sample_and_falls_back_to_baseline():
    mon_cfg = {"growth_window_hours": 24}
    now = T0
    base = {"mounts": {"/": {"used_bytes": 100}}, "samples": [
        {"at": (now - timedelta(hours=30)).isoformat(), "mounts": {"/": 100}},  # outside window
        {"at": (now - timedelta(hours=20)).isoformat(), "mounts": {"/": 120}},  # earliest within 24h
        {"at": (now - timedelta(hours=1)).isoformat(), "mounts": {"/": 200}},
    ]}
    assert DMON.growth_reference(base, mon_cfg, now, "/") == 120
    assert DMON.growth_reference({"mounts": {"/": {"used_bytes": 42}}, "samples": []}, mon_cfg, now, "/") == 42
    assert DMON.growth_reference({"samples": []}, mon_cfg, now, "/") is None


# ── 3. transition-only dedupe + stable key ─────────────────────────────────────────────────────────────────────────


def test_condition_key_is_stable_and_never_a_percent_or_timestamp():
    assert DMON.condition_key("/", "used") == "host:disk_monitor:/:used"
    assert DMON.condition_key("/", "growth") == "host:disk_monitor:/:growth"
    for k in (DMON.condition_key("/", "used"), DMON.condition_key("cache", "hotspot")):
        assert "%" not in k and "T" not in k.split(":")[-1]


def test_predict_notify_transitions_once_per_state_change():
    warn = {"state": "warn", "alertable": True}
    assert DMON._predict_notify(None, "warn", True) is True            # new
    assert DMON._predict_notify(warn, "warn", True) is False           # ongoing
    assert DMON._predict_notify(warn, "critical", True) is True        # warn -> critical
    assert DMON._predict_notify({"state": "critical", "alertable": True}, "ok", False) is True  # recovered
    assert DMON._predict_notify({"state": "ok", "alertable": False}, "ok", False) is False       # steady ok


def test_used_band_alerts_once_per_band_change_end_to_end(mon):
    assert _run(mon, apply=True, used=50.0) == 0
    assert _run(mon, apply=True, used=85.0, hours=1.0) == 0
    assert len(mon.sends) == 1 and "WARN" in mon.sends[0][0] and mon.sends[0][1] == "P2"
    assert _run(mon, apply=True, used=87.5, hours=1.0) == 0
    assert len(mon.sends) == 1  # same band: deduped
    assert _run(mon, apply=True, used=92.0, hours=1.0) == 0
    assert len(mon.sends) == 2 and "CRITICAL" in mon.sends[1][0] and mon.sends[1][1] == "P1"
    assert _run(mon, apply=True, used=60.0, hours=1.0) == 0
    assert len(mon.sends) == 3 and "recovered" in mon.sends[2][0] and mon.sends[2][1] == "P2"


def test_growth_band_alerts_once_end_to_end(mon):
    mon.doc["grow_warn_bytes"] = 10 * GIB
    mon.doc["grow_critical_bytes"] = 50 * GIB
    mon.doc["growth_window_hours"] = 1
    mon.cfg.write_text(json.dumps(mon.doc, indent=1))
    # used stays 40% (below the 80% warn band); only growth can fire
    assert _run(mon, apply=True, used=40.0) == 0
    # +20 GiB in one hour -> growth warn (>= 10 GiB, < 50 GiB), used still 44% (ok)
    assert _run(mon, apply=True, used=44.0, hours=1.0) == 0
    assert len(mon.sends) == 1 and "growth" in mon.sends[0][0] and "WARN" in mon.sends[0][0]


# ── 4. dry-run writes and sends nothing ───────────────────────────────────────────────────────────────────────────


def test_dry_run_writes_nothing_and_sends_nothing(mon, capsys):
    assert _run(mon, apply=False, used=50.0) == 0
    out = capsys.readouterr().out
    assert '"dry_run": true' in out or "DRY-RUN" in out
    assert "disk_monitor_baseline.json" in out  # the dry run says WHAT it would write
    assert mon.sends == []
    assert not (mon.state / "data" / "runtime" / "disk_monitor_baseline.json").exists()
    assert not (mon.state / "data" / "runtime" / "disk-monitor_last.json").exists()
    assert not mon.alert.exists()


def test_dry_run_reports_the_transition_it_would_send(mon, capsys):
    # seed an apply so the condition store is real, then ask what the next warn would do
    assert _run(mon, apply=True, used=50.0) == 0
    capsys.readouterr()
    assert _run(mon, apply=False, used=85.0, hours=1.0) == 0
    out = capsys.readouterr().out
    assert "WARN" in out and "would_send" in out
    assert mon.sends == []  # predicted, not sent


def test_monitor_imports_no_sender_or_broker():
    src = (ROOT / "scripts" / "disk_monitor.py").read_text()
    for bad in ("requests", "urllib", "psycopg", "place_order", "alpaca", "schwab"):
        assert bad not in src, bad
