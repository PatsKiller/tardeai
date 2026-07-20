#!/usr/bin/env python3
"""Pipeline-stage failures must be loud, durable and visible in the exit code.

Before 2026-07-20 every stage was `except Exception as e: print(f"[x] ❌ {e}")`.
That discarded the traceback, produced an empty line for exceptions with no
message, and left no durable signal — the covered-call dashboard section
vanished for an unknown number of days with no alert.

Pure tests: no network, no broker, no pipeline run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_orchestrator as po  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    po._STAGE_FAILURES.clear()
    yield
    po._STAGE_FAILURES.clear()


def test_failure_records_exception_type_not_just_message():
    """str(KeyError('iv')) is just the key — the TYPE is what identifies it."""
    try:
        raise KeyError("iv")
    except Exception as e:
        po._stage_failed("options", e)
    f = po._STAGE_FAILURES[0]
    assert f["stage"] == "options"
    assert f["error_type"] == "KeyError"


def test_empty_message_exception_is_still_legible():
    """RuntimeError('') used to print '❌ ' and convey nothing."""
    try:
        raise RuntimeError("")
    except Exception as e:
        po._stage_failed("tax", e)
    f = po._STAGE_FAILURES[0]
    assert f["error"] == "(no message)"
    assert f["error_type"] == "RuntimeError"


def test_traceback_is_captured():
    try:
        {}["missing"]
    except Exception as e:
        po._stage_failed("dividends", e)
    assert "KeyError" in po._STAGE_FAILURES[0]["traceback"]


def test_clean_run_reports_zero_and_writes_no_alert(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        type("M", (), {"send_telegram": staticmethod(lambda m: sent.append(m))}))
    assert po._report_stage_failures(tmp_path) == 0
    assert sent == [], "a clean run must not alert"
    assert not (tmp_path / "orchestrator_stage_failures.json").exists()


def test_failures_persist_a_durable_artifact(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        type("M", (), {"send_telegram": staticmethod(lambda m: None)}))
    try:
        raise ValueError("boom")
    except Exception as e:
        po._stage_failed("options", e)
    n = po._report_stage_failures(tmp_path)
    assert n == 1
    art = json.loads((tmp_path / "orchestrator_stage_failures.json").read_text())
    assert art["failure_count"] == 1
    assert art["failures"][0]["stage"] == "options"
    assert art["failures"][0]["error_type"] == "ValueError"


def test_failures_alert(tmp_path, monkeypatch):
    """A silently-dying stage is the exact defect this must prevent."""
    sent = []
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        type("M", (), {"send_telegram": staticmethod(lambda m: sent.append(m))}))
    try:
        raise ValueError("boom")
    except Exception as e:
        po._stage_failed("options", e)
    po._report_stage_failures(tmp_path)
    assert len(sent) == 1
    assert "options" in sent[0]


def test_alert_failure_does_not_mask_the_report(tmp_path, monkeypatch):
    """If Telegram is down we still return the count and persist the artifact."""
    def _boom(_m):
        raise RuntimeError("telegram down")
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        type("M", (), {"send_telegram": staticmethod(_boom)}))
    try:
        raise ValueError("boom")
    except Exception as e:
        po._stage_failed("tax", e)
    assert po._report_stage_failures(tmp_path) == 1
    assert (tmp_path / "orchestrator_stage_failures.json").exists()


def test_every_stage_handler_uses_the_registry():
    """No stage may go back to a bare print — that is how this got lost."""
    import re
    src = (ROOT / "scripts" / "portfolio_orchestrator.py").read_text()
    # Anchor to line start so the illustrative example inside _stage_failed's
    # own docstring (mid-line, inside backticks) is not a false positive.
    leftovers = re.findall(r'^\s*print\(f"  \[[a-z\-]+\] ❌ \{\w+\}"\)',
                           src, re.M)
    assert not leftovers, f"stage handlers still printing instead of recording: {leftovers}"
    assert src.count("_stage_failed(") >= 15
