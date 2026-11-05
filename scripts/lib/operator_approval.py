"""The one form of operator approval a push guard will accept: a GitHub comment URL.

The grant-free push path (`bin/agent-push <branch>`) reads an
``Operator-approval: <ref>`` line from the claim's worklog or the open PR body. The guard does
not accept a free-text reference — it resolves the ref to a comment the operator posted on the
canonical repository, because a relayed or self-written line is not an approval (AGENTS.md
§28.4). This module validates that shape early, so an agent finds the mistake at claim time
instead of at push time.

It is advisory only: the guard remains the authority. Nothing here records an approval that the
operator did not post, and nothing here pushes.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import re
from typing import Optional

CANONICAL_REPO = "PatsKiller/tardeai"
#: ``https://github.com/<owner>/<repo>/pull/<n>#issuecomment-<id>`` (an issue URL also serves).
URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?:pull|issues)/(?P<num>\d+)"
    r"#issuecomment-(?P<id>\d+)$"
)
PREFIX = "Operator-approval:"

#: Printed when a push is refused for a missing or unresolvable approval line.
FIX_HINT = (
    "the operator posts the approval from their own GitHub account, then gives the agent the "
    "comment URL:\n"
    "  ~/bin/approve-push <PR>:<branch>     # posts 'APPROVE_PUSH <branch>' as the operator\n"
    "  then: scripts/agent_claim.py claim ... --operator-approval '<comment URL>'"
)


def validate(ref: Optional[str]) -> str:
    """Return the ref unchanged, or raise with the exact fix. Accepts only a comment URL."""
    value = (ref or "").strip()
    if not value:
        raise ValueError(f"an approval ref is required.\n{FIX_HINT}")
    m = URL_RE.match(value)
    if not m:
        raise ValueError(
            f"Operator-approval {value!r} is not a GitHub comment URL.\n"
            f"It must look like https://github.com/{CANONICAL_REPO}/pull/<n>#issuecomment-<id>.\n"
            f"{FIX_HINT}"
        )
    repo = f"{m.group('owner')}/{m.group('repo')}"
    if repo.lower() != CANONICAL_REPO.lower():
        raise ValueError(f"Operator-approval must be a comment on {CANONICAL_REPO}, not {repo}.\n{FIX_HINT}")
    return value


def approval_line(ref: Optional[str]) -> str:
    """The line to write into a claim worklog or a PR body."""
    return f"{PREFIX} {validate(ref)}"


def merge_into_note(note: Optional[str], ref: Optional[str]) -> Optional[str]:
    """Prepend the approval line to a claim note, leaving the note otherwise untouched."""
    if not ref:
        return note
    line = approval_line(ref)
    return f"{line}\n{note}" if note else line
