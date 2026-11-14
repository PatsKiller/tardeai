"""ANCHOR: LQ3151_VOLUME_GUARD — LQ-20261113-3151 (P0): heavy writes live on the verified /data volume, and
they fail clearly when it is not mounted.

Two things are pinned here:

* the guard's four proofs (mount point, filesystem UUID, sentinel, a different device from ``/``) and its
  per-path device check — with injected mountinfo/stat so the pass and fail cases are synthetic and hermetic;
* ``scripts/new-worktree.sh`` — the tree lands under the volume root, the legacy path is a symlink to it, and a
  refusing guard stops the script before git or the filesystem is touched (there is no fallback to root).

Synthetic temp roots only: the real ``/data`` is never written. The one host-shaped assertion (the CLI on this
host) refuses a genuinely same-device directory and, when the volume is present, accepts it read-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.lib import tradeai_volume as TV

ROOT = Path(__file__).resolve().parents[1]
UUID = TV.EXPECTED_UUID
SCRIPT = ROOT / "scripts" / "new-worktree.sh"

MOUNTINFO_PLAIN = "20 1 8:2 / / rw,noatime - ext4 /dev/root rw\n"


def _volume(tmp_path: Path, *, uuid: str = UUID, mountinfo: str | None = None,
            source: str = "synth0", sentinel_body: str | None = None, attach_uuid: bool = True) -> dict:
    """A synthetic volume root plus the injection points the guard's tests need.

    The mount source is a real temp file, so the by-uuid symlink and the mountinfo source can be compared
    with ``realpath`` exactly as the guard does on the host.
    """
    vol = tmp_path / "volume"
    vol.mkdir(exist_ok=True)
    (vol / TV.SENTINEL).write_text(sentinel_body if sentinel_body is not None
                                   else f"# test volume\nuuid={uuid}\n")
    devs = tmp_path / "devs"
    devs.mkdir(exist_ok=True)
    (devs / "synth0").write_text("")
    (devs / "other").write_text("")
    by_uuid = tmp_path / "by-uuid"
    by_uuid.mkdir(exist_ok=True)
    link = by_uuid / UUID
    if link.is_symlink() or link.exists():
        link.unlink()
    if attach_uuid:
        link.symlink_to(devs / ("synth0" if source == "synth0" else "other"))
    text = mountinfo if mountinfo is not None else (
        "20 1 8:2 / / rw,noatime - ext4 /dev/root rw\n"
        f"36 20 8:1 / {vol} rw,noatime - ext4 {devs / 'synth0'} rw\n")
    return {"root": vol, "mountinfo": text, "by_uuid_dir": by_uuid, "devs": devs, "source": source}


def _stat_map(mapping: dict[str, int]):
    """stat() that reports the given st_dev per real path (``/`` defaults to the root device)."""
    def _stat(path):
        real = os.path.realpath(str(path))
        if real in mapping:
            return SimpleNamespace(st_dev=mapping[real])
        return SimpleNamespace(st_dev=mapping.get("/", 1))
    return _stat


def _check(fx: dict, *, paths=None, sentinel: str = TV.SENTINEL, stat=None):
    root = str(fx["root"])
    mapping = {"/": 1, os.path.realpath(root): 100}
    for extra, dev in (fx.get("devices") or {}).items():
        mapping[os.path.realpath(extra)] = dev
    return TV.check(root, expect_uuid=UUID, paths=paths, sentinel=sentinel, mountinfo=fx["mountinfo"],
                    by_uuid_dir=fx["by_uuid_dir"], stat=stat or _stat_map(mapping))


# ── the four proofs ───────────────────────────────────────────────────────────────────────────────────────────────


def test_verified_volume_passes(tmp_path):
    rep = _check(_volume(tmp_path))
    assert rep.ok, rep.reason()
    assert rep.checks == {name: None for name in TV._CHECK_NAMES}


def test_plain_directory_on_root_is_refused(tmp_path):
    """The mountpoint proof: an empty /data directory on root is not a volume (and is on root's device)."""
    fx = _volume(tmp_path, mountinfo=MOUNTINFO_PLAIN)
    rep = _check(fx, stat=_stat_map({"/": 1, os.path.realpath(str(fx["root"])): 1}))
    assert not rep.ok
    assert "not a mount point" in rep.checks["mountpoint"]
    assert "same device" in rep.checks["device"]


def test_bind_of_a_root_path_is_refused(tmp_path):
    """A mount at /data whose device is root's is the broken-bind case: it must be refused by check 4."""
    fx = _volume(tmp_path)
    rep = _check(fx, stat=_stat_map({"/": 1, os.path.realpath(str(fx["root"])): 1}))
    assert not rep.ok
    assert rep.checks["mountpoint"] is None  # it IS a mount
    assert "same device" in rep.checks["device"]


def test_wrong_filesystem_uuid_is_refused(tmp_path):
    rep = _check(_volume(tmp_path, source="other"))
    assert not rep.ok
    assert "UUID" in rep.checks["uuid"]


def test_missing_expected_uuid_device_is_refused(tmp_path):
    fx = _volume(tmp_path, attach_uuid=False)
    rep = _check(fx)
    assert not rep.ok
    assert "not attached" in rep.checks["uuid"]


def test_missing_sentinel_is_refused(tmp_path):
    rep = _check(_volume(tmp_path), sentinel=".not-here")
    assert not rep.ok
    assert "missing" in rep.checks["sentinel"]


def test_sentinel_naming_another_uuid_is_refused(tmp_path):
    rep = _check(_volume(tmp_path, sentinel_body="uuid=00000000-0000-0000-0000-000000000000\n"))
    assert not rep.ok
    assert "different UUID" in rep.checks["sentinel"]


def test_sentinel_without_uuid_line_is_accepted(tmp_path):
    assert _check(_volume(tmp_path, sentinel_body="# plain marker\n")).ok


# ── per-path device checks (the TMPDIR / worktree guarantee) ─────────────────────────────────────────────────────


def test_path_on_volume_passes(tmp_path):
    fx = _volume(tmp_path)
    good = Path(fx["root"]) / "agent-tmp" / "cc-x" / "tmp"
    good.mkdir(parents=True)
    fx["devices"] = {good: 100}
    rep = _check(fx, paths=[good])
    assert rep.ok, rep.reason()
    assert rep.paths[0]["reason"] is None


def test_path_on_root_device_is_refused(tmp_path):
    """The TMPDIR hole: the path exists, is inside a symlinked-looking parent, and is on root's device."""
    fx = _volume(tmp_path)
    bad = tmp_path / "root-side" / "tmp"
    bad.mkdir(parents=True)
    fx["devices"] = {bad: 1}
    rep = _check(fx, paths=[bad])
    assert not rep.ok
    assert "bind to" in rep.paths[0]["reason"] or "root device" in rep.paths[0]["reason"]


def test_path_on_a_third_device_is_refused(tmp_path):
    fx = _volume(tmp_path)
    odd = tmp_path / "otherfs"
    odd.mkdir()
    fx["devices"] = {odd: 77}
    rep = _check(fx, paths=[odd])
    assert not rep.ok
    assert "not the volume's device" in rep.paths[0]["reason"]


def test_missing_path_uses_nearest_existing_ancestor(tmp_path):
    """A fresh worker's TMPDIR does not exist yet; its ancestor decides, and that is the bind in question."""
    fx = _volume(tmp_path)
    parent = Path(fx["root"]) / "agent-tmp" / "cc-new"
    parent.mkdir(parents=True)
    fx["devices"] = {parent: 100}
    rep = _check(fx, paths=[parent / "tmp" / "deep"])
    assert rep.ok, rep.reason()
    assert rep.paths[0]["resolved"] == os.path.realpath(parent)


def test_missing_path_over_root_parent_is_refused(tmp_path):
    fx = _volume(tmp_path)
    parent = tmp_path / "cache-root"
    parent.mkdir()
    fx["devices"] = {parent: 1}
    rep = _check(fx, paths=[parent / "cc-new" / "tmp"])
    assert not rep.ok
    assert "root device" in rep.paths[0]["reason"]


def test_bind_target_on_root_is_refused_while_the_volume_is_mounted(tmp_path):
    """F1 (review cc-deepseek-8): /data verifies, but the ``agent-tmp`` **bind target** is an ordinary
    directory on root because the nofail bind did not happen. The guard must refuse that path — the
    relauncher now passes ``~/.cache/agent-tmp``, which is exactly this shape."""
    fx = _volume(tmp_path)
    target = tmp_path / "home" / ".cache" / "agent-tmp"
    target.mkdir(parents=True)
    fx["devices"] = {target: 1}
    rep = _check(fx, paths=[target, Path(fx["root"]) / "worktrees"])
    assert rep.checks == {name: None for name in TV._CHECK_NAMES}, "the volume itself verifies"
    assert not rep.ok
    assert rep.paths[0]["reason"].startswith("resolves to the root device")
    assert rep.paths[1]["reason"] is None, "a worktree under the mounted volume still passes"


# ── layout map ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_layout_routes_every_heavy_location_to_the_volume():
    lay = TV.layout({"TRADEAI_VOLUME_ROOT": "/data"})
    for key in ("worktrees", "agent_tmp", "cc_tmp", "test_db", "dumps", "build"):
        assert lay[key].startswith("/data/"), key
    assert lay["caches"]["ms-playwright"].startswith("/data/")
    assert lay["compat_links"]["~/cc-tmp"] == "/data/cc-tmp"


def test_layout_honours_a_worktree_root_override():
    lay = TV.layout({"TRADEAI_VOLUME_ROOT": "/data", "TRADEAI_WORKTREE_ROOT": "/elsewhere/trees"})
    assert lay["worktrees"] == "/elsewhere/trees"


def test_layout_follows_a_volume_override():
    assert TV.layout({"TRADEAI_VOLUME_ROOT": "/mnt/big"}).get("cc_tmp") == "/mnt/big/cc-tmp"


# ── the CLI, on real paths ──────────────────────────────────────────────────────────────────────────────────────


def _cli(*args, env=None):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "lib" / "tradeai_volume.py"), *args],
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


