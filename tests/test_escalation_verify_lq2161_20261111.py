"""STOP-ESCALATION-VERIFY-LQ2161: a retry that exits 0 must not be recorded FIXED
unless the condition is re-measured and clear. Synthetic data only."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _esc():
    spec = importlib.util.spec_from_file_location("esc_lq2161", ROOT / "scripts" / "claude_escalation_handler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


STALE = "health:data_quality:data_source_stale"
ITEM = {"component": STALE, "detail": "data source 'synthetic_src' stale: last success 9.0h ago (window 1.0h)"}


def _row(hours_ago, status="healthy"):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"source_key": "synthetic_src", "status": status, "last_success_at": ts,
            "last_failure_at": None, "max_stale_minutes": 60, "last_error": None, "failure_count": 0}


def test_stale_source_still_stale_is_not_cleared(monkeypatch):
    esc = _esc()
    monkeypatch.setattr(esc, "_data_source_rows", lambda: [_row(100)])
    cleared, note = esc._verify_remediation(ITEM)
    assert cleared is False, "retry exit 0 but source still stale must not be FIXED"
    assert note.startswith("data_source_still_")


def test_stale_source_refreshed_is_cleared(monkeypatch):
    esc = _esc()
    monkeypatch.setattr(esc, "_data_source_rows", lambda: [_row(0.01)])
    cleared, note = esc._verify_remediation(ITEM)
    assert cleared is True and note.startswith("data_source_ok")


def test_stale_source_unreadable_or_unparseable_fails_closed(monkeypatch):
    esc = _esc()
    monkeypatch.setattr(esc, "_data_source_rows", lambda: None)
    assert esc._verify_remediation(ITEM)[0] is False
    monkeypatch.setattr(esc, "_data_source_rows", lambda: [_row(0.01)])
    assert esc._verify_remediation({"component": STALE, "detail": "no source named"})[0] is False
    monkeypatch.setattr(esc, "_data_source_rows", lambda: [])
    assert esc._verify_remediation(ITEM)[0] is False, "source absent from table is unknown, not clear"


def _pin_clock(monkeypatch, esc, y, m, d):
    class _Pinned(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(y, m, d, 12, 0, tzinfo=tz)

    monkeypatch.setattr(esc, "datetime", _Pinned)


def test_agent_jobs_stale_measures_age_not_backlog(monkeypatch):
    esc = _esc()
    _pin_clock(monkeypatch, esc, 2026, 11, 11)  # Wednesday: 4h limit, independent of the real day
    item = {"component": "health:data_quality:agent_jobs_stale"}
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: (True, 4.4, "ok"))
    cleared, note = esc._verify_remediation(item)
    assert cleared is False and note.startswith("agent_jobs_age_still_")
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: (True, 0.5, "ok"))
    assert esc._verify_remediation(item)[0] is True
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: (True, None, "ok"))
    assert esc._verify_remediation(item)[0] is False, "no completed job at all is unknown, not clear"


def test_agent_jobs_stale_weekend_limit_is_48h(monkeypatch):
    esc = _esc()
    _pin_clock(monkeypatch, esc, 2026, 11, 14)  # Saturday
    item = {"component": "health:data_quality:agent_jobs_stale"}
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: (True, 30.0, "ok"))
    assert esc._verify_remediation(item)[0] is True
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: (True, 50.0, "ok"))
    assert esc._verify_remediation(item)[0] is False


def _view_returning(monkeypatch, status):
    import lib.data_source_health_view as v

    monkeypatch.setattr(v, "view_rows", lambda rows, now, reg: [{"status": status}])


def test_not_alerted_statuses_clear_but_error_and_unknown_do_not(monkeypatch):
    esc = _esc()
    monkeypatch.setattr(esc, "_data_source_rows", lambda: [_row(0.01)])
    for status in ("idle", "premium_endpoint_unavailable"):
        _view_returning(monkeypatch, status)
        cleared, note = esc._verify_remediation(ITEM)
        assert cleared is True and note == f"data_source_ok_{status}"
    for status in ("error", "unknown", "stale"):
        _view_returning(monkeypatch, status)
        cleared, note = esc._verify_remediation(ITEM)
        assert cleared is False and note == f"data_source_still_{status}"


def test_view_exception_fails_closed(monkeypatch):
    esc = _esc()
    import lib.data_source_health_view as v

    monkeypatch.setattr(esc, "_data_source_rows", lambda: [_row(0.01)])

    def boom(*a, **k):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(v, "view_rows", boom)
    cleared, note = esc._verify_remediation(ITEM)
    assert cleared is False and note.startswith("data_source_verify_error")


def test_unmeasured_type_is_not_fixed():
    esc = _esc()
    cleared, note = esc._verify_remediation({"component": "health:x:some_unmeasured_type"})
    assert cleared is False and note.startswith("unverified")
    assert esc._verify_remediation({"component": "weird"})[0] is False
