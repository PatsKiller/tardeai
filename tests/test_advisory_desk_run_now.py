"""Advisory Desk run-now + weekday 09:15 ET schedule."""
from __future__ import annotations

import importlib
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _mod(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ADVISORY_RUN_STATUS", str(tmp_path / "advisory_run_now.json"))
    monkeypatch.setenv("TRADEAI_ADVISORY_RUN_LOCK", str(tmp_path / "advisory_run_now.lock"))
    import lib.advisory_desk_schedule as m
    m = importlib.reload(m)
    m._SYSTEMD_CACHE.update({"at": 0.0, "iso": None})
    monkeypatch.setattr(m, "_systemd_next_iso", lambda: None)
    return m


def test_before_0915_weekday_is_today(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    now = datetime(2026, 8, 19, 8, 0, tzinfo=m.ET)  # Wednesday
    nxt = m.next_weekday_0915_et(now)
    assert nxt.date().isoformat() == "2026-08-19"
    assert (nxt.hour, nxt.minute) == (9, 15)
    assert nxt.tzname() == "EDT"


def test_at_or_after_0915_rolls_forward(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    now = datetime(2026, 8, 19, 9, 15, tzinfo=m.ET)
    nxt = m.next_weekday_0915_et(now)
    assert nxt.date().isoformat() == "2026-08-20"


def test_friday_after_0915_skips_weekend(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    now = datetime(2026, 8, 21, 10, 0, tzinfo=m.ET)  # Friday
    nxt = m.next_weekday_0915_et(now)
    assert nxt.date().isoformat() == "2026-08-24"
    assert nxt.strftime("%a") == "Mon"


def test_saturday_jumps_to_monday(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    now = datetime(2026, 8, 22, 12, 0, tzinfo=m.ET)
    nxt = m.next_weekday_0915_et(now)
    assert nxt.date().isoformat() == "2026-08-24"


def test_january_is_est(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    now = datetime(2026, 1, 15, 10, 0, tzinfo=m.ET)  # Thursday
    nxt = m.next_weekday_0915_et(now)
    assert nxt.tzname() == "EST"
    assert nxt.date().isoformat() == "2026-01-16"


def test_schedule_payload_calendar_source(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    payload = m.schedule_payload(datetime(2026, 8, 19, 8, 0, tzinfo=m.ET))
    assert payload["source"] == "calendar"
    assert payload["cadence"] == "weekdays 09:15 America/New_York"
    assert payload["authority"] == "READ_ONLY_ADVISORY"
    assert payload["financial_action"] is False
    assert "09:15" in payload["next_run_et"]


def test_schedule_payload_prefers_systemd(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    iso = datetime(2026, 8, 20, 13, 15, tzinfo=timezone.utc).isoformat()
    monkeypatch.setattr(m, "_systemd_next_iso", lambda: iso)
    payload = m.schedule_payload(datetime(2026, 8, 19, 20, 0, tzinfo=m.ET))
    assert payload["source"] == "systemd"
    assert payload["next_run_et"].startswith("Thu 2026-08-20 09:15")


def test_start_run_now_rejects_second_while_locked(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    gate = threading.Event()

    def fake(*, live_llm, lock_fd):
        gate.wait(timeout=5)
        m._unlock(lock_fd)
        m._write_status({"state": "ok", "live_llm": live_llm})

    monkeypatch.setattr(m, "_execute_run", fake)
    first = m.start_run_now(live_llm=False)
    second = m.start_run_now(live_llm=False)
    assert first["accepted"] is True
    assert first["financial_action"] is False
    assert first["broker_write_authority"] == "NONE"
    assert second["accepted"] is False
    assert second["reason"] == "already_running"
    gate.set()


def test_run_now_never_mentions_broker_writes():
    src = (ROOT / "scripts" / "lib" / "advisory_desk_schedule.py").read_text(encoding="utf-8")
    assert "READ_ONLY_ADVISORY" in src
    assert "financial_action" in src
    assert "broker_write_authority" in src
    assert "place_order" not in src
    assert "schwab" not in src.lower()


def test_api_routes_run_now():
    api = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert "run-now" in api
    assert "post_run_now" in api
    assert "run-status" in api
    adv = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert "schedule" in adv
    assert "post_run_now" in adv
    assert "get_run_status" in adv


def test_ui_has_run_now_and_next_scheduled():
    ui = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "AdvisoryDeskHub.tsx").read_text(
        encoding="utf-8"
    )
    assert "NEXT SCHEDULED" in ui
    assert "Run now" in ui
    assert "/api/v3/advisory/run-now" in ui
    assert "READ_ONLY_ADVISORY" in ui
    assert "no broker writes" in ui
