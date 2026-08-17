"""Schwab Fernet key must resolve from stable fallbacks; never mint on reauth."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import broker_secrets as bs  # noqa: E402


def test_iter_prefers_stable_home(tmp_path, monkeypatch):
    stable = tmp_path / "stable.env"
    project = tmp_path / "project.env"
    stable.write_text("SCHWAB_TOKEN_ENC_KEY=stable-key-not-real\n")
    project.write_text("SCHWAB_TOKEN_ENC_KEY=project-key-not-real\n")
    monkeypatch.setattr(bs, "_STABLE", stable)
    monkeypatch.setattr(bs, "_PROJECT_SECRETS", project)
    monkeypatch.setattr(bs, "_CURRENT", tmp_path / "missing-current.env")
    monkeypatch.setattr(bs, "_CANONICAL", tmp_path / "missing-canon.env")
    found = bs.iter_secrets_files()
    assert found[0] == stable


def test_load_into_env_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / "creds.env"
    f.write_text("SCHWAB_TOKEN_ENC_KEY=from-file\n")
    monkeypatch.setattr(bs, "_STABLE", f)
    monkeypatch.setattr(bs, "_PROJECT_SECRETS", tmp_path / "nope")
    monkeypatch.setattr(bs, "_CURRENT", tmp_path / "nope")
    monkeypatch.setattr(bs, "_CANONICAL", tmp_path / "nope")
    monkeypatch.setattr(bs, "_loaded", False)
    monkeypatch.setenv("SCHWAB_TOKEN_ENC_KEY", "already-set")
    applied = bs.load_into_env(force=True)
    assert applied == 0
    assert __import__("os").environ["SCHWAB_TOKEN_ENC_KEY"] == "already-set"


def test_load_into_env_from_fallback(tmp_path, monkeypatch):
    f = tmp_path / "creds.env"
    f.write_text("SCHWAB_TOKEN_ENC_KEY=from-file-only\n")
    monkeypatch.setattr(bs, "_STABLE", tmp_path / "no-stable")
    monkeypatch.setattr(bs, "_PROJECT_SECRETS", tmp_path / "no-project")
    monkeypatch.setattr(bs, "_CURRENT", tmp_path / "no-current")
    monkeypatch.setattr(bs, "_CANONICAL", f)
    monkeypatch.setattr(bs, "_loaded", False)
    monkeypatch.delenv("SCHWAB_TOKEN_ENC_KEY", raising=False)
    applied = bs.load_into_env(force=True)
    assert applied == 1
    assert __import__("os").environ.get("SCHWAB_TOKEN_ENC_KEY") == "from-file-only"
    monkeypatch.delenv("SCHWAB_TOKEN_ENC_KEY", raising=False)


def test_missing_file_applies_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_STABLE", tmp_path / "a")
    monkeypatch.setattr(bs, "_PROJECT_SECRETS", tmp_path / "b")
    monkeypatch.setattr(bs, "_CURRENT", tmp_path / "c")
    monkeypatch.setattr(bs, "_CANONICAL", tmp_path / "d")
    monkeypatch.setattr(bs, "_loaded", False)
    monkeypatch.delenv("SCHWAB_TOKEN_ENC_KEY", raising=False)
    assert bs.iter_secrets_files() == []
    assert bs.load_into_env(force=True) == 0
    assert not __import__("os").environ.get("SCHWAB_TOKEN_ENC_KEY")


def test_deploy_script_links_broker_credentials():
    src = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text()
    assert "broker_credentials.env" in src
    assert ".config/tradeai/broker_credentials.env" in src
    assert "init-key" not in src.split("link_pipeline_data")[1][:2000]
