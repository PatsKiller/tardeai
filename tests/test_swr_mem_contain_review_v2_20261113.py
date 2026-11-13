"""MEM-CONTAIN v2 independent review (REWORK, 2026-11-13): regression tests for NB1, NB2, C1 and C5.
Adapted from the reviewer's findings file. Synthetic keys, pids and payloads only; nothing is ever signalled."""
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from scripts.lib import shared_get_swr as swr

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "portfolio_server_watchdog.sh"
FAKE_PID = "2147483000"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("SWR_SLOT_DIR", "SWR_BUILD_LEASE_S", "SWR_MAX_CONCURRENT_BUILDS", "SWR_MAX_ABANDONED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (None, None))
    swr.clear()
    yield
    swr.clear()


def _hang(gate, counter):
    def build():
        counter.append(1)
        gate.wait(10)
        return {"ok": True}
    return build


# ── NB1 / F1: an expired lease never lets a second build of the same key start ─────────────────────────────
def test_same_key_is_never_built_twice_after_lease_expiry(monkeypatch):
    monkeypatch.setenv("SWR_BUILD_LEASE_S", "0.1")
    gate, calls = threading.Event(), []
    try:
        for _ in range(6):
            swr.get("dup", 60, _hang(gate, calls))
            time.sleep(0.15)
        assert len(calls) == 1, f"{len(calls)} builds of one key"
    finally:
        gate.set()


# ── NB1 / F1b: abandoned (lease-expired, still running) builds stay bounded ─────────────────────────────────
def test_abandoned_builds_are_bounded(monkeypatch):
    monkeypatch.setenv("SWR_BUILD_LEASE_S", "0.1")
    gate, calls = threading.Event(), []
    try:
        for i in range(10):
            swr.get(f"k{i % 2}", 60, _hang(gate, calls))
            swr.get(f"x{i}", 60, _hang(gate, calls))
            time.sleep(0.15)
        st = swr.stats()
        assert st["abandoned_builds"] <= swr.max_abandoned() == 2
        assert len(calls) <= swr.max_concurrent_builds() + swr.max_abandoned()
    finally:
        gate.set()


def test_abandon_limit_keeps_cap_and_logs(monkeypatch, capsys):
    monkeypatch.setenv("SWR_BUILD_LEASE_S", "0.05")
    monkeypatch.setenv("SWR_MAX_ABANDONED", "0")
    gate, calls = threading.Event(), []
    try:
        swr.get("a", 60, _hang(gate, calls))
        swr.get("b", 60, _hang(gate, calls))
        time.sleep(0.1)
        out = swr.get("c", 60, _hang(gate, calls))
        assert out.get("build_refused") == "REFUSED_CAP"  # expired builds were NOT reaped: they still hold the cap
        assert len(calls) == 2 and swr.stats()["abandoned_builds"] == 0
        # Review v2c T2 (mutant NB1-i): the limit state is loud, never silent.
        assert '"outcome": "ABANDONED_LEASE_LIMIT"' in capsys.readouterr().out
    finally:
        gate.set()


# ── NB2 / F2 and C5: watchdog fixture ───────────────────────────────────────────────────────────────────────
def _stub(d, name, body):
    p = d / name
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(0o755)


def _env(tmp_path, active="active", rc=0):
    stub = tmp_path / "bin"
    stub.mkdir()
    rec = tmp_path / "calls.log"
    _stub(stub, "curl", f'echo "curl $*" >> "{rec}"; exit 7')
    _stub(stub, "pgrep", f'echo "pgrep $*" >> "{rec}"; echo {FAKE_PID}')
    _stub(stub, "systemctl", f'echo "systemctl $*" >> "{rec}"; case "$*" in *is-active*) echo {active}; exit {rc};; '
                              f'*ControlGroup*) echo ""; exit 0;; esac; exit 0')
    _stub(stub, "sleep", f'echo "sleep $*" >> "{rec}"; exit 0')
    _stub(stub, "fake_kill", f'echo "kill $*" >> "{rec}"; [ "$1" = "-0" ] && exit 1; exit 0')
    logs = tmp_path / "logs"
    logs.mkdir()
    e = dict(os.environ)
    e.update({"PATH": f"{stub}:{os.environ.get('PATH', '/usr/bin:/bin')}",
              "PORTFOLIO_WATCHDOG_URL": "http://127.0.0.1:9/fake-health",
              "PORTFOLIO_WATCHDOG_LOG": str(logs / "wd.log"),
              "PORTFOLIO_WATCHDOG_PROC": "fake_portfolio_server_for_test.py",
              "PORTFOLIO_WATCHDOG_KILL_CMD": str(stub / "fake_kill"),
              "PORTFOLIO_WATCHDOG_VERIFY_SEC": "1",
              "PORTFOLIO_WATCHDOG_KILL_COOLDOWN_S": "0",
              "XDG_RUNTIME_DIR": str(tmp_path / "run"),
              "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"})
    return e, rec, logs


def _kills(rec):
    return sum(1 for c in (rec.read_text().splitlines() if rec.exists() else []) if c.startswith("kill -TERM"))


def test_unwritable_kill_state_never_kills(tmp_path):
    e, rec, logs = _env(tmp_path)
    ro = tmp_path / "ro"
    ro.mkdir()
    e["PORTFOLIO_WATCHDOG_KILL_STATE"] = str(ro / "kills")
    ro.chmod(0o555)
    try:
        if os.access(ro, os.W_OK):
            pytest.skip("running as a user that ignores directory permissions")
        for _ in range(4):
            cp = subprocess.run(["/bin/bash", str(SH)], env=e, capture_output=True, text=True, timeout=60)
            assert cp.returncode == 0, cp.stderr
    finally:
        ro.chmod(0o755)
    assert _kills(rec) == 0
    assert "KILL_STATE unwritable" in (logs / "wd.log").read_text()
    # Review v2c T1 (mutant WD-k): a refused kill escalates durably, with the true reason, one FINDING not one per run.
    import json
    recs = [json.loads(x) for x in (logs / "watchdog_escalations.jsonl").read_text().splitlines()]
    assert len(recs) == 4 and all(r["reason"] == "kill_state_unwritable" for r in recs)
    findings = list(logs.glob("FINDING-portfolio-server-watchdog-ESCALATE-*.md"))
    assert len(findings) == 1 and "kill_state_unwritable" in findings[0].read_text()
    assert "reached the cap" not in findings[0].read_text()


def test_orphan_branch_honours_the_kill_budget(tmp_path):
    e, rec, logs = _env(tmp_path, active="inactive", rc=3)
    now = int(time.time())
    (logs / ".portfolio_server_watchdog_kills").write_text("".join(f"{now - s}\n" for s in (100, 600, 1200)))
    cp = subprocess.run(["/bin/bash", str(SH)], env=e, capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, cp.stderr
    assert _kills(rec) == 0
    assert "ESCALATE" in (logs / "wd.log").read_text()
    assert '"reason": "kill_cap"' in (logs / "watchdog_escalations.jsonl").read_text()


# ── C1 / F3: a stop decision is never assembled from stale risk ──────────────────────────────────────────────
@pytest.mark.parametrize("extra", [{"stale": True, "age_s": 7200}, {"age_s": 601}, {"stale": True}])
def test_stale_risk_is_unknown_for_stop_alerts(monkeypatch, extra):
    import stop_alert_assembler as saa
    data = {"positions": [{"symbol": "SYNTH", "status": "TRIGGERED", "current_price": 1, "stop_price": 2}], **extra}
    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": data} if p == "/api/v2/risk" else {})
    out = saa.assemble_stop_alert_data("SYNTH")
    assert out is not None and out["status"] == "UNKNOWN" and out.get("stale") is True and "stale" in out["reason"]


def test_fresh_risk_still_assembles(monkeypatch):
    import stop_alert_assembler as saa
    data = {"positions": [{"symbol": "SYNTH", "status": "TRIGGERED", "current_price": 1, "stop_price": 2}],
            "stale": True, "age_s": 30}
    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": data} if p == "/api/v2/risk" else {})
    out = saa.assemble_stop_alert_data("SYNTH")
    assert out is not None and out.get("status") != "UNKNOWN"


# ── 3034b review A5: an OSError while taking a slot never leaks the key lock ───────────────────────────────────────
def test_slot_oserror_releases_the_key_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("SWR_SLOT_DIR", str(tmp_path / "slots"))
    real = swr._flock_nb

    def flaky(path):
        if "slot-" in path:
            raise OSError("synthetic slot failure")
        return real(path)
    monkeypatch.setattr(swr, "_flock_nb", flaky)
    assert swr.acquire_host_slots("k-a5", 2) == ([], None)  # fails open to the per-process cap
    monkeypatch.setattr(swr, "_flock_nb", real)
    fds, why = swr.acquire_host_slots("k-a5", 2)
    try:
        assert why is None and fds, f"key lock leaked: {why}"
    finally:
        swr.release_slots(fds or [])
