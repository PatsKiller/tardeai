"""ANCHOR: DISK_HYGIENE_SCRATCH_PROTECTION_20261109 — rule T exempts a file by its SHAPE, never by where it sits.

Rule T's meaning of "protected" inside an agent scratch dir, on top of LQ-1456 (LQ-20261107-1366).

LQ-1456 gave rule T a rules-driven repo-copy exemption for two source globs (``*token*``, ``*secret*``). The
non-author reviews of LQ-20261107-1366 (agent2_grok, grok-a) found the remaining false holds: a template
(``.env.example``, matched by ``.env.*``) and a source file whose name is not one of those two globs
(``credential_monitor.py``) still pin the whole scratch tree, and the harness-written ``emulation.env`` pins
every emulated lane. This file fixes the boundary by FILE SHAPE, not by where the file sits:

* a template carries no value -> never holds;
* source code names a subject, not a value -> never holds;
* a harness ``emulation.env`` is exempt on its header, and a credential line beside it outranks every tree
  exemption, case-insensitively;
* every credential STORE shape (``.env``, ``*.pem``, ``*.key``, ``credentials.json``, ``id_ed25519``) still holds.

grok-a's review (2026-11-09) found the first cut of this file proved a list the module did not use: rule T's
suffix tuple shared a global name with ``_credential_name``'s shorter one, and the later assignment won, so
``.tmpl``/``.tpl``/``.dist`` still held. The tuple has its own name now, and the three shapes are pinned
(``test_templates_never_hold``) alongside the constant itself — ``config/env.dist`` was dropped from that
parametrization because it never matched a credential name at all, so it could only pass for the wrong reason.

Synthetic tmp_path trees only; no host census, no real home.
COVERS = ["scripts/disk_hygiene.py"]
"""
from __future__ import annotations

import pytest

from scripts import disk_hygiene as DH
from tests.test_disk_standing_apply_20261024 import world  # noqa: F401 -- a pytest fixture, used by name in the signatures

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
    # a repo copy is not evidence about an untracked file, so a credential STORE still holds below the marker
    (".env", True),
    ("config/.env", True),
    ("certs/server.pem", True),
    ("certs/server.key", True),
    (".ssh/id_rsa", True),
    ("id_ed25519", True),
    ("config/credentials.json", True),
    # a template is not a store, and a source file names a subject: neither holds, marker or not
    ("config/.env.example", False),
    ("config/settings.env.sample", False),
    ("config/.env.dist", False),
    ("scripts/credential_monitor.py", False),
    ("src/lib/designTokens.ts", False),
    ("tokens.css", False),
    (".github/workflows/secret-scan.yml", False),   # the LQ-1456 case, now by shape rather than by glob name
])
def test_scratch_protected_inside_a_repo_export(world, rel, holds):
    root, rules = _root(world)
    _repo_export(root, ".")
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("marker", [True, False], ids=["repo_copy", "bare_tree"])
@pytest.mark.parametrize("rel, holds", [
    ("config/.env", True),
    ("certs/server.key", True),
    (".ssh/id_rsa", True),
    ("scripts/credential_monitor.py", False),   # source stays exempt with or without the marker
    ("config/.env.example", False),             # a template carries no secret either way
])
def test_the_repo_marker_changes_nothing_about_a_credential(world, rel, holds, marker):
    """The review's core case: the same paths with and without ``pyproject.toml`` above them."""
    root, rules = _root(world)
    if marker:
        _repo_export(root, ".")
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("rel, holds", [
    # a *partial* export carries no project marker; the file shape is what decides
    ("lq258/base/tests/test_youtube_cookie_path_20261014.py", False),
    ("lq601/run_b/scripts/credential_monitor.py", False),
    ("src/lib/designTokens.ts", False),
    ("scripts/lib/secret_name_classes.py", False),
    ("scripts/brokers/__pycache__/alpaca_credentials.cpython-314.pyc", False),
    ("lq861/head/config/credentials.json", True),
    ("logs/prepublish-secrets.log", True),
    ("certs/cacert.pem", True),
])
def test_scratch_protected_by_file_shape_without_markers(world, rel, holds):
    root, rules = _root(world)
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("rel", ["config/.env.example", "config/.env.sample", "config/settings.env.template",
                                 "config/.env.tmpl", "config/.env.tpl", "config/.env.dist"])
