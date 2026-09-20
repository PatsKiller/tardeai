"""gap_resolver.live_armed host-file arm (no crontab edit)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_live_armed_env_dict_is_hermetic(tmp_path, monkeypatch):
    from scripts.lib import gap_resolver as gr

    monkeypatch.setattr(gr, "HOST_FLAG_PATH", tmp_path / "gap_resolver_live")
    gr.HOST_FLAG_PATH.write_text("1\n", encoding="utf-8")
    assert gr.live_armed({}) is False
    assert gr.live_armed({gr.FLAG_LIVE: "1"}) is True
    assert gr.live_armed({gr.FLAG_LIVE: "0"}) is False


def test_live_armed_host_file_when_env_omitted(tmp_path, monkeypatch):
    from scripts.lib import gap_resolver as gr

    monkeypatch.setattr(gr, "HOST_FLAG_PATH", tmp_path / "gap_resolver_live")
    monkeypatch.delenv(gr.FLAG_LIVE, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    gr.HOST_FLAG_PATH.write_text("on\n", encoding="utf-8")
    assert gr.live_armed() is True
    gr.HOST_FLAG_PATH.write_text("0\n", encoding="utf-8")
    assert gr.live_armed() is False


def test_live_armed_ignores_host_under_pytest(tmp_path, monkeypatch):
    from scripts.lib import gap_resolver as gr

    monkeypatch.setattr(gr, "HOST_FLAG_PATH", tmp_path / "gap_resolver_live")
    monkeypatch.delenv(gr.FLAG_LIVE, raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_live_armed_ignores_host_under_pytest")
    gr.HOST_FLAG_PATH.write_text("1\n", encoding="utf-8")
    assert gr.live_armed() is False
