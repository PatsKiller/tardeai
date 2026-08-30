"""Diligence scoreboard + master plan kickoff contract."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.md"
JS = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.json"
PLAN = ROOT / "docs" / "audits" / "CIO_PLATFORM_DILIGENCE_MASTER_PLAN_2026-08-30.md"
GAPS = ROOT / "docs" / "audits" / "CIO_DILIGENCE_GAP_REGISTER.md"
DIL = ROOT / "docs" / "audits" / "diligence"


def test_diligence_files_exist():
    assert MD.is_file()
    assert JS.is_file()
    assert PLAN.is_file()
    assert GAPS.is_file()
    assert "READ_ONLY_ADVISORY" in MD.read_text(encoding="utf-8")
    assert "Phase 1" in PLAN.read_text(encoding="utf-8")


def test_diligence_json_contract():
    data = json.loads(JS.read_text(encoding="utf-8"))
    assert data.get("authority") == "READ_ONLY_ADVISORY"
    assert data.get("memory_behavior_influence") in {0, "0"}
    now = data["now"]
    assert now["health"] == 200
    assert now["cio"] == 200
    assert "lineage" in now
    # These fields are readings of live, append-only stores -- not constants.
    # Asserting equality against a fixed literal is green forever by
    # construction: on 2026-08-30 this test still asserted 406 / 54.0 while the
    # live producer (scripts.lib.cio_lineage_health.completion_report) reported
    # 453 / 808 / 56.06%, and it passed. Restamping the literals to 453 would
    # reproduce the same defect with fresher-looking numbers. Assert instead
    # what cannot drift: the snapshot's own arithmetic, and its bounds. The
    # live-store comparison lives in
    # test_lineage_snapshot_is_bounded_by_the_live_producer below.
    lin = now["lineage"]
    workflows = lin["workflows"]
    complete = lin["complete_to_checkpoint"]
    assert isinstance(workflows, int) and workflows >= 1
    assert isinstance(complete, int)
    assert 0 <= complete <= workflows
    assert lin["complete_pct"] == round(complete / workflows * 100, 1)
    # Same reasoning: a census percentage over a growing event population. The
    # invariant this number exists to defend is that it is NOT the fabricated
    # 99.99% the gap register was opened about.
    weighted = now["event_lifecycle"]["weighted_full_lifecycle_pct"]
    assert isinstance(weighted, (int, float))
    assert 0.0 <= weighted < 99.99
    assert now["event_lifecycle"]["claim_99_99"] is False
    identity_pct = now["identity_production_resolvable_pct"]
    assert isinstance(identity_pct, (int, float))
    assert 0.0 <= identity_pct <= 100.0
    assert now["schg_surface_a"] == "EXITED"
    assert now["phase_cursor"] in {"COMPLETE", "DONE"}
    # A commit pin, not a measurement -- but pinning the literal made the test
    # track the document instead of the tree (it still asserted "015a7891"
    # while origin/main was 9d92b6e0). Assert the shape and the snapshot's
    # internal agreement; reality is checked in test_current_pin_is_a_real_commit.
    pin = now["current_pin"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", pin), pin
    assert now["origin_main_full"].startswith(pin), (pin, now["origin_main_full"])
    assert now["origin_main"] == pin
    assert now.get("this_package_pre_promote") is True
    gc = now.get("gap_closeout") or {}
    assert "G-AUTH-01" in gc.get("closed_mitigated", [])
    assert "G-LOOP-01" in gc.get("partial", [])
    assert "G-NOTIFY-01" in gc.get("partial", [])
    assert gc.get("claim_99_99") is False
    assert gc.get("notify_on") is False
    assert gc.get("canary") == "DEFERRED_OPS"
    pkgs = data["packages"]
    assert pkgs["P0"]["status"] == "DONE"
    assert "P1-WS1" in pkgs
    assert "P9" in pkgs
    assert data["drive"]["status"] in {"OK", "FAIL"}


def test_lineage_snapshot_is_bounded_by_the_live_producer():
    """Regenerate the metric and check the snapshot against it.

    The scoreboard's lineage block is a point-in-time reading of an
    append-only JSONL store, so it cannot be asserted equal to any constant:
    the store grew from 286 to 808 workflows in the 36 hours around this
    snapshot, and the file itself records no timestamp for the reading, so the
    exact value is not even reproducible by replaying to a shared as_of.

    What IS structurally guaranteed: the store is append-only and keyed by
    workflow_id, so the count of distinct workflows never decreases. A snapshot
    claiming MORE workflows than the producer reports right now was not
    measured -- it was written. That is the assertion worth having.
    """
    from scripts.lib.cio_lineage import default_lineage_path
    from scripts.lib.cio_lineage_health import completion_report

    store = default_lineage_path()
    if not store.exists():
        pytest.skip(f"live lineage store not present: {store}")
    live = completion_report()
    if not live.get("workflows"):
        pytest.skip(f"live lineage store empty: {store}")

    snap = json.loads(JS.read_text(encoding="utf-8"))["now"]["lineage"]
    assert snap["workflows"] <= live["workflows"], (
        f"snapshot claims {snap['workflows']} workflows but the live store "
        f"reports {live['workflows']}; an append-only store cannot shrink"
    )
    assert snap["complete_to_checkpoint"] <= live["workflows"], (
        f"snapshot claims {snap['complete_to_checkpoint']} completions against "
        f"a live population of {live['workflows']}"
    )


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True,
    )


def test_current_pin_is_a_real_commit():
    """The pinned SHA must exist in this repository, not merely look like one.

    Skipped where the object genuinely cannot be present -- no git, or a
    shallow clone that does not carry history -- rather than asserted anyway.
    A skip states that nothing was checked; a literal comparison against a
    copy of the same SHA would have claimed a check it never made.
    """
    probe = _git("rev-parse", "--is-shallow-repository")
    if probe.returncode != 0:
        pytest.skip("not a git checkout")
    if probe.stdout.strip() == "true":
        pytest.skip("shallow clone: commit objects are not all present")

    pin = json.loads(JS.read_text(encoding="utf-8"))["now"]["origin_main_full"]
    proc = _git("cat-file", "-t", pin)
    assert proc.returncode == 0, f"pinned SHA {pin} is not an object here: {proc.stderr}"
    assert proc.stdout.strip() == "commit", f"{pin} is a {proc.stdout.strip()}, not a commit"


REQUIRED_PACKAGES = (
    "P0",
    "P1-WS1",
    "P1-WS2",
    "P1-WS3",
    "P2-WS4",
    "P2-WS5",
    "P3",
    "P4",
    "P5",
    "P6",
    "P7",
    "P8",
    "P9",
)

PACKAGE_PRS = {
    "P0": 681,
    "P1-WS1": 686,
    "P1-WS2": 685,
    "P1-WS3": 689,
    "P2-WS4": 688,
    "P2-WS5": 688,
    "P3": 682,
    "P4": 687,
    "P5": 687,
    "P6": 683,
    "P7": 683,
    "P8": 683,
    "P9": 684,
}


def test_all_packages_p0_p9_done_with_pr_and_proof():
    data = json.loads(JS.read_text(encoding="utf-8"))
    pkgs = data["packages"]
    md = MD.read_text(encoding="utf-8")
    assert "COMPLETE" in md or "all packages P0–P9 DONE" in md
    for pid in REQUIRED_PACKAGES:
        assert pid in pkgs, pid
        assert pkgs[pid]["status"] == "DONE", pid
        assert pkgs[pid].get("pr") == PACKAGE_PRS[pid], pid
        assert pkgs[pid].get("sha"), pid
        assert pkgs[pid].get("proof"), pid
        proofs = pkgs[pid]["proof"]
        paths = proofs if isinstance(proofs, list) else []
        for p in paths:
            if "/" in str(p) and not str(p).startswith("weighted_"):
                assert (ROOT / p).is_file(), f"missing proof path {p} for {pid}"
    assert data["now"]["telegram_sent"] is False
    assert data["memory_behavior_influence"] == 0
    assert data["now"].get("packages_done_out_of_order") in ([], None)
    gaps = GAPS.read_text(encoding="utf-8")
    assert "CLOSED (mitigated)" in gaps
    assert "PARTIAL" in gaps
    assert "#695" in gaps and "#702" in gaps
    assert "no fake 99.99%" in gaps.lower() or "no 99.99%" in gaps.lower()
    assert "DEFERRED_OPS" in gaps
    md = MD.read_text(encoding="utf-8")
    assert "PR-G" in md or "gap-register closeout" in md.lower()
    assert "DEFERRED_OPS" in md


def test_p6_p7_p8_packages_done_with_proof():
    data = json.loads(JS.read_text(encoding="utf-8"))
    pkgs = data["packages"]
    for pid in ("P6", "P7", "P8"):
        assert pkgs[pid]["status"] == "DONE", pid
        assert pkgs[pid].get("proof"), pid
    assert (DIL / "P6_COUNCIL_DETERMINISM_2026-08-30.md").is_file()
    assert (DIL / "P7_NOTIFICATION_MATRIX_2026-08-30.md").is_file()
    assert (DIL / "P8_MBI_PARTITION_2026-08-30.md").is_file()
    assert data["now"]["telegram_sent"] is False
    assert data["memory_behavior_influence"] == 0