def test_templates_never_hold(world, rel):
    root, rules = _root(world)
    target = _make(root, rel)
    assert DH.scratch_protected(target, root, rules) is False


def test_the_rule_t_suffix_tuple_is_its_own_global():
    """grok-a, 2026-11-09. ``_credential_name`` keeps a SHORTER tuple under ``_TEMPLATE_SUFFIXES`` later in the
    module. A second assignment of one global is read at call time, so the first version of this fix shipped a
    list that said ``.tmpl``/``.tpl``/``.dist`` while the tuple rule T actually saw did not: those shapes held.
    The rule-T list has its own name and the long value; a regression here means one of the two was renamed back."""
    assert DH._SCRATCH_TEMPLATE_SUFFIXES == (".example", ".sample", ".template", ".tmpl", ".tpl", ".dist")
    assert ".tmpl" in DH._SCRATCH_TEMPLATE_SUFFIXES and ".tpl" in DH._SCRATCH_TEMPLATE_SUFFIXES


@pytest.mark.parametrize("body, holds", [
    (HARNESS_HEADER + "DB_HOST=127.0.0.1\nDB_USER=trade_ai\nTRADEAI_ENV=emulation\n", False),
    # the same name without the harness header is not ours to judge as config-only
    ("DB_HOST=127.0.0.1\nDB_USER=trade_ai\n", True),
    # a password line means the harness contract was broken: hold it
    (HARNESS_HEADER + "DB_HOST=127.0.0.1\nDB_PASSWORD=hunter2\n", True),
    (HARNESS_HEADER + "export API_TOKEN=abc\n", True),
    # the scan is case-insensitive: a lower-case assignment is just as much a credential (review, 2026-11-09)
    (HARNESS_HEADER + "db_host=127.0.0.1\ndb_password=hunter2\n", True),
    (HARNESS_HEADER + "db_host=127.0.0.1\napi_key=abc\n", True),
])
def test_emulation_env_holds_unless_the_harness_header_says_config_only(world, body, holds):
    root, rules = _root(world)
    target = _make(root, "n8n-emulate/lane/20261107T224519/emulation.env", body)
    assert DH.scratch_protected(target, root, rules) is holds


@pytest.mark.parametrize("body, holds", [
    (HARNESS_HEADER + "DB_HOST=127.0.0.1\n", False),   # config only: exempt even below a repo marker
    (HARNESS_HEADER + "db_password=hunter2\n", True),  # a broken harness contract outranks the repo exemption
])
def test_a_secret_line_in_an_emulation_env_survives_every_tree_exemption(world, body, holds):
    root, rules = _root(world)
    _repo_export(root, ".")
    target = _make(root, "lanes/n8n-emulate/20261107T224519/emulation.env", body)
    assert DH.scratch_protected(target, root, rules) is holds


def test_a_secret_line_in_an_emulation_env_survives_a_pytest_fixture_tree(world):
    root, rules = _root(world)
    target = _make(root, "pytest-of-u/pytest-3/t0/emulation.env", HARNESS_HEADER + "API_SECRET=abc\n")
    assert DH.scratch_protected(target, root, rules) is True


def test_never_touch_path_still_wins_over_every_shape_exemption(world):
    """A protected PATH is absolute: no template or source shape releases it (the shape checks sit after it)."""
    home, rules, _, _ = world
    root, _ = _root(world)
    _repo_export(root, ".")
    protected = home / "persistent-state"
    protected.mkdir(parents=True, exist_ok=True)
    rules = {**rules, "_never_paths": [protected]}
    for rel in ("x.env", "x.env.example", "credential_monitor.py"):
        target = _make(protected, rel)
        assert DH.scratch_protected(target, protected, rules) is True


def test_a_symlink_never_holds(world):
    root, rules = _root(world)
    link = root / "link.env"
    link.symlink_to(root / "notes-target")
    assert DH.scratch_protected(link, root, rules) is False
