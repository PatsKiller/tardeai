#!/usr/bin/env python3
"""guard_push_free -- may this ``git push`` run WITHOUT a guard ``git-push`` grant?

AGENTS.md 21.0.0 §28.15 item 8 (a), ratified by the operator 2026-10-25 (PR #2128). Operator, verbatim: "I need the
agents to be able to upload their own approved work without grants. And the building tests without grants."

A push is grant-free only when ALL of these hold (otherwise the caller keeps today's behaviour: a grant is needed):

  1. ``AGENTS.md`` on the REMOTE ``main`` is 21.0.0 or later and ACTIVE (``scripts/lib/hands_off_policy.py``). The
     remote main SHA comes from ``git ls-remote``, never from the local ``origin/main`` ref an agent could move, and
     the AGENTS.md text is read from that commit (it must be present locally: ``git fetch origin main``).
  2. The command is ONE plain ``git push`` to ``origin`` of ONE ref: no force (``-f``, ``--force``,
     ``--force-with-lease``, ``--force-if-includes``, ``+refspec``), no ``--delete`` / ``:dst``, no ``--mirror`` /
     ``--all`` / ``--tags`` / ``--prune``, no ``--no-verify``, no ``-c`` / ``--git-dir`` / ``-o``, no command
     substitution, no variables or globs in the push words. Any option this module does not know refuses.
  3. The destination is a feature branch: never ``main`` / ``master``, ``release/*``, ``train/*``, a tag or a
     non-branch ref.
  4. It is a fast-forward: the remote branch is absent (a new branch) or ``git merge-base --is-ancestor <remote sha>
     <local sha>`` holds, with the remote sha from ``git ls-remote``.
  5. The branch is covered by an approved plan: a LIVE claim on the claim board for that branch whose note, or whose
     worklog Goal/Plan section, carries an ``Operator-approval: <ref>`` line; or a coordinator task file under
     ``data/coordination/handoffs/`` (top level or one batch directory down) that names the branch (or a live
     claim's id on that branch).
  6. Within the per-branch push budget (``scripts/lib/tradeai_push_budget.py``; the pre-push hook still enforces it).

TRUST. Every module this file imports comes from the tree this hook file lives in (the installed guardrails tree),
never from the repository being pushed -- a branch cannot change the rules that judge its own push. The repository
being pushed is only ever read through ``git``.

FAIL CLOSED. Any error, timeout or missing module is a refusal (rc 1) with a reason; the caller falls back to the
grant path. This module never writes the ledger and never consumes a grant; the caller records the
``grant-free-push`` event in the guard log.

CLI::

    guard_push_free.py check --command '<shell command>' [--cwd DIR]   # the Cursor shell guard
    guard_push_free.py check-args [--cwd DIR] -- <git push args...>     # bin/agent-push

Prints one JSON object. rc 0 = grant-free (``other_segments`` lists the non-push parts of the command, which the
shell guard classifies itself and requires to be unguarded); rc 1 = refused (``reason``).

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "GuardGrantFreePush@v1"
MIN_POLICY = (21, 0, 0)
MIN_POLICY_TEXT = "21.0.0"
REMOTE = "origin"
LS_REMOTE_TIMEOUT_S = float(os.environ.get("GUARD_PUSH_FREE_LS_REMOTE_TIMEOUT", "5"))
GIT_TIMEOUT_S = 5

HOOKS_DIR = Path(__file__).resolve().parent
TRUSTED_ROOT = HOOKS_DIR.parents[1]

ENV_CLAIMS_DIR = "TRADEAI_AGENT_CLAIMS_DIR"
ENV_HANDOFFS_DIR = "TRADEAI_COORDINATION_HANDOFFS_DIR"

#: Environment assignments allowed in front of the push word. Anything else (GIT_*, the override flag, the secrets
#: scan skip) refuses: the override is the coordinator's path past the budget, never a grant-free push (item 1).
ALLOWED_ENV_PREFIX = frozenset({"TRADEAI_REMOTE_PUSH_AUTHORIZED", "AGENT_CLAIM_SESSION", "TMPDIR"})

#: push options that change nothing about WHAT is written to the remote.
SAFE_LONG = frozenset({"--set-upstream", "--quiet", "--verbose", "--progress", "--no-progress", "--porcelain",
                       "--dry-run", "--atomic"})
SAFE_SHORT = frozenset("uqvn")
REFUSED_HINT = {
    "-f": "force", "--force": "force", "--force-with-lease": "force", "--force-if-includes": "force",
    "-d": "delete", "--delete": "delete", "--mirror": "mirror", "--all": "all branches", "--branches": "all branches",
    "--tags": "tags", "--follow-tags": "tags", "--prune": "prune", "--no-verify": "skips the pre-push hook",
    "-o": "push option", "--push-option": "push option", "--repo": "alternate repo", "--receive-pack": "receive-pack",
    "--exec": "receive-pack", "--signed": "signed push",
}
OPERATORS = frozenset({"&&", "||", ";", "|", "&", ";;", "(", ")", "|&"})
SEGMENT_SPLIT = frozenset({"&&", "||", ";", "|"})
_TRAILING_REDIRECTS = (["2", ">&", "1"], ["2", ">", "/dev/null"], [">", "/dev/null"], ["&>", "/dev/null"])
_BAD_TEXT = re.compile(r"\$\(|`|<\(|>\(|\n|\r")
_BAD_WORD = re.compile(r"[$*?\[\]{}~]")
_PROTECTED = re.compile(r"^(main|master|head)$|^(release|train)(/|$)", re.IGNORECASE)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SECTION = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)


class Refused(Exception):
    """A grant-free push condition does not hold."""


# --------------------------------------------------------------------------- trusted imports


def _trusted_import(name: str):
    root = str(TRUSTED_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    import importlib

    mod = importlib.import_module(name)
    origin = Path(getattr(mod, "__file__", "") or "").resolve()
    if TRUSTED_ROOT not in origin.parents:
        raise Refused(f"{name} resolved outside the guard tree ({origin}); refusing")
    return mod


# --------------------------------------------------------------------------- policy (hands_off_policy reuse)
#
# The policy reading and the ``Operator-approval:`` grammar are scripts/lib/hands_off_policy.py's (PRs #2115, #2118,
# #2125 each carry the same file). When the guard tree has it, it is used; until one of those PRs merges, the minimal
# reader below applies the same three conditions (header Policy-Version, header Status ACTIVE, that version's history
# row ACTIVE) and the same approval-line grammar. tests/test_guard_item8_grant_free_push_20261025.py pins the two to
# agree whenever the module exists.

_V_ROW = r"^\|\s*{v}\s*\|[^|]*\|\s*([^|]*)\|"
_APPROVAL_RE = re.compile(
    r"^[ \t>*-]*(?:\[[ xX]\][ \t]*)?Operator-approval:[ \t]*(?P<ref>\S[^\n]*?)[ \t]*$", re.MULTILINE
)
_PLACEHOLDER = re.compile(r"^(?:<[^>]*>|tbd|todo|none|n/?a|pending|-+|\.+)$", re.IGNORECASE)


def _hands_off():
    try:
        return _trusted_import("scripts.lib.hands_off_policy")
    except (ImportError, Refused):
        return None


def _semver(v: Optional[str]) -> Optional[tuple[int, int, int]]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _vendored_policy_state(text: Optional[str], source: str) -> dict[str, Any]:
    base: dict[str, Any] = {"source": source, "version": None, "active": False}
    if not isinstance(text, str) or not text.strip():
        return {**base, "detail": f"{source}: no AGENTS.md text"}
    m = re.search(r"```\n(Policy-Version:.*?)```", text, re.DOTALL)
    cb = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            cb[k.strip()] = v.strip()
    version, status = cb.get("Policy-Version"), cb.get("Status", "")
    base["version"] = version
    if _semver(version) is None:
        return {**base, "detail": "no Policy-Version in the control block"}
    if not status.upper().startswith("ACTIVE"):
        return {**base, "detail": f"AGENTS.md {version} header is {status!r}"}
    row = re.search(_V_ROW.format(v=re.escape(version or "")), text, re.M)
    if not row or not row.group(1).strip().upper().startswith("ACTIVE"):
        return {**base, "detail": f"AGENTS.md {version} version-history row is not ACTIVE"}
    return {**base, "active": True, "detail": f"AGENTS.md {version} ACTIVE"}


def policy_state_from_text(text: Optional[str], *, source: str = "text") -> dict[str, Any]:
    hop = _hands_off()
    if hop is not None:
        return hop.policy_state_from_text(text, source=source)
    return _vendored_policy_state(text, source)


def approval_ref(text: Optional[str]) -> Optional[str]:
    hop = _hands_off()
    if hop is not None:
        return hop.approval_ref(text)
    for m in _APPROVAL_RE.finditer(text or ""):
        ref = (m.group("ref") or "").strip().strip("`").strip()
        if ref and not _PLACEHOLDER.match(ref):
            return ref[:300]
    return None


# --------------------------------------------------------------------------- git


def _git(repo: Path, *args: str, timeout: float = GIT_TIMEOUT_S, runner: Callable[..., Any] = subprocess.run):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return runner(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, check=False,
                  env=env)


def _git_out(repo: Path, *args: str, **kw) -> Optional[str]:
    try:
        cp = _git(repo, *args, **kw)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout.strip() if cp.returncode == 0 else None


# --------------------------------------------------------------------------- command parsing


def _tokens(cmd: str) -> list[str]:
    if _BAD_TEXT.search(cmd):
        raise Refused("command substitution, process substitution or a newline in the command")
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
        raw = shlex.shlex(cmd, posix=False, punctuation_chars=True)
        raw.whitespace_split = True
        raw_toks = list(raw)
    except ValueError as exc:
        raise Refused(f"unparseable command ({exc})") from None
    ops = [t for t in toks if t in OPERATORS or set(t) <= set("();<>|&")]
    raw_ops = [t for t in raw_toks if t in OPERATORS or set(t) <= set("();<>|&")]
    if ops != raw_ops:
        raise Refused("a quoted shell operator makes the command ambiguous")
    return toks


def split_segments(cmd: str) -> list[list[str]]:
    segs: list[list[str]] = [[]]
    for t in _tokens(cmd):
        if t in SEGMENT_SPLIT:
            segs.append([])
        elif t in ("&", ";;", "(", ")", "|&"):
            raise Refused(f"shell operator {t!r} (background, subshell or case) in the command")
        else:
            segs[-1].append(t)
    if any(not s for s in segs):
        raise Refused("empty command segment")
    return segs


def _is_push_segment(seg: list[str]) -> bool:
    i = 0
    while i < len(seg) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]):
        i += 1
    if i < len(seg) and seg[i] in ("env", "command", "exec", "nohup", "timeout", "xargs", "sudo"):
        return any(os.path.basename(w) == "git" for w in seg[i:]) and "push" in seg[i:]
    if i >= len(seg) or os.path.basename(seg[i]) != "git":
        return False
    j = i + 1
    while j < len(seg) and seg[j].startswith("-"):
        j += 2 if seg[j] in ("-C", "-c") else 1
    return j < len(seg) and seg[j] == "push"


def _expand_dir(word: str, cwd: Path) -> Path:
    if word.startswith("~"):
        word = os.path.expanduser(word)
    elif _BAD_WORD.search(word):
        raise Refused(f"cd target {word!r} is not a literal path")
    p = Path(word)
    return (p if p.is_absolute() else cwd / p).resolve()


def parse_command(cmd: str, cwd: Path) -> dict[str, Any]:
    """Locate the single ``git push`` segment of ``cmd``; track ``cd`` before it. Pure apart from path resolution."""
    segs = split_segments(cmd)
    push_idx = [i for i, s in enumerate(segs) if _is_push_segment(s)]
    if len(push_idx) != 1:
        raise Refused(f"{len(push_idx)} git push segments in the command; exactly one is allowed")
    k = push_idx[0]
    here = cwd
    for s in segs[:k]:
        if s[0] in ("pushd", "popd"):
            raise Refused("pushd/popd before the push")
        if s[0] == "cd":
            if len(s) == 1:
                here = Path.home()
            elif len(s) == 2 and s[1] != "-":
                here = _expand_dir(s[1], here)
            else:
                raise Refused("cd with options before the push")
    seg = list(segs[k])
    for tail in _TRAILING_REDIRECTS:
        if seg[-len(tail):] == tail:
            seg = seg[: -len(tail)]
            break
    others = [shlex.join(s) for i, s in enumerate(segs) if i != k]
    return {"cwd": here, "push_words": seg, "other_segments": others}


def parse_push_words(words: list[str], cwd: Path) -> dict[str, Any]:
    """``[ENV=..] git [-C dir] push [opts] [remote [refspec]]`` -> repo, remote, refspecs. Refuses the rest."""
    i = 0
    env: dict[str, str] = {}
    while i < len(words) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i]):
        name, _, val = words[i].partition("=")
        if name not in ALLOWED_ENV_PREFIX:
            raise Refused(f"environment assignment {name}= in front of the push")
        env[name] = val
        i += 1
    if i >= len(words) or os.path.basename(words[i]) != "git":
        raise Refused("the push is not a direct git invocation (env/timeout/sudo/xargs wrappers refuse)")
    i += 1
    repo = cwd
    while i < len(words) and words[i] != "push":
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            repo = _expand_dir(words[i + 1], repo)
            i += 2
        elif w == "--no-pager":
            i += 1
        else:
            raise Refused(f"git global option {w!r} before push")
    i += 1  # 'push'
    positional: list[str] = []
    for w in words[i:]:
        if _BAD_WORD.search(w) and not w.startswith("-"):
            raise Refused(f"push word {w!r} contains a variable, glob or brace")
        if w == "--":
            raise Refused("'--' in the push arguments")
        if w.startswith("--"):
            key = w.split("=", 1)[0]
            if key in REFUSED_HINT:
                raise Refused(f"{w} ({REFUSED_HINT[key]}) needs the operator's grant")
            if key not in SAFE_LONG or "=" in w:
                raise Refused(f"unknown or unsupported push option {w}")
        elif w.startswith("-") and len(w) > 1:
            flags = w[1:]
            for f in flags:
                if f"-{f}" in REFUSED_HINT:
                    raise Refused(f"-{f} ({REFUSED_HINT['-' + f]}) needs the operator's grant")
            if not set(flags) <= SAFE_SHORT:
                raise Refused(f"unknown or unsupported push option {w}")
        else:
            positional.append(w)
    if len(positional) > 2:
        raise Refused("more than one refspec; a grant-free push writes exactly one branch")
    remote = positional[0] if positional else None
    refspec = positional[1] if len(positional) > 1 else None
    return {"repo": repo, "remote": remote, "refspec": refspec, "env": env}


# --------------------------------------------------------------------------- ref resolution


def resolve_target(repo: Path, remote: Optional[str], refspec: Optional[str]) -> dict[str, str]:
    """-> {"src": local ref, "branch": destination branch, "local_sha": sha}."""
    current = _git_out(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if refspec is None:
        if not current:
            raise Refused("detached HEAD and no refspec")
        name = current
        push_default = (_git_out(repo, "config", "--get", "push.default") or "simple").strip()
        if push_default not in ("simple", "current", "upstream"):
            raise Refused(f"push.default={push_default} may write more than the current branch")
        for key in (f"branch.{name}.pushRemote", "remote.pushDefault") + (() if remote else (f"branch.{name}.remote",)):
            val = _git_out(repo, "config", "--get", key)
            if val and val != REMOTE:
                raise Refused(f"{key}={val}: the push would not go to {REMOTE}")
        merge = _git_out(repo, "config", "--get", f"branch.{name}.merge")
        if merge and merge != f"refs/heads/{name}":
            raise Refused(f"branch.{name}.merge={merge}: the upstream has a different name")
        src, dst = name, name
    else:
        if refspec.startswith("+"):
            raise Refused(f"+refspec {refspec!r} is a force push")
        if ":" in refspec:
            src, _, dst = refspec.partition(":")
            if not src:
                raise Refused(f"refspec {refspec!r} deletes the remote branch")
        else:
            src, dst = refspec, refspec
        if src == "HEAD":
            if not current and ":" not in refspec:
                raise Refused("detached HEAD pushed without a destination branch")
            if ":" not in refspec:
                dst = current or ""
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        elif dst.startswith("refs/"):
            raise Refused(f"destination {dst!r} is not a branch")
        if src.startswith("refs/tags/") or (
            not src.startswith("refs/") and src != "HEAD"
            and _git_out(repo, "show-ref", "--verify", "--quiet", f"refs/tags/{src}") is not None
            and _git_out(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{src}") is None
        ):
            raise Refused(f"source {src!r} is a tag")
    if remote not in (None, REMOTE):
        raise Refused(f"remote {remote!r}: grant-free pushes go to {REMOTE} only")
    if not dst or _PROTECTED.search(dst):
        raise Refused(f"destination branch {dst!r} is protected (main, master, release/*, train/*)")
    if _git_out(repo, "check-ref-format", f"refs/heads/{dst}") is None:
        raise Refused(f"destination {dst!r} is not a valid branch name")
    sha = _git_out(repo, "rev-parse", "--verify", "--quiet", f"{src}^{{commit}}")
    if not sha or not _SHA.match(sha):
        raise Refused(f"source {src!r} does not resolve to a local commit")
    return {"src": src, "branch": dst, "local_sha": sha}


def ls_remote(repo: Path, branch: str) -> dict[str, str]:
    try:
        cp = _git(repo, "ls-remote", REMOTE, "refs/heads/main", f"refs/heads/{branch}", timeout=LS_REMOTE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f"git ls-remote {REMOTE} failed ({type(exc).__name__})") from None
    if cp.returncode != 0:
        raise Refused(f"git ls-remote {REMOTE} failed rc={cp.returncode}")
    out: dict[str, str] = {}
    for line in cp.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and _SHA.match(parts[0]):
            out[parts[1]] = parts[0]
    return out


def check_policy(repo: Path, main_sha: str) -> dict[str, Any]:
    if _git_out(repo, "cat-file", "-e", f"{main_sha}^{{commit}}") is None:
        raise Refused(f"remote main {main_sha[:9]} is not in the local object store; run: git fetch {REMOTE} main")
    text = _git_out(repo, "show", f"{main_sha}:AGENTS.md")
    st = policy_state_from_text(text, source=f"git:{main_sha[:12]}:AGENTS.md")
    ver = _semver(st.get("version"))
    if not st.get("active") or ver is None or ver < MIN_POLICY:
        raise Refused(f"AGENTS.md on remote main is not {MIN_POLICY_TEXT}+ ACTIVE ({st.get('detail')})")
    return st


def check_fast_forward(repo: Path, remote_sha: Optional[str], local_sha: str) -> str:
    if not remote_sha:
        return "new-branch"
    if remote_sha == local_sha:
        return "up-to-date"
    if _git_out(repo, "cat-file", "-e", f"{remote_sha}^{{commit}}") is None:
        raise Refused(f"remote branch head {remote_sha[:9]} is not local; fetch it to prove a fast-forward")
    try:
        cp = _git(repo, "merge-base", "--is-ancestor", remote_sha, local_sha)
    except (OSError, subprocess.SubprocessError):
        raise Refused("merge-base failed") from None
    if cp.returncode != 0:
        raise Refused(f"not a fast-forward: remote {remote_sha[:9]} is not an ancestor of {local_sha[:9]}")
    return "fast-forward"


def check_budget(repo: Path, branch: str) -> dict[str, int]:
    pb = _trusted_import("scripts.lib.tradeai_push_budget")
    prev = os.getcwd()
    try:
        os.chdir(repo)
        count = int(pb.count_for(branch))
        try:
            budget = int(pb.budget_for(branch, hands_off=True))
        except TypeError:  # main before PR #2115: no hands-off budget yet
            budget = int(pb.budget_for(branch))
    finally:
        os.chdir(prev)
    if count >= budget:
        raise Refused(f"push budget used ({count}/{budget}) for {branch}; past it is the coordinator override path")
    return {"count": count, "budget": budget}


# --------------------------------------------------------------------------- approved plan


def _branch_token_re(token: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9._/-])" + re.escape(token) + r"(?![A-Za-z0-9_/-]|\.[A-Za-z0-9_])")


def _plan_sections(worklog: str) -> str:
    """The Goal and Plan sections of a claim worklog (where a plan's approval line belongs)."""
    out, marks = [], list(_SECTION.finditer(worklog))
    for n, m in enumerate(marks):
        if m.group("name").strip().lower() in ("goal", "plan"):
            end = marks[n + 1].start() if n + 1 < len(marks) else len(worklog)
            out.append(worklog[m.end():end])
    return "\n".join(out)


def claims_dir() -> Path:
    env = os.environ.get(ENV_CLAIMS_DIR)
    if env:
        return Path(env).expanduser()
    board = _trusted_import("scripts.lib.agent_claim_board")
    return Path(board.default_claims_dir())


def handoffs_dir() -> Path:
    env = os.environ.get(ENV_HANDOFFS_DIR)
    if env:
        return Path(env).expanduser()
    return claims_dir().parent / "handoffs"


def live_claims_on(branch: str) -> list[dict[str, Any]]:
    board = _trusted_import("scripts.lib.agent_claim_board")
    views, _bad = board.ClaimBoard(claims_dir()).views()
    return [dict(v.doc, _state=v.state, _path=str(v.path)) for v in views
            if v.state == "live" and str(v.doc.get("branch") or "") == branch]


def claim_approval(branch: str) -> Optional[dict[str, str]]:
    for row in live_claims_on(branch):
        ref = approval_ref(str(row.get("note") or ""))
        where = "note"
        if not ref:
            wl = Path(row["_path"]).with_name(f"{row.get('claim_id')}.worklog.md")
            try:
                text = wl.read_text(encoding="utf-8") if wl.is_file() and not wl.is_symlink() else ""
            except OSError:
                text = ""
            ref = approval_ref(_plan_sections(text))
            where = "worklog plan"
        if ref:
            return {"source": "claim", "claim_id": str(row.get("claim_id")), "session": str(row.get("session") or ""),
                    "approval_ref": ref, "where": where}
    return None


def handoff_approval(branch: str, *, max_files: int = 2000, max_bytes: int = 1_000_000) -> Optional[dict[str, str]]:
    root = handoffs_dir()
    if not root.is_dir():
        return None
    root = root.resolve()
    tokens = [branch] + [str(r.get("claim_id")) for r in live_claims_on(branch) if r.get("claim_id")]
    tokens = [t for t in tokens if len(t) >= 6]
    pats = [(t, _branch_token_re(t)) for t in tokens]
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Task files live at handoffs/<file> or handoffs/<batch>/<file>; deeper levels are evidence (screenshots,
        # packets: 1.4 GB on 2026-10-25) and are never read.
        if len(Path(dirpath).relative_to(root).parts) >= 1:
            dirnames[:] = []
        dirnames.sort()
        for fn in sorted(filenames):
            if not fn.endswith((".md", ".json", ".txt", ".yaml", ".yml")) or "log" in fn.lower():
                continue  # a progress/worklog names branches as history, not as an assignment
            p = Path(dirpath) / fn
            seen += 1
            if seen > max_files:
                return None
            try:
                if p.is_symlink() or p.stat().st_size > max_bytes:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for tok, pat in pats:
                if pat.search(text):
                    rel = p.relative_to(root).as_posix()
                    inner = approval_ref(text)
                    ref = f"handoff:{rel}" + (f" ({inner})" if inner else "")
                    return {"source": "handoff", "handoff": rel, "names": tok, "approval_ref": ref[:300]}
    return None


# --------------------------------------------------------------------------- the check


def evaluate(push_words: list[str], cwd: Path) -> dict[str, Any]:
    p = parse_push_words(push_words, cwd)
    repo = p["repo"]
    top = _git_out(repo, "rev-parse", "--show-toplevel")
    if not top:
        raise Refused(f"{repo} is not a git work tree")
    repo = Path(top)
    tgt = resolve_target(repo, p["remote"], p["refspec"])
    branch = tgt["branch"]
    remote_refs = ls_remote(repo, branch)
    main_sha = remote_refs.get("refs/heads/main")
    if not main_sha:
        raise Refused(f"{REMOTE} has no main branch")
    st = check_policy(repo, main_sha)
    ff = check_fast_forward(repo, remote_refs.get(f"refs/heads/{branch}"), tgt["local_sha"])
    budget = check_budget(repo, branch)
    plan = claim_approval(branch) or handoff_approval(branch)
    if not plan:
        raise Refused(f"no approved plan covers {branch}: no live claim with an 'Operator-approval:' line in its note "
                      f"or worklog plan, and no coordinator task file under handoffs/ names it")
    return {
        "schema": SCHEMA,
        "allow": True,
        "repo": str(repo),
        "branch": branch,
        "head": tgt["local_sha"],
        "remote_head": remote_refs.get(f"refs/heads/{branch}") or "",
        "ff": ff,
        "policy": {"version": st.get("version"), "main": main_sha},
        "budget": budget,
        "plan": plan,
        "approval_ref": plan["approval_ref"],
        "env_authorized": p["env"].get("TRADEAI_REMOTE_PUSH_AUTHORIZED") == "1",
    }


def check_command(cmd: str, cwd: Path) -> dict[str, Any]:
    parsed = parse_command(cmd, cwd)
    out = evaluate(parsed["push_words"], parsed["cwd"])
    out["other_segments"] = parsed["other_segments"]
    return out


def _default_cwd(arg: Optional[str]) -> Path:
    for c in (arg, os.environ.get("CURSOR_PROJECT_DIR"), os.getcwd()):
        if c and Path(c).is_dir():
            return Path(c).resolve()
    return Path.cwd()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check")
    pc.add_argument("--command", required=True)
    pc.add_argument("--cwd")
    pa = sub.add_parser("check-args")
    pa.add_argument("--cwd")
    pa.add_argument("args", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            out = check_command(a.command, _default_cwd(a.cwd))
        else:
            args = [x for x in a.args]
            if args and args[0] == "--":
                args = args[1:]
            out = evaluate(["git", "push", *args], _default_cwd(a.cwd))
            out["other_segments"] = []
    except Refused as exc:
        print(json.dumps({"schema": SCHEMA, "allow": False, "reason": str(exc)}))
        return 1
    except Exception as exc:  # fail closed: any bug is a refusal, never an allow
        print(json.dumps({"schema": SCHEMA, "allow": False, "reason": f"internal error: {type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
