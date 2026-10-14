"""Schwab paused (incident 2026-10-14) — A: the pause switch, H: positions phase-2 proof.

Operator deactivated the Schwab developer app ~15:00 ET 2026-10-14. A paused day must be SKIPPED_SCHWAB_PAUSED:
not a pass (it proves nothing) and not a failure (it must not reset the "day N of 10" counter).
Fakes only: no database, no broker, no Telegram.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import positions_proof_daily as pd  # noqa: E402
from lib import schwab_access_mode as sam  # noqa: E402

COVERS = ["scripts/positions_proof_daily.py"]   # the SKIPPED line is observed at the real transport
ET = ZoneInfo("America/New_York")


# ── A: the switch ───────────────────────────────────────────────────────────

def test_committed_switch_is_forbidden(monkeypatch):
    monkeypatch.delenv("TRADEAI_SCHWAB_ACCESS_MODE", raising=False)
    st = sam.status()
    assert st["mode"] == "forbidden" and st["paused"] and not st["reads_allowed"]
    assert st["since"].startswith("2026-10-14")


def test_absent_file_defaults_to_normal(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADEAI_SCHWAB_ACCESS_MODE", raising=False)
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE_PATH", str(tmp_path / "missing.yaml"))
    assert sam.mode() == "normal" and sam.reads_allowed()


def test_json_file_and_read_only(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADEAI_SCHWAB_ACCESS_MODE", raising=False)
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"mode": "read_only"}))
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE_PATH", str(p))
    assert sam.mode() == "read_only" and sam.reads_allowed() and not sam.is_paused()


def test_unknown_value_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADEAI_SCHWAB_ACCESS_MODE", raising=False)
    p = tmp_path / "m.yaml"
    p.write_text("mode: maybe\n")
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE_PATH", str(p))
    st = sam.status()
    assert st["mode"] == "forbidden" and "unknown" in st["error"]


def test_auth_failure_classifier():
    assert sam.is_auth_failure("Schwab rejected the login token (HTTP 401)")
    assert sam.is_auth_failure({"error": "no Schwab login token for schwab_roth_ira"})
    assert sam.is_auth_failure({"status_code": 403})
    assert not sam.is_auth_failure("connection reset by peer")
    assert not sam.is_auth_failure(None)


def test_log_skip_emits_one_line_per_component(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    lines: list[str] = []
    sam._logged.discard("unit-x")
    for _ in range(5):
        sam.log_skip("unit-x", printer=lines.append)
    assert len(lines) == 1 and "mode=forbidden" in lines[0]


# ── H: positions proof ──────────────────────────────────────────────────────

class _Cur:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def cursor(self):
        return _Cur()

    def rollback(self):
        pass


def _runs(day: date, status="complete"):
    base = datetime(day.year, day.month, day.day, 9, 24, tzinfo=ET)
    return [{"run_id": i, "status": status, "promoted": status == "complete",
             "finished_at": base + timedelta(minutes=m)} for i, m in enumerate(range(0, 7 * 60 + 1, 15))]


def _setup(tmp_path, monkeypatch, *, status="partial", ledger=None):
    monkeypatch.setattr(pd, "ROOT", tmp_path)
    monkeypatch.setattr(pd.ps, "_conn", lambda: _Conn())
    monkeypatch.setattr(pd, "read_day", lambda cur, day: (_runs(day, status), [], []))
    monkeypatch.setattr(pd, "load_proof_config",
                        lambda: {"start": "2026-10-07", "days": 10, "stale_after_minutes_market": 30})
    if ledger:
        path = tmp_path / pd.LEDGER_REL
        pd.write_ledger(path, ledger)
    return tmp_path / pd.LEDGER_REL


def test_paused_day_is_skipped_not_failed_and_counter_holds(alarm_capture, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    path = _setup(tmp_path, monkeypatch, status="partial",
                  ledger=[{"date": "2026-10-13", "pass": True}])
    assert pd.main(["--date", "2026-10-14", "--send"]) == 0
    row = [r for r in pd.read_ledger(path) if r["date"] == "2026-10-14"][0]
    assert row["status"] == pd.SKIPPED_SCHWAB_PAUSED and row["pass"] is False
    alarm_capture.assert_fired(contains="SKIPPED_SCHWAB_PAUSED")
    alarm_capture.assert_fired(contains="counter held at 1 of 10")
    # the next passing day continues the run: day 2, not day 1
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "normal")
    monkeypatch.setattr(pd, "read_day", lambda cur, day: (_runs(day), [], []))
    assert pd.main(["--date", "2026-10-15"]) == 0
    assert pd.proof_day_number(pd.read_ledger(path), date(2026, 10, 15), date(2026, 10, 7)) == 2


def test_paused_day_never_counts_as_a_pass_even_if_runs_look_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    path = _setup(tmp_path, monkeypatch, status="complete", ledger=[{"date": "2026-10-13", "pass": True}])
    pd.main(["--date", "2026-10-14"])
    row = [r for r in pd.read_ledger(path) if r["date"] == "2026-10-14"][0]
    assert row["pass"] is False and row["graded_pass"] is True    # a clean-looking paused day is still not a pass
    assert pd.proof_day_number(pd.read_ledger(path), date(2026, 10, 14), date(2026, 10, 7)) == 1


def test_normal_mode_partial_day_still_fails_and_resets(alarm_capture, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "normal")
    _setup(tmp_path, monkeypatch, status="partial", ledger=[{"date": "2026-10-13", "pass": True}])
    assert pd.main(["--date", "2026-10-14", "--send"]) == 1
    alarm_capture.assert_fired(contains="counter reset to 0 of 10")


def test_days_before_the_pause_are_graded_normally(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    assert pd.schwab_paused_for(date(2026, 10, 14)) is not None   # since defaults to no date via env
    monkeypatch.delenv("TRADEAI_SCHWAB_ACCESS_MODE")
    assert pd.schwab_paused_for(date(2026, 10, 13)) is None       # committed since 2026-10-14
    assert pd.schwab_paused_for(date(2026, 10, 14)) is not None


def test_counter_skips_skipped_rows():
    led = [{"date": "2026-10-12", "pass": True}, {"date": "2026-10-13", "pass": True},
           {"date": "2026-10-14", "pass": False, "status": pd.SKIPPED_SCHWAB_PAUSED},
           {"date": "2026-10-15", "pass": True}]
    assert pd.proof_day_number(led, date(2026, 10, 14), date(2026, 10, 7)) == 2
    assert pd.proof_day_number(led, date(2026, 10, 15), date(2026, 10, 7)) == 3
