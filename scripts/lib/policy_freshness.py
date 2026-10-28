#!/usr/bin/env python3
"""policy_freshness.py — is the AGENTS.md this agent reads the one origin/main has right now?

Operator, 2026-10-28, verbatim: "How can we force every agent to, before they start, to look at the latest copy of
the agents.md and not a cache copy? This is critical … How about if we go to [version] 27? How do the agents
automatically know to check in to see if there's a new one?"

One library, used by every gate (claim, pre-commit, pre-push, CI, the version-change broadcast and the session-start
reminder). Nothing here hard-codes a version: each call compares the agent's copy with what ``origin/main`` holds at
that moment.

How the comparison works
------------------------
1. ``git fetch origin +refs/heads/main:refs/remotes/origin/main``, best effort, bounded by a short timeout
   (``TRADEAI_POLICY_FETCH_TIMEOUT_S``, default 6 s, never below ``MIN_FETCH_TIMEOUT_S`` = 3 s so the variable cannot
   force offline mode). No prompt, no credential helper dialogue.
2. The agent's copy is the worktree file ``AGENTS.md`` (what the agent actually reads), or ``<rev>:AGENTS.md`` when a
   revision is named (the pre-push gate checks each pushed commit). Main's copy is ``origin/main:AGENTS.md``. Both are
   compared by git blob id, and both ``Policy-Version`` values are parsed for the message.
3. Verdicts:
   * ``OK``      the blobs match; or the branch edits AGENTS.md *on top of* main's current copy (the merge-base of the
                 branch and origin/main already holds main's AGENTS.md blob: the branch is ahead, not behind) AND its
                 Policy-Version is not lower than main's — reported as ``exempt``.
   * ``STALE``   the blobs differ and the branch is not ahead of main's copy; or it is "ahead" but carries a LOWER or
                 unreadable Policy-Version (a downgrade is never exempt). Every gate refuses this.
   * ``UNKNOWN`` the comparison could not be made (no origin/main ref, no AGENTS.md on one side, git failed).
                 **UNKNOWN is a warning, not a pass**: gates print it loudly and continue, because a missing remote must
                 not stop local work, but nobody may read it as "fresh".
4. **No network.** When the fetch fails the comparison falls back to the last-fetched ``origin/main`` and says so
   (``offline: true`` plus the time of the last fetch). An offline OK is still printed with that caveat; an offline
   STALE still refuses.

CLI (used by the hooks)::

    python3 scripts/lib/policy_freshness.py [--repo DIR] [--rev REV ...] [--no-fetch] [--json] [--gate NAME]

Exit codes: 0 OK · 1 STALE · 3 UNKNOWN (warning) · 2 usage.
AUTHORITY: READ_ONLY_ADVISORY — reads git objects and refreshes the ``origin/main`` remote-tracking ref; writes nothing
else, never pushes, never calls GitHub's API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "PolicyFreshness@v1"
POLICY_FILE = "AGENTS.md"
REMOTE = "origin"
BRANCH = "main"
OK, STALE, UNKNOWN = "OK", "STALE", "UNKNOWN"
EXIT = {OK: 0, STALE: 1, UNKNOWN: 3}
_RANK = {OK: 0, UNKNOWN: 1, STALE: 2}  # the worst verdict of several wins
ENV_FETCH_TIMEOUT = "TRADEAI_POLICY_FETCH_TIMEOUT_S"
DEFAULT_FETCH_TIMEOUT_S = 6.0
MIN_FETCH_TIMEOUT_S = 3.0  # floor: a tiny timeout would force "offline" and compare against an old fetch
FIX_HINT = "work from fresh origin/main (scripts/new-worktree.sh) and re-read §0"

_CONTROL_RE = re.compile(r"```\n(Policy-Version:.*?)```", re.DOTALL)
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass
class Freshness:
    status: str
    local_version: str | None = None
    remote_version: str | None = None
    local_blob: str | None = None
    remote_blob: str | None = None
    local_source: str = "worktree"
    remote_ref: str = f"{REMOTE}/{BRANCH}"
    exempt: bool = False
    offline: bool = False
    fetch: str = "skipped"
    last_fetch_at: str | None = None
    reason: str = ""
    schema: str = SCHEMA
    notes: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return EXIT[self.status]

    def message(self) -> str:
        offline = (
            f" (offline: compared with {self.remote_ref} as last fetched {self.last_fetch_at or 'at an unknown time'};"
            f" fetch {self.fetch})"
            if self.offline
            else ""
        )
        if self.status == STALE:
            lv, rv = self.local_version or "unversioned", self.remote_version or "unversioned"
            same = " (same version number, different text)" if lv == rv else ""
            why = f" ({self.reason})" if self.reason else ""
            return f"STALE_POLICY: your AGENTS.md is {lv}, {self.remote_ref} is {rv}{same}{why}; {FIX_HINT}{offline}"
        if self.status == UNKNOWN:
            return (
                f"UNKNOWN_POLICY: could not compare your AGENTS.md with {self.remote_ref} ({self.reason}). "
                "This is a warning, not a pass: check by hand with "
                f"`git fetch {REMOTE} {BRANCH} && git diff --stat HEAD {self.remote_ref} -- {POLICY_FILE}`"
            )
        if self.exempt:
            return (
                f"policy OK: this branch edits AGENTS.md ({self.local_version}) on top of {self.remote_ref}'s"
                f" {self.remote_version}{offline}"
            )
        return f"policy OK: AGENTS.md {self.local_version} matches {self.remote_ref}{offline}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["message"] = self.message()
        return d


def parse_policy_version(text: str | None) -> str | None:
    """The control block's ``Policy-Version`` value, or None."""
    if not text:
        return None
    m = _CONTROL_RE.search(text)
    for line in (m.group(1) if m else "").splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() == "Policy-Version":
            return v.strip() or None
    return None


