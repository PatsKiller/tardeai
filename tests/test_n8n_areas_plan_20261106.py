"""n8n 0.1g: the area mapping and the read-only plan, hermetic."""
from __future__ import annotations

from pathlib import Path

from scripts import n8n_areas_plan as p

AREAS = {"Trading alerts", "Risk", "Rotation", "Data feeds", "Health & watchdogs", "Digests", "Platform"}


def test_seven_areas_and_every_name_once():
    areas = p.load_areas()
    assert set(areas) == AREAS
    names = [n for v in areas.values() for n in v]
    assert len(names) == len(set(names)) == 49


def test_plan_ok_and_moves_only_root_workflows():
    areas = p.load_areas()
    live = {n: None for v in areas.values() for n in v}
    live["tradeai-dispatcher"] = "folder1"
    res = p.plan(areas, live)
    assert res["ok"] and res["in_root_list"] == 48 and "tradeai-dispatcher" not in res["to_move"]
    assert res["to_move"]["tradeai-incident-router"] == "Health & watchdogs"


def test_unmapped_absent_and_duplicate_are_reported():
    areas = {"A": ["x", "y"], "B": ["y"]}
    res = p.plan(areas, {"x": None, "z": None})
    assert not res["ok"] and res["unmapped"] == ["z"] and res["mapped_but_absent"] == ["y"] and res["duplicated"] == ["y"]


def test_script_never_writes():
    src = Path(p.__file__).read_text(encoding="utf-8").lower()
    for verb in ("insert into", "update workflow", "delete from", "drop "):
        assert verb not in src.split('"""', 2)[2]
