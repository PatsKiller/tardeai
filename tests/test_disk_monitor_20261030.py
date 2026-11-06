"""Disk monitor — host-resident growth monitor (operator 2026-10-30 ENOSPC follow-on).

Pins the baseline seed/update contract, the pure band/growth/hotspot guards (including the mutation check that each
guard reads its configured threshold, not a constant), the transition-only dedupe (band changes alert once, same band
sends nothing, recovery sends once), the stable dedupe key, and that --dry-run writes nothing and sends nothing.

Hermetic: tmp home, tmp state root, tmp config, tmp alert-condition state, a fake df (measure_mount) and du
(du_bytes), and a fake Telegram notify. No live home, ledger, n8n, Telegram or production state.

COVERS = ["scripts/disk_monitor.py", "config/disk_monitor.json"]
"""

from __future__ import annotations

import importlib.util
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

# Test isolation: load the producer by FILE PATH with an importlib spec, register it in sys.modules BEFORE
# execution, and never import it through the shared ``scripts`` package. A cached or stubbed package module must not
# be able to stand in for the implementation under test.
_MODULE_NAME = "disk_monitor_20261030_under_test"
_MODULE_PATH = ROOT / "scripts" / "disk_monitor.py"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
DMON = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = DMON
_spec.loader.exec_module(DMON)

ORIG_DU = DMON.du_bytes  # the real subprocess-backed measurement, before the fixture monkeypatches it


def test_the_producer_is_loaded_by_path_not_through_the_shared_scripts_package():
    """Test-isolation rule: the implementation under test comes from its FILE, not a cached/stubbed package module."""
    assert DMON.__name__ == _MODULE_NAME
    assert Path(DMON.__file__) == _MODULE_PATH
    assert sys.modules[_MODULE_NAME] is DMON
    # a stub registered under the package path must not be what this suite exercises
    stub = types.ModuleType("scripts.disk_monitor")
    real = sys.modules.get("scripts.disk_monitor")
    try:
        sys.modules["scripts.disk_monitor"] = stub
        assert DMON is not stub
    finally:
        if real is None:
            sys.modules.pop("scripts.disk_monitor", None)
        else:
            sys.modules["scripts.disk_monitor"] = real

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


def test_a_partially_unmeasurable_glob_is_unmeasured_and_preserves_the_baseline(mon, monkeypatch, capsys):
    """CX3: one measured + one timed-out target is NOT a total; storing the partial sum would later read the
    reappearing target's existing bytes as new growth."""
    (mon.home / "wt-a").mkdir()
    (mon.home / "wt-b").mkdir()
    mon.doc["hotspots"] = [{"id": "wt_glob", "path": "~/wt-*", "glob": True, "purge": "rule G"}]
    mon.cfg.write_text(json.dumps(mon.doc, indent=1))

    sizes = {mon.home / "wt-a": 4 * GIB, mon.home / "wt-b": 6 * GIB}
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: sizes.get(Path(path)))
    assert _run(mon, apply=True, used=50.0) == 0
    assert _baseline(mon)["hotspots"]["wt_glob"]["bytes"] == 10 * GIB
    capsys.readouterr()

    # one target stops answering: the partial 4 GiB must NOT replace the complete 10 GiB baseline
    monkeypatch.setattr(DMON, "du_bytes",
                        lambda path, timeout: 4 * GIB if Path(path).name == "wt-a" else None)
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 0  # degradation, not a run failure
    b = _baseline(mon)
    assert b["hotspots"]["wt_glob"]["bytes"] == 10 * GIB  # complete prior value preserved
    assert b["hotspots"]["wt_glob"]["last_failure"] is not None
    assert b["hotspots"]["wt_glob"]["unmeasured"] == 1
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["degraded_hotspots"] == 1 and report["failures"] == 0


