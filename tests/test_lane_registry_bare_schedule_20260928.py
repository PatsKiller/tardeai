"""LP-DEF-19: a lane whose scheduler.expression is a bare cron schedule must not declare every cron line that shares it."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import lane_registry as lr  # noqa: E402


def test_bare_schedule_is_not_a_pattern():
    reg = {"lanes": [{"lane_id": "a", "scheduler": {"kind": "cron", "expression": "5 * * * *"}},
                     {"lane_id": "b", "scheduler": {"kind": "cron", "expression": "30 2 * * * report_platform_conformance.py --write", "match": "report_platform_conformance.py"}}],
           "undeclared_baseline": []}
    found = {"systemd": [], "cron": [
        {"expression": "5 * * * * cd $PROJ && bash sync-docs-to-drive.sh"},                       # shares the minute field only → UNDECLARED
        {"expression": "30 2 * * * cd $PROJ && $PY scripts/report_platform_conformance.py --write"},  # declared through `match`
        {"expression": "30 2 * * * cd $PROJ && $PY scripts/populate_performance_context.py"}]}      # shares the schedule only → UNDECLARED
    out = {o["expression"] for o in lr.find_undeclared(reg, found)}
    assert "5 * * * * cd $PROJ && bash sync-docs-to-drive.sh" in out
    assert "30 2 * * * cd $PROJ && $PY scripts/populate_performance_context.py" in out
    assert "30 2 * * * cd $PROJ && $PY scripts/report_platform_conformance.py --write" not in out
    assert lr._BARE_CRON_SCHEDULE.match("*/15 7-16 * * 1-5") and not lr._BARE_CRON_SCHEDULE.match("*/15 * * * * foo.py")


def test_inherited_tranche_masks_known_debt_only():
    reg = {"lanes": [{"lane_id": "a", "scheduler": {"kind": "cron", "expression": "5 * * * *"}}], "undeclared_baseline": [],
           "inherited_tranches": [{"date": "2026-09-28", "lines": ["5 * * * * cd $PROJ && bash sync-docs-to-drive.sh"]}]}
    found = {"systemd": [], "cron": [{"expression": "5 * * * * cd $PROJ && bash sync-docs-to-drive.sh"}, {"expression": "5 * * * * new_thing.py"}]}
    assert {o["expression"] for o in lr.find_undeclared(reg, found)} == {"5 * * * * new_thing.py"}
