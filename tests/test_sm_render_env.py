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


def test_render_rolls_replaced_overlap_values_and_keeps_them_on_rerender(tmp_path, monkeypatch):
    old_bearer = "oldbeareroldbeareroldbearerold12"
    new_bearer = "newbearernewbearernewbearernew12"
    old_hmac = "oldhmacoldhmacoldhmacoldhmacold1"
    new_hmac = "newhmacnewhmacnewhmacnewhmacnew1"
    runtime = tmp_path / "rt"
    runtime.mkdir()
    envp = runtime / "env"
    envp.write_text(
        "OTHER=1\n"
        f"TRADEAI_N8N_RELAY_BEARER={old_bearer}\n"
        f"TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N={old_hmac}\n"
    )
    manifest = runtime / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "shell_keys": [
                    "OTHER",
                    "TRADEAI_N8N_RELAY_BEARER",
                    "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N",
                ]
            }
        )
    )
    monkeypatch.setattr(re, "RENDER_PATH", envp)
    monkeypatch.setattr(re, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(re, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(re, "DISK_ENV", tmp_path / "missing.env")
    monkeypatch.setattr(re, "_token", lambda: "tok")
    monkeypatch.setattr(re, "_telegram", lambda _msg: None)
    monkeypatch.setattr(
        re,
        "_fetch_secrets",
        lambda _tok: {
            "OTHER": "1",
            "TRADEAI_N8N_RELAY_BEARER": new_bearer,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": new_hmac,
        },
    )
    first = re.render()
    assert first["ok"] is True
    text = envp.read_text(encoding="utf-8")
    assert f"TRADEAI_N8N_RELAY_BEARER={new_bearer}\n" in text
    assert f"TRADEAI_N8N_RELAY_BEARER_PREVIOUS={old_bearer}\n" in text
    assert f"TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS={old_hmac}\n" in text
    assert old_bearer not in json.dumps(first)
    written = json.loads(manifest.read_text(encoding="utf-8"))
    assert "TRADEAI_N8N_RELAY_BEARER_PREVIOUS" not in written["shell_keys"]
    assert "TRADEAI_N8N_RELAY_BEARER_PREVIOUS" in written["overlap_previous"]
    second = re.render()
    assert second["ok"] is True
    kept = envp.read_text(encoding="utf-8")
    assert f"TRADEAI_N8N_RELAY_BEARER_PREVIOUS={old_bearer}\n" in kept
    assert "SM_KEYS_DISAPPEARED" not in json.dumps(second)


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
