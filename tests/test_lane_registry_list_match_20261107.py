"""find_undeclared reads a list `match` item by item (2026-11-07).

The cutover planner clears `match_hits_2_lines` with a per-line match list. The gate used str(match), a Python repr
that matches no crontab line, so both lines of research-intelligence-queue read as undeclared.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_registry as LR  # noqa: E402

LINES = [
    "45 16 * * 1-5 cd $PROJ && flock -n /tmp/q.lock $PY scripts/q.py --drain",
    "40 2 * * * cd $PROJ && bash wrap.sh --official -- flock -n /tmp/q.lock $PY scripts/q.py --drain",
]
FOUND = {"cron": [{"expression": l} for l in LINES]}


def _reg(match, kind="cron"):
    return {"lanes": [{"lane_id": "q", "scheduler": {"kind": kind, "expression": "45 16 * * 1-5", "match": match}}]}


def test_each_list_item_declares_its_line():
    reg = _reg(["&& flock -n /tmp/q.lock $PY scripts/q.py", "--official -- flock -n /tmp/q.lock $PY scripts/q.py"])
    assert LR.find_undeclared(reg, FOUND, n8n_known_ids=set()) == []


def test_a_list_item_declares_only_the_lines_it_hits():
    reg = _reg(["&& flock -n /tmp/q.lock $PY scripts/q.py"])
    assert LR.find_undeclared(reg, FOUND, n8n_known_ids=set()) == [{"kind": "cron", "expression": LINES[1]}]


def test_a_string_match_is_unchanged_and_a_systemd_row_never_declares_cron():
    assert LR.find_undeclared(_reg("scripts/q.py"), FOUND, n8n_known_ids=set()) == []
    out = LR.find_undeclared(_reg(["scripts/q.py"], kind="systemd"), FOUND, n8n_known_ids=set())
    assert [o["expression"] for o in out] == LINES


def test_reconcile_line_mapping_uses_the_same_rule():
    import reconcile_lane_registry as R
    reg = _reg(["&& flock -n /tmp/q.lock $PY scripts/q.py", "--official -- flock -n /tmp/q.lock $PY scripts/q.py"])
    assert R.declarations(reg["lanes"][0]) == list(reg["lanes"][0]["scheduler"]["match"])
    assert R.line_mapping(reg, LINES) == {LINES[0]: ["q"], LINES[1]: ["q"]}