def test_du_bytes_rejects_a_nonzero_exit_even_with_a_numeric_total(monkeypatch):
    """A traversal that could not finish may still print a PARTIAL total; it is not the directory's size."""
    class Proc:
        def __init__(self, stdout, returncode):
            self.stdout, self.returncode, self.stderr = stdout, returncode, "du: cannot read directory"

    for rc, expected in ((0, 123456), (1, None), (2, None)):
        monkeypatch.setattr(DMON.subprocess, "run", lambda *a, _rc=rc, **k: Proc("123456\t/x\n", _rc))
        assert DMON.du_bytes(Path("/x"), 5) == expected


def test_a_nonzero_du_exit_never_overwrites_the_hotspot_baseline(mon, monkeypatch, capsys):
    """The rejected measurement must keep the complete prior value and record the failure beside it."""
    mon.doc["hotspots"] = [{"id": "cache", "path": "~/.cache", "purge": "rule C"}]
    mon.cfg.write_text(json.dumps(mon.doc, indent=1))
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: 10 * GIB)
    assert _run(mon, apply=True, used=50.0) == 0
    assert _baseline(mon)["hotspots"]["cache"]["bytes"] == 10 * GIB
    capsys.readouterr()

    class Proc:
        returncode, stdout, stderr = 1, f"{4 * GIB}\t{mon.home / '.cache'}\n", "du: cannot read directory"

    monkeypatch.setattr(DMON, "du_bytes", ORIG_DU)  # drive the real helper over a failing `du`
    monkeypatch.setattr(DMON.subprocess, "run", lambda *a, **k: Proc())
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 0  # degradation, not a run failure
    b = _baseline(mon)["hotspots"]["cache"]
    assert b["bytes"] == 10 * GIB  # the partial 4 GiB never lands in the value slot
    assert b["last_failure"] is not None
    # the REPORTED result labels it a degradation, never a complete value
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["degraded_hotspots"] == 1 and report["failures"] == 0
    assert report["hotspots"][0]["bytes"] is None and report["hotspots"][0]["flag"] == "unknown"

    # negative control: a successful traversal is accepted and updates the stored value
    class OK:
        returncode, stdout, stderr = 0, f"{5 * GIB}\t{mon.home / '.cache'}\n", ""

    monkeypatch.setattr(DMON.subprocess, "run", lambda *a, **k: OK())
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 0
    assert _baseline(mon)["hotspots"]["cache"]["bytes"] == 5 * GIB


def test_a_rejected_notification_is_retried_not_consumed(mon, monkeypatch, capsys):
    """A transition whose send is not accepted must survive in the condition store so the next run retries it."""
    assert _run(mon, apply=True, used=50.0) == 0  # seed
    capsys.readouterr()
    monkeypatch.setattr(DMON, "default_notify", lambda text, priority: "send_returned_false")
    assert _run(mon, apply=True, used=85.0, hours=1.0) == 1  # the rejected send fails the run
    assert mon.sends == []  # nothing accepted; the fixture's accepted-notifier list stays empty
    # the transition is still PENDING: the unaccepted observation was rolled back, not consumed as "ongoing"
    assert DMON._load_condition(mon.alert).get(DMON.condition_key("/", "used")) is None
    # the failure is REPORTED, not merely returned: the receipt is failed and counts it, and so does the report
    receipt = json.loads((mon.state / "data" / "runtime" / "disk-monitor_last.json").read_text())
    assert receipt["status"] == "failed" and receipt["summary"]["failures"] >= 1
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["failures"] >= 1 and report["dry_run"] is False

    # negative control: the SAME still-bad warn band is delivered once transport works, not suppressed as "ongoing"
    monkeypatch.setattr(DMON, "default_notify",
                        lambda text, priority: (mon.sends.append((text, priority)), "accepted")[1])
    assert _run(mon, apply=True, used=86.0, hours=1.0) == 0
    assert len(mon.sends) == 1 and "WARN" in mon.sends[0][0]
    # accepted: the condition is now recorded, so the next still-warn run stays quiet (no heartbeat)
    assert DMON._load_condition(mon.alert).get(DMON.condition_key("/", "used")) is not None
    assert _run(mon, apply=True, used=87.0, hours=1.0) == 0
    assert len(mon.sends) == 1


