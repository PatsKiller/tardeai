"""A CIO run that produced no advisory action sends no "CIO Run Complete" check-in.

Telegram export audit 2026-09-14: 86 of 95 CIO Desk messages were "CIO Run Complete — <uuid>"
check-ins; the summary differed slightly per run so the 6-hour content dedupe never held. Operator
decision: noise to the digest. Source-level pin (the worker needs a full run fixture otherwise).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERS = ["scripts/lib/cio_run_worker.py"]


def test_checkin_is_skipped_when_no_action_notification_was_enqueued():
    """Operator 2026-09-26 supersedes 09-14: no "CIO Run Complete — <uuid>" check-in at all,
    and no id-only "CIO Advisory Action <id>" message; material actions go out as one
    readable message (scripts/lib/cio_action_notify.py)."""
    src = (ROOT / "scripts" / "lib" / "cio_run_worker.py").read_text(encoding="utf-8")
    guard = src.index("        if summary:\n")
    checkin = src.index('"subject": f"CIO Run Complete')
    assert guard < checkin
    assert "summary = None" in src[guard:checkin]
    assert 'f"CIO Advisory Action' not in src
    assert "produced action {action_id}" not in src
    assert "select_new(" in src and "render(" in src
