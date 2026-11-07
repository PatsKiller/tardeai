"""LQ-121: the pressure loop stops before a pass that cannot finish inside the run's wall budget.

Live evidence: hourly disk-hygiene runs took 2,600-3,000 s because pass 2 re-scanned everything (~20 min) after pass 1
removed 8 KiB; a run that long overlaps the next hourly slot (flock -n skips it). Synthetic tmp_path fixture only.
COVERS = ["scripts/disk_hygiene.py"]
"""
from __future__ import annotations

import json

import pytest

from scripts import disk_hygiene as DH
from tests.test_disk_workspace_lifecycle_20261031 import pworld  # noqa: F401 -- fixture imported for pytest
from tests.test_disk_standing_apply_20261024 import world  # noqa: F401 -- fixture imported for pytest


@pytest.fixture
def slow_passes(monkeypatch):
    """Every time.monotonic() call advances 400 s, so a pass costs several hundred seconds of fake wall time."""
    t = {"now": 0.0}

    def fake():
        t["now"] += 400.0
        return t["now"]

    monkeypatch.setattr(DH.time, "monotonic", fake)


def test_loop_stops_when_the_next_pass_cannot_finish_inside_the_budget(pworld, slow_passes):  # noqa: F811 -- fixture parameter shadows the import
    make, run, calls, *_ = pworld
    make(6)
    rc, rep = run("--until-target", "50")
    p = rep["pressure"]
    assert rc == 0 and p["stopped_because"] == "wall_budget"
    assert 1 <= len(p["passes"]) < 5  # old code ran all max_passes (5) while items remained


def test_budget_is_configurable_and_validated(pworld):  # noqa: F811 -- fixture parameter shadows the import
    make, run, calls, state, rules_path, home = pworld
    cfg = json.loads(rules_path.read_text())
    cfg["standing_apply"]["pressure"]["run_budget_s"] = 3300
    rules_path.write_text(json.dumps(cfg))
    make(6)
    rc, rep = run("--until-target", "50")
    assert rc == 0 and rep["pressure"]["stopped_because"] != "wall_budget"  # a generous budget lets the passes run
    cfg["standing_apply"]["pressure"]["run_budget_s"] = 5
    rules_path.write_text(json.dumps(cfg))
    with pytest.raises(DH.RulesError, match="pressure_run_budget_s"):
        DH.load_rules(rules_path, home=home)
