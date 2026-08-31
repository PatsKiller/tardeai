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

# The scoreboard JSON has no schema file, so this is the test's declared
# vocabulary rather than a copy of the document's current contents. Membership
# is the assertion; WHICH member is the document's business.
#
# Pinning the member instead -- `status == "DONE"` -- is shape (b) with a string
# in place of a number, and it is worse than the numeric case. A stale number is
# inert; a pinned status actively resists an honest downgrade. On 2026-08-30 R2
# moved P4 to NEEDS_REVERIFICATION because its evidence could not be regenerated
# as published, and three tests went red -- not because anything regressed, but
# because someone told the truth. A test must go red when reality regresses, not
# when the document catches up with it.
PACKAGE_STATUSES = {
    "DONE",
    "NEEDS_REVERIFICATION",
    "IN_PROGRESS",
    "PENDING",
    "BLOCKED",
    "SKIP",
    "FAIL",
}
SURFACE_STATES = {"EXITED", "ENTERED", "NOT_ENTERED", "UNKNOWN"}


def _packages(data: dict) -> dict:
    return data["packages"]


def _outstanding(pkgs: dict) -> list[str]:
    """Package ids whose status is anything other than DONE."""
    return sorted(p for p, v in pkgs.items() if v.get("status") != "DONE")


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
    # Recorded probe results, not policy floors. Pinned to 200 they could only
    # fail when the document honestly recorded an outage. That a failing probe
    # is incompatible with claiming completion is asserted as a cross-field
    # rule below, which is the part that actually matters.
    for probe in ("health", "cio"):
        assert isinstance(now[probe], int), (probe, now[probe])
        assert 100 <= now[probe] <= 599, (probe, now[probe])
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
    # An observed state of a live surface, not a required one. Pinned to
    # "EXITED" it could only fail when the document honestly recorded a
    # re-entry. (A real producer for this exists --
    # scripts/lib/cio_identity_confidence_census.py computes
    # schg_surface_a_exited -- but the scoreboard is hand-stamped and nothing
    # wires the two together; see the wiring note in the final report.)
    assert now["schg_surface_a"] in SURFACE_STATES, now["schg_surface_a"]
    # Progress cursor: a non-empty token. Whether it may say COMPLETE is a
    # cross-field question, asserted in
    # test_completion_is_claimed_only_when_nothing_is_outstanding.
    assert isinstance(now["phase_cursor"], str) and now["phase_cursor"].strip()
    # A commit pin, not a measurement -- but pinning the literal made the test
    # track the document instead of the tree (it still asserted "015a7891"
    # while origin/main was 9d92b6e0). Assert the shape and the snapshot's
    # internal agreement; reality is checked in test_current_pin_is_a_real_commit.
    pin = now["current_pin"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", pin), pin
    assert now["origin_main_full"].startswith(pin), (pin, now["origin_main_full"])
    assert now["origin_main"] == pin
    # Whether this snapshot was taken pre-promote is a fact about the snapshot,
    # not a requirement on it. Pinning True meant the test would fail the moment
    # a post-promote scoreboard was recorded honestly.
    assert isinstance(now.get("this_package_pre_promote"), bool)
    gc = now.get("gap_closeout") or {}
    # Which bucket a gap sits in is an adjudication and may legitimately change
    # -- a gap can reopen. What must hold regardless: the buckets are lists of
    # gap ids, and no gap is claimed closed and partial at the same time.
    closed = gc.get("closed_mitigated") or []
    partial = gc.get("partial") or []
    assert isinstance(closed, list) and isinstance(partial, list)
    assert all(isinstance(g, str) and g.strip() for g in [*closed, *partial])
    assert not (set(closed) & set(partial)), set(closed) & set(partial)
    assert closed or partial, "gap register records no adjudicated gaps at all"
    # Policy floors, not adjudications. These are the values the register was
    # opened to defend; any other value is forbidden rather than merely
    # different, so pinning them is correct.
    assert gc.get("claim_99_99") is False
    assert gc.get("notify_on") is False
    assert isinstance(gc.get("canary"), str) and gc["canary"].strip()
    pkgs = _packages(data)
    assert pkgs["P0"]["status"] in PACKAGE_STATUSES, pkgs["P0"]["status"]
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


def test_all_packages_p0_p9_present_with_pr_and_regenerable_proof():
    """Every package is present, attributed, and its proof paths exist.

    Renamed from ..._done_with_pr_and_proof. The old name was the defect: it
    required every package to be DONE and required the markdown to contain the
    word COMPLETE, so an honest downgrade turned it red. It asserted the
    verdict; this asserts the evidence, which is the part a test can actually
    check. Whether the evidence earns a DONE is the coordinator's call.
    """
    data = json.loads(JS.read_text(encoding="utf-8"))
    pkgs = _packages(data)
    for pid in REQUIRED_PACKAGES:
        assert pid in pkgs, pid
        assert pkgs[pid]["status"] in PACKAGE_STATUSES, (pid, pkgs[pid]["status"])
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


def test_p6_p7_p8_packages_carry_proof():
    data = json.loads(JS.read_text(encoding="utf-8"))
    pkgs = _packages(data)
    for pid in ("P6", "P7", "P8"):
        assert pkgs[pid]["status"] in PACKAGE_STATUSES, (pid, pkgs[pid]["status"])
        assert pkgs[pid].get("proof"), pid
    assert (DIL / "P6_COUNCIL_DETERMINISM_2026-08-30.md").is_file()
    assert (DIL / "P7_NOTIFICATION_MATRIX_2026-08-30.md").is_file()
    assert (DIL / "P8_MBI_PARTITION_2026-08-30.md").is_file()
    assert data["now"]["telegram_sent"] is False
    assert data["memory_behavior_influence"] == 0


def test_completion_is_claimed_only_when_nothing_is_outstanding():
    """COMPLETE is a claim about every package at once; check it as one.

    This is what `phase_cursor in {"COMPLETE", "DONE"}` should always have
    been. Pinned to the happy path it could only fail when the cursor honestly
    recorded that work remained -- which is exactly what happened on
    2026-08-30. Inverted, it catches the state that is actually dangerous: a
    scoreboard still claiming COMPLETE while a package is unverified or a
    probe is down. That failure means someone forgot to downgrade the cursor,
    which is a real defect, and it stays green through an honest downgrade.
    """
    data = json.loads(JS.read_text(encoding="utf-8"))
    now = data["now"]
    outstanding = _outstanding(_packages(data))
    unhealthy = [p for p in ("health", "cio") if now.get(p) != 200]

    if now["phase_cursor"] == "COMPLETE":
        assert not outstanding, (
            f"phase_cursor claims COMPLETE while these packages are not DONE: "
            f"{outstanding}"
        )
        assert not unhealthy, (
            f"phase_cursor claims COMPLETE while these probes are not 200: "
            f"{ {p: now.get(p) for p in unhealthy} }"
        )
    else:
        # The converse: a cursor that is not COMPLETE should be able to say why.
        assert outstanding or unhealthy, (
            f"phase_cursor is {now['phase_cursor']!r} but every package is DONE "
            "and every probe is 200; the cursor and the packages disagree"
        )


def test_a_package_that_is_not_done_explains_itself():
    """A downgrade must carry a reason, a date, and an author.

    The mirror image of the defect this file was cleaned of. Removing
    `status == "DONE"` means the suite no longer resists an honest downgrade;
    this makes sure it does not accept a silent one either. A status flipped
    with no note is the thing to be afraid of now.
    """
    pkgs = _packages(json.loads(JS.read_text(encoding="utf-8")))
    for pid in _outstanding(pkgs):
        pkg = pkgs[pid]
        note = pkg.get("status_note") or pkg.get("finding_note")
        assert note and str(note).strip(), f"{pid} is {pkg['status']} with no stated reason"
        assert pkg.get("status_changed_at"), f"{pid} is {pkg['status']} with no change date"
        assert pkg.get("status_changed_by"), f"{pid} is {pkg['status']} with no author"


def test_a_declared_evidence_producer_exists():
    """Where a package names the producer of its evidence, that file is real.

    This is the assertion that would have caught P4: it was awarded DONE on an
    evidence JSON carrying four keys its named producer does not emit. A test
    cannot re-adjudicate the award, but it can insist the named producer is a
    real file rather than a citation, so the claim stays falsifiable.
    """
    pkgs = _packages(json.loads(JS.read_text(encoding="utf-8")))
    declared = {p: v["evidence_producer"] for p, v in pkgs.items() if v.get("evidence_producer")}
    for pid, producer in declared.items():
        assert (ROOT / producer).is_file(), f"{pid} names a producer that does not exist: {producer}"
