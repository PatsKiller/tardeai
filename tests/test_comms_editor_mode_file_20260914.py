"""The Comms Editor mode reaches every sender: environment first, then one host mode file.

2026-09-14: most Telegram senders are cron jobs that never load an env file, so an environment variable
alone would have put only some processes in shadow mode. Offline: temp files, env patched.
"""
from __future__ import annotations

import scripts.lib.comms_editor as ce

COVERS = ["scripts/lib/comms_editor.py"]


def test_environment_wins(monkeypatch, tmp_path):
    f = tmp_path / "mode"
    f.write_text("live\n")
    monkeypatch.setenv("COMMS_EDITOR_MODE_FILE", str(f))
    monkeypatch.setenv("COMMS_EDITOR_MODE", "shadow")
    assert ce.mode() == "shadow"


def test_host_file_applies_when_the_environment_is_silent(monkeypatch, tmp_path):
    f = tmp_path / "mode"
    f.write_text("shadow\n# reviewed after one trading day\n")
    monkeypatch.delenv("COMMS_EDITOR_MODE", raising=False)
    monkeypatch.setenv("COMMS_EDITOR_MODE_FILE", str(f))
    assert ce.mode() == "shadow"


def test_missing_or_garbled_file_means_off(monkeypatch, tmp_path):
    monkeypatch.delenv("COMMS_EDITOR_MODE", raising=False)
    monkeypatch.setenv("COMMS_EDITOR_MODE_FILE", str(tmp_path / "absent"))
    assert ce.mode() == "off"
    bad = tmp_path / "bad"
    bad.write_text("maybe\n")
    monkeypatch.setenv("COMMS_EDITOR_MODE_FILE", str(bad))
    assert ce.mode() == "off"
