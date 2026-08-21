"""Provider spend snapshot — never publish k-char estimator as truth."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.provider_spend_snapshot import (  # noqa: E402
    QUALITY_TRUSTED,
    QUALITY_UNTRUSTED,
    build_snapshot,
    classify_event_quality,
    load_json_events,
    snapshot_path,
)

NOW = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
FIXTURES = ROOT / "tests" / "fixtures" / "provider_spend"


def test_trusted_flash_fixture_publishes_14d():
    events = load_json_events(FIXTURES / "trusted_flash_14d.json")
    snap = build_snapshot(events=events, now=NOW, write=False)
    assert snap["source_quality"] == QUALITY_TRUSTED
    assert snap["published_as_truth"] is True
    assert snap["financial_action"] is False
    assert snap["totals"]["usd"] == 0.0045
    assert snap["per_provider"]["deepseek"]["events"] == 3
    assert "flash" in snap["per_lane"] or "FAST" in snap["per_lane"]
    assert "2026-08-18" in snap["per_day"]
    assert snap["untrusted_reason"] is None


def test_untrusted_kchar_estimator_not_published():
    events = load_json_events(FIXTURES / "untrusted_consumption_kchar.json")
    assert all(classify_event_quality(e) == QUALITY_UNTRUSTED for e in events)
    snap = build_snapshot(events=events, now=NOW, write=False)
    assert snap["source_quality"] == QUALITY_UNTRUSTED
    assert snap["published_as_truth"] is False
    assert snap["totals"]["usd"] is None
    assert snap["per_provider"] == {}
    assert snap["per_day"] == {}
    assert snap["diagnostics"]["discarded_untrusted_usd"] >= 10000
    assert "12k" in (snap["untrusted_reason"] or "").lower() or "k-char" in (snap["untrusted_reason"] or "").lower()


def test_mixed_prefers_flash_discards_estimator():
    trusted = load_json_events(FIXTURES / "trusted_flash_14d.json")
    garbage = load_json_events(FIXTURES / "untrusted_consumption_kchar.json")
    snap = build_snapshot(events=trusted + garbage, now=NOW, write=False)
    assert snap["source_quality"] == QUALITY_TRUSTED
    assert snap["published_as_truth"] is True
    assert snap["totals"]["usd"] == 0.0045
    assert snap["diagnostics"]["discarded_untrusted_usd"] >= 10000


def test_write_opt_in_tmp(tmp_path):
    events = load_json_events(FIXTURES / "trusted_flash_14d.json")
    snap = build_snapshot(root=tmp_path, events=events, now=NOW, write=True)
    path = snapshot_path(root=tmp_path)
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["source_quality"] == QUALITY_TRUSTED
    assert saved["totals"]["usd"] == snap["totals"]["usd"]
    assert saved["financial_action"] is False


def test_untrusted_write_does_not_store_garbage_totals(tmp_path):
    events = load_json_events(FIXTURES / "untrusted_consumption_kchar.json")
    build_snapshot(root=tmp_path, events=events, now=NOW, write=True)
    saved = json.loads(snapshot_path(root=tmp_path).read_text(encoding="utf-8"))
    assert saved["source_quality"] == QUALITY_UNTRUSTED
    assert saved["published_as_truth"] is False
    assert saved["totals"]["usd"] is None
    blob = json.dumps(saved)
    assert "8065" not in blob or saved["per_provider"] == {}
    assert saved["per_provider"] == {}


def test_missing_sources_untrusted_not_truth(tmp_path):
    snap = build_snapshot(root=tmp_path, now=NOW, write=False)
    assert snap["source_quality"] == QUALITY_UNTRUSTED
    assert snap["published_as_truth"] is False
    assert snap["totals"]["usd"] is None
