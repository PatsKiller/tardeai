"""Resolve attestation HEAD / base SHAs without exception-as-predicate.

CI shallow checkouts often lack ``origin/main``. Callers must supply an
explicit base (``--base-sha`` / ``SOP_ATTESTATION_BASE_SHA``) or ensure the
base ref is fetchable. Never treat ``check_output`` raising as a boolean.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.I)


class AttestationBaseError(RuntimeError):
    """Fail-closed base/head resolution error (machine-readable prefix)."""


def _git_try(args: list[str], *, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        out = (proc.stderr or "").strip()
    return proc.returncode, out


def _normalize_sha(raw: str, *, label: str) -> str:
    s = (raw or "").strip().lower()
    if s.startswith("origin/"):
        # Allow ref names through rev-parse below; not a bare sha yet.
        return s
    if len(s) > 40 and _SHA_RE.match(s[:40]):
        s = s[:40]
    if not _SHA_RE.match(s) and not s.startswith("origin/") and "/" not in s and not s.startswith("refs/"):
        # short sha or other — still try rev-parse
        pass
    return s


def resolve_commit(cwd: Path, rev: str, *, label: str) -> str:
    """Resolve ``rev`` to a full 40-char commit SHA or raise."""
    rc, out = _git_try(["rev-parse", "--verify", f"{rev}^{{commit}}"], cwd=cwd)
    if rc != 0 or not out:
        raise AttestationBaseError(f"BASE_SHA_INVALID:{label}:{rev}")
    sha = out.lower()
    if not _SHA_RE.match(sha):
        raise AttestationBaseError(f"BASE_SHA_INVALID:{label}:{rev}->{sha}")
    return sha


def resolve_attestation_head_sha(*, cwd: Path, explicit: str | None = None) -> str:
    """Prefer explicit override, else ``git rev-parse HEAD`` (never GITHUB merge SHA).

    GitHub Actions sets ``GITHUB_SHA`` to the *synthetic merge commit* for
    ``pull_request`` events. After checking out ``pull_request.head.sha``,
    ``HEAD`` is the true source tip — use that.
    """
    if explicit and explicit.strip():
        return resolve_commit(cwd, explicit.strip(), label="explicit_head")
    env = (os.environ.get("SOP_ATTESTATION_HEAD_SHA") or "").strip()
    if env:
        return resolve_commit(cwd, env, label="SOP_ATTESTATION_HEAD_SHA")
    rc, out = _git_try(["rev-parse", "HEAD"], cwd=cwd)
    if rc != 0 or not _SHA_RE.match(out.lower()):
        raise AttestationBaseError("HEAD_SHA_UNAVAILABLE")
    return out.lower()


def resolve_attestation_base_sha(
    *,
    cwd: Path,
    explicit: str | None = None,
    head_sha: str | None = None,
) -> str:
    """Resolve merge-base / base tip for attestation.

    Order:
    1. ``explicit`` / ``--base-sha``
    2. ``SOP_ATTESTATION_BASE_SHA`` or ``GITHUB_BASE_SHA``
    3. ``merge-base(HEAD, origin/main)`` only if ``origin/main`` resolves
       without treating exceptions as booleans

    Fail closed with ``BASE_SHA_UNAVAILABLE`` when none work.
    """
    head = head_sha or resolve_attestation_head_sha(cwd=cwd)
    candidates: list[tuple[str, str]] = []
    if explicit and explicit.strip():
        candidates.append(("explicit", explicit.strip()))
    for key in ("SOP_ATTESTATION_BASE_SHA", "GITHUB_BASE_SHA"):
        val = (os.environ.get(key) or "").strip()
        if val:
            candidates.append((key, val))

    for label, rev in candidates:
        base_tip = resolve_commit(cwd, rev, label=label)
        rc, mb = _git_try(["merge-base", head, base_tip], cwd=cwd)
        if rc != 0 or not mb:
            # If tip equals HEAD (empty PR) merge-base may still work; otherwise fail.
            raise AttestationBaseError(f"BASE_SHA_MERGE_BASE_FAILED:{label}:{base_tip}")
        return mb.lower()

    # origin/main optional path — probe without exception-as-predicate
    rc, origin_main = _git_try(["rev-parse", "--verify", "origin/main^{commit}"], cwd=cwd)
    if rc == 0 and origin_main:
        rc2, mb = _git_try(["merge-base", head, origin_main], cwd=cwd)
        if rc2 == 0 and mb:
            return mb.lower()
        raise AttestationBaseError("BASE_SHA_MERGE_BASE_FAILED:origin/main")

    raise AttestationBaseError(
        "BASE_SHA_UNAVAILABLE: pass --base-sha or set SOP_ATTESTATION_BASE_SHA "
        "(CI must fetch the PR base); origin/main is not present in this checkout"
    )
