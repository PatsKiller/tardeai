"""Lane registry: dated inherited tranches (2026-09-28) — fail→pass.

107 cron lines were installed on the host on 2026-09-27/28 with no lane row, so the lane gate
failed on main itself and blocked every local acceptance. They are recorded as a dated tranche
WITH provenance (not appended to the original baseline). A tranche line counts as baseline for
the gate, carries `added`/`reason`/`count`, and its count must equal its line count so the debt
cannot be misreported.

COVERS = ["scripts/lib/lane_registry.py", "scripts/check_lane_registry.py", "config/lane_registry.json"]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_registry as lr  # noqa: E402

COVERS = ["scripts/lib/lane_registry.py", "scripts/check_lane_registry.py", "config/lane_registry.json"]


def _reg():
    return json.loads((ROOT / "config" / "lane_registry.json").read_text())


def test_tranche_recorded_with_provenance_and_honest_count():
    reg = _reg()
    tranches = reg.get("inherited_tranches") or []
    t = next(x for x in tranches if x["added"] == "2026-09-28")
    assert t["count"] == len(t["lines"]) == len(t["lines"]) and t["count"] >= 100
    assert len(t["reason"]) > 120 and "crons-to-CURRENT" in t["reason"]
    assert "recorded_by" in t
    assert len(set(t["lines"])) == len(t["lines"]), "duplicate lines in tranche"
    # the original baseline was NOT grown to absorb them
    assert not (set(t["lines"]) & set(reg["undeclared_baseline"]))


def test_tranche_lines_count_as_baseline_for_the_gate():
    reg = {"lanes": [], "undeclared_baseline": ["old line"],
           "inherited_tranches": [{"added": "2026-09-28", "count": 1, "reason": "x", "lines": ["0 4 * * * cd /x && run.sh"]}]}
    found = {"cron": [{"expression": "0 4 * * * cd /x && run.sh"}, {"expression": "old line"},
                      {"expression": "1 1 * * * brand new"}], "systemd": []}
    fn = getattr(lr, "undeclared_schedulers", None) or getattr(lr, "find_undeclared", None)
    assert fn is not None, "gate matcher not found"
    out = fn(reg, found)
    assert [o["expression"] for o in out] == ["1 1 * * * brand new"]


def test_every_tranche_line_is_a_real_cron_expression():
    t = next(x for x in _reg()["inherited_tranches"] if x["added"] == "2026-09-28")
    for line in t["lines"]:
        head = line.split()
        assert len(head) >= 6 and not line.lstrip().startswith("#"), line[:80]
