#!/usr/bin/env python3
"""PR4 — pipeline hook + market-hours gating tests.

    .venv/bin/python -m pytest tests/test_options_paper_monitor_ops.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import paper_monitor_ops as ops  # noqa: E402


def test_should_run_lifecycle_disabled():
    ok, reason = ops.should_run_lifecycle({"enabled": False})
    assert not ok and reason == "disabled in config"


def test_should_run_lifecycle_market_hours(monkeypatch):
    monkeypatch.setattr(ops, "is_market_hours", lambda: True)
    ok, reason = ops.should_run_lifecycle({"enabled": True})
    assert ok and reason == "market_hours"


def test_should_run_lifecycle_after_hours_snapshot(monkeypatch):
    monkeypatch.setattr(ops, "is_market_hours", lambda: False)
    ok, reason = ops.should_run_lifecycle({"enabled": True, "after_hours_snapshot": True})
    assert ok and reason == "after_hours_snapshot"


def test_should_run_lifecycle_after_hours_skipped(monkeypatch):
    monkeypatch.setattr(ops, "is_market_hours", lambda: False)
    ok, reason = ops.should_run_lifecycle({"enabled": True, "after_hours_snapshot": False})
    assert not ok and reason == "after_hours_skipped"


def test_run_pipeline_hook_skips_when_after_hours(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "RUNTIME_PATH", tmp_path / "last.json")
    monkeypatch.setattr(ops, "is_market_hours", lambda: False)
    out = ops.run_pipeline_hook(cfg={"enabled": True, "after_hours_snapshot": False})
    assert out["skipped"] and out["reason"] == "after_hours_skipped"
    assert (tmp_path / "last.json").exists()


def test_run_pipeline_hook_calls_monitor(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "RUNTIME_PATH", tmp_path / "last.json")
    monkeypatch.setattr(ops, "is_market_hours", lambda: True)
    monkeypatch.setattr(
        "lib.options_pipeline.paper_position_monitor.run_monitor",
        lambda **k: {"ok": True, "count": 2, "monitored": []})
    out = ops.run_pipeline_hook(cfg={"enabled": True})
    assert out["count"] == 2
    saved = json.loads((tmp_path / "last.json").read_text(encoding="utf-8"))
    assert saved["pipeline_reason"] == "market_hours"


def test_install_script_exists_and_executable():
    path = ROOT / "scripts" / "install_options_paper_monitor_cron.sh"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "options-paper-lifecycle-cron" in text
    assert "run_options_paper_position_monitor.sh" in text
    assert "DB_HOST" in text or "DB_PASSWORD" in text