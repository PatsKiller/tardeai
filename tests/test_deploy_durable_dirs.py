"""Durable data directories must survive a promote.

Measured 2026-09-05 inside the serving release:

    data/cio      -> persistent-state/data/cio      (symlink)
    data/runtime  -> persistent-state/data/runtime  (symlink)
    data/audit    -> a REAL DIRECTORY in the release

`cio-material-scan` ran at 20:03 that day, its systemd service exited SUCCESS,
and it wrote a 39KB receipt into `data/audit` — a directory that disappears on
the next promote. Orphaned copies of that receipt sit in at least four
superseded release dirs, and every monitor reading the canonical root reported
the lane SILENT.

AGENTS.md says exit code 0 is not evidence of work. This is the same failure
seen from the other side: the work happened and the evidence was thrown away.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"

#: Directories observed holding same-day writes with no copy under the canonical
#: root. Each one silently discarded its producer's output on every deploy.
NEWLY_DURABLE = ("data/audit", "data/paper_trading", "data/state", "state/hermes")

#: Already linked before this change; they must not be dropped by a later edit.
ALREADY_DURABLE = ("data/portfolios/state", "data/runtime", "data/cio",
                   "data/health", "state/data_broker", "logs")


@pytest.fixture(scope="module")
def src() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _else_branch(src: str) -> str:
    """The branch taken when the canonical source does not yet exist.

    Anchored on the loop, not on any one log line: the previous version keyed on
    the WARN message that this change replaced, so the test broke on the very
    edit it was written to describe.
    """
    body = re.search(r'for rel in "\$\{dirs\[@\]\}"; do(.*?)\n  done', src, re.S)
    assert body, "could not locate the durable-directory link loop"
    return body.group(1).split("else", 1)[1]


@pytest.fixture(scope="module")
def dirs_block(src: str) -> str:
    m = re.search(r"local dirs=\((.*?)\n  \)", src, re.S)
    assert m, "could not find the durable-directory list in the deploy script"
    return m.group(1)


@pytest.mark.parametrize("rel", NEWLY_DURABLE)
def test_the_orphaning_directories_are_declared_durable(dirs_block: str, rel: str):
    assert f'"{rel}"' in dirs_block, (
        f"{rel} holds same-day writes and is not linked to the canonical root, "
        "so every promote discards it")


@pytest.mark.parametrize("rel", ALREADY_DURABLE)
def test_the_existing_durable_directories_are_still_declared(dirs_block: str, rel: str):
    assert f'"{rel}"' in dirs_block


def test_a_declared_directory_is_linked_even_when_the_source_is_missing(src: str):
    """Adding a name to the list must actually fix something.

    reports/ was added on 2026-09-01 and linked nothing, because the source did
    not exist and the else-branch only logged a warning. A path on that list is
    DECLARED durable; if the canonical source is absent it gets created.
    """
    else_branch = _else_branch(src)
    assert 'mkdir -p "$source"' in else_branch, (
        "a missing canonical source still only warns — the directory stays "
        "orphaned and the list entry does nothing")
    assert 'ln -sfn "$source" "$target"' in else_branch


def test_release_local_contents_are_preserved_not_merged_and_not_deleted(src: str):
    """Two populated copies is a divergence. AGENTS.md 0.5: a machine choosing
    one can destroy the other."""
    else_branch = _else_branch(src)
    assert "release-local-" in else_branch, "no preservation path for existing contents"
    assert 'mv "$target" "$stash"' in else_branch, (
        "existing release-local contents are removed rather than preserved")
    assert "RECONCILE" in else_branch, "the divergence is not reported to the operator"
    # It must not try to be clever and combine the two copies.
    #
    # Checked as BEHAVIOUR, not vocabulary. The first version forbade the word
    # "merge", which matched the branch's own log line promising "nothing
    # merged, nothing deleted" — the sentence guaranteeing the property failed
    # the test for the property. Copying is the only way to actually merge two
    # directories, so the copy commands are what to forbid.
    code_only = "\n".join(ln for ln in else_branch.splitlines()
                          if not ln.strip().startswith("#") and "log " not in ln)
    for forbidden in ("cp ", "rsync", "install -", "tar "):
        assert forbidden not in code_only, (
            f"else-branch runs {forbidden.strip()!r} — that combines two copies of "
            "a durable store, which is the operator's call, not the deploy's")


def test_the_preserved_copy_is_timestamped_so_two_promotes_do_not_collide(src: str):
    else_branch = _else_branch(src)
    assert "date -u +" in else_branch


def test_the_script_still_parses():
    import subprocess
    r = subprocess.run(["bash", "-n", str(DEPLOY)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
