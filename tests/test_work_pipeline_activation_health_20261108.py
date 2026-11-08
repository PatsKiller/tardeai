"""LQ-20261107-1262: a live-integration activation flips CURRENT without writing a deploy receipt.

So ``deploy_receipt.json`` keeps naming the build that last used the promote path, the pipeline's ``verified``
stage can never be reached, and ``/v3/system/releases`` says "activated another way". These tests pin the fix:
the served build is believed when the host's own activation record converges on it — the release directory's
three pins agree, ``CURRENT`` still resolves to it, and ``ACTIVE_RELEASE`` names it — with the CURRENT symlink's
mtime as the activation clock and a basis that never claims a deploy health check. A receipt naming another build
neither proves nor paints the served build; a receipt naming the served build stays authoritative in both
directions, including ``ok False``. Hermetic: temp release bases and state roots only.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import agent_claim_lifecycle as LC  # noqa: E402
from scripts.lib import work_pipeline as W  # noqa: E402
from scripts.lib import work_pipeline_sources as WPS  # noqa: E402

SERVED = "4" * 40
OLDER = "9" * 40
NOW = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
FLIPPED = NOW - timedelta(hours=3)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ago(**kw) -> str:
    return iso(NOW - timedelta(**kw))


def receipt(sha: str | None = OLDER, *, ok: bool = True, at: datetime | None = None) -> dict:
    return {"schema": "CioExactMainDeployReceipt@v2", "ok": ok, "mode": "promote",
            "health": "ok" if ok else "degraded", "rolled_back": False,
            "deployed_sha": sha, "at": iso(at or (NOW - timedelta(days=1)))}


def host(tmp_path, *, served: str = SERVED, pins: dict | None = None, with_current: bool = True,
         active_release: str | None = None, expected_release: str | None = None,
         with_active_file: bool = True, deploy_receipt: dict | None = None) -> tuple[Path, Path, Path]:
    """A synthetic release base: one activated-looking release directory, a CURRENT symlink and both pin files."""
    base = tmp_path / "releases"
    base.mkdir()
    rel = base / f"{served[:9]}-live-integration-20261108-160000"
    rel.mkdir()
    for name in ("BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT"):
        (rel / name).write_text(f"{(pins or {}).get(name, served)}\n")
    if with_current:
        os.symlink(rel, base / "CURRENT")
        ts = FLIPPED.timestamp()
        os.utime(base / "CURRENT", (ts, ts), follow_symlinks=False)
    if with_active_file:
        (base / "ACTIVE_RELEASE").write_text(str(active_release or rel) + "\n")
    (base / "EXPECTED_RELEASE").write_text(str(expected_release or rel) + "\n")
    state = tmp_path / "state"
    state.mkdir()
    if deploy_receipt is not None:
        # nosemgrep: tq-py-nonatomic-store-write -- synthetic deploy_receipt.json under pytest tmp_path, read back immediately, never a store
        (state / "deploy_receipt.json").write_text(json.dumps(deploy_receipt))
    return base, state, rel


def serving_of(base: Path, state: Path) -> dict:
    return LC.ReleaseReader(releases_base=base, deploy_state_dir=state,
                            is_ancestor=lambda a, b: None).serving()


def merged(served: str = SERVED, **extra) -> dict:
    return {"number": 2002, "title": "Synthetic merge", "state": "merged", "merged_at": ago(hours=5),
            "merge_sha": "8" * 40, "branch": "wt/test", "author": "agent", "ci": None, **extra}


def released_fact(at: str | None, sha: str = SERVED) -> dict:
    return {"at": at, "sha": sha, "basis": "served CURRENT/BUILD_SHA"}


# ------------------------------------------------------------------------------------------ the activation clock


def test_serving_since_is_the_current_flip_when_the_receipt_names_another_build(tmp_path):
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(OLDER))
    srv = serving_of(base, state)
    assert srv["sha"] == SERVED
    assert srv["since"] == iso(FLIPPED) and srv["since_basis"] == "CURRENT symlink mtime"


def test_serving_since_stays_the_receipt_when_it_names_the_served_build(tmp_path):
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(SERVED, at=NOW - timedelta(hours=4)))
    srv = serving_of(base, state)
    assert srv["since"] == iso(NOW - timedelta(hours=4)) and srv["since_basis"] == "deploy_receipt.at"


def test_an_unavailable_current_never_invents_a_since(tmp_path):
    base, state, _rel = host(tmp_path, with_current=False, deploy_receipt=receipt(OLDER))
    srv = serving_of(base, state)
    assert srv["sha"] is None and srv.get("since") is None


# ------------------------------------------------------------------------------------------ the binding


def test_the_activation_record_binds_the_served_build_when_the_receipt_names_another(tmp_path):
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(OLDER))
    health = W.bind_served_health(W.release_health(state), serving_of(base, state))
    assert health["ok"] is True and health["sha"] == SERVED
    assert health["basis"] == W.ACTIVATION_BASIS and health["at"] == iso(FLIPPED)
    # the stale receipt travels along, so the evidence can say which build it names
    assert health["receipt_sha"] == OLDER and health["receipt_ok"] is True


def test_a_receipt_naming_the_served_build_is_untouched_in_both_directions(tmp_path):
    for ok in (True, False):
        state = tmp_path / f"state-{ok}"
        state.mkdir()
        # nosemgrep: tq-py-nonatomic-store-write -- synthetic deploy_receipt.json under pytest tmp_path, read back immediately, never a store
        (state / "deploy_receipt.json").write_text(json.dumps(receipt(SERVED, ok=ok)))
        health = W.bind_served_health(W.release_health(state), {"sha": SERVED, "release_dir": "/nowhere"})
        assert health["basis"] == "deploy_receipt.json" and health["ok"] is ok


@pytest.mark.parametrize("defect", ["no_active_file", "active_names_another", "expected_names_another", "pins_disagree"])
def test_each_part_of_the_activation_record_must_agree(tmp_path, defect):
    kw = {"deploy_receipt": receipt(OLDER)}
    if defect == "no_active_file":
        kw["with_active_file"] = False
    elif defect == "active_names_another":
        kw["active_release"] = str(tmp_path / "releases" / "elsewhere")
    elif defect == "expected_names_another":
        kw["expected_release"] = str(tmp_path / "releases" / "elsewhere")
    else:
        kw["pins"] = {"GIT_SHA": "7" * 40}
    base, state, rel = host(tmp_path, **kw)
    act = W.activation_health({"sha": SERVED, "release_dir": str(rel)})
    assert act["ok"] is not True and act["at"] is None, defect
    assert act["basis"] != W.ACTIVATION_BASIS, defect
    health = W.bind_served_health(W.release_health(state), serving_of(base, state))
    # fail closed: the receipt is left exactly as read, so its older sha can never satisfy the served-sha gate
    assert health["sha"] == OLDER and "receipt_sha" not in health, defect
    assert health["basis"] == "deploy_receipt.json", defect


def test_a_missing_current_cannot_bind_an_activation(tmp_path):
    base, state, _rel = host(tmp_path, with_current=False, deploy_receipt=receipt(OLDER))
    health = W.bind_served_health(W.release_health(state), serving_of(base, state))
    assert health["sha"] == OLDER and "receipt_sha" not in health
    row = W.derive(pr=merged(released=released_fact(ago(hours=2))), health={**health, "served_sha": None}, now=NOW)
    assert row["stage"] != "verified"


def test_a_flip_between_the_read_and_the_bind_cannot_use_the_old_serving(tmp_path):
    # The live-integration line flips CURRENT while the pipeline runs; a stale serving dict must not be blessed.
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(OLDER))
    stale = serving_of(base, state)
    newer_sha = "5" * 40
    newer = base / f"{newer_sha[:9]}-live-integration-20261108-181433"
    newer.mkdir()
    for name in ("BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT"):
        (newer / name).write_text(f"{newer_sha}\n")
    (base / "ACTIVE_RELEASE").write_text(f"{newer}\n")
    (base / "EXPECTED_RELEASE").write_text(f"{newer}\n")
    os.symlink(newer, base / "CURRENT.new")
    os.replace(base / "CURRENT.new", base / "CURRENT")
    health = W.bind_served_health(W.release_health(state), stale)
    assert health["sha"] == OLDER and "receipt_sha" not in health
    act = W.activation_health(stale)
    assert act["ok"] is not True and act["basis"] != W.ACTIVATION_BASIS


# ------------------------------------------------------------------------------------------ the stage


def test_the_verified_stage_advances_on_the_activation_without_claiming_a_receipt(tmp_path):
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(OLDER))
    srv = serving_of(base, state)
    health = {**W.bind_served_health(W.release_health(state), srv), "served_sha": srv["sha"]}
    row = W.derive(pr=merged(released=released_fact(srv["since"]), served_contains=True), health=health, now=NOW)
    assert row["stage"] == "verified" and row["finished"]
    verified = next(c for c in row["cells"] if c["stage"] == "verified")
    assert verified["rag"] == "green"
    assert "activated on this host" in verified["evidence"]
    assert "deploy health ok" not in verified["evidence"]
    assert OLDER[:9] in verified["evidence"]  # the stale receipt is named, not implied away


def test_without_convergence_the_row_stays_released_and_amber(tmp_path):
    base, state, _rel = host(tmp_path, with_active_file=False, deploy_receipt=receipt(OLDER))
    srv = serving_of(base, state)
    health = {**W.bind_served_health(W.release_health(state), srv), "served_sha": srv["sha"]}
    row = W.derive(pr=merged(released=released_fact(srv["since"]), served_contains=True), health=health, now=NOW)
    assert row["stage"] == "released" and not row["finished"]
    assert row["rag"] == "amber" and next(c for c in row["cells"] if c["stage"] == "verified")["rag"] == "grey"


def test_a_failed_receipt_for_the_served_build_still_paints_it_red(tmp_path):
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(SERVED, ok=False))
    srv = serving_of(base, state)
    health = {**W.bind_served_health(W.release_health(state), srv), "served_sha": srv["sha"]}
    row = W.derive(pr=merged(released=released_fact(srv["since"]), served_contains=True), health=health, now=NOW)
    assert row["stage"] == "released" and row["rag"] == "red" and row["label"] == "health failed"


def test_a_failed_receipt_for_an_older_build_cannot_paint_the_served_build_red(tmp_path):
    # Deliberate: the receipt is evidence about the older build; a converged activation is what the host says now.
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(OLDER, ok=False))
    srv = serving_of(base, state)
    health = {**W.bind_served_health(W.release_health(state), srv), "served_sha": srv["sha"]}
    row = W.derive(pr=merged(released=released_fact(srv["since"]), served_contains=True), health=health, now=NOW)
    assert row["stage"] == "verified" and row["rag"] == "green"
    assert "receipt_ok" not in str(row)  # internal provenance, never a rendered field


def test_the_live_timeline_names_the_activation_not_the_receipt(tmp_path):
    base, state, _rel = host(tmp_path, deploy_receipt=receipt(OLDER))
    srv = serving_of(base, state)
    health = {**W.bind_served_health(W.release_health(state), srv), "served_sha": srv["sha"]}
    pr = {"number": 2501, "branch": "wt/test", "head_sha": "a" * 40, "merged_at": ago(hours=5),
          "released": released_fact(srv["since"]), "served_contains": True}
    out = WPS.build([pr], [], [], [], [], NOW, serving=srv, health=health)
    row = out["by_pr"][2501]
    assert row["live"]["value"] is True
    live = [e for e in row["timeline"] if e["kind"] == "verified_live"]
    assert len(live) == 1 and live[0]["source"] == "served_activation"
    assert live[0]["source_ref"] == W.ACTIVATION_BASIS
