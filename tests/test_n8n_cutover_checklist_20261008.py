"""Cutover checklist renders with and without evidence; every input is optional.

Evidence is planted under tmp_path only (check_test_host_paths forbids literal host paths).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import n8n_cutover_checklist as cl

LANE = "n8n-lab-watchdog"


def _lane() -> dict:
    return next(lane for lane in cl.LANES if lane["lane_id"] == LANE)


def test_renders_with_no_evidence_at_all(tmp_path):
    text = cl.render(tmp_path, tmp_path, [_lane()], LANE)
    assert f"# n8n cutover checklist — {LANE}" in text
    assert text.count("- [ ]") == 12 and "- [x]" not in text
    assert "none in data/runtime/n8n_runs" in text
    assert "n8n_lane_readiness_last.json absent" in text
    assert "lane not in INDEX.json" in text or "INDEX.json absent" in text


def _plant(root: Path, rel: str, obj) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_ticks_follow_the_evidence(tmp_path):
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    # workflows committed
    _plant(
        repo,
        "docs/implementation/n8n-parallel/workflows/generated/INDEX.json",
        {"lanes": [{"lane_id": LANE, "shadow_file": f"{LANE}-shadow.json", "live_file": f"{LANE}.json"}]},
    )
    _plant(repo, f"docs/implementation/n8n-parallel/workflows/generated/{LANE}-shadow.json", {})
    _plant(repo, f"docs/implementation/n8n-parallel/workflows/generated/{LANE}.json", {})
    # registry row flipped to n8n
    _plant(state, "config/lane_registry.json", {"lanes": [{"lane_id": LANE, "scheduler": {"kind": "n8n"}}]})
    # run receipts: one dry_run done, one live done, one unrelated lane
    _plant(
        state, "data/runtime/n8n_runs/a.json", {"lane_id": LANE, "mode": "dry_run", "state": "RUN_DONE", "exit_code": 0}
    )
    _plant(
        state, "data/runtime/n8n_runs/b.json", {"lane_id": LANE, "mode": "live", "state": "RUN_DONE", "exit_code": 0}
    )
    _plant(state, "data/runtime/n8n_runs/c.json", {"lane_id": "other", "mode": "live", "state": "RUN_FAILED"})
    # cutover receipts: dry + apply, rollback dry only
    _plant(state, "data/runtime/n8n_cutover/1.json", {"lane_id": LANE, "action": "cutover", "dry_run": True})
    _plant(state, "data/runtime/n8n_cutover/2.json", {"lane_id": LANE, "action": "cutover", "dry_run": False})
    _plant(state, "data/runtime/n8n_cutover/3.json", {"lane_id": LANE, "action": "rollback", "dry_run": True})
    # readiness + board
    _plant(state, "data/runtime/n8n_lane_readiness_last.json", {"lanes": [{"lane_id": LANE, "verdict": "READY"}]})
    _plant(
        state,
        "data/runtime/n8n_migration_board_last.json",
        {
            "rows": {
                LANE: {
                    "phase": "cutover",
                    "rollback_ready": True,
                    "output_signal_fresh": True,
                    "output_signal_age_h": 0.1,
                }
            }
        },
    )
    items = {i["step"]: i["done"] for i in cl.lane_items(state, repo, _lane())}
    assert items == {
        "workflows": True,
        "registry_row": True,
        "shadow": True,
        "canary": True,
        "readiness": True,
        "cutover_dry": True,
        "cutover_apply": True,
        "registry_n8n": True,
        "rollback_dry": True,
        "rollback_real": False,
        "board": True,
        "natural_fire": True,
    }
    text = cl.render(state, repo, [_lane()], LANE)
    assert text.count("- [x]") == 11 and text.count("- [ ]") == 1


def test_failed_live_receipt_blocks_canary_and_garbage_files_are_ignored(tmp_path):
    state = tmp_path
    _plant(state, "data/runtime/n8n_runs/ok.json", {"lane_id": LANE, "mode": "live", "state": "RUN_DONE"})
    _plant(
        state,
        "data/runtime/n8n_runs/bad.json",
        {"lane_id": LANE, "mode": "live", "state": "RUN_SKIPPED_LOCK", "exit_code": 0},
    )
    (state / "data/runtime/n8n_runs/junk.json").write_text("{not json", encoding="utf-8")
    items = {i["step"]: i for i in cl.lane_items(state, state, _lane())}
    assert items["canary"]["done"] is False
    assert "1 live ok, 1 not ok" in items["canary"]["evidence"]


def test_cli_lane_tranche_and_write(tmp_path, capsys):
    assert cl.main(["--lane", LANE, "--state-root", str(tmp_path), "--repo-root", str(tmp_path)]) == 0
    assert LANE in capsys.readouterr().out
    assert cl.main(["--tranche", "N1", "--state-root", str(tmp_path), "--repo-root", str(tmp_path), "--write"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["lanes"] == 9
    written = Path(out["wrote"])
    assert written == tmp_path / "data" / "runtime" / "n8n_cutover_checklist_N1.md"
    assert "across 9 lane(s)" in written.read_text(encoding="utf-8")
    assert cl.main(["--lane", "no-such-lane", "--state-root", str(tmp_path)]) == 2
