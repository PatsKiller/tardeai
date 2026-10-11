"""`_cutover.py --lane` multi-line lanes (2026-10-10, JOB_REDUCTION_DEEP_PASS decision D-3).

A lane with up to MAX_LANE_LINES cron slots (the dispatcher's `dispatch.cron` cap) retires every slot in
ONE cutover: `scheduler.match` as a list (each item exactly one live line) or a string with
`--expect-lines K`. Every single-line safety check is kept; rollback uncomments exactly the tagged lines
and refuses unless their count equals the receipt's. Hermetic: fake `crontab` (CRONTAB_CMD), tmp code
root/registry, tmp state root and lock. The single-line contract keeps its own tests in
tests/test_n8n_lane_cutover_20261008.py.

COVERS = ["scripts/pipelines/cutover/_cutover.py", "scripts/lib/lane_dispatch.py"]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_n8n_lane_cutover_20261008 import (  # noqa: E402
    OTHER,
    _env,
    _fake_crontab,
    _last,
    _receipts,
    _registry,
    _run,
    _serialise,
)

LANE = "fixture-multi"
SCRIPT = "scripts/fixture_multi.py"
L1 = f"5 9 * * 1-5 cd $PROJ && $PY {SCRIPT} --mode open >> logs/fixture_multi.log 2>&1"
L2 = f"0 12 * * 1-5 cd $PROJ && $PY {SCRIPT} --mode mid >> logs/fixture_multi.log 2>&1"
L3 = f"30 20 * * 0 cd $PROJ && $PY {SCRIPT} --mode week >> logs/fixture_multi_weekly.log 2>&1"
TAG = f"# RETIRED 2026-10-08 n8n-cutover {LANE} "


def _row(match, dispatch=None):
    row = {
        "lane_id": LANE,
        "owner": "platform",
        "scheduler": {"kind": "cron", "expression": "multi-slot fixture_multi.py", "match": match},
        "expected_cadence_hours": 24.0,
        "state": "ACTIVE",
        "output_signal": {"kind": "file_mtime", "path": "data/runtime/fixture_multi.json"},
    }
    if dispatch is not None:
        row["dispatch"] = dispatch
    return row


def _root(tmp_path: Path, row) -> Path:
    root = tmp_path / "code"
    (root / "config").mkdir(parents=True)
    doc = {"schema": "LaneRegistry@v1", "authority": "READ_ONLY_ADVISORY", "lanes": [row], "undeclared_baseline": []}
    (root / "config" / "lane_registry.json").write_text(_serialise(doc), encoding="utf-8")
    return root


def _setup(tmp_path, match, lines, dispatch=None):
    root = _root(tmp_path, _row(match, dispatch))
    fake, store = _fake_crontab(tmp_path)
    store.write_text("\n".join(lines) + "\n")
    return root, store, _env(tmp_path, fake, root)


def test_cap_mirrors_the_dispatch_cron_slot_cap():
    from scripts.lib import lane_dispatch
    from scripts.pipelines.cutover import _cutover

    assert _cutover.MAX_LANE_LINES == lane_dispatch.DISPATCH_CRON_MAX_SLOTS == 8


def test_list_match_retires_every_line_in_one_write_and_rolls_back(tmp_path):
    match = ["--mode open", "--mode mid", "--mode week"]
    root, store, env = _setup(tmp_path, match, [OTHER, L1, L2, L3])
    reg_before = (root / "config" / "lane_registry.json").read_text(encoding="utf-8")
    # dry run: names all three, writes only its receipt
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "dispatcher", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("would comment") == 3 and store.read_text().splitlines() == [OTHER, L1, L2, L3]
    assert not (tmp_path / "backups").exists()
    # apply
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "dispatcher", "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert store.read_text().splitlines() == [OTHER, TAG + L1, TAG + L2, TAG + L3]
    assert len(list((tmp_path / "backups").glob("crontab-*-pre-cutover-lane-*"))) == 1  # one backup, one write
    sched = next(r for r in _registry(root)["lanes"] if r["lane_id"] == LANE)["scheduler"]
    assert sched == {"kind": "n8n", "expression": "dispatcher", "match": match, "cadence": "5 9 * * 1-5",
                     "cadence_slots": ["5 9 * * 1-5", "0 12 * * 1-5", "30 20 * * 0"], "stage": "cutover"}
    rc = _last(tmp_path)
    assert rc["applied"] is True and rc["line_before"] is None and len(rc["lines"]) == 3
    assert [e["before"] for e in rc["lines"]] == [L1, L2, L3] and [e["after"] for e in rc["lines"]] == [TAG + L1, TAG + L2, TAG + L3]
    # rollback: all three back, registry byte-identical
    r = _run("rollback_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert store.read_text().splitlines() == [OTHER, L1, L2, L3]
    assert (root / "config" / "lane_registry.json").read_text(encoding="utf-8") == reg_before
    assert len(_last(tmp_path)["lines"]) == 3


def test_string_match_hitting_several_lines_needs_expect_lines(tmp_path):
    root, store, env = _setup(tmp_path, SCRIPT, [L1, L2, OTHER])
    reg_before = (root / "config" / "lane_registry.json").read_bytes()
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "found on 2 uncommented line(s) (need exactly 1)" in r.stdout
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--expect-lines", "3", "--apply", env=env)
    assert r.returncode == 2 and "need exactly 3, --expect-lines 3" in r.stdout
    assert store.read_text().splitlines() == [L1, L2, OTHER]
    assert (root / "config" / "lane_registry.json").read_bytes() == reg_before
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--expect-lines", "2", "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert store.read_text().splitlines() == [TAG + L1, TAG + L2, OTHER]
    assert _registry(root)["lanes"][0]["scheduler"]["match"] == SCRIPT


def test_more_lines_than_the_cap_refuse(tmp_path):
    lines = [f"{m} 9 * * 1-5 cd $PROJ && $PY {SCRIPT} --slot {m}" for m in range(9)]
    root, store, env = _setup(tmp_path, SCRIPT, lines)
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--expect-lines", "9", "--apply", env=env)
    assert r.returncode == 2 and "outside 1..8" in r.stdout
    root2 = tmp_path / "b"
    root2.mkdir()
    root2, store2, env2 = _setup(root2, [f"--slot {m}" for m in range(9)], lines)
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env2)
    assert r.returncode == 2 and "at most 8 lines per lane" in r.stdout
    assert store.read_text().splitlines() == lines and store2.read_text().splitlines() == lines


def test_list_items_must_each_hit_exactly_one_distinct_line(tmp_path):
    root, store, env = _setup(tmp_path, ["--mode open", "--mode nope"], [L1, L2])
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "match item '--mode nope' found on 0 uncommented line(s)" in r.stdout
    b = tmp_path / "b"
    b.mkdir()
    _, store_b, env_b = _setup(b, ["--mode open", "fixture_multi.log"], [L1, L2])
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env_b)
    assert r.returncode == 2 and "match item 'fixture_multi.log' found on 2 uncommented line(s)" in r.stdout
    c = tmp_path / "c"
    c.mkdir()
    _, store_c, env_c = _setup(c, ["--mode open", "open >>"], [L1, L2])
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env_c)
    assert r.returncode == 2 and "hit the same crontab line" in r.stdout
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--expect-lines", "2", "--apply", env=env_c)
    assert r.returncode == 2 and "--expect-lines applies to a string" in r.stdout
    for s in (store, store_b, store_c):
        assert s.read_text().splitlines() == [L1, L2]
    assert all(p.name.endswith("-refused.json") for p in _receipts(tmp_path))


def test_a_partly_tagged_lane_refuses(tmp_path):
    root, store, env = _setup(tmp_path, ["--mode open", "--mode mid"], [TAG + L1, L2])
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 2 and "already tagged" in r.stdout
    assert store.read_text().splitlines() == [TAG + L1, L2]


def test_dispatch_cron_must_equal_the_retired_slots(tmp_path):
    block = {"cron": ["5 9 * * 1-5"]}
    root, store, env = _setup(tmp_path, ["--mode open", "--mode mid"], [L1, L2], dispatch=block)
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "dispatcher", "--apply", env=env)
    assert r.returncode == 2 and "a slot would be lost or added" in r.stdout
    assert store.read_text().splitlines() == [L1, L2]


def test_rollback_refuses_on_count_mismatch_and_double_schedule(tmp_path):
    root, store, env = _setup(tmp_path, ["--mode open", "--mode mid"], [L1, L2])
    assert _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env).returncode == 0
    # one tagged line went missing: count != receipt
    store.write_text(TAG + L1 + "\n")
    r = _run("rollback_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 2 and "found 1 line(s) tagged" in r.stdout and "need exactly 2" in r.stdout
    # someone re-added one slot by hand: uncommenting would double-schedule
    store.write_text("\n".join([TAG + L1, TAG + L2, L2]) + "\n")
    r = _run("rollback_lane.sh", LANE, "--apply", env=env)
    assert r.returncode == 2 and "already live" in r.stdout
    assert store.read_text().splitlines() == [TAG + L1, TAG + L2, L2]
    assert _registry(root)["lanes"][0]["scheduler"]["kind"] == "n8n"


def test_single_line_receipt_shape_is_unchanged(tmp_path):
    root, store, env = _setup(tmp_path, "--mode open", [L1, L2])
    r = _run("cutover_lane.sh", LANE, "--workflow-id", "wf", "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    rc = _last(tmp_path)
    assert "lines" not in rc and rc["line_before"] == L1 and rc["line_after"] == TAG + L1
    assert _registry(root)["lanes"][0]["scheduler"] == {"kind": "n8n", "expression": "wf", "match": "--mode open",
                                                       "cadence": "5 9 * * 1-5"}