def test_cli_refuses_a_real_directory_on_root(tmp_path):
    """No injection: a genuinely same-device directory is refused with exit 78 and a readable reason."""
    real = tmp_path / "pretend-volume"
    real.mkdir()
    r = _cli("check", "--root", str(real))
    assert r.returncode == TV.REFUSED
    assert "TRADEAI_VOLUME_GUARD: refusing" in r.stderr
    assert "not a mount point" in r.stderr


def test_cli_refuses_a_real_path_outside_the_volume():
    """No injection: ``/`` is by construction not the volume, and the guard must refuse it."""
    r = _cli("check", "--path", "/")
    assert r.returncode == TV.REFUSED
    assert "root device" in r.stderr or "not the volume's device" in r.stderr


def test_cli_json_names_every_check():
    r = _cli("check", "--json", "--root", "/nonexistent-tradeai-volume")
    body = json.loads(r.stdout)
    assert body["ok"] is False
    assert set(body["checks"]) == set(TV._CHECK_NAMES)
    assert r.returncode == TV.REFUSED


def test_json_reports_unrun_checks_as_skipped_not_ok():
    """A1 (review cc-deepseek-8): a check that never ran must not read as ``ok`` — unknown beats wrong."""
    r = _cli("check", "--json", "--root", "/nonexistent-tradeai-volume")
    body = json.loads(r.stdout)
    assert "not a directory" in body["checks"]["mountpoint"]
    assert body["checks"]["uuid"] == TV.SKIPPED
    assert body["checks"]["sentinel"] == TV.SKIPPED
    assert body["checks"]["device"] == TV.SKIPPED
    assert TV.SKIPPED not in body["reason"]  # skipped is not a failure reason either


