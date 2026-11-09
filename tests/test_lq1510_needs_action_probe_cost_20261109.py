"""ANCHOR: LQ1510_NEEDS_ACTION_PROBE_COST_20261109. LQ-20261107-1510.

Home needs_action times out at 5s because n8n-today rebuilds on every receipt-directory
mtime and the Anthropic probe rereads the whole provider-cost log. A changed n8n input
inside the configured stale window is served from the last projection. An appended
Anthropic event is parsed from the new bytes only. Hermetic files. No network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import anthropic_monitoring as AM  # noqa: E402
from scripts.lib.data_broker import n8n_today as NT  # noqa: E402
from scripts.lib.needs_action_probe_config import n8n_today_stale_s, n8n_today_ttl_s  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def test_config_holds_the_n8n_cache_windows():
    assert n8n_today_ttl_s() == 60
    assert n8n_today_stale_s() == 180


def test_n8n_today_serves_stale_when_the_run_directory_changes(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = NT.build

    def counting(root, now=None):
        calls["n"] += 1
        return real(root, now)

    monkeypatch.setattr(NT, "build", counting)
    NT._CACHE.clear()
    assert NT.get_n8n_today(tmp_path, NOW)["cache"] == "MISS"
    assert calls["n"] == 1
    runs = tmp_path / "data" / "runtime" / "n8n_runs"
    runs.mkdir(parents=True)
    (runs / "extra.json").write_text("{}\n", encoding="utf-8")
    again = NT.get_n8n_today(tmp_path, NOW)
    assert again["cache"] == "STALE"
    assert calls["n"] == 1
    forced = NT.get_n8n_today(tmp_path, NOW, ttl_s=0)
    assert forced["cache"] == "MISS"
    assert calls["n"] == 2


def test_appended_anthropic_events_parse_only_the_new_bytes(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    first = '{"provider":"anthropic","usage_start":"2026-11-09T00:00:00+00:00"}\n'
    path.write_text(first, encoding="utf-8")
    AM._EVENT_CACHE.clear()
    rows, coverage = AM._events(path)
    assert coverage == "COMPLETE_FILE" and len(rows) == 1
    starts = []
    real = AM._appended_text

    def spy(p, start):
        starts.append(start)
        return real(p, start)

    monkeypatch.setattr(AM, "_appended_text", spy)
    path.write_text(
        first + '{"provider":"anthropic","usage_start":"2026-11-09T01:00:00+00:00"}\n',
        encoding="utf-8",
    )
    rows2, coverage2 = AM._events(path)
    assert coverage2 == "COMPLETE_FILE"
    assert [r["usage_start"] for r in rows2] == [
        "2026-11-09T00:00:00+00:00",
        "2026-11-09T01:00:00+00:00",
    ]
    assert starts == [len(first.encode())]


def test_a_plain_comment_is_not_required_here():
    """The timeout constant stays 5s. This task does not raise it."""
    from scripts.lib.needs_action import DEFAULT_TIMEOUT_S

    assert DEFAULT_TIMEOUT_S == 5.0
