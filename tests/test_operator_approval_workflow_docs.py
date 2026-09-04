"""Guarded remote-push and live-deployment workflow must stay fail-closed."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
TITLE = "## Operator approval for remote push and live deployment"


def _section() -> str:
    text = AGENTS.read_text(encoding="utf-8")
    start = text.index(TITLE)
    end = text.find("\n## ", start + len(TITLE))
    return text[start:] if end == -1 else text[start:end]


def test_operator_approval_section_has_absolute_guard_workflow() -> None:
    section = _section()
    required = (
        'GUARD_PATH="<absolute_repo_or_worktree_root>/bin/guard"',
        '"$GUARD_PATH" grant git-push --for 30m --uses 3 --reason',
        '"$GUARD_PATH" grant release-write --for 30m --uses 3 --reason',
        '"$GUARD_PATH" revoke git-push',
        '"$GUARD_PATH" revoke release-write',
        '"$GUARD_PATH" show',
        'CANDIDATE_PATH="/known/candidate/path"',
        'REPO_ROOT="$(git -C "$CANDIDATE_PATH" rev-parse --show-toplevel)"',
    )
    for expected in required:
        assert expected in section
    assert "native interactive guard prompt" in section
    assert "The operator types" in section
    assert "exact merge SHA" in section
    assert "automatically roll back" in section


def test_guard_grants_cannot_be_relative_or_combined() -> None:
    section = _section()
    assert not re.search(r"(?<![\"$\w])bin/guard\s+grant\b", section)
    grant_lines = [line for line in section.splitlines() if '"$GUARD_PATH" grant ' in line]
    assert len(grant_lines) == 2
    for line in grant_lines:
        assert line.count("git-push") + line.count("release-write") == 1
        assert '"$GUARD_PATH"' in line


def test_approval_cannot_be_automated_and_cleanup_is_mandatory() -> None:
    section = _section()
    assert not re.search(
        r"(?:echo|printf|yes|expect|python\S*|bash\S*|sh\S*)[^\n]*\bAPPROVE\b",
        section,
        flags=re.IGNORECASE,
    )
    assert "never type, pipe, simulate, automate, or infer" in section
    revoke_push = section.index('"$GUARD_PATH" revoke git-push')
    revoke_release = section.index('"$GUARD_PATH" revoke release-write')
    final_show = section.rindex('"$GUARD_PATH" show')
    assert revoke_push < final_show
    assert revoke_release < final_show


def test_scope_boundaries_are_explicit() -> None:
    section = _section()
    assert "git-push` does not authorize merge or deployment" in section
    assert "release-write` does not authorize Git operations" in section
    for forbidden in (
        "force-push",
        "history rewriting",
        "production data mutation",
        "credential mutation",
        "scheduler mutation",
        "broker mutation",
        "trading authority",
    ):
        assert forbidden in section
