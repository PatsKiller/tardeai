"""LQ-20261107-2993c-v2 (review 2993cr R1-R5): failed runs, unknown counts, wiring, Discover clock."""
import os
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import watch_alerts_record as rec  # noqa: E402
from lib import watch_setups_reads as ws  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


def test_unknown_armed_is_stored_null_and_certified_null_not_zero():
    # R2: a run that could not read watch_alerts reports armed=None; the record must not coerce it to 0.
    with tempfile.TemporaryDirectory() as d:
        rec.append_run(armed=None, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=5))
        out = rec.read_record(root=d, now=NOW)
        assert out["certified"]["armed"] is None
        assert '"armed": null' in rec.record_path(d).read_text()
        rec.append_run(armed=0, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=1))
        assert rec.read_record(root=d, now=NOW)["certified"]["armed"] == 0  # a real zero stays a zero


def test_fired_24h_counts_ok_runs_inside_the_window_only():
    # kills B7: failed runs and runs older than 24 h must not count as fired.
    with tempfile.TemporaryDirectory() as d:
        rec.append_run(armed=3, fired=7, composites=0, rc=0, root=d, now=NOW - timedelta(hours=30))
        rec.append_run(armed=3, fired=2, composites=0, rc=1, error="x", root=d, now=NOW - timedelta(hours=2))
        rec.append_run(armed=3, fired=1, composites=0, rc=0, root=d, now=NOW - timedelta(hours=1))
        c = rec.read_record(root=d, now=NOW)["certified"]
        assert c["fired_24h"] == 1
        assert c["runs_24h"] == 2 and c["ok_runs_24h"] == 1


def test_last_error_and_rc_are_served_for_a_failing_evaluator():
    with tempfile.TemporaryDirectory() as d:
        rec.append_run(armed=3, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=50))
        rec.append_run(armed=None, fired=0, composites=0, rc=1, error="db down", root=d, now=NOW - timedelta(minutes=5))
        out = rec.read_record(root=d, now=NOW)
        assert out["last_rc"] == 1 and out["last_error"] == "db down"
        assert out["last_ok_at"] == (NOW - timedelta(minutes=50)).isoformat()


def test_record_file_is_private():
    old = os.umask(0)  # a restrictive host umask would hide a wider create mode
    try:
        with tempfile.TemporaryDirectory() as d:
            rec.append_run(armed=1, fired=0, composites=0, rc=0, root=d, now=NOW)
            assert stat.S_IMODE(os.stat(rec.record_path(d)).st_mode) == 0o600
    finally:
        os.umask(old)


def test_pins_clock_is_the_listed_rows_not_the_dead_feed():
    # R3: Discover is stamped by the screener-find pins it lists.
    pins = [{"symbol": "A", "auto_research_at": "2026-11-13T10:00:00+00:00", "pinned_at": "2026-10-01T00:00:00+00:00"},
            {"symbol": "B", "auto_research_at": "2026-11-12T10:00:00+00:00", "pinned_at": None}]
    out = ws.pins_as_of(pins)
    assert out == {"pins_as_of": "2026-11-13T10:00:00+00:00", "pins_as_of_basis": "screener_find_pins.auto_research_at"}


def test_pins_clock_falls_back_to_pinned_at_then_unknown():
    out = ws.pins_as_of([{"symbol": "A", "auto_research_at": None, "pinned_at": "2026-10-01T00:00:00+00:00"}])
    assert out["pins_as_of_basis"] == "screener_find_pins.pinned_at"
    none = ws.pins_as_of([])
    assert none == {"pins_as_of": None, "pins_as_of_basis": None}  # unknown, never now


def test_pins_clock_handles_datetime_values():
    out = ws.pins_as_of([{"symbol": "A", "auto_research_at": datetime(2026, 11, 13, 10, tzinfo=timezone.utc)}])
    assert out["pins_as_of"].startswith("2026-11-13T10:00:00")
