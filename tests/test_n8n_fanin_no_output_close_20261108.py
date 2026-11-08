"""NO_OUTPUT_AUTOCLOSE: a NO_OUTPUT breach the fresh detector stopped re-emitting closes (LQ-20261107-456)."""
import json
from datetime import datetime, timezone

from scripts import n8n_incident_fanin as F

NOW = datetime(2026, 11, 8, 0, 35, tzinfo=timezone.utc)


def _row(lane, day, kind="NO_OUTPUT", authority="READ_ONLY_ADVISORY"):
    return {"lane_id": lane, "kind": kind, "state": "OPEN", "authority": authority,
            "detected_at": f"{day}T02:00:00+00:00", "evidence": {}}


def _rt(tmp_path, rows, ok_at):
    (tmp_path / "supervisor_breaches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if ok_at:
        (tmp_path / "supervisor_breach_detector_latest.json").write_text(json.dumps({"ok_at": ok_at}))
    return tmp_path


def _items(tmp_path):
    return {f["item"] for f in F._breach_findings(tmp_path, NOW)}


def test_old_day_row_closes_when_detector_fresh_on_later_day(tmp_path):
    rt = _rt(tmp_path, [_row("a", "2026-11-07"), _row("b", "2026-11-08")], "2026-11-08T00:32:00+00:00")
    assert _items(rt) == {"b:NO_OUTPUT"}  # a was not re-emitted on 11-08: closed; b was: stays
    assert F.NOTES["breach_no_output_closed"] == "1"


def test_stalled_or_missing_detector_closes_nothing(tmp_path):
    assert _items(_rt(tmp_path, [_row("a", "2026-11-07")], "2026-11-07T20:00:00+00:00")) == {"a:NO_OUTPUT"}
    assert _items(_rt(tmp_path, [_row("a", "2026-11-07")], None)) == {"a:NO_OUTPUT"}


def test_same_day_detector_run_closes_nothing(tmp_path):
    rt = _rt(tmp_path, [_row("a", "2026-11-08")], "2026-11-08T00:32:00+00:00")
    assert _items(rt) == {"a:NO_OUTPUT"}


def test_other_kinds_and_other_writers_untouched(tmp_path):
    rows = [_row("a", "2026-11-07", kind="STALE_OUTPUT"), _row("b", "2026-11-07", authority="HEARTBEAT")]
    assert _items(_rt(tmp_path, rows, "2026-11-08T00:32:00+00:00")) == {"a:STALE_OUTPUT", "b:NO_OUTPUT"}