def test_a_condition_store_write_failure_fails_the_run(mon, capsys):
    """A condition store that cannot be written must make the run fail, not silently succeed with no alert."""
    assert _run(mon, apply=True, used=50.0) == 0  # seed (the first run observes nothing)
    capsys.readouterr()
    bad = mon.state / "store_is_a_dir"
    bad.mkdir()  # os.replace() onto a directory raises: the condition store cannot be written
    mon.alert = bad
    assert _run(mon, apply=True, used=92.0, hours=1.0) == 1  # measured CRITICAL, store unwritable
    assert mon.sends == []  # observe never returned notify=True, so no alert was attempted
    receipt = json.loads((mon.state / "data" / "runtime" / "disk-monitor_last.json").read_text())
    assert receipt["status"] == "failed" and receipt["summary"]["failures"] >= 1
    # the REPORTED run result carries the observation error beside the measured critical condition
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["failures"] >= 1
    assert report["mounts"][0]["used_band"] == "critical"
    assert report["degraded_hotspots"] == 0  # the alert was not suppressed by a measurement degradation


def test_a_writable_condition_store_alerts_the_critical_band(mon):
    """Negative control for the store-failure finding: a writable store lets the same critical reading alert."""
    assert _run(mon, apply=True, used=50.0) == 0  # seed
    assert _run(mon, apply=True, used=92.0, hours=1.0) == 0
    assert len(mon.sends) == 1 and mon.sends[0][1] == "P1" and "CRITICAL" in mon.sends[0][0]
    receipt = json.loads((mon.state / "data" / "runtime" / "disk-monitor_last.json").read_text())
    assert receipt["status"] == "ok"


def test_a_rejected_mount_notification_fails_the_run(mon, monkeypatch):
    """CX1: send_telegram() returning False is a rejected alert, not a healthy run."""
    assert _run(mon, apply=True, used=50.0) == 0  # seed
    monkeypatch.setattr(DMON, "default_notify", lambda text, priority: "send_returned_false")
    assert _run(mon, apply=True, used=85.0, hours=1.0) == 1
    receipt = json.loads((mon.state / "data" / "runtime" / "disk-monitor_last.json").read_text())
    assert receipt["status"] == "failed"


def test_a_rejected_hotspot_notification_fails_the_run(mon, monkeypatch):
    """CX1: the hotspot branch has the same rule."""
    mon.doc["hotspots"] = [{"id": "cache", "path": "~/.cache", "purge": "rule C"}]
    mon.cfg.write_text(json.dumps(mon.doc, indent=1))
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: 0)
    assert _run(mon, apply=True, used=50.0) == 0  # seed at 0 bytes
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: 10 * GIB)
    monkeypatch.setattr(DMON, "default_notify", lambda text, priority: "send_returned_false")
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 1
    receipt = json.loads((mon.state / "data" / "runtime" / "disk-monitor_last.json").read_text())
    assert receipt["status"] == "failed"


def test_an_unwritable_receipt_fails_the_run(mon, capsys):
    """A durable receipt that cannot be written must fail the run instead of passing with stale/missing evidence."""
    target = mon.state / "data" / "runtime" / "disk-monitor_last.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()  # os.replace() onto a directory raises: the receipt target cannot be written
    assert _run(mon, apply=True, used=50.0) == 1
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["failures"] >= 1
    assert report["error"] == "lane_receipt_write_failed"
    assert report["dry_run"] is False


def test_a_writable_receipt_is_written_and_the_run_succeeds(mon):
    """Negative control for the receipt finding: the healthy apply path writes its receipt and exits 0."""
    assert _run(mon, apply=True, used=50.0) == 0
    receipt = json.loads((mon.state / "data" / "runtime" / "disk-monitor_last.json").read_text())
    assert receipt["status"] == "ok" and receipt["lane_id"] == "disk-monitor"


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
    mon_cfg = {"growth_window_hours": 24, "warn_pct": 80.0, "critical_pct": 90.0,
               "grow_warn_bytes": 10 ** 18, "grow_critical_bytes": 10 ** 18}
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


