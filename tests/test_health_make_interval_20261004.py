"""The ensemble-stall check passes an integer to make_interval(hours => ...).

Postgres has make_interval(hours => int) only; the float from ENSEMBLE_STALL_HOURS
raised "function make_interval(hours => numeric) does not exist" on every health
run (17 errors in 400 log lines), which the log-error check escalated to a critical.
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import health_agent as ha  # noqa: E402


def test_stall_query_casts_hours_to_int(monkeypatch):
    seen = []
    unexpected = []

    def fake_db(sql, params=None, fetch=None):
        if "make_interval(hours" in sql:
            seen.append((sql, params))
        return {}

    def no_network(*_a, **_k):
        raise OSError("no network in tests")

    def captured_scheduler(argv, **kwargs):
        if argv != ["crontab", "-l"] or kwargs != {"capture_output": True, "text": True, "timeout": 5}:
            unexpected.append((argv, kwargs))
            raise AssertionError("unexpected subprocess in the health-query fixture")
        return subprocess.CompletedProcess(argv, 0, "# fixture: no apply-authorized RAG worker\n", "")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(subprocess, "run", captured_scheduler)
    monkeypatch.setattr(ha, "_db", fake_db)
    monkeypatch.setenv("ENSEMBLE_STALL_HOURS", "72.5")
    ha.collect_intelligence_quality()
    assert not unexpected
    assert seen, "the ensemble-stall query did not run"
    for sql, params in seen:
        assert "make_interval(hours => %s::int)" in sql
        assert params == (72,) or params == (73,)
        assert all(isinstance(p, int) for p in params)
