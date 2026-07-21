#!/usr/bin/env python3
"""S3 tests: render formatting, skip BWS_*, last-known-good on failure."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))
sys.path.insert(0, str(ROOT / "scripts"))

import render_env as re  # noqa: E402


def test_format_env_quotes_special():
    text = re._format_env({"A": "plain", "B": "has;semi"})
    assert "A=plain" in text
    assert "B='has;semi'" in text


def test_hashes_stable():
    h1 = re._hashes({"K": "v1"})
    h2 = re._hashes({"K": "v1"})
    h3 = re._hashes({"K": "v2"})
    assert h1 == h2 and h1["K"] != h3["K"]


def test_render_uses_last_known_good(tmp_path, monkeypatch):
    runtime = tmp_path / "tradeai"
    runtime.mkdir()
    envp = runtime / "env"
    envp.write_text("FOO=bar\n")
    monkeypatch.setattr(re, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(re, "RENDER_PATH", envp)
    monkeypatch.setattr(re, "MANIFEST_PATH", runtime / "manifest.json")
    monkeypatch.setattr(re, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(re, "DISK_ENV", tmp_path / "missing.env")
    monkeypatch.setattr(re, "_token", lambda: "tok")
    monkeypatch.setattr(re, "_fetch_secrets", mock.Mock(side_effect=RuntimeError("bw down")))
    monkeypatch.setattr(re, "_telegram", mock.Mock())
    r = re.render(force=True)
    assert r["ok"] is True
    assert r["source"] == "last_known_good"
    assert envp.read_text() == "FOO=bar\n"  # not deleted
    re._telegram.assert_called()


def test_fetch_skips_bws_keys(monkeypatch):
    monkeypatch.setattr(re, "_project_id", lambda t: "pid")
    def fake_bws(args, token):
        class R:
            returncode = 0
            stdout = json.dumps([
                {"key": "DB_HOST", "value": "localhost", "projectId": "pid"},
                {"key": "BWS_READ_TOKEN", "value": "0.should.not", "projectId": "pid"},
            ])
            stderr = ""
        return R()
    monkeypatch.setattr(re, "_bws", fake_bws)
    out = re._fetch_secrets("tok")
    assert "DB_HOST" in out
    assert "BWS_READ_TOKEN" not in out