def test_an_unchanged_band_never_heartbeats(mon):
    """CX2: transition-only means an unchanged warn band stays silent however long it has been bad, in both
    apply and dry-run (the config no longer carries a heartbeat interval)."""
    assert "realert_minutes" not in json.loads(mon.cfg.read_text())
    assert _run(mon, apply=True, used=85.0) == 0  # seed; the first run sends nothing
    assert mon.sends == []
    old = (datetime.now(timezone.utc) - timedelta(minutes=600)).isoformat()
    key = DMON.condition_key("/", "used")
    mon.alert.write_text(json.dumps({"conditions": {
        key: {"state": "warn", "alertable": True, "last_notify_at": old, "first_seen_at": old}}}))
    assert _run(mon, apply=True, used=86.0, hours=1.0) == 0
    assert mon.sends == []  # 10 hours unchanged: no heartbeat re-alert
    assert _run(mon, apply=False, used=86.0, hours=1.0) == 0
    assert mon.sends == []  # dry-run predicts the same silence


def test_hotspot_recovery_clears_the_condition_so_a_later_growth_alerts_again(mon, monkeypatch):
    """CX4: an ok observation resolves the stored condition; without it the second growth episode is an
    "ongoing" unchanged state and is suppressed."""
    mon.doc["hotspots"] = [{"id": "cache", "path": "~/.cache", "purge": "rule C"}]
    mon.cfg.write_text(json.dumps(mon.doc, indent=1))
    size = {"now": 0}
    monkeypatch.setattr(DMON, "du_bytes", lambda path, timeout: size["now"])
    assert _run(mon, apply=True, used=50.0) == 0  # seed baseline at 0
    size["now"] = 10 * GIB
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 0
    assert len(mon.sends) == 1  # growth episode 1
    size["now"] = 10 * GIB
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 0
    assert len(mon.sends) == 1  # healthy: recorded (alertable=False), no send
    size["now"] = 30 * GIB
    assert _run(mon, apply=True, used=50.0, hours=1.0) == 0
    assert len(mon.sends) == 2  # episode 2 alerts independently instead of being "ongoing"


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
    """The monitor is read-only: it must not import a network client, a broker or an order path.

    Cloud ticket at 8aaa00c45 asked for this to inspect IMPORTS rather than scan the source text, and it is right for
    two concrete reasons. A text scan fails a clean module that merely mentions one of these words — a comment, a log
    line, the word "schwab" in a docstring — so it punishes documentation. And it misses the shapes that actually
    import something: `import requests as r` still contains the word, but `from urllib.parse import urlparse` is only
    caught if you happen to ban the right substring, while a package reached through a helper or an alias is not
    caught at all.

    Parsing asks the only question that matters: what does this module bring into scope? A dynamic import is refused
    outright (`__import__`, `importlib.import_module`), because it would make the answer unknowable from the file —
    and this is the same lesson as AGENTS.md:484's "inspect the thing, not its spelling".
    """
    import ast

    tree = ast.parse((ROOT / "scripts" / "disk_monitor.py").read_text(encoding="utf-8"))
    banned = {"requests", "urllib", "urllib2", "urllib3", "http", "httpx", "aiohttp", "socket",
              "psycopg", "psycopg2", "psycopg3", "sqlalchemy"}
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Call):
            called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert called not in ("__import__", "import_module"), (
                f"dynamic import at line {node.lineno} — this check can no longer prove what the module imports")
    tops = {name.split(".")[0] for name in imported if name}
    assert not (tops & banned), f"the monitor imports a sender/network package: {sorted(tops & banned)}"
    broker = [name for name in imported if any(w in name.lower() for w in ("alpaca", "schwab", "moomoo", "broker"))]
    assert not broker, f"the monitor imports a broker package: {broker}"
    assert not any(name == "place_order" for name in imported), "the monitor imports an order path"


