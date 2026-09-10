"""The wake state root must survive a release promote.

INC-2026-09-09-STATE-ROOT-FORK. Persistent-wake evidence lived at
``<release>/data/persistent_wake/state``. ``prepare`` snapshots the current
release, so any wake firing between prepare and promote was stranded in the
retiring release and never appeared in the new one. The evidence FORKED on every
deploy, invisibly: both files look healthy in isolation.

Observed on 2026-09-09:

    dbdf498b9 (retired)   102 rows, latest slot 2026-09-09T23:00Z
    a8a896609 (promoted)   99 rows, latest slot 2026-09-09T19:00Z
    promote at 23:14Z, i.e. AFTER the 23:00Z wake

Consequence: three contiguous organic cycles can never accumulate across a
promote, so the M2 acceptance bar was structurally unreachable whenever a deploy
landed mid-epoch.

These controls must fail if the release-internal default is reintroduced.
"""
from __future__ import annotations

from pathlib import Path

from scripts.run_persistent_wake import (
    DEFAULT_STATE_ENV,
    SHARED_STATE_ROOT,
    _default_state_root,
    _is_release_tree,
)


def test_explicit_env_var_always_wins(tmp_path):
    """An operator-set root is honoured verbatim, release or not."""
    assert _default_state_root({DEFAULT_STATE_ENV: str(tmp_path)}) == tmp_path


def test_release_tree_resolves_to_the_shared_root():
    """The regression control: a release must NOT use a release-internal path."""
    import scripts.run_persistent_wake as rpw

    original = rpw._PROJECT
    try:
        rpw._PROJECT = Path(
            "/home/johnclaw/trade-ai-releases/portfolio-server/"
            "a8a896609-main-exact-phase2-20260909-191102"
        )
        got = _default_state_root({})
        assert got == SHARED_STATE_ROOT, f"release tree resolved to {got}"
        assert "trade-ai-releases" not in got.parts, (
            "state root is inside a release directory; it will fork on the next "
            "promote exactly as it did on 2026-09-09"
        )
    finally:
        rpw._PROJECT = original


def test_dev_tree_keeps_project_local_path():
    """Non-release checkouts are unchanged, so dev and CI behaviour is stable."""
    import scripts.run_persistent_wake as rpw

    original = rpw._PROJECT
    try:
        rpw._PROJECT = Path("/home/johnclaw/trade-ai-worktrees/some-dev-tree")
        got = _default_state_root({})
        assert got == rpw._PROJECT / "data" / "persistent_wake" / "state"
    finally:
        rpw._PROJECT = original


def test_release_marker_detection():
    assert _is_release_tree(Path("/home/johnclaw/trade-ai-releases/portfolio-server/x"))
    assert not _is_release_tree(Path("/home/johnclaw/trade-ai-worktrees/x"))
    assert not _is_release_tree(Path("/tmp/x"))


def test_two_consecutive_releases_share_one_root():
    """The property that actually matters: evidence does not fork on promote."""
    import scripts.run_persistent_wake as rpw

    original = rpw._PROJECT
    roots = []
    try:
        for rel in (
            "dbdf498b9-main-exact-phase2-20260909-182342",
            "a8a896609-main-exact-phase2-20260909-191102",
        ):
            rpw._PROJECT = Path(f"/home/johnclaw/trade-ai-releases/portfolio-server/{rel}")
            roots.append(_default_state_root({}))
    finally:
        rpw._PROJECT = original
    assert roots[0] == roots[1], (
        f"consecutive releases resolved to different roots {roots}; "
        "wake evidence would fork across the promote"
    )
