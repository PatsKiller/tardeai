"""SharedIntelligenceBridge fetches its prefs only on the routes where it renders.

Site validation 2026-10-22: the bridge is mounted app-wide (App.tsx) but renders only on /watch and
/journal. It fetched five ui prefs on every page, one of them
(portfolio.shared-symbol-context.v1) about 9.4 MB and re-polled every 2 minutes, while the
server was OOM-cycling at its 2 GiB cgroup limit. Every useJson call must pass the `show` gate.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "apps/command-center-v3/src/components/SharedIntelligenceBridge.tsx"


def _text() -> str:
    return SRC.read_text(encoding="utf-8")


def test_use_json_takes_an_enabled_gate():
    s = _text()
    assert re.search(r"function useJson\(url: string, refreshMs = 120_000, enabled = true\)", s)
    assert "if (!enabled) return" in s
    assert "[url, tick, refreshMs, enabled]" in s


def test_every_pref_fetch_is_gated_on_show():
    s = _text()
    calls = re.findall(r"useJson\(`/api/v2/ui/prefs/get\?key=\$\{encodeURIComponent\((\w+)\)\}`, ([\w_]+)(, show)?\)", s)
    assert len(calls) == 5, calls
    ungated = [key for key, _ms, gate in calls if not gate]
    assert not ungated, f"pref fetched on every route: {ungated}"


def test_show_is_defined_before_the_fetches():
    s = _text()
    assert s.index("const show = showWatch || showJournal") < s.index("useJson(`/api/v2/ui/prefs/get")
