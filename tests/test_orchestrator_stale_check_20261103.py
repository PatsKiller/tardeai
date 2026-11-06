"""ORCHESTRATOR_STALE_CHECK_20261103 — R3: the guard verdict may not depend on the clock.

cx-openai-2, whole-head BLOCK at 1920aaf14: `portfolio_orchestrator.py` nested the entire
guard-failure branch inside `if _sd_fm.get("completed_at"):`. So every state where the guard says
`ok is False` AND no usable clock exists ran the pipeline with zero warnings:

    1. no manifest file at all
    2. a 0-byte manifest
    3. a manifest that is not JSON
    4. a valid manifest with no `completed_at`
    5. a valid manifest whose `completed_at` is not a timestamp

The clock may only add the age branch. These tests drive the extracted check through all five,
plus the healthy control that must stay silent, plus the "every collaborator is broken" case that
must still not raise.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.authoritative_store_guard import holdings_hash
from scripts.portfolio_orchestrator import _parse_manifest_clock, _pre_run_stale_check

NOW = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)
HEALTHY_ROW = {"symbol": "AAA", "account": "schwab_taxable", "shares": 10,
               "market_value": 1200.0, "price": 120.0}


def _healthy_store(state_dir, manifest):
    doc = {"holdings": [HEALTHY_ROW], "as_of": "2026-11-03"}
    (state_dir / "holdings.json").write_text(json.dumps(doc), encoding="utf-8")
    if manifest is not None:
        (state_dir / "_freshness.json").write_text(
            manifest if isinstance(manifest, str) else json.dumps(manifest), encoding="utf-8")
    return state_dir


def _manifest(**over):
    doc = {"status": "fresh", "completed_at": NOW.isoformat(),
           "holdings_hash": holdings_hash({"holdings": [HEALTHY_ROW]}), "run_id": "run-42"}
    doc.update(over)
    return doc


class Recorder:
    def __init__(self):
        self.sent = []
        self.records = []

    def send(self, text, **kwargs):
        self.sent.append(text)
        return True

    def record(self, entry):
        self.records.append(entry)


def _run(state_dir):
    rec = Recorder()
    verdict = _pre_run_stale_check(state_dir, date_str="2026-11-03", now=NOW,
                                   send=rec.send, already_logged=lambda key: False,
                                   record=rec.record)
    return verdict, rec


# ── the five silent states ────────────────────────────────────────────────────────────────────
SILENT = {
    "no_manifest_at_all": lambda d: _healthy_store(d, None),
    "zero_byte_manifest": lambda d: _healthy_store(d, ""),
    "manifest_not_json": lambda d: _healthy_store(d, "{ not json"),
    "manifest_without_completed_at": lambda d: _healthy_store(d, _manifest(completed_at=None)),
    "manifest_with_unparseable_clock": lambda d: _healthy_store(d, _manifest(completed_at="yesterday-ish")),
}


@pytest.mark.parametrize("state", sorted(SILENT))
def test_every_clockless_guard_failure_warns(tmp_path, state):
    SILENT[state](tmp_path)
    verdict, rec = _run(tmp_path)
    assert verdict["guard_ok"] is False, f"{state}: the guard verdict was not read"
    assert verdict["alerted"] is True, f"{state}: guard ok=False produced no warning"
    assert len(rec.sent) == 1, f"{state}: exactly one alert must be attempted, got {rec.sent}"
    assert rec.records and rec.records[0]["notification_type"] == "stale_data_alert"


def test_a_missing_completed_at_alert_says_it_could_not_confirm_currentness(tmp_path):
    """The lead's reproduction: delete completed_at from the manifest."""
    SILENT["manifest_without_completed_at"](tmp_path)
    verdict, rec = _run(tmp_path)
    assert "could not be confirmed current" in rec.sent[0]
    assert "freshness_clock_missing" in rec.sent[0], "the reason the guard refused must be shown"
    assert verdict["age_hours"] is None, "no clock means no invented age"


def test_no_age_is_invented_in_the_recorded_payload(tmp_path):
    SILENT["manifest_without_completed_at"](tmp_path)
    _verdict, rec = _run(tmp_path)
    assert rec.records[0]["payload"]["age_hours"] is None
    assert rec.records[0]["payload"]["guard_reasons"]


# ── the controls ─────────────────────────────────────────────────────────────────────────────
def test_a_healthy_current_store_does_not_warn(tmp_path):
    _healthy_store(tmp_path, _manifest())
    verdict, rec = _run(tmp_path)
    assert verdict["guard_ok"] is True
    assert verdict["alerted"] is False
    assert rec.sent == []


def test_a_stale_clock_with_a_healthy_store_still_warns(tmp_path):
    """The age branch must survive the restructure."""
    _healthy_store(tmp_path, _manifest(completed_at=(NOW - timedelta(hours=80)).isoformat()))
    verdict, rec = _run(tmp_path)
    assert verdict["alerted"] is True
    assert verdict["age_hours"] > 78
    assert "80h old" in rec.sent[0] or "79h old" in rec.sent[0]


def test_an_already_logged_alert_is_not_repeated(tmp_path):
    SILENT["manifest_without_completed_at"](tmp_path)
    rec = Recorder()
    verdict = _pre_run_stale_check(tmp_path, date_str="2026-11-03", now=NOW, send=rec.send,
                                   already_logged=lambda key: True, record=rec.record)
    assert verdict["alerted"] is False
    assert rec.sent == []


# ── never raises ─────────────────────────────────────────────────────────────────────────────
def test_broken_collaborators_cannot_swallow_the_verdict(tmp_path):
    SILENT["manifest_without_completed_at"](tmp_path)
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("notifier down")

    verdict = _pre_run_stale_check(tmp_path, date_str="2026-11-03", now=NOW, send=boom,
                                   already_logged=boom, record=boom)
    assert verdict["alerted"] is True, "the check must still report that it fired"
    assert verdict["sent"] is False
    assert "notifier down" in (verdict["error"] or "")
    assert calls["n"] >= 2, "a failing dedupe must still allow the send attempt"


def test_an_unreadable_state_dir_does_not_raise(tmp_path):
    verdict = _pre_run_stale_check(tmp_path / "does-not-exist", date_str="2026-11-03", now=NOW,
                                   send=lambda *a, **k: True,
                                   already_logged=lambda key: False, record=lambda e: None)
    assert verdict["guard_ok"] is False
    assert verdict["alerted"] is True


# ── the clock helper ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value", [None, "", "   ", 17, {}, [], "not-a-date", "2026-13-45T99:99:99"])
def test_a_manifest_clock_that_is_not_a_timestamp_is_absent(value):
    assert _parse_manifest_clock(value) is None


def test_both_clock_spellings_parse():
    assert _parse_manifest_clock("2026-11-03T07:46:01.164393Z").tzinfo is not None
    assert _parse_manifest_clock("2026-11-03T07:46:01+00:00") == datetime(2026, 11, 3, 7, 46, 1, tzinfo=timezone.utc)