def test_json_reports_the_uuid_check_skipped_when_the_mount_check_failed(tmp_path):
    """A real directory that is not a mount: sentinel and device do run; uuid cannot."""
    real = tmp_path / "pretend-volume"
    real.mkdir()
    (real / TV.SENTINEL).write_text(f"uuid={UUID}\n")
    r = _cli("check", "--json", "--root", str(real))
    body = json.loads(r.stdout)
    assert "not a mount point" in body["checks"]["mountpoint"]
    assert body["checks"]["uuid"] == TV.SKIPPED
    assert body["checks"]["sentinel"] == "ok"
    assert body["checks"]["device"] == "ok" or "same device" in body["checks"]["device"]


def test_cli_paths_lists_the_routed_locations():
    r = _cli("paths", "--json")
    assert r.returncode == 0
    lay = json.loads(r.stdout)
    assert "/worktrees" in lay["worktrees"] and lay["cc_tmp"].endswith("/cc-tmp")


@pytest.mark.skipif(not Path("/data/" + TV.SENTINEL).exists(), reason="/data volume not mounted on this host")
def test_cli_accepts_the_real_volume_read_only():
    r = _cli("check", "--quiet")
    assert r.returncode == 0, r.stderr


# ── scripts/new-worktree.sh ─────────────────────────────────────────────────────────────────────────────────────


