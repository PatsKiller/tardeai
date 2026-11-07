"""LQ-20261107-261: the scope-governor crontab reader falls back to the cron snapshot.

Under the hardened health agent (NoNewPrivileges) `crontab -l` and the spool are
both denied. Before this fix `_crontab_text()` returned "" in that case and the
health check failed open ("Could not read crontab this cycle"), even though the
cron-written snapshot (lib.crontab_snapshot) was fresh.

Fixtures are synthetic: no real crontab, paths or credentials are read.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.hermes_scope_governor.health as H  # noqa: E402

SYNTHETIC_CRONTAB = (
    "# synthetic fixture\n"
    "0 3 * * * cd $PROJ && flock -n /tmp/fixture.lock $PY scripts/hermes_scope_governor.py --apply\n"
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # No spool file for this synthetic user; clear the 90 s cache between tests.
    monkeypatch.setenv("USER", "lq261-no-such-user")
    H._CRONTAB_CACHE.clear()
    yield
    H._CRONTAB_CACHE.clear()


def _deny_crontab(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="crontab: Permission denied")
    monkeypatch.setattr(H.subprocess, "run", fake_run)


def test_denied_crontab_uses_fresh_snapshot(monkeypatch, tmp_path):
    snap = tmp_path / "crontab_snapshot.txt"
    snap.write_text(SYNTHETIC_CRONTAB, encoding="utf-8")
    monkeypatch.setenv("TRADEAI_CRONTAB_SNAPSHOT_PATH", str(snap))
    _deny_crontab(monkeypatch)
    text = H._crontab_text()
    assert "hermes_scope_governor.py --apply" in text
    assert H._crontab_has_script_apply(text, "hermes_scope_governor.py")


def test_denied_crontab_with_no_snapshot_still_fails_open(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_CRONTAB_SNAPSHOT_PATH", str(tmp_path / "missing.txt"))
    _deny_crontab(monkeypatch)
    assert H._crontab_text().strip() == ""


def test_stale_snapshot_is_not_used(monkeypatch, tmp_path):
    import os
    import time

    snap = tmp_path / "crontab_snapshot.txt"
    snap.write_text(SYNTHETIC_CRONTAB, encoding="utf-8")
    old = time.time() - 3 * 3600
    os.utime(snap, (old, old))
    monkeypatch.setenv("TRADEAI_CRONTAB_SNAPSHOT_PATH", str(snap))
    _deny_crontab(monkeypatch)
    assert H._crontab_text().strip() == ""


def test_live_crontab_is_preferred_over_snapshot(monkeypatch, tmp_path):
    snap = tmp_path / "crontab_snapshot.txt"
    snap.write_text("# stale copy\n", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_CRONTAB_SNAPSHOT_PATH", str(snap))

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=SYNTHETIC_CRONTAB, stderr="")
    monkeypatch.setattr(H.subprocess, "run", fake_run)
    assert "hermes_scope_governor.py --apply" in H._crontab_text()