def semver(v: str | None) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match((v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def version_behind(head: str | None, base: str | None) -> bool:
    """True when ``head`` is a strictly lower semantic version than ``base``; False when either is unparseable."""
    h, b = semver(head), semver(base)
    return bool(h and b and h < b)


def _git(repo: Path | str, *args: str, timeout: float = 15, env: dict | None = None) -> str | None:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", **(env or {})},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def toplevel(repo: Path | str | None = None) -> Path | None:
    out = _git(repo or os.getcwd(), "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None


def fetch_timeout() -> float:
    try:
        return max(MIN_FETCH_TIMEOUT_S, float(os.environ.get(ENV_FETCH_TIMEOUT, DEFAULT_FETCH_TIMEOUT_S)))
    except ValueError:
        return DEFAULT_FETCH_TIMEOUT_S


def fetch_main(repo: Path | str, *, timeout: float | None = None) -> tuple[bool, str]:
    """Refresh ``refs/remotes/origin/main``. Returns (ok, detail); never raises."""
    t = fetch_timeout() if timeout is None else timeout
    env = {}
    if not os.environ.get("GIT_SSH_COMMAND"):
        env["GIT_SSH_COMMAND"] = f"ssh -o BatchMode=yes -o ConnectTimeout={max(1, int(t))}"
    try:
        p = subprocess.run(
            ["git", "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{BRANCH}:refs/remotes/{REMOTE}/{BRANCH}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=t,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **env},
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {t:g} s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, type(exc).__name__
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()
        return False, (tail[-1] if tail else f"rc {p.returncode}")[:160]
    return True, "fetched"


def _last_fetch_at(repo: Path | str) -> str | None:
    common = _git(repo, "rev-parse", "--git-common-dir")
    if not common:
        return None
    base = Path(common.strip())
    if not base.is_absolute():
        base = Path(repo) / base
    for name in ("FETCH_HEAD", f"refs/remotes/{REMOTE}/{BRANCH}", f"logs/refs/remotes/{REMOTE}/{BRANCH}"):
        p = base / name
        if p.exists():
            return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def blob_at(repo: Path | str, rev: str, path: str = POLICY_FILE) -> str | None:
    out = _git(repo, "rev-parse", "--verify", "-q", f"{rev}:{path}")
    return out.strip() if out else None


def text_of_blob(repo: Path | str, blob: str | None) -> str | None:
    return _git(repo, "cat-file", "-p", blob) if blob else None


def remote_policy(repo: Path | str) -> dict:
    """origin/main's AGENTS.md: {"blob", "version", "text"} (values None when unreadable). Does not fetch."""
    ref = f"refs/remotes/{REMOTE}/{BRANCH}"
    blob = blob_at(repo, ref)
    text = text_of_blob(repo, blob)
    return {"ref": ref, "blob": blob, "version": parse_policy_version(text), "text": text}


def local_policy(repo: Path | str, rev: str | None = None) -> dict:
    """The agent's AGENTS.md: the worktree file, or ``rev:AGENTS.md``. {"blob", "version", "source"}."""
    if rev:
        blob = blob_at(repo, rev)
        return {"blob": blob, "version": parse_policy_version(text_of_blob(repo, blob)), "source": f"rev:{rev}"}
    f = Path(repo) / POLICY_FILE
    if not f.is_file():
        return {"blob": None, "version": None, "source": "worktree"}
    out = _git(repo, "hash-object", "--", POLICY_FILE)
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None
    return {"blob": out.strip() if out else None, "version": parse_policy_version(text), "source": "worktree"}


def evaluate(
    repo: Path | str | None = None,
    *,
    rev: str | None = None,
    fetch: bool = True,
    fetch_result: tuple[bool, str] | None = None,
) -> Freshness:
    """Compare the agent's AGENTS.md with origin/main's. Never raises; an error is UNKNOWN with the reason."""
    try:
        return _evaluate(repo, rev=rev, fetch=fetch, fetch_result=fetch_result)
    except Exception as exc:  # noqa: BLE001 - a gate must report, never crash into a silent pass
        return Freshness(UNKNOWN, reason=f"freshness check failed: {type(exc).__name__}: {exc}"[:200])


def _evaluate(
    repo: Path | str | None, *, rev: str | None, fetch: bool, fetch_result: tuple[bool, str] | None
) -> Freshness:
    top = toplevel(repo)
    if top is None:
        return Freshness(UNKNOWN, reason="not inside a git repository")
    if fetch_result is not None:
        fetched, detail = fetch_result
    elif fetch:
        fetched, detail = fetch_main(top)
    else:
        fetched, detail = False, "skipped (--no-fetch)"
    res = Freshness(UNKNOWN, fetch=detail, offline=not fetched)
    if not fetched:
        res.last_fetch_at = _last_fetch_at(top)
    remote = remote_policy(top)
    local = local_policy(top, rev)
    res.local_source = local["source"]
    res.local_blob, res.local_version = local["blob"], local["version"]
    res.remote_blob, res.remote_version = remote["blob"], remote["version"]
    if not remote["blob"]:
        res.reason = f"no {POLICY_FILE} on {res.remote_ref} (no such ref, or never fetched)" + (
            "" if fetched else f"; fetch {detail}"
        )
        return res
    if not local["blob"]:
        res.reason = f"no {POLICY_FILE} in {local['source']}"
        return res
    if local["blob"] == remote["blob"]:
        res.status = OK
        return res
    base_rev = rev or "HEAD"
    mb = _git(top, "merge-base", base_rev, remote["ref"])
    if mb is None:
        res.status = STALE
        res.notes.append(f"no merge-base between {base_rev} and {res.remote_ref}")
        return res
    if blob_at(top, mb.strip()) == remote["blob"]:
        lv, rv = semver(local["version"]), semver(remote["version"])
        if lv is None or rv is None:
            res.status = STALE
            res.reason = "a branch that edits AGENTS.md must carry a readable Policy-Version"
            return res
        if lv < rv:
            res.status = STALE
            res.reason = "this branch lowers Policy-Version below main's; a downgrade is never exempt"
            return res
        res.status = OK
        res.exempt = True
        res.notes.append(f"merge-base {mb.strip()[:12]} already holds {res.remote_ref}'s {POLICY_FILE}")
        return res
    res.status = STALE
    return res


def evaluate_many(repo: Path | str | None, revs: list[str], *, fetch: bool = True) -> list[Freshness]:
    """Evaluate several revisions with one fetch (the pre-push gate: one result per pushed commit)."""
    top = toplevel(repo)
    if top is None:
        return [Freshness(UNKNOWN, reason="not inside a git repository")]
    fr = fetch_main(top) if fetch else (False, "skipped (--no-fetch)")
    targets: list[str | None] = list(revs) if revs else [None]
    return [evaluate(top, rev=r, fetch_result=fr) for r in targets]


def worst(results: list[Freshness]) -> Freshness:
    return max(results, key=lambda r: _RANK[r.status])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=None, help="repository or worktree (default: the current directory)")
    ap.add_argument("--rev", action="append", default=None, help="check REV:AGENTS.md instead of the worktree file")
    ap.add_argument("--no-fetch", action="store_true", help="compare with the last-fetched origin/main")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", default=None, help="label for the printed line (claim, pre-commit, pre-push, session)")
    a = ap.parse_args(argv)
    results = evaluate_many(a.repo, list(a.rev or []), fetch=not a.no_fetch)
    w = worst(results)
    label = f"[{a.gate}] " if a.gate else ""
    if a.json:
        print(json.dumps([r.to_dict() for r in results] if len(results) > 1 else w.to_dict(), indent=2))
    else:
        for r in results if len(results) > 1 else [w]:
            src = f" ({r.local_source})" if r.local_source != "worktree" else ""
            stream = sys.stdout if r.status == OK else sys.stderr
            print(f"{label}{r.message()}{src}", file=stream)
    return w.exit_code


if __name__ == "__main__":
    sys.exit(main())
