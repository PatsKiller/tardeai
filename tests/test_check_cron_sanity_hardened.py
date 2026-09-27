"""Cron sanity must not warn when crontab -l is blocked by systemd hardening."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_cron_sanity as ccs  # noqa: E402


def test_permission_denied_without_snapshot_is_a_warning_that_checks_did_not_run(monkeypatch, tmp_path):
    """R-03 (2026-09-26): this used to be `info` — which is how a dead cron, a stale
    cron and the P1 scheduler defects stayed invisible for weeks. With no readable
    crontab AND no fresh snapshot the checks did not run, and that is a warning."""
    def fake_run(*a, **k):
        return SimpleNamespace(returncode=1, stdout="", stderr="crontabs/johnclaw/: fopen: Permission denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("TRADEAI_CRONTAB_SNAPSHOT_PATH", str(tmp_path / "absent.txt"))
    findings = ccs.check()
    assert len(findings) == 1
    assert findings[0]["type"] == "cron_sanity_check_hardened"
    assert findings[0]["severity"] == "warning"
    assert "SNAPSHOT_CRON_LINE" in findings[0]["message"]
