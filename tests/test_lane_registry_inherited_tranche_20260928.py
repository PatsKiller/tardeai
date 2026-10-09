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


def test_tranche_debt_is_paid_and_gone():
    """2026-10-09 (N8N maturity B1): every tranche line now has a lane row, so the tranche and the
    original baseline are removed. The matcher still honours a tranche (next test) for old fixtures."""
    reg = _reg()
    assert "inherited_tranches" not in reg
    assert "undeclared_baseline" not in reg


def test_tranche_lines_count_as_baseline_for_the_gate():
    reg = {"lanes": [], "undeclared_baseline": ["old line"],
           "inherited_tranches": [{"added": "2026-09-28", "count": 1, "reason": "x", "lines": ["0 4 * * * cd /x && run.sh"]}]}
    found = {"cron": [{"expression": "0 4 * * * cd /x && run.sh"}, {"expression": "old line"},
                      {"expression": "1 1 * * * brand new"}], "systemd": []}
    fn = getattr(lr, "undeclared_schedulers", None) or getattr(lr, "find_undeclared", None)
    assert fn is not None, "gate matcher not found"
    out = fn(reg, found)
    assert [o["expression"] for o in out] == ["1 1 * * * brand new"]
