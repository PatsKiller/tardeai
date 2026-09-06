"""Runtime state must not live where `git checkout` can destroy it.

Two files were classified as runtime state and still owned by git. Both bit on
2026-09-06, during a routine fast-forward of the tree that actually executes.

SEARXNG'S LIVE CONFIG
    infra/searxng/core-config was bind-mounted rw into the container, which chowns
    it to 977:977. uid 1000 then cannot unlink anything in it, so checkout did not
    merely clobber the live config — it FAILED OUTRIGHT:

        error: unable to unlink old 'infra/searxng/core-config/settings.yml':
        Permission denied

    That single file blocked the other 70 from updating, which is how eighteen
    commits of merged fixes ended up not running on the executing tree. The live
    config now lives outside the repository; the tracked copy is a template.

HERMES SCORE WEIGHTS
    cio_release_manifest already classified config/hermes_score_weights.yaml as
    "runtime_state_with_release_seed" — the tracked copy is a seed, the live weights
    are learned from the outcome ledger. Nothing ENFORCED that, so it stayed an
    ordinary tracked config. The fast-forward reverted v11 to the v9 seed, discarding
    nine grafts of learning; only an out-of-band backup recovered it.

    A declared classification that nothing enforces is documentation, not a control.

No docker, no network, no database: these read source and config only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra" / "searxng" / "docker-compose.yml"
INSTALLER = ROOT / "scripts" / "install_searxng_config.sh"
TUNER = ROOT / "scripts" / "hermes_autonomous_self_tune.py"


# ── the live config is no longer pinned inside the repository ───────────────

@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_the_config_mount_is_not_hardcoded_to_the_repo(compose: dict):
    vols = compose["services"]["searxng"]["volumes"]
    mount = next(v for v in vols if v.endswith("/etc/searxng:rw"))
    assert "SEARXNG_CONFIG_DIR" in mount, (
        "the live config is pinned inside the worktree again; a checkout will "
        "fail on it and block every other file")


def test_a_fresh_clone_still_works(compose: dict):
    """The default must remain, or someone who has not set the variable gets a
    container with no config at all. Fixing one failure by causing another is not
    a fix."""
    vols = compose["services"]["searxng"]["volumes"]
    mount = next(v for v in vols if v.endswith("/etc/searxng:rw"))
    assert ":-./core-config}" in mount, "the in-repo default was removed"


def test_the_reason_is_recorded_where_the_next_person_edits(compose: dict):
    """A bare ${VAR} invites someone to 'simplify' it back to a literal path."""
    text = COMPOSE.read_text(encoding="utf-8")
    for marker in ("977", "unlink", "OUTSIDE"):
        assert marker in text, f"the volume comment does not explain {marker!r}"


# ── the installer cannot silently write to a directory nobody serves ────────

def test_the_installer_verifies_its_target_against_the_container():
    """Now that the default no longer matches the mount, an unset
    SEARXNG_CONFIG_DIR would install into a dead directory, validate, report
    success, restart, and change nothing — the exact silent-success class this
    script was written to end."""
    src = INSTALLER.read_text(encoding="utf-8")
    assert "ACTUAL_MOUNT" in src
    assert "docker inspect searxng" in src
    assert "is not the directory the container serves" in src


def test_the_installer_refuses_rather_than_warning():
    src = INSTALLER.read_text(encoding="utf-8")
    guard = src.split("ACTUAL_MOUNT=", 1)[1].split("\nfi\n", 1)[0]
    assert "exit 1" in guard, "a mismatch must stop the install, not annotate it"


def test_an_unreadable_container_does_not_block_the_install():
    """Docker being unavailable is not evidence of a wrong directory. Refusing
    there would make the script unusable on a host where docker needs sudo."""
    src = INSTALLER.read_text(encoding="utf-8")
    guard = src.split("ACTUAL_MOUNT=", 1)[1].split("\nfi\n", 1)[0]
    assert "unverified" in guard


def test_the_guard_runs_after_its_helpers_are_defined():
    """Bash resolves functions at call time. The first draft of this guard called
    say() eleven lines before say() was defined."""
    src = INSTALLER.read_text(encoding="utf-8").splitlines()
    say_def = next(i for i, l in enumerate(src) if l.startswith("say()"))
    guard = next(i for i, l in enumerate(src) if l.startswith("ACTUAL_MOUNT="))
    assert guard > say_def, "the guard calls say()/die() before they exist"


# ── a graft is archived before it can be lost ───────────────────────────────

def test_grafts_are_archived_before_the_live_file_is_rewritten():
    src = TUNER.read_text(encoding="utf-8")
    assert "_archive_graft" in src
    archive_at = src.index("archived = _archive_graft(doc)")
    write_at = src.index("WEIGHTS_FILE.write_text")
    assert archive_at < write_at, "archived after the write is not a backup"


def test_the_archive_survives_the_checkout_that_causes_the_problem():
    """Under data/runtime, which is gitignored. An archive inside tracked config
    would be reverted by the same checkout it exists to recover from."""
    src = TUNER.read_text(encoding="utf-8")
    assert 'data" / "runtime" / "weight_grafts"' in src
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^\s*(/)?data/runtime", ignored, re.M), \
        "data/runtime is not gitignored, so the archive is not durable"


def test_the_archive_location_is_configurable():
    src = TUNER.read_text(encoding="utf-8")
    assert "HERMES_WEIGHT_GRAFT_ARCHIVE" in src


def test_an_archive_failure_is_reported_and_not_fatal(tmp_path, monkeypatch, capsys):
    """Two failure modes, both bad: crashing loses the graft, silence leaves the
    recovery path looking healthy while holding nothing."""
    tuner = pytest.importorskip("hermes_autonomous_self_tune")

    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(tuner, "GRAFT_ARCHIVE_DIR", blocked / "sub")

    assert tuner._archive_graft({"version": 3, "weights": {}}) is None
    assert "WARN" in capsys.readouterr().err


def test_a_successful_archive_writes_readable_yaml(tmp_path, monkeypatch):
    tuner = pytest.importorskip("hermes_autonomous_self_tune")

    monkeypatch.setattr(tuner, "GRAFT_ARCHIVE_DIR", tmp_path / "grafts")
    doc = {"version": 12, "weights": {"analyst": 0.5}, "graft_source": "outcome_ledger"}
    dest = tuner._archive_graft(doc)

    assert dest is not None and dest.is_file()
    assert yaml.safe_load(dest.read_text(encoding="utf-8")) == doc
    assert "v12" in dest.name, "the version must be recoverable from the filename"


def test_two_grafts_in_the_same_run_do_not_overwrite_each_other(tmp_path, monkeypatch):
    tuner = pytest.importorskip("hermes_autonomous_self_tune")

    monkeypatch.setattr(tuner, "GRAFT_ARCHIVE_DIR", tmp_path / "grafts")
    a = tuner._archive_graft({"version": 1, "weights": {}})
    b = tuner._archive_graft({"version": 2, "weights": {}})
    assert a != b