def _project(tmp_path: Path) -> Path:
    """A temp git repo carrying the script under test and a stub guard that records its argv."""
    repo = tmp_path / "project"
    (repo / "scripts" / "lib").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
    (repo / "README").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    (repo / "scripts" / "new-worktree.sh").write_text(SCRIPT.read_text())
    (repo / "scripts" / "lib" / "tradeai_volume.py").write_text(
        "import os, sys\n"
        "open(os.environ['GUARD_LOG'], 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "sys.exit(int(os.environ.get('GUARD_EXIT', '0')))\n")
    return repo


def _run(project: Path, tmp_path: Path, *args, guard_exit=0, env=None):
    log = tmp_path / "guard.log"
    e = {**os.environ, "GUARD_LOG": str(log), "GUARD_EXIT": str(guard_exit),
         "TRADEAI_PROJECT_ROOT": str(project), "TRADEAI_VOLUME_ROOT": str(tmp_path / "vol"),
         "TRADEAI_WORKTREE_ROOT": str(tmp_path / "vol" / "worktrees"),
         "TRADEAI_WORKTREE_LEGACY_HOME": str(tmp_path / "home"),
         "TRADEAI_WORKTREE_LINK_ENV": "0", **(env or {})}
    (tmp_path / "home").mkdir(exist_ok=True)
    r = subprocess.run(["bash", str(project / "scripts" / "new-worktree.sh"), *args],
                       capture_output=True, text=True, env=e)
    return r, (log.read_text().splitlines() if log.exists() else [])


def test_new_worktree_creates_the_tree_on_the_volume_and_links_the_legacy_path(tmp_path):
    project = _project(tmp_path)
    r, logged = _run(project, tmp_path, "demo", "HEAD")
    assert r.returncode == 0, r.stderr
    tree = tmp_path / "vol" / "worktrees" / "tradeai-wt-demo"
    link = tmp_path / "home" / "tradeai-wt-demo"
    assert tree.is_dir() and (tree / "README").is_file()
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(tree)
    assert any("check" in line and str(tmp_path / "vol" / "worktrees") in line for line in logged)


def test_new_worktree_refuses_before_touching_anything_when_the_guard_fails(tmp_path):
    project = _project(tmp_path)
    r, logged = _run(project, tmp_path, "demo", "HEAD", guard_exit=TV.REFUSED)
    assert r.returncode == TV.REFUSED
    assert "refusing to create" in r.stderr
    assert not (tmp_path / "vol" / "worktrees" / "tradeai-wt-demo").exists()
    assert not (tmp_path / "home" / "tradeai-wt-demo").exists()
    assert logged, "the guard must have been consulted"
    # and nothing fell back to the legacy home on root
    assert not any(p.is_dir() for p in (tmp_path / "home").iterdir())


def test_new_worktree_dry_run_creates_nothing(tmp_path):
    project = _project(tmp_path)
    r, _ = _run(project, tmp_path, "--dry-run", "demo", "HEAD")
    assert r.returncode == 0, r.stderr
    assert "dry run" in r.stdout
    assert str(tmp_path / "vol" / "worktrees" / "tradeai-wt-demo") in r.stdout
    assert not (tmp_path / "vol" / "worktrees" / "tradeai-wt-demo").exists()


def test_new_worktree_refuses_an_existing_legacy_path_without_touching_it(tmp_path):
    project = _project(tmp_path)
    legacy = tmp_path / "home" / "tradeai-wt-demo"
    legacy.mkdir(parents=True)
    (legacy / "keep").write_text("peer work\n")
    r, _ = _run(project, tmp_path, "demo", "HEAD")
    assert r.returncode == 1
    assert "already exists" in r.stderr
    assert (legacy / "keep").read_text() == "peer work\n"
    assert not (tmp_path / "vol" / "worktrees" / "tradeai-wt-demo").exists()
