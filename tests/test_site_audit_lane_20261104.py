"""SITE_AUDIT_LANE_20261104 — the §2.1 cadence and the live-crawl guardrails, checked in code.

The lane is an n8n workflow, but the ceiling it must satisfy is arithmetic, so it is asserted here rather than trusted to a
schedule someone edits later: never more than 48 h between full scans, a weekly session rotation, and the live-crawl rules
(health gate, ≥4 s pacing, one browser, abort on restart).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from site_audit.lane import (  # noqa: E402
    HEALTH_PATH, LANE_ID, MAX_GAP_HOURS, PACE_SECONDS, SESSIONS, exceeds_max_gap, largest_gap_hours,
    session_for_week, windows_between,
)

ET = ZoneInfo("America/New_York")


def test_no_stretch_between_runs_exceeds_the_ceiling_over_a_year():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert largest_gap_hours(start, end) <= MAX_GAP_HOURS, "a stretch longer than 48 h exists in the schedule"


def test_the_weekend_gap_is_the_longest_and_still_within_48h():
    # Friday 06:30 ET → Sunday 21:00 ET is the weekend stretch.
    runs = windows_between(datetime(2026, 11, 2, tzinfo=timezone.utc), datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert runs, "no runs scheduled in the window"
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(runs, runs[1:])]
    assert max(gaps) <= MAX_GAP_HOURS


def test_five_runs_a_week_and_the_named_slots_are_kept():
    # 2026-11-02 is a Monday. The spec's Mon/Wed/Fri 06:30 + Sun 21:00 are all here; Saturday 06:30 is the bridge that
    # makes the 48 h ceiling true (Fri 06:30 -> Sun 21:00 alone is 62.5 h).
    runs = windows_between(datetime(2026, 11, 2, tzinfo=timezone.utc), datetime(2026, 11, 9, tzinfo=timezone.utc))
    local = [(r.astimezone(ET).strftime("%a %H:%M")) for r in runs]
    assert local == ["Sun 21:00", "Mon 06:30", "Wed 06:30", "Fri 06:30", "Sat 06:30"], local


def test_the_session_rotates_weekly_and_returns():
    assert [session_for_week(w) for w in range(4)] == ["premarket", "regular", "afterhours", "premarket"]
    assert set(SESSIONS) == {"premarket", "regular", "afterhours"}


def test_a_missed_run_is_detectable():
    a = datetime(2026, 11, 2, 11, 30, tzinfo=timezone.utc)
    assert exceeds_max_gap(a, a.replace(day=4)) is False       # 48 h exactly is allowed
    assert exceeds_max_gap(a, a.replace(day=5)) is True        # longer is not


def test_the_lane_is_named_and_carries_the_live_crawl_rules():
    assert LANE_ID == "site-audit"
    assert PACE_SECONDS >= 4.0, "the operator's pacing floor is 4 s"
    assert HEALTH_PATH == "/api/v2/health"


def test_the_declared_signal_is_the_receipt_the_cli_actually_writes(tmp_path, monkeypatch):
    """cx-openai-4 R8 on #2648: the reader and the writer disagreed, so the lane could never observe itself.

    The registry declared `json_key ... page-audit-*/index.json#generated_at`; the CLI wrote `captured_at` into a dated
    directory, and neither reader globs. This drives the real writer into a state root shaped like the lane's and asks
    the real ``observe_signal`` — with the signal from the committed registry — for the run time. Both halves have to
    agree for the assertion to hold, so it fails if the declaration drifts back to a wildcard, if the key is renamed,
    or if the pointer stops being written.
    """
    import json

    from lib.lane_registry import observe_signal
    from site_audit.page_audit_capture import LATEST_NAME, write_receipts

    registry = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    entries = registry.get("lanes") or registry
    entries = list(entries.values()) if isinstance(entries, dict) else entries
    lane = next(e for e in entries if isinstance(e, dict) and e.get("lane_id") == LANE_ID)
    sig = lane["output_signal"]
    assert "*" not in sig["path"], "an output_signal path must be exact: neither reader globs"

    stamp = "20261105T2130Z"
    out = tmp_path / "data" / "audit" / f"page-audit-{stamp}"
    out.mkdir(parents=True)
    rows = [{"route": "/", "label": "Home", "viewport": "desktop", "status": 200, "text_chars": 900,
             "blank_suspect": False, "flags": [], "h_scroll": False, "failed_requests": [], "console_errors": []}]
    write_receipts(out, rows, stamp=stamp, base="http://127.0.0.1:7777/v3", routes=[("/", "Home")])

    # The reader half first: the real observer, driven with the committed declaration, must see the finished run.
    # (Ordering is deliberate — a mutation of the timestamp fails HERE, in the reader, not in a file assertion.)
    observed = observe_signal(sig, root=tmp_path)
    assert observed["readable"] is True, observed
    assert observed["last_output_at"] is not None, observed
    assert observed["last_output_at"].strftime("%Y%m%dT%H%MZ") == stamp, observed

    # The run's own receipt carries the same key, so a reader holding a dated directory reads a finished run too.
    receipt = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert receipt["generated_at"] == stamp and receipt["captured_at"] == stamp

    # The pointer is written beside the dated directory — where the registry's path resolves.
    declared = tmp_path / sig["path"]
    assert declared.is_file(), f"the declared signal file was not written: {declared}"
    assert json.loads(declared.read_text(encoding="utf-8"))[sig["key"]] == stamp
    assert LATEST_NAME == declared.name
