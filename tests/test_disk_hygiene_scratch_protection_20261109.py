"""Rule T's meaning of "protected" inside an agent scratch dir (LQ-20261107-1366).

A credential-named *source file* pinned the whole scratch tree: ``activity()`` returns
``activity_contains_protected_entry`` the instant it meets one, and the planner then reports
``scratch_not_older_than_12_hours`` -- an unmeasured fallback, not a measurement. On 2026-11-08 that
held 158.8 GiB while the disk ran to 89%. These cases fix the boundary: repo content (source code,
templates, a harness-written emulation env) never holds; a real credential file still does.

Synthetic tmp_path trees only; no host census, no real home.
COVERS = ["scripts/disk_hygiene.py"]
"""
from __future__ import annotations

import pytest

from scripts import disk_hygiene as DH
from tests.test_disk_standing_apply_20261024 import world  # noqa: F401

HARNESS_HEADER = ("# emulation env: configuration only, written by scripts/ops/n8n_lane_emulate.py; "
                  "no secret lives here\n")


def _root(world):
    home, rules, _, _ = world
    root = home / ".cache" / "agent-tmp" / "task"
    root.mkdir(parents=True, exist_ok=True)
    return root, rules


def _make(root, rel, text="fixture"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _repo_export(root, rel):
    """A ``git archive`` copy: the project tree with no ``.git`` and its top-level marker files."""
    p = root / rel
    p.mkdir(parents=True, exist_ok=True)
    (p / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    (p / "AGENTS.md").write_text("fixture\n")
    return p


@pytest.mark.parametrize("rel, holds", [
    # a repo export that *is* the scratch dir: its own tracked files are repo content
    ("tests/test_secret_single_path_20261005.py", False),
    ("tokens.css", False),
    ("config/ci_gates/secret_pii_scan_20261027.json", False),
    ("config/secret_registry.yaml", False),
    # ...but a credential file sitting at the export's top level is still a credential: a repo's own
    # ``.env`` is untracked, so the export says nothing about it
    (".env", True),
])
def test_scratch_protected_inside_a_repo_export(world, rel, holds):
    root, rules = _root(world)
    _repo_export(root, ".")
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("rel, holds", [
    # a *partial* export carries no project marker; the source extension is what identifies it
    ("lq258/base/tests/test_youtube_cookie_path_20261014.py", False),
    ("lq601/run_b/scripts/credential_monitor.py", False),
    ("src/lib/designTokens.ts", False),
    ("scripts/lib/secret_name_classes.py", False),
    ("scripts/brokers/__pycache__/alpaca_credentials.cpython-314.pyc", False),
    # a dump of a credential is a dump of a credential, whatever it is named
    ("lq861/head/config/ci_gates/secret_pii_scan_20261027.json", True),
    ("config/secret_registry.yaml", True),
    ("logs/prepublish-secrets.log", True),
    ("certs/cacert.pem", True),
])
def test_scratch_protected_in_a_partial_export_without_markers(world, rel, holds):
    root, rules = _root(world)
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("rel, holds", [
    ("wt/config/secret_registry.yaml", False),   # a nested work tree is already exempt
    ("task/notes/.env", True),                   # no marker anywhere: a real credential name at large
    ("task/config/lane_stay_on_cron_tokens.json", True),
])
def test_scratch_protected_partial_copy_without_markers(world, rel, holds):
    root, rules = _root(world)
    (root / "wt").mkdir(parents=True, exist_ok=True)
    (root / "wt" / ".git").write_text("gitdir: /nonexistent")
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("rel", ["config/.env.example", "config/.env.sample", "config/settings.env.template",
                                 "config/env.dist"])
def test_templates_never_hold(world, rel):
    root, rules = _root(world)
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is False


@pytest.mark.parametrize("body, holds", [
    (HARNESS_HEADER + "DB_HOST=127.0.0.1\nDB_USER=trade_ai\nTRADEAI_ENV=emulation\n", False),
    # the same name without the harness header is not ours to judge as config-only
    ("DB_HOST=127.0.0.1\nDB_USER=trade_ai\n", True),
    # a password line means the harness contract was broken: hold it
    (HARNESS_HEADER + "DB_HOST=127.0.0.1\nDB_PASSWORD=hunter2\n", True),
    (HARNESS_HEADER + "export API_TOKEN=abc\n", True),
])
def test_emulation_env_holds_unless_the_harness_header_says_config_only(world, body, holds):
    root, rules = _root(world)
    target = _make(root, "n8n-emulate/lane/20261107T224519/emulation.env", body)
    assert DH.scratch_protected(target, root, rules) is holds


def test_never_touch_path_still_wins_over_the_repo_export_exemption(world):
    home, rules, _, _ = world
    root, _ = _root(world)
    _repo_export(root, ".")
    assert DH.scratch_protected(home / "persistent-state" / "x.env", root, rules) is True
