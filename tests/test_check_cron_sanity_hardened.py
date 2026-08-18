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


def test_permission_denied_is_info_not_warning(monkeypatch):
    def fake_run(*a, **k):
        return SimpleNamespace(returncode=1, stdout="", stderr="crontabs/johnclaw/: fopen: Permission denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    findings = ccs.check()
    assert len(findings) == 1
    assert findings[0]["type"] == "cron_sanity_check_hardened"
    assert findings[0]["severity"] == "info"
