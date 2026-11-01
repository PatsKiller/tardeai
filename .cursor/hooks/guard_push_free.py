#!/usr/bin/env python3
"""guard_push_free -- the ONLY grant-free push route: ``bin/agent-push <branch>`` (AGENTS.md 21.0.0 §28.15 item 8).

Operator, 2026-10-25, verbatim: "I need the agents to be able to upload their own approved work without grants. And
the building tests without grants." Ratified as §28.15 item 8 (PR #2128).

Design (after two adversarial reviews of PR #2148, both DO-NOT-MERGE on the shell-parsing design):

* A raw ``git push`` typed in a shell is NEVER grant-free. The Cursor shell guard keeps today's grant path for it;
  nothing here parses shell text.
* The grant-free route is ``bin/agent-push <branch>`` with exactly one argument that matches ``BRANCH_RE``. The shell
  guard classifies every ``agent-push`` invocation as ``git-push`` and only lets this strict form through when the
  invoked wrapper is byte-identical to the guard tree's and this module's ``check`` passes. The wrapper then clears
  the environment (``env -i``) and runs THIS file from the trusted guard tree (the one ``~/.cursor/hooks.json``
  names, found through the passwd home, never ``$HOME`` or the agent's worktree), which re-checks everything and
  performs the push itself with pinned arguments.
* Trust: this module imports only from the guard tree it lives in (``python3 -I``). Configuration is never read
  from the environment or from a file beside this module; ``--test-config <path>`` is the hermetic-test seam, and
  neither bin/agent-push nor the shell guard passes it in production.
* Fail closed: any error, missing file, unresolvable approval or failed audit write is a refusal (rc 1). The caller
  falls back to the operator's grant path, unchanged.

Conditions for ``push`` (``check`` is the same minus the pusher-session binding and the push):

 1. Environment: no ``GIT_*``, ``TRADEAI_*``, ``GUARD_*``, ``PYTHON*``, ``LD_*``, ``BASH_ENV``/``ENV`` variables.
 2. Branch: strict name, never main/master/release/train; the local ``refs/heads/<branch>`` exists.
 3. Remote: ``origin`` fetch URL == push URL == the pinned canonical URL; no ``url.*.insteadOf``/``pushInsteadOf``
    in any scope; no hijacking keys in local/worktree config (remote.origin.push/mirror/receivepack/pushurl,
    include/includeIf, credential.*, http.*, core.sshCommand, core.gitProxy, a foreign core.hooksPath).
 4. Policy: ``git ls-remote <canonical URL>`` main is in the local object store and its AGENTS.md is 21.0.0+
    ACTIVE (header version, header status, that version's history row).
 5. The tracked pre-push and everything it executes from the worktree (``PREPUSH_CLOSURE``) are byte-identical to
    remote main's, and no module in its import path shadows the stdlib; the push runs it (``core.hooksPath``
    pinned), so the budget count and the secrets scan happen.
 6. Fast-forward: remote branch absent or its ls-remote sha is an ancestor of the local sha; confirmed by a
    ``--dry-run --porcelain`` push that must report exactly one ref, new or fast-forward.
 7. No path in ``merge-base(main)..head`` matches the train's ``broker_active_trader`` globs.
 8. Budget: ``count_for(branch) < budget_for(branch)`` (``scripts/lib/tradeai_push_budget.py`` of the guard tree).
 9. Approved plan, either:
    (a) a LIVE claim on the branch held by the pusher's ``AGENT_CLAIM_SESSION`` whose note or worklog Goal/Plan
        has an ``Operator-approval: <ref>`` line, or
    (b) a coordinator task file (``.md``/``.txt``, handoffs top level or one batch directory down, regular file,
        owned by this user, not group/other-writable) with the exact lines ``Assigned-branch: <branch>``,
        ``Assigned-by: <session>`` (a claim on ``coordination/COORDINATOR`` held by that session) and
        ``Operator-approval: <ref>``;
    and in both cases ``<ref>`` RESOLVES to a GitHub comment on the canonical repo whose author is the operator
    login (``gh api``), which carries no ``APPROVE_AGENTS_POLICY_`` token and has the line ``APPROVE_PUSH <branch>``.
    (c) STANDING approval (operator, 2026-11-01: "Yes, draft stand and approval."): on path (a) only -- the pusher's
        own live claim on the branch is still required -- when no per-branch ref resolves, an operator comment on the
        configured standing-approval issue with the line ``APPROVE_PUSH_STANDING <glob> until <YYYY-MM-DD>`` admits
        the branch only while remote main's AGENTS.md is 29.3.0+ ACTIVE, if: the glob starts with a configured literal prefix (wt/ feat/ fix/ chore/ docs/), never ``*``
        alone and never anything that could match main/master/release/train; the date is today or later (UTC) and at
        most ``standing_max_days`` after the comment; the comment carries no ``APPROVE_AGENTS_POLICY_`` token; and no
        later operator comment on that issue contains ``REVOKE_PUSH_STANDING`` (any case or markup). A closed issue
        admits nothing, and comments made before its latest close never count again (a reopen does not revive them);
        an edited operator comment refuses; lines inside code fences are ignored; dates are UTC. The issue is pinned by
        number or is the single operator issue with the configured title (duplicates refuse). The admitting
        comment's URL is the logged ``approval_ref``. Every other condition above still runs.
    Agent-side ``gh`` comment/review writes are guarded by the shell guard (tier ``gh-write``) because ``gh`` on the
    host is logged in as the operator; the durable fix is a separate agent GitHub identity or passkey-signed
    approvals (follow-up). The
    coordinator claim must be live or stale (not done) with a heartbeat in the last 24 h. The pushed branch must be the
    checked-out HEAD with no modified tracked files (the pre-push secrets scan reads the worktree). Decision-ledger rows are not accepted until they are signed.

    The pusher's session (``AGENT_CLAIM_SESSION``) is self-declared and therefore ADVISORY: it only selects which
    claim is consulted. It cannot widen anything -- the push can only fast-forward that claim's own feature branch,
    and only under an operator comment bound to that branch -- so spoofing it gains another agent's already-approved
    fast-forward at most. Binding it to a process identity (pid/tty) is not possible today: claims record neither.
10. Audit: a hash-chained ``grant-free-push-intent`` line is written BEFORE the push (failure refuses) and a
    ``grant-free-push`` outcome line after it.

stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "GuardGrantFreePush@v2"
MIN_POLICY = (21, 0, 0)
MIN_POLICY_TEXT = "21.0.0"
HOOKS_DIR = Path(__file__).resolve().parent
TRUSTED_ROOT = HOOKS_DIR.parents[1]
#: Test seam only: read when the caller passes ``--test-config <path>`` (the wrapper and the shell guard never do in
#: production; the shell guard forwards GUARD_PUSH_FREE_TEST_CONFIG from ITS OWN environment, which agents cannot
#: set). A file planted beside this module is ignored.
TEST_CONFIG: Optional[Path] = None
GIT = "/usr/bin/git"
SAFE_PATH = "/usr/bin:/bin"

#: One prefix segment, one name segment. The shell guard and bin/agent-push use the same pattern.
BRANCH_RE = re.compile(r"^[a-z][a-z0-9-]{1,19}/[A-Za-z0-9][A-Za-z0-9._-]{2,120}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")
PROTECTED_RE = re.compile(r"^(main|master|head)$|^(release|train)(/|$)", re.IGNORECASE)
FORBIDDEN_ENV = re.compile(r"^(GIT_|TRADEAI_|GUARD_|PYTHON|LD_)|^(BASH_ENV|ENV|CDPATH)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COORDINATOR_PATH = "coordination/COORDINATOR"
STALE_HOURS = 2.0
#: A stale COORDINATOR claim still assigns work for a day (the coordinator's worklog spans the day), not longer.
COORDINATOR_MAX_AGE_HOURS = 24.0

APPROVAL_RE = re.compile(r"^[ \t>*-]*(?:\[[ xX]\][ \t]*)?Operator-approval:[ \t]*(?P<ref>\S[^\n]*?)[ \t]*$",
                         re.MULTILINE)
COMMENT_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/(?:pull|issues)/(?P<num>\d+)"
    r"#issuecomment-(?P<id>\d+)$"
)
_SECTION = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)
STANDING_RE = re.compile(r"^[ \t]*APPROVE_PUSH_STANDING[ \t]+(?P<glob>\S+)[ \t]+until[ \t]+(?P<until>\S+)[ \t]*$",
                         re.MULTILINE)
#: A standing glob: one literal prefix segment, then a name part of branch characters plus ``*``/``?`` only.
STANDING_GLOB_RE = re.compile(r"^(?P<prefix>[a-z][a-z0-9-]{1,19}/)(?P<rest>[A-Za-z0-9._*?-]{1,121})$")
PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{1,19}/$")
#: (c) is live only once main's AGENTS.md carries it, ACTIVE.
STANDING_MIN_POLICY = (29, 3, 0)
STANDING_MIN_POLICY_TEXT = "29.3.0"
_PROTECTED_PROBES = ("main", "master", "HEAD", "head", "release/x", "release/2026-11-01", "train/x", "train/2026-11-01")

DEFAULTS: dict[str, Any] = {
    "canonical_url": "https://github.com/PatsKiller/tardeai",
    "operator_login": "PatsKiller",
    "comment_repo": None,  # default: owner/repo of canonical_url
    "gh": "/usr/bin/gh",
    "credential_helper": "!/usr/bin/gh auth git-credential",
    "state_root": None,  # default: <passwd home>/trade-ai-releases/persistent-state
    "claims_dir": None,
    "handoffs_dir": None,
    "approvals_dir": None,  # default: <passwd home>/.cursor/approvals
    "audit_log": None,  # default: <passwd home>/logs/cursor-agent-audit.jsonl
    "budget_path": None,  # default: the push-budget module's own (git common dir)
    "ls_remote_timeout": 10,
    "gh_timeout": 10,
    "push_timeout": 300,
    # (c) standing approval. The issue is found by number, or (number None) as the lowest-numbered OPEN issue the
    # operator opened with exactly this title. Only these literal prefixes may be covered; never a protected branch.
    "standing_issue": None,
    "standing_issue_title": "Standing push approvals",
    "standing_prefixes": ["wt/", "feat/", "fix/", "chore/", "docs/"],
    "standing_max_days": 45,
    "standing_max_pages": 10,
}


class Refused(Exception):
    """A grant-free push condition does not hold."""


# --------------------------------------------------------------------------- config + environment


def passwd_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if TEST_CONFIG is not None:
        try:
            cfg.update(json.loads(TEST_CONFIG.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise Refused(f"unreadable test config {TEST_CONFIG}: {exc}") from None
    home = passwd_home()
    state = Path(cfg["state_root"] or home / "trade-ai-releases" / "persistent-state")
    cfg["claims_dir"] = Path(cfg["claims_dir"] or state / "data" / "coordination" / "claims")
    cfg["handoffs_dir"] = Path(cfg["handoffs_dir"] or state / "data" / "coordination" / "handoffs")
    cfg["approvals_dir"] = Path(cfg["approvals_dir"] or home / ".cursor" / "approvals")
    cfg["audit_log"] = Path(cfg["audit_log"] or home / "logs" / "cursor-agent-audit.jsonl")
    return cfg


def installed_hooks_dir() -> Optional[Path]:
    """The hooks dir ~/.cursor/hooks.json (passwd home) runs guard-shell.sh from, if any."""
    try:
        doc = json.loads((passwd_home() / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        for h in doc["hooks"]["beforeShellExecution"]:
            c = str(h.get("command") or "")
            if os.path.isabs(c) and c.endswith("/guard-shell.sh"):
                return Path(c).resolve().parent
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def refuse_dirty_env(environ: Optional[dict[str, str]] = None) -> None:
    bad = sorted(k for k in (os.environ if environ is None else environ) if FORBIDDEN_ENV.search(k))
    if bad:
        raise Refused(f"environment overrides are not allowed on a grant-free push: {', '.join(bad)}")


def _clean_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    env = {"PATH": SAFE_PATH, "HOME": str(passwd_home()), "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
    env.update(extra or {})
    return env


def _git(repo: Path, *args: str, timeout: float = 15, env_extra: Optional[dict[str, str]] = None,
         pins: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([GIT, "-C", str(repo), *pins, *args], capture_output=True, text=True,
                              timeout=timeout, check=False, env=_clean_env(env_extra))
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f"git {args[0]} failed ({type(exc).__name__})") from None


def _out(repo: Path, *args: str, **kw) -> Optional[str]:
    cp = _git(repo, *args, **kw)
    return cp.stdout.strip() if cp.returncode == 0 else None


# --------------------------------------------------------------------------- policy


def _semver(v: Optional[str]) -> Optional[tuple[int, int, int]]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def policy_state_from_text(text: Optional[str]) -> dict[str, Any]:
    """Same three conditions as scripts/lib/hands_off_policy.py, plus the 21.0.0 floor."""
    base: dict[str, Any] = {"version": None, "active": False}
    if not isinstance(text, str) or not text.strip():
        return {**base, "detail": "no AGENTS.md text"}
    m = re.search(r"```\n(Policy-Version:.*?)```", text, re.DOTALL)
    cb: dict[str, str] = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            cb[k.strip()] = v.strip()
    version, status = cb.get("Policy-Version"), cb.get("Status", "")
    base["version"] = version
    sv = _semver(version)
    if sv is None:
        return {**base, "detail": "no Policy-Version in the control block"}
    if sv < MIN_POLICY:
        return {**base, "detail": f"AGENTS.md {version} is below {MIN_POLICY_TEXT}"}
    if not status.upper().startswith("ACTIVE"):
        return {**base, "detail": f"AGENTS.md {version} header is {status!r}"}
    row = re.search(r"^\|\s*" + re.escape(version or "") + r"\s*\|[^|]*\|\s*([^|]*)\|", text, re.M)
    if not row or not row.group(1).strip().upper().startswith("ACTIVE"):
        return {**base, "detail": f"AGENTS.md {version} version-history row is not ACTIVE"}
    return {**base, "active": True, "detail": f"AGENTS.md {version} ACTIVE"}


# --------------------------------------------------------------------------- repo checks


_HIJACK_LOCAL = re.compile(
    r"^(remote\.origin\.(push|mirror|receivepack|uploadpack|pushurl|proxy|vcs|pushoption)|include\.|includeif\."
    r"|credential\.|http\.|core\.sshcommand|core\.gitproxy|core\.askpass|push\.)"
)


def check_remote_config(repo: Path, canonical: str) -> None:
    fetch = _out(repo, "remote", "get-url", "origin")
    push = _out(repo, "remote", "get-url", "--push", "origin")
    allowed = {canonical, canonical + ".git"} if not canonical.endswith(".git") else {canonical, canonical[:-4]}
    if fetch not in allowed or push not in allowed:
        raise Refused(f"origin url {fetch!r} / push url {push!r} is not the canonical {canonical}")
    listing = _out(repo, "config", "--show-scope", "--get-regexp", ".") or ""
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        scope, key = parts[0], parts[1].lower()
        val = parts[2] if len(parts) > 2 else ""
        if key.startswith("url.") and key.endswith(("insteadof", "pushinsteadof")):
            raise Refused(f"{scope} config {key} rewrites remote URLs")
        if scope in ("local", "worktree", "command") and _HIJACK_LOCAL.search(key):
            raise Refused(f"{scope} config {key} can redirect or alter a push")
        if scope in ("local", "worktree", "command") and key == "core.hookspath" and val not in (
                ".githooks", str(repo / ".githooks")):
            raise Refused(f"{scope} config core.hooksPath={val} would skip the tracked pre-push hook")


def ls_remote(repo: Path, url: str, branch: str, timeout: float, pins: tuple[str, ...]) -> dict[str, str]:
    cp = _git(repo, "ls-remote", url, "refs/heads/main", f"refs/heads/{branch}", timeout=timeout, pins=pins)
    if cp.returncode != 0:
        raise Refused(f"git ls-remote {url} failed rc={cp.returncode}")
    out = {}
    for line in cp.stdout.splitlines():
        p = line.split()
        if len(p) == 2 and SHA_RE.match(p[0]):
            out[p[1]] = p[0]
    return out


def _has(repo: Path, sha: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def check_policy(repo: Path, main_sha: str) -> dict[str, Any]:
    if not _has(repo, main_sha):
        raise Refused(f"remote main {main_sha[:9]} is not in the local object store; run: git fetch origin main")
    st = policy_state_from_text(_out(repo, "show", f"{main_sha}:AGENTS.md"))
    if not st["active"]:
        raise Refused(f"AGENTS.md on remote main is not {MIN_POLICY_TEXT}+ ACTIVE ({st['detail']})")
    return st


#: What the tracked pre-push hook executes or imports from the WORKTREE (it runs with PYTHONPATH=<repo root>). Each must
#: be byte-identical to remote main's (present or absent alike), so a branch cannot neuter its own budget count or
#: secrets scan. Missing on main but present here, or the reverse, refuses.
PREPUSH_CLOSURE = (
    ".githooks/pre-push",
    "scripts/check_no_secrets.py",
    "scripts/lib/tradeai_push_budget.py",
    "scripts/lib/guard_push_auth.py",
    "scripts/lib/__init__.py",
    "scripts/__init__.py",
    ".cursor/hooks/guard_ledger.py",
)
#: Directories the pre-push's Python puts on sys.path (repo root via PYTHONPATH and scripts/lib/__init__.py; the hooks
#: dir via guard_push_auth). A module there named like a stdlib module, or sitecustomize/usercustomize, would run in
#: the hook; it must match main exactly.
SHADOW_DIRS = ("", "scripts", "scripts/lib", ".cursor/hooks")
_SHADOW_EXTRA = frozenset({"sitecustomize", "usercustomize"})


def _main_blob(repo: Path, main_sha: str, rel: str) -> Optional[str]:
    return _out(repo, "rev-parse", "--verify", "--quiet", f"{main_sha}:{rel}")


def check_prepush(repo: Path, main_sha: str) -> None:
    for rel in PREPUSH_CLOSURE:
        p = repo / rel
        want = _main_blob(repo, main_sha, rel)
        if p.is_symlink():
            raise Refused(f"{rel} is a symlink; the pre-push closure must match remote main")
        have = _out(repo, "hash-object", "--no-filters", str(p)) if p.exists() else None
        if rel == ".githooks/pre-push" and not want:
            raise Refused("remote main has no .githooks/pre-push")
        if want != have:
            raise Refused(f"{rel} differs from remote main's; the pre-push budget count and secrets scan must run "
                          f"unmodified")
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | _SHADOW_EXTRA
    for d in SHADOW_DIRS:
        base = repo / d if d else repo
        if not base.is_dir():
            continue
        for e in base.iterdir():
            name = e.name[:-3] if e.name.endswith(".py") else e.name
            if name not in stdlib or not (e.name.endswith(".py") or (e / "__init__.py").exists()):
                continue
            rel = f"{d}/{e.name}" if d else e.name
            want = _main_blob(repo, main_sha, rel)
            have = _out(repo, "hash-object", "--no-filters", str(e)) if e.is_file() and not e.is_symlink() else None
            if e.is_dir() or want != have:
                raise Refused(f"{rel} would shadow the stdlib module {name!r} inside the pre-push hook")


def check_fast_forward(repo: Path, remote_sha: Optional[str], local_sha: str) -> str:
    if not remote_sha:
        return "new-branch"
    if remote_sha == local_sha:
        return "up-to-date"
    if not _has(repo, remote_sha):
        raise Refused(f"remote branch head {remote_sha[:9]} is not local; fetch it to prove a fast-forward")
    if _git(repo, "merge-base", "--is-ancestor", remote_sha, local_sha).returncode != 0:
        raise Refused(f"not a fast-forward: remote {remote_sha[:9]} is not an ancestor of {local_sha[:9]}")
    return "fast-forward"


def _glob_re(glob: str) -> re.Pattern[str]:
    """``**`` spans directories, ``*`` and ``?`` do not (scripts/lib/test_impact.py glob_to_re)."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def broker_globs() -> list[str]:
    p = TRUSTED_ROOT / "config" / "release_train_policy.json"
    try:
        pol = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read the train's broker_active_trader globs ({type(exc).__name__})") from None

    def find(o: Any) -> Optional[list[str]]:
        if isinstance(o, dict):
            if o.get("id") == "broker_active_trader" and isinstance(o.get("globs"), list):
                return [str(g) for g in o["globs"]]
            for v in o.values():
                r = find(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r is not None:
                    return r
        return None

    globs = find(pol)
    if not globs:
        raise Refused("the train policy has no broker_active_trader globs")
    return globs


def check_broker_paths(repo: Path, main_sha: str, local_sha: str) -> None:
    base = _out(repo, "merge-base", main_sha, local_sha)
    if not base:
        raise Refused("no merge-base with remote main")
    names = _out(repo, "diff", "--name-only", "--no-renames", f"{base}..{local_sha}")
    if names is None:
        raise Refused("git diff failed")
    pats = [_glob_re(g) for g in broker_globs()]
    hit = [n for n in names.splitlines() if any(p.match(n) for p in pats)]
    if hit:
        raise Refused(f"the branch touches broker/Active Trader paths ({', '.join(hit[:3])}); always held")


def check_budget(repo: Path, branch: str, cfg: dict[str, Any]) -> dict[str, int]:
    root = str(TRUSTED_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    import importlib

    pb = importlib.import_module("scripts.lib.tradeai_push_budget")
    if TRUSTED_ROOT not in Path(pb.__file__).resolve().parents:
        raise Refused("push-budget module resolved outside the guard tree")
    prev_cwd, prev_env = os.getcwd(), os.environ.get("TRADEAI_PUSH_BUDGET_PATH")
    try:
        os.chdir(repo)
        if cfg.get("budget_path"):
            os.environ["TRADEAI_PUSH_BUDGET_PATH"] = str(cfg["budget_path"])
        count = int(pb.count_for(branch))
        try:
            budget = int(pb.budget_for(branch, hands_off=True))
        except TypeError:  # main before PR #2115
            budget = int(pb.budget_for(branch))
    finally:
        os.chdir(prev_cwd)
        if prev_env is None:
            os.environ.pop("TRADEAI_PUSH_BUDGET_PATH", None)
    if count >= budget:
        raise Refused(f"push budget used ({count}/{budget}) for {branch}")
    return {"count": count, "budget": budget}


# --------------------------------------------------------------------------- approval evidence


def approval_refs(text: Optional[str]) -> list[str]:
    out = []
    for m in APPROVAL_RE.finditer(text or ""):
        ref = (m.group("ref") or "").strip().strip("`").strip()
        if ref:
            out.append(ref[:300])
    return out[:20]


def approval_ref(text: Optional[str]) -> Optional[str]:
    refs = approval_refs(text)
    return refs[0] if refs else None


def _gh_api(cfg: dict[str, Any], path: str) -> dict[str, Any]:
    try:
        cp = subprocess.run([str(cfg["gh"]), "api", path], capture_output=True, text=True,
                            timeout=float(cfg["gh_timeout"]), check=False, env=_clean_env())
        doc = json.loads(cp.stdout) if cp.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        doc = {}
    return doc if isinstance(doc, dict) else {}


def resolve_approval(ref: Optional[str], cfg: dict[str, Any], *, branch: str, bind_branch: bool) -> dict[str, str]:
    """``ref`` must be a GitHub comment by the operator on the canonical repo; anything else is refused.

    A comment carrying ``APPROVE_AGENTS_POLICY_`` anywhere never approves a push. The body must contain the line
    ``APPROVE_PUSH <branch>`` (G2), which binds the approval to the branch on both paths; ``bind_branch`` only
    records whether the comment is also on the PR whose head is the branch.

    Not accepted (follow-up): operator-decision ledger rows. They are unsigned today, so any same-uid write could
    forge one; they become acceptable when rows carry the operator's passkey identity."""
    if not ref:
        raise Refused("no Operator-approval line")
    # The record is the first token; agent_claim.py appends "  _(added <ts>)_" to worklog plan steps.
    ref = ref.split()[0].strip("`<>()[]")
    m = COMMENT_URL_RE.match(ref)
    if m:
        canon = re.match(r"^https://github\.com/([^/]+)/([^/.]+)", str(cfg["canonical_url"]))
        want = str(cfg.get("comment_repo") or (f"{canon.group(1)}/{canon.group(2)}" if canon else ""))
        if not want or f"{m.group('owner')}/{m.group('repo')}" != want:
            raise Refused(f"approval comment {ref} is not on the canonical repository")
        doc = _gh_api(cfg, f"repos/{m.group('owner')}/{m.group('repo')}/issues/comments/{m.group('id')}")
        login = str(((doc.get("user") or {}).get("login")) or "")
        html = str(doc.get("html_url") or "")
        body = str(doc.get("body") or "")
        if login != cfg["operator_login"]:
            raise Refused(f"approval comment {m.group('id')} is not authored by the operator (got {login or 'none'})")
        if not html.endswith(f"/{m.group('num')}#issuecomment-{m.group('id')}"):
            raise Refused(f"approval comment {m.group('id')} does not belong to #{m.group('num')}")
        if "APPROVE_AGENTS_POLICY_" in body:
            raise Refused(f"comment {m.group('id')} carries a policy ratification token; it does not approve a push")
        # G2: an explicit, branch-specific token on its own line. It binds the approval to this branch on both paths.
        if not re.search(r"^[ \t]*APPROVE_PUSH[ \t]+" + re.escape(branch) + r"[ \t]*$", body, re.MULTILINE):
            raise Refused(f"approval comment {m.group('id')} has no line 'APPROVE_PUSH {branch}'")
        bound = "approve-push-token"
        if bind_branch and "/pull/" in ref:
            pr = _gh_api(cfg, f"repos/{m.group('owner')}/{m.group('repo')}/pulls/{m.group('num')}")
            if str(((pr.get("head") or {}).get("ref")) or "") == branch:
                bound = "approve-push-token+pr-head"
        return {"kind": "github_comment", "ref": ref, "author": login, "comment_id": m.group("id"), "bound": bound}
    raise Refused(f"Operator-approval {ref!r} does not resolve: it must be the URL of a GitHub comment by the operator "
                  f"on the canonical repository")


# --------------------------------------------------------------------------- (c) standing approval


def _gh_api_list(cfg: dict[str, Any], path: str) -> Optional[list]:
    """One GET that must return a JSON array; None on any failure (callers fail closed)."""
    try:
        cp = subprocess.run([str(cfg["gh"]), "api", path], capture_output=True, text=True,
                            timeout=float(cfg["gh_timeout"]), check=False, env=_clean_env())
        doc = json.loads(cp.stdout) if cp.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        doc = None
    return doc if isinstance(doc, list) else None


def standing_prefixes(cfg: dict[str, Any]) -> list[str]:
    """Configured prefixes, minus anything malformed or protected (a bad config can only narrow)."""
    out = []
    for p in cfg.get("standing_prefixes") or []:
        p = str(p)
        if PREFIX_RE.match(p) and not PROTECTED_RE.search(p) and not PROTECTED_RE.search(p.rstrip("/")):
            out.append(p)
    return out


def _standing_glob_re(glob: str) -> re.Pattern[str]:
    m = STANDING_GLOB_RE.match(glob)
    assert m is not None
    body = "".join("[A-Za-z0-9._-]*" if c == "*" else "[A-Za-z0-9._-]" if c == "?" else re.escape(c)
                   for c in m.group("rest"))
    return re.compile("^" + re.escape(m.group("prefix")) + body + "$")


def standing_glob_problem(glob: str, cfg: dict[str, Any]) -> Optional[str]:
    """Why ``glob`` may not be a standing approval, or None. Refuses ``*`` alone, unknown prefixes, protected reach."""
    m = STANDING_GLOB_RE.match(glob)
    if not m:
        return f"glob {glob!r} is not '<prefix>/<pattern>' (only letters, digits, . _ - * ?; '*' alone is refused)"
    if m.group("prefix") not in standing_prefixes(cfg):
        return f"glob {glob!r}: prefix {m.group('prefix')!r} is not one of {standing_prefixes(cfg)}"
    rx = _standing_glob_re(glob)
    hit = [p for p in _PROTECTED_PROBES if rx.match(p)]
    if hit or PROTECTED_RE.search(m.group("prefix")):
        return f"glob {glob!r} could match a protected branch ({', '.join(hit) or m.group('prefix')})"
    return None


def _date(v: str) -> Optional[datetime]:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", v or ""):
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _standing_repo(cfg: dict[str, Any]) -> str:
    canon = re.match(r"^https://github\.com/([^/]+)/([^/.]+)", str(cfg["canonical_url"]))
    want = str(cfg.get("comment_repo") or (f"{canon.group(1)}/{canon.group(2)}" if canon else ""))
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", want):
        raise Refused("standing approval: the canonical repository is unknown")
    return want


def _gh_pages(cfg: dict[str, Any], path: str, what: str) -> list[dict]:
    """Every page of a list endpoint (``path`` already has a query string). Fails closed on any error or the cap."""
    max_pages = int(cfg.get("standing_max_pages") or 10)
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = _gh_api_list(cfg, f"{path}&per_page=100&page={page}")
        if rows is None:
            raise Refused(f"standing approval: could not read {what}")
        out += [r for r in rows if isinstance(r, dict)]
        if len(rows) < 100:
            return out
    # a revocation, a close or a duplicate could sit past the cap: fail closed
    raise Refused(f"standing approval: {what} has more than {max_pages * 100} entries; refusing")


def _login(doc: Any) -> str:
    return str(((doc or {}).get("user") or {}).get("login") or "") if isinstance(doc, dict) else ""


def standing_issue(cfg: dict[str, Any], repo: str) -> int:
    """The standing-approval issue: pinned by ``standing_issue``, or the ONE issue (never a PR) the operator opened with
    exactly ``standing_issue_title``, searched over every page oldest first; two such issues refuse (a newer duplicate
    must never shadow a revoked original). It must be open and opened by the operator."""
    op = str(cfg["operator_login"])
    num = cfg.get("standing_issue")
    if num is None:
        title = str(cfg.get("standing_issue_title") or "")
        rows = _gh_pages(cfg, f"repos/{repo}/issues?creator={op}&state=all&sort=created&direction=asc",
                         "the operator's issues")
        nums = sorted({r["number"] for r in rows if r.get("title") == title and "pull_request" not in r
                       and isinstance(r.get("number"), int) and not isinstance(r.get("number"), bool)
                       and _login(r) == op})
        if not nums:
            raise Refused(f"standing approval: no operator issue titled {title!r}")
        if len(nums) > 1:
            raise Refused(f"standing approval: {len(nums)} operator issues are titled {title!r} "
                          f"(#{', #'.join(map(str, nums[:5]))}); pin one with standing_issue")
        num = nums[0]
    if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
        raise Refused("standing approval: standing_issue is not an issue number")
    doc = _gh_api(cfg, f"repos/{repo}/issues/{num}")
    if doc.get("number") != num or str(doc.get("state") or "") != "open" or "pull_request" in doc:
        raise Refused(f"standing approval: issue #{num} is not an open issue")
    if _login(doc) != op:
        raise Refused(f"standing approval: issue #{num} was not opened by the operator (got {_login(doc) or 'none'})")
    return num


_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?(^[ \t]*\1[ \t]*$|\Z)", re.MULTILINE | re.DOTALL)


def _unfenced(body: str) -> str:
    """The body with fenced code blocks removed: an example inside a fence is never an approval."""
    return _FENCE_RE.sub("", body)


def standing_approval(branch: str, cfg: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, str]:
    """(c): the newest unrevoked, unexpired operator ``APPROVE_PUSH_STANDING`` line whose glob covers ``branch``.

    Comments created at or before the issue's latest ``closed`` event never count (a close voids for good, even after
    a reopen). An edited operator comment after that point refuses the whole path (its earlier text is unknowable).
    A ``REVOKE_PUSH_STANDING`` anywhere in an operator comment, in any case or markup, voids everything before it.
    Dates are UTC: the expiry is the last valid UTC day, and the cap counts days from the comment's UTC date."""
    if PROTECTED_RE.search(branch):
        raise Refused(f"standing approval never covers {branch}")
    st = cfg.get("_main_policy") or {}
    sv = _semver(st.get("version"))
    if not st.get("active") or sv is None or sv < STANDING_MIN_POLICY:
        raise Refused(f"standing approval needs AGENTS.md {STANDING_MIN_POLICY_TEXT}+ ACTIVE on main "
                      f"(main has {st.get('version') or 'unknown'}, {'ACTIVE' if st.get('active') else 'not active'})")
    repo = _standing_repo(cfg)
    num = standing_issue(cfg, repo)
    op = str(cfg["operator_login"])
    events = _gh_pages(cfg, f"repos/{repo}/issues/{num}/events?direction=asc", f"the events of #{num}")
    closes = [e for e in events if str(e.get("event") or "") == "closed"]
    cutoff: Optional[datetime] = None
    for e in closes:
        t = _parse_ts(e.get("created_at"))
        if t is None:
            raise Refused(f"standing approval: a close event on #{num} has no time; refusing")
        cutoff = t if cutoff is None or t > cutoff else cutoff
    comments = _gh_pages(cfg, f"repos/{repo}/issues/{num}/comments?direction=asc", f"the comments of #{num}")
    prefix = f"https://github.com/{repo}/issues/{num}#issuecomment-"
    op_rows = []
    for c in comments:
        if _login(c) != op:
            continue
        made = _parse_ts(c.get("created_at"))
        if made is None or not isinstance(c.get("id"), int) or isinstance(c.get("id"), bool):
            raise Refused(f"standing approval: an operator comment on #{num} has no usable id or time; refusing")
        if cutoff is not None and made <= cutoff:
            continue  # voided by a later close, even if the issue was reopened
        if str(c.get("updated_at") or "") != str(c.get("created_at") or ""):
            raise Refused(f"standing approval: operator comment {c.get('id')} on #{num} was edited; post a new comment"
                          " (close and reopen the issue to clear it)")
        op_rows.append((made, c["id"], c))
    op_rows.sort(key=lambda r: (r[0], r[1]))
    lines: list[tuple[dict, str, str]] = []
    for _made, _cid, c in op_rows:
        body = str(c.get("body") or "")
        if "REVOKE_PUSH_STANDING" in body.upper():
            lines = []  # voids everything before it, and the revoking comment itself
            continue
        if "APPROVE_AGENTS_POLICY_" in body or str(c.get("html_url") or "") != f"{prefix}{c['id']}":
            continue
        lines += [(c, m.group("glob").strip("`"), m.group("until").strip("`"))
                  for m in STANDING_RE.finditer(_unfenced(body))]
    if not lines:
        raise Refused(f"standing approval: no unrevoked APPROVE_PUSH_STANDING line on #{num}")
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    max_days = int(cfg.get("standing_max_days") or 45)
    errs: list[str] = []
    for c, glob, until in reversed(lines):  # newest first
        url = str(c.get("html_url"))
        problem = standing_glob_problem(glob, cfg)
        exp, made = _date(until), _parse_ts(c.get("created_at"))
        if problem:
            errs.append(f"{url}: {problem}")
        elif exp is None:
            errs.append(f"{url}: expiry {until!r} is not a YYYY-MM-DD date")
        elif made is None:
            errs.append(f"{url}: comment has no created_at")
        elif exp < today:
            errs.append(f"{url}: expired {until} (UTC)")
        elif (exp - made.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).days > max_days:
            errs.append(f"{url}: expiry {until} is more than {max_days} days after the comment")
        elif not _standing_glob_re(glob).match(branch):
            errs.append(f"{url}: {glob} does not cover {branch}")
        else:
            return {"kind": "standing_comment", "ref": url, "author": op,
                    "comment_id": str(c.get("id")), "bound": f"standing:{glob} until {until}", "glob": glob,
                    "until": until, "issue": str(num)}
    raise Refused("standing approval: " + " | ".join(errs[:3]))


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_claims(claims_dir: Path) -> list[dict[str, Any]]:
    """Claim docs with a derived ``_state`` (live|stale|done|abandoned); vendored from agent_claim_board."""
    if not claims_dir.is_dir():
        return []
    docs = []
    for i, p in enumerate(sorted(claims_dir.glob("*.json"))):
        if i >= 2000:
            break
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("schema") == "AgentClaim@v1" and d.get("claim_id") == p.stem:
            d["_path"] = str(p)
            docs.append(d)
    taken = {str(t.get("claim_id") if isinstance(t, dict) else t)
             for d in docs if d.get("status") == "active" for t in (d.get("takeover_of") or [])}
    now = datetime.now(timezone.utc)
    for d in docs:
        if d.get("status") == "active":
            hb = _parse_ts(d.get("heartbeat_at") or d.get("started_at"))
            d["_age_h"] = (now - hb).total_seconds() / 3600 if hb is not None else 1e9
            live = hb is not None and (now - hb).total_seconds() <= STALE_HOURS * 3600
            d["_state"] = "live" if live and str(d["claim_id"]) not in taken else "stale"
        else:
            d["_state"] = d.get("status") if d.get("status") in ("done", "abandoned") else "abandoned"
    return docs


def _plan_sections(worklog: str) -> str:
    out, marks = [], list(_SECTION.finditer(worklog))
    for n, m in enumerate(marks):
        if m.group("name").strip().lower() in ("goal", "plan"):
            end = marks[n + 1].start() if n + 1 < len(marks) else len(worklog)
            out.append(worklog[m.end():end])
    return "\n".join(out)


def claim_approval(branch: str, session: Optional[str], cfg: dict[str, Any], claims: list[dict]) -> dict[str, str]:
    """(a): the pusher's own live claim on the branch (hands_off_policy.claim_plan_approval semantics)."""
    rows = [r for r in claims if r["_state"] == "live" and str(r.get("branch") or "") == branch
            and (session is None or str(r.get("session") or "") == session)]
    if not rows:
        who = f"session {session}" if session else "any session"
        raise Refused(f"no live claim on {branch} held by {who}")
    errs: list[str] = []
    for r in rows:
        wl = Path(r["_path"]).with_name(f"{r.get('claim_id')}.worklog.md")
        try:
            plan = _plan_sections(wl.read_text(encoding="utf-8")) if wl.is_file() and not wl.is_symlink() else ""
        except OSError:
            plan = ""
        refs = approval_refs(str(r.get("note") or "")) + approval_refs(plan)
        for ref in refs or [None]:
            try:
                res = resolve_approval(ref, cfg, branch=branch, bind_branch=True)
            except Refused as exc:
                errs.append(str(exc))
                continue
            return {"source": "claim", "claim_id": str(r.get("claim_id")), "session": str(r.get("session") or ""),
                    **{f"approval_{k}": v for k, v in res.items()}, "approval_ref": res["ref"]}
    # (c): no per-branch approval resolved; the same live claim may stand under the operator's standing approval.
    try:
        res = standing_approval(branch, cfg)
    except Refused as exc:
        errs.append(str(exc))
        raise Refused(" | ".join(errs[-3:])) from None
    r = rows[0]
    return {"source": "claim+standing", "claim_id": str(r.get("claim_id")), "session": str(r.get("session") or ""),
            **{f"approval_{k}": v for k, v in res.items()}, "approval_ref": res["ref"]}


def _line(text: str, key: str) -> Optional[str]:
    m = re.search(r"^" + re.escape(key) + r":[ \t]*(\S+)[ \t]*$", text, re.MULTILINE)
    return m.group(1) if m else None


def handoff_approval(branch: str, cfg: dict[str, Any], claims: list[dict]) -> dict[str, str]:
    """(b): a coordinator task file assigning exactly this branch."""
    root = Path(cfg["handoffs_dir"])
    if not root.is_dir():
        raise Refused("no handoffs directory")
    coordinators = {str(r.get("session") or "") for r in claims if r["_state"] in ("live", "stale")
                    and r.get("_age_h", 1e9) <= COORDINATOR_MAX_AGE_HOURS
                    and COORDINATOR_PATH in [str(p).strip().strip("/") for p in (r.get("paths") or [])]}
    coordinators.discard("")
    uid = os.getuid()
    last: Optional[Refused] = None
    candidates = []
    for d in [root] + sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        for p in sorted(d.iterdir()):
            if p.suffix in (".md", ".txt") and "log" not in p.name.lower():
                candidates.append(p)
    for p in candidates[:2000]:
        try:
            st = p.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_mode & 0o022 or st.st_size > 1_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _line(text, "Assigned-branch") != branch:
            continue
        by = _line(text, "Assigned-by")
        rel = p.relative_to(root).as_posix()
        if not by or by not in coordinators:
            last = Refused(f"handoff {rel}: Assigned-by {by!r} is not a session holding {COORDINATOR_PATH}")
            continue
        try:
            res = resolve_approval(approval_ref(text), cfg, branch=branch, bind_branch=False)
        except Refused as exc:
            last = Refused(f"handoff {rel}: {exc}")
            continue
        return {"source": "handoff", "handoff": rel, "assigned_by": by,
                **{f"approval_{k}": v for k, v in res.items()}, "approval_ref": res["ref"]}
    raise last or Refused(f"no coordinator task file with 'Assigned-branch: {branch}'")


def find_plan(branch: str, session: Optional[str], cfg: dict[str, Any], *, bind_session: bool) -> dict[str, str]:
    claims = read_claims(Path(cfg["claims_dir"]))
    errors = []
    if bind_session and not session:
        errors.append("claim path: AGENT_CLAIM_SESSION is not set for the pusher")
    else:
        try:
            return claim_approval(branch, session if bind_session else None, cfg, claims)
        except Refused as exc:
            errors.append(f"claim path: {exc}")
    try:
        return handoff_approval(branch, cfg, claims)
    except Refused as exc:
        errors.append(f"handoff path: {exc}")
    raise Refused("no approved plan covers " + branch + " — " + "; ".join(errors))


# --------------------------------------------------------------------------- audit (hash-chained)


def _ledger():
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    import importlib

    gl = importlib.import_module("guard_ledger")
    if Path(gl.__file__).resolve().parent != HOOKS_DIR:
        raise Refused("guard_ledger resolved outside the guard tree")
    return gl


def audit(record: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Append one hash-chained line to the guard log under the audit lock. Raises Refused on any failure."""
    try:
        gl = _ledger()
        adir, log = Path(cfg["approvals_dir"]), Path(cfg["audit_log"])
        gl.ensure_dir(adir)
        head = adir / "grant_free_chain.head"
        log.parent.mkdir(parents=True, exist_ok=True)
        with gl._flock(gl.audit_lock_path(adir), exclusive=True):
            prev = head.read_text(encoding="utf-8").strip() if head.exists() else "genesis"
            rec = dict(record, ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), chain_prev=prev)
            rec["chain_hash"] = hashlib.sha256((prev + json.dumps(rec, sort_keys=True)).encode()).hexdigest()
            line = json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n"
            fd = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            tmp = head.with_suffix(".tmp")
            tmp.write_text(rec["chain_hash"] + "\n", encoding="utf-8")
            os.replace(tmp, head)
        return rec
    except Refused:
        raise
    except Exception as exc:
        raise Refused(f"guard log write failed ({type(exc).__name__}: {exc}); grant-free push refused") from None


# --------------------------------------------------------------------------- the push


def push_pins(repo: Path, canonical: str, cfg: dict[str, Any]) -> tuple[str, ...]:
    pins = ["-c", "remote.origin.mirror=false", "-c", "push.followTags=false", "-c", "push.recurseSubmodules=no",
            "-c", "push.gpgSign=false", "-c", "push.pushOption=", "-c", "push.default=nothing",
            "-c", f"core.hooksPath={repo / '.githooks'}", "-c", "core.fsmonitor=false",
            "-c", "core.sshCommand=ssh", "-c", "core.gitProxy=", "-c", "protocol.ext.allow=never",
            "-c", "protocol.allow=never"]
    if canonical.startswith("https://"):
        host = re.match(r"^(https://[^/]+)", canonical).group(1)  # type: ignore[union-attr]
        pins += ["-c", "protocol.https.allow=always", "-c", "credential.helper=",
                 "-c", f"credential.{host}.helper=", "-c", f"credential.helper={cfg['credential_helper']}"]
    else:  # hermetic tests: a local bare repository
        pins += ["-c", "protocol.file.allow=always"]
    return tuple(pins)


def _porcelain(stdout: str, branch: str) -> dict[str, str]:
    lines = [ln for ln in stdout.splitlines() if "\t" in ln]
    if len(lines) != 1:
        raise Refused(f"push reported {len(lines)} refs; exactly one is allowed")
    flag, refs, *summary = lines[0].split("\t")
    src, _, dst = refs.partition(":")
    if dst != f"refs/heads/{branch}":
        raise Refused(f"push would write {dst!r}")
    if flag not in (" ", "*", "="):
        raise Refused(f"push would be {flag!r} ({' '.join(summary)}); only new or fast-forward refs")
    return {"flag": flag, "line": lines[0]}


def evaluate(repo_arg: str, branch: str, session: Optional[str], *, bind_session: bool) -> dict[str, Any]:
    cfg = load_config()
    if not BRANCH_RE.match(branch) or PROTECTED_RE.search(branch) or ".." in branch or branch.endswith(
            (".lock", ".")):
        raise Refused(f"branch {branch!r} is not an allowed feature-branch name")
    if session is not None and not SESSION_RE.match(session):
        raise Refused("malformed AGENT_CLAIM_SESSION")
    top = _out(Path(repo_arg), "rev-parse", "--show-toplevel")
    if not top:
        raise Refused(f"{repo_arg} is not a git work tree")
    repo = Path(top)
    local_sha = _out(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    if not local_sha or not SHA_RE.match(local_sha):
        raise Refused(f"no local branch {branch}")
    # The pre-push secrets scan reads the WORKTREE, so the pushed branch must be the checked-out HEAD with no
    # modified tracked files; otherwise the scan would vouch for different content than the commit pushed.
    if _out(repo, "symbolic-ref", "--quiet", "HEAD") != f"refs/heads/{branch}":
        raise Refused(f"{branch} is not the checked-out HEAD of {repo}; check it out before pushing")
    dirty = _out(repo, "status", "--porcelain", "--untracked-files=no")
    if dirty is None:
        raise Refused("git status failed")
    if dirty:
        names = (_out(repo, "diff", "--name-only", "HEAD") or "").splitlines()[:5]
        raise Refused(f"the worktree has uncommitted changes to tracked files ({', '.join(names)}); commit or stash")
    canonical = str(cfg["canonical_url"])
    check_remote_config(repo, canonical)
    pins = push_pins(repo, canonical, cfg)
    refs = ls_remote(repo, canonical, branch, float(cfg["ls_remote_timeout"]), pins)
    main_sha = refs.get("refs/heads/main")
    if not main_sha:
        raise Refused("the canonical remote has no main")
    st = check_policy(repo, main_sha)
    cfg["_main_policy"] = st  # gates (c): the standing path needs main's AGENTS.md 29.3.0+ ACTIVE
    check_prepush(repo, main_sha)
    remote_sha = refs.get(f"refs/heads/{branch}")
    ff = check_fast_forward(repo, remote_sha, local_sha)
    check_broker_paths(repo, main_sha, local_sha)
    budget = check_budget(repo, branch, cfg)
    plan = find_plan(branch, session, cfg, bind_session=bind_session)
    refspec = f"{local_sha}:refs/heads/{branch}"
    dry = _git(repo, "push", "--dry-run", "--porcelain", "--no-verify", "--no-follow-tags", "--no-signed",
               "--recurse-submodules=no", canonical, refspec, pins=pins, timeout=float(cfg["ls_remote_timeout"]))
    if dry.returncode != 0:
        raise Refused(f"dry-run push failed rc={dry.returncode}: {dry.stderr.strip()[:200]}")
    dry_line = _porcelain(dry.stdout, branch)
    return {"schema": SCHEMA, "allow": True, "cfg": cfg, "repo": str(repo), "branch": branch, "head": local_sha,
            "remote_head": remote_sha or "", "ff": ff, "refspec": refspec, "canonical": canonical,
            "policy": {"version": st["version"], "main": main_sha}, "budget": budget, "plan": plan,
            "approval_ref": plan["approval_ref"], "dry_run": dry_line["line"], "pins": pins}


def do_push(ev: dict[str, Any], session: Optional[str], cwd: str) -> dict[str, Any]:
    cfg, repo = ev["cfg"], Path(ev["repo"])
    rule = "AGENTS.md 21.0.0 §28.15 item 8 (a)"
    if ev["plan"].get("source") == "claim+standing":
        rule = "AGENTS.md §28.15 item 8 (a) under a standing approval (c)"
    base = {"tier": "git-push", "rule": rule, "branch": ev["branch"],
            "head": ev["head"], "remote_head": ev["remote_head"], "ff": ev["ff"], "refspec": ev["refspec"],
            "remote": ev["canonical"], "repo": ev["repo"], "cwd": cwd, "pusher_session": session or "",
            "pusher_uid": os.getuid(), "approval_ref": ev["approval_ref"], "plan": ev["plan"],
            "budget": ev["budget"], "policy": ev["policy"], "dry_run": ev["dry_run"],
            "command": f"bin/agent-push {ev['branch']}",
            "standing_approval_url": ev["plan"]["approval_ref"] if ev["plan"].get("source") == "claim+standing" else ""}
    intent = audit(dict(base, event="grant-free-push-intent"), cfg)  # refuses on failure (M2)
    cp = _git(repo, "push", "--porcelain", "--no-follow-tags", "--no-signed", "--recurse-submodules=no",
              ev["canonical"], ev["refspec"], pins=ev["pins"], timeout=float(cfg["push_timeout"]),
              env_extra={"TRADEAI_REMOTE_PUSH_AUTHORIZED": "1", "TRADEAI_GRANT_FREE": "1",
                         "TRADEAI_GUARD_CONSUME": "0"})
    try:
        line = _porcelain(cp.stdout, ev["branch"])["line"] if cp.returncode == 0 else ""
        outcome = "pushed" if cp.returncode == 0 else "failed"
    except Refused as exc:
        line, outcome = str(exc), "unexpected-result"
    rec = audit(dict(base, event="grant-free-push", outcome=outcome, rc=cp.returncode, result=line,
                     stderr_tail=cp.stderr.strip()[-400:], intent_hash=intent["chain_hash"]), cfg)
    return {"allow": outcome == "pushed", "outcome": outcome, "rc": cp.returncode, "branch": ev["branch"],
            "head": ev["head"], "approval_ref": ev["approval_ref"], "result": line, "chain_hash": rec["chain_hash"],
            "stderr": cp.stderr.strip()[-2000:]}


def verify_chain(cfg: dict[str, Any]) -> dict[str, Any]:
    """Recompute the grant-free hash chain in the guard log and compare it with the stored chain head."""
    log, head = Path(cfg["audit_log"]), Path(cfg["approvals_dir"]) / "grant_free_chain.head"
    prev, n, bad = "genesis", 0, []
    if log.exists():
        with log.open(encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                if '"chain_hash"' not in line or '"grant-free-push' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad.append(f"line {lineno}: unparseable")
                    continue
                got = rec.pop("chain_hash", "")
                rec.pop("event_id", None)
                if rec.get("chain_prev") != prev:
                    bad.append(f"line {lineno}: chain_prev {str(rec.get('chain_prev'))[:12]} != {prev[:12]}")
                want = hashlib.sha256((str(rec.get("chain_prev")) + json.dumps(rec, sort_keys=True)).encode()).hexdigest()
                if want != got:
                    bad.append(f"line {lineno}: chain_hash does not match its content")
                prev, n = got, n + 1
    stored = head.read_text(encoding="utf-8").strip() if head.exists() else "genesis"
    if stored != prev:
        bad.append(f"chain head {stored[:12]} != last logged {prev[:12]}")
    return {"schema": "GuardGrantFreeChain@v1", "ok": not bad, "events": n, "head": prev, "problems": bad[:50]}


def main(argv: Optional[list[str]] = None) -> int:
    global TEST_CONFIG
    ap = argparse.ArgumentParser(description="grant-free push check/push (AGENTS.md §28.15 item 8)")
    ap.add_argument("mode", choices=("check", "push", "verify-chain"))
    ap.add_argument("--repo")
    ap.add_argument("--branch")
    ap.add_argument("--test-config", default=None, help="hermetic tests only")
    ap.add_argument("--session", default=None)
    ap.add_argument("--cwd", default="")
    a = ap.parse_args(argv)
    TEST_CONFIG = Path(a.test_config) if a.test_config else None
    if TEST_CONFIG is not None and installed_hooks_dir() == HOOKS_DIR:
        print(json.dumps({"schema": SCHEMA, "allow": False,
                          "reason": "--test-config is refused in the installed guard tree (~/.cursor/hooks.json)"}))
        return 1
    if a.mode == "verify-chain":
        try:
            out = verify_chain(load_config())
        except Refused as exc:
            out = {"ok": False, "problems": [str(exc)]}
        print(json.dumps(out, sort_keys=True))
        return 0 if out.get("ok") else 1
    if not a.repo or not a.branch:
        ap.error("--repo and --branch are required")
    try:
        refuse_dirty_env()
        ev = evaluate(a.repo, a.branch, a.session, bind_session=(a.mode == "push"))
        if a.mode == "check":
            out = {k: v for k, v in ev.items() if k not in ("cfg", "pins")}
        else:
            out = do_push(ev, a.session, a.cwd)
    except Refused as exc:
        print(json.dumps({"schema": SCHEMA, "allow": False, "reason": str(exc)}))
        return 1
    except Exception as exc:  # fail closed
        print(json.dumps({"schema": SCHEMA, "allow": False, "reason": f"internal error: {type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(out, sort_keys=True, default=str))
    return 0 if out.get("allow") else 1


if __name__ == "__main__":
    sys.exit(main())
