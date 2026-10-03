"""Auto-approver survives a dropped DB connection; market_day_gate actually runs its check.

2026-10-02 14:40-16:00 ET, atm.log: psycopg2.InterfaceError "connection already
closed" at _count_positions killed whole cycles. The cycle held the connection
it got at start while db_adapter only self-heals on get_connection(). The same
log showed market_day_gate failing open on every run: release dirs have no
.venv/bin/python, so the session check never executed.

Pure: fake driver module, fake connections, no DB, no broker, no network.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import atm_auto_approver as atm  # noqa: E402


class _Dropped(Exception):
    pass


@pytest.fixture
def fake_driver(monkeypatch):
    mod = types.ModuleType("psycopg2")
    mod.InterfaceError = _Dropped
    mod.OperationalError = type("OperationalError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "psycopg2", mod)
    return mod


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, *_a, **_k):
        if self.conn.dead:
            raise _Dropped("connection already closed")

    def fetchone(self):
        return (self.conn.count,)


class _Conn:
    def __init__(self, count: int, dead: bool = False):
        self.count, self.dead = count, dead

    def cursor(self):
        return _Cursor(self)


def test_dropped_connection_reconnects_and_reads_real_counts(fake_driver, monkeypatch):
    fresh = _Conn(count=2)
    monkeypatch.setattr(atm, "get_connection", lambda: fresh)
    conn, pos_open, pos_total, new_today, new_total = atm._read_position_counts(
        _Conn(count=99, dead=True), "acct_a", ["acct_a", "acct_b"])
    assert conn is fresh
    assert (pos_open, pos_total, new_today, new_total) == (2, 4, 2, 4)


def test_unreadable_counts_abort_instead_of_reading_zero(fake_driver, monkeypatch):
    monkeypatch.setattr(atm, "get_connection", lambda: _Conn(count=0, dead=True))
    with pytest.raises(atm.PositionCountsUnavailable):
        atm._read_position_counts(_Conn(count=0, dead=True), "acct_a", ["acct_a"])


def test_no_connection_after_drop_aborts(fake_driver, monkeypatch):
    monkeypatch.setattr(atm, "get_connection", lambda: None)
    with pytest.raises(atm.PositionCountsUnavailable):
        atm._read_position_counts(_Conn(count=1, dead=True), "acct_a", ["acct_a"])


def test_cycle_refreshes_connection_per_proposal_and_fails_closed():
    src = (ROOT / "scripts" / "atm_auto_approver.py").read_text()
    loop = src[src.index("    for p in proposals:"):]
    head = loop[:loop.index('pid = p["id"]')]
    assert "conn = get_connection()" in head
    assert "except PositionCountsUnavailable" in loop
    abort = loop[loop.index("except PositionCountsUnavailable"):]
    assert "break" in "\n".join(abort.split("\n")[:6])


def _release_dir(tmp_path: Path, trading_day: bool) -> Path:
    rel = tmp_path / "release"
    (rel / "scripts").mkdir(parents=True)
    (rel / "scripts" / "market_day_gate.sh").write_text(
        (ROOT / "scripts" / "market_day_gate.sh").read_text(), encoding="utf-8")
    (rel / "scripts" / "market_session.py").write_text(
        f"def is_trading_day():\n    return {trading_day}\n\n"
        "def current_market_session():\n    return 'weekend'\n", encoding="utf-8")
    return rel


def _gate(rel: Path, tmp_path: Path, *job: str, env_extra: dict | None = None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path / "nohome")}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(rel / "scripts" / "market_day_gate.sh"), *job],
                          capture_output=True, text=True, env=env, timeout=30)


def test_gate_runs_the_check_from_a_release_dir_without_venv(tmp_path):
    rel = _release_dir(tmp_path, trading_day=False)
    marker = tmp_path / "ran"
    out = _gate(rel, tmp_path, sys.executable, "-c", f"open({str(marker)!r}, 'w').write('x')")
    assert "skipped: weekend" in out.stdout
    assert "session check FAILED" not in out.stdout
    assert not marker.exists()


def test_gate_runs_the_job_on_a_trading_day(tmp_path):
    rel = _release_dir(tmp_path, trading_day=True)
    marker = tmp_path / "ran"
    out = _gate(rel, tmp_path, sys.executable, "-c", f"open({str(marker)!r}, 'w').write('x')")
    assert out.returncode == 0, out.stdout + out.stderr
    assert marker.exists()


def test_gate_falls_back_to_python3_when_the_job_is_not_python(tmp_path):
    rel = _release_dir(tmp_path, trading_day=False)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python3").symlink_to(sys.executable)
    out = _gate(rel, tmp_path, "echo", "JOB RAN",
                env_extra={"PATH": f"{bindir}:/usr/bin:/bin"})
    assert "skipped: weekend" in out.stdout
    assert "JOB RAN" not in out.stdout
