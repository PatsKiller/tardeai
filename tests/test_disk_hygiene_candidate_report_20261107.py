"""LQ-277: bounded, read-only agent-tmp / release candidate report and the apply-time live-claim refusal.

Synthetic tmp_path fixtures only. ``NOW`` is set days after the real clock so freshly created fixture files (whose ctime
is real-now) are older than the 6 h cutoff; "recent activity" is faked with an mtime/ctime-safe future stamp.
COVERS = ["scripts/disk_hygiene.py", "scripts/lib/disk_hygiene_report.py"]
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH
from scripts.lib import disk_hygiene_report as DR
from tests.test_disk_standing_apply_20261024 import world  # noqa: F401 -- fixture imported for pytest
from tests.test_disk_hygiene_20261018 import NOW as FIXTURE_NOW, _apply, _last_apply, world as apply_world  # noqa: F401 -- fixture imported for pytest

NOW = time.time() + 3 * 86400
ISO_FRESH = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 600))
ISO_STALE = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 5 * 3600))


def _claim(claims: Path, cid: str, session: str, beat: str, status: str = "active", paths=()):
    claims.mkdir(parents=True, exist_ok=True)
    (claims / f"{cid}.json").write_text(json.dumps({
        "schema": "AgentClaim@v1", "claim_id": cid, "session": session, "agent": "claude", "status": status,
        "heartbeat_at": beat, "started_at": beat, "paths": list(paths)}))


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    root = home / ".cache" / "agent-tmp"
    root.mkdir(parents=True)
    claims = tmp_path / "claims"
    claims.mkdir()
    return home, root, claims


def _entry(root: Path, owner: str, name: str, mtime=None, nbytes=2048) -> Path:
    d = root / owner / name if owner else root / name
    d.mkdir(parents=True)
    (d / "blob").write_bytes(b"x" * nbytes)
    if mtime is not None:
        for p in (d / "blob", d):
            os.utime(p, (mtime, mtime))
    return d


def _report(home, claims):
    return DR.agent_tmp_report(home, claims, NOW, proc_root=home / "noproc")


def _cands(rep):
    return {Path(r["path"]).relative_to(rep["root"]).as_posix() for r in rep["candidates"]}


def _held(rep):
    return {Path(r["path"]).relative_to(rep["root"]).as_posix(): r["why"] for r in rep["held"]}


def test_idle_entry_of_an_owner_without_a_claim_is_a_candidate_and_is_sized(env):
    home, root, claims = env
    d = _entry(root, "cc-deepseek-3", "copy-a")
    rep = _report(home, claims)
    assert rep["dry_only"] is True and _cands(rep) == {"cc-deepseek-3/copy-a"}
    row = rep["candidates"][0]
    assert row["owner"] == "cc-deepseek-3" and row["size_kib"] >= 2 and row["idle_h"] > 6
    assert d.exists()


def test_owner_with_a_fresh_live_claim_is_held_but_a_stale_heartbeat_does_not_hold(env):
    home, root, claims = env
    _entry(root, "cc-a-1", "x")
    _entry(root, "cc-b-2", "y")
    _entry(root, "cc-c-3", "z")
    _claim(claims, "C1", "cc-a-1", ISO_FRESH)
    _claim(claims, "C1sub", "cc-c-3-hermes", ISO_FRESH)  # a sub-session holds its owner dir
    _claim(claims, "C2", "cc-b-2", ISO_STALE)
    rep = _report(home, claims)
    assert _cands(rep) == {"cc-b-2/y"}
    assert _held(rep)["cc-a-1/x"] == "owner_holds_live_claim:C1"
    assert _held(rep)["cc-c-3/z"] == "owner_holds_live_claim:C1sub"


def test_released_and_non_claim_documents_do_not_hold(env):
    home, root, claims = env
    _entry(root, "cc-a-1", "x")
    _claim(claims, "C1", "cc-a-1", ISO_FRESH, status="released")
    (claims / "board.json").write_text(json.dumps({"schema": "Other@v1"}))
    assert _cands(_report(home, claims)) == {"cc-a-1/x"}


def test_unreadable_claims_refuse_to_report_candidates(env):
    home, root, claims = env
    _entry(root, "cc-a-1", "x")
    (claims / "bad.json").write_text("{")
    rep = _report(home, claims)
    assert rep["error"].startswith("claims_unreadable") and rep["candidates"] == []


def test_recent_activity_symlink_harness_and_root_dirs(env, tmp_path):
    home, root, claims = env
    _entry(root, "cc-a-1", "fresh", mtime=NOW - 3600)
    (root / "cc-a-1" / "link").symlink_to(tmp_path)
    _entry(root, "", "tmp")  # harness scratch
    _entry(root, "", "stray-dir")
    rep = _report(home, claims)
    assert _cands(rep) == {"stray-dir"} and rep["candidates"][0]["owner"] == "(root)"
    held = _held(rep)
    assert held["cc-a-1/link"] == "symlink" and "harness" in held["tmp"] and held["cc-a-1/fresh"] == "active_within_6h"


def test_never_touch_and_in_use_cwd_are_held(env):
    home, root, claims = env
    keep = _entry(root, "cc-a-1", "keep")
    busy = _entry(root, "cc-a-1", "busy")
    proc = home / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "42" / "cwd").symlink_to(busy)
    rep = DR.agent_tmp_report(home, claims, NOW, proc_root=proc, never_touch=lambda q: str(q) == str(keep))
    assert _cands(rep) == set() and len(rep["held"]) == 2


def test_releases_keep_current_and_the_newest_five(env):
    home, root, claims = env
    rel = home / "trade-ai-releases" / "portfolio-server"
    names = [f"aaa{i}-live-integration-202611{i:02d}-120000" for i in range(1, 9)]
    for n in names:
        (rel / n).mkdir(parents=True)
        (rel / n / "f").write_bytes(b"y" * 4096)
    (rel / "CURRENT").symlink_to(rel / names[0])  # the oldest is CURRENT
    rep = DR.release_report(home, claims, NOW, proc_root=home / "noproc")
    assert [r["entry"] for r in rep["candidates"]] == names[1:3]
    why = {r["entry"]: r["why"] for r in rep["held"]}
    assert why[names[0]] == "current" and all(why[n].startswith("keep_newest") for n in names[3:])
    assert all(r["size_kib"] >= 4 for r in rep["candidates"])


def test_a_live_claim_naming_a_release_holds_it(env):
    home, root, claims = env
    rel = home / "trade-ai-releases" / "portfolio-server"
    names = [f"aaa{i}-live-integration-202611{i:02d}-120000" for i in range(1, 8)]
    for n in names:
        (rel / n).mkdir(parents=True)
    _claim(claims, "R1", "cc-z-9", ISO_FRESH, paths=[str(rel / names[0])])
    rep = DR.release_report(home, claims, NOW, proc_root=home / "noproc")
    assert [r["entry"] for r in rep["candidates"]] == [names[1]]
    assert {r["entry"]: r["why"] for r in rep["held"]}[names[0]] == "path_in_live_claim:R1"


def test_live_claim_hold_by_owner_and_by_named_path(tmp_path):
    home = tmp_path
    live = [{"claim_id": "A", "session": "cc-a-1", "paths": []}, {"claim_id": "B", "session": "cc-b-2", "paths": [str(tmp_path / "w")]}]
    scratch = home / ".cache" / "agent-tmp"
    assert DR.live_claim_hold(scratch / "cc-a-1" / "d", home, live) == "owner_holds_live_claim:A"
    assert DR.live_claim_hold(scratch / "cc-a-10" / "d", home, live) is None  # prefix needs a '-' boundary
    assert DR.live_claim_hold(tmp_path / "w" / "sub", home, live) == "path_in_live_claim:B"
    assert DR.live_claim_hold(tmp_path / "elsewhere", home, live) is None


def test_the_report_writes_and_deletes_nothing(env):
    home, root, claims = env
    _entry(root, "cc-a-1", "x")
    before = sorted(str(p) for p in home.rglob("*"))
    DR.build_report(home, claims, now=NOW, proc_root=home / "noproc")
    assert sorted(str(p) for p in home.rglob("*")) == before


def test_cli_candidate_report_prints_json_and_refuses_other_modes(world, capsys):  # noqa: F811 -- fixture parameter shadows the import
    home, _, rules_path, _ = world
    base = ["--rules", str(rules_path), "--home", str(home)]
    assert DH.main(["--candidate-report", *base]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == DR.SCHEMA and out["dry_only"] is True and "agent_tmp" in out and "releases" in out
    for other in ("--apply", "--plan", "--standing"):
        assert DH.main(["--candidate-report", other, *base]) == 2


def test_apply_skips_a_worktree_named_by_a_live_claim_and_removes_it_once_the_claim_is_gone(apply_world):
    w = apply_world
    wt = w.worktree("wt-clean")
    w.plan()
    claims = DH._claims_dir(DH.load_rules(w.rules_path, home=w.home))
    assert str(w.home) in str(claims)  # never the real coordination dir
    beat = FIXTURE_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    _claim(claims, "L1", "cc-a-1", beat, paths=[str(wt)])
    assert _apply(w, **{DH.GRANT_ENV: "g1"}) == 0
    rep = _last_apply(w)
    assert rep["removed"] == [] and rep["skipped"] == [{"path": str(wt), "why": "path_in_live_claim:L1"}] and wt.exists()
    _claim(claims, "L1", "cc-a-1", beat, status="released", paths=[str(wt)])
    w.plan()
    assert _apply(w, **{DH.GRANT_ENV: "g1"}) == 0
    assert not wt.exists() and _last_apply(w)["skipped"] == []