def test_a_four_hour_old_sample_is_not_reported_as_a_24_hour_rate():
    """Cloud ticket at 8aaa00c45: the reference sample is the earliest in the window, but the rate divided by the
    CONFIGURED window. A sample four hours old measures four hours of growth: 20 GiB there is 120 GiB/day, and
    "20 GiB/day over 24h" is an operator alert that says something false about the disk (D51)."""
    now = T0
    mon_cfg = {"growth_window_hours": 24, "warn_pct": 80.0, "critical_pct": 90.0,
               "grow_warn_bytes": 10 ** 18, "grow_critical_bytes": 10 ** 18}
    base = {"mounts": {"/": {"used_bytes": 100}}, "samples": [
        {"at": (now - timedelta(hours=4)).isoformat(), "mounts": {"/": 100}},
    ]}
    mounts = [{"mount": "/", "used_pct": 50.0, "used_bytes": 120.0, "avail_bytes": 80.0, "size_bytes": 200.0}]
    row = DMON.evaluate(base, mounts, [], mon_cfg, now)["mounts"][0]
    assert row["growth_interval_hours"] == 4.0, row["growth_interval_hours"]
    assert row["growth_interval_source"] == "sample", row["growth_interval_source"]
    assert row["rate_bytes_per_day"] == 120.0, row["rate_bytes_per_day"]   # 20 bytes / 4h * 24, not / 24h * 24


def test_the_rate_falls_back_to_the_window_only_when_no_sample_time_exists():
    """The baseline mount value carries no clock of its own: the configured window is then the only interval there
    is, and the row says so instead of pretending a sample supplied it."""
    now = T0
    mon_cfg = {"growth_window_hours": 24, "warn_pct": 80.0, "critical_pct": 90.0,
               "grow_warn_bytes": 10 ** 18, "grow_critical_bytes": 10 ** 18}
    base = {"mounts": {"/": {"used_bytes": 100}}, "samples": []}
    mounts = [{"mount": "/", "used_pct": 50.0, "used_bytes": 220.0, "avail_bytes": 80.0, "size_bytes": 200.0}]
    row = DMON.evaluate(base, mounts, [], mon_cfg, now)["mounts"][0]
    assert row["growth_interval_source"] == "window", row["growth_interval_source"]
    assert row["growth_interval_hours"] == 24.0
    assert row["rate_bytes_per_day"] == 120.0, row["rate_bytes_per_day"]   # 120 bytes over the 24h window


def test_an_unmeasured_size_is_not_printed_as_a_confident_zero():
    """tq taxonomy #2 at this module: `(n or 0)` printed an unmeasured directory as `0.0G`.

    A zero here is not "nothing there" — it is "we never got a size", and an alert that says 0.0G tells the operator a
    directory is empty when the `du` that would have measured it failed. The text must say what it does not know, and a
    real zero must still read as zero.
    """
    assert DMON._gb(None) == "size unknown"
    assert DMON._gb(0) == "0.0G"        # a measured zero IS a measurement
    assert DMON._gb(1024 ** 3) == "1.0G"
    assert DMON._gb_delta(None) == "change unknown"
    assert DMON._gb_delta(2 * 1024 ** 3) == "+2.0G"

    text = DMON.hotspot_alert_text(
        {"id": "hot", "bytes": None, "baseline_bytes": 5 * 1024 ** 3, "purge": "none"})
    assert "size unknown" in text and "change unknown" in text
    assert "0.0G" not in text, text

    # a hotspot with both ends measured still prints the numbers, so the guard did not swallow the real case
    measured = DMON.hotspot_alert_text(
        {"id": "hot", "bytes": 6 * 1024 ** 3, "baseline_bytes": 4 * 1024 ** 3, "purge": "none"})
    assert "6.0G" in measured and "+2.0G" in measured, measured
