#!/usr/bin/env python3
"""agent_scratch_cleanup.py — an agent removes ITS OWN scratch when a task ends.

Design: ``docs/designs/DSN-20261030-disk-governance-process.md``. This is the agent self-cleanup leg of the
repeatable disk-governance process: the contract "if an agent writes caches, it cleans them up afterwards",
enforced at claim-close / takeover / session-end (``scripts/agent_claim.py`` hooks this, report-only until the
operator ratifies AGENTS.md 27.0.0 §0 rule-6 exception (c)).

An agent's own scratch is, by construction (DELIVERY_LIFECYCLE.md "Build")::

    TMPDIR=$HOME/.cache/agent-tmp/<task>

plus anything else the agent names with ``--scratch`` (its own review worktree under /tmp or ~/.cache).

REMOVAL IS REFUSED unless EVERY check passes. A path is a candidate only when it is:
  * inside an allowed scratch root (default ``~/.cache/agent-tmp``, ``~/.cache/rtc``, ``/tmp``) and NOT the root
    itself, and NOT a symlink (symlinks are never followed and never removed);
  * not on the never-touch list — the protected paths / names / globs mirrored from
    ``config/disk_hygiene_rules.json`` (db_backups, persistent-state, models, .ssh, .config, .docker, .gnupg,
    .aws, .n8n, the dev repo, CURRENT; any .env / credential / cookie / token / key name);
  * not the recorded worktree of this session's live claim, and not referenced by any live claim's worktree;
  * not the cwd or an open fd of any live process (``/proc/<pid>/cwd``, ``/proc/<pid>/fd``).
A linked git worktree under a scratch root is removed with ``git worktree remove`` (never --force); a standalone
clone is refused (a repo is not scratch).

Modes (the default is dry-run: it prints exactly what it would delete and deletes nothing):
    python3 scripts/agent_scratch_cleanup.py [--claim ID | --task T] [--scratch PATH ...]
    python3 scripts/agent_scratch_cleanup.py --apply [same]

Exit: 0 = plan printed / apply finished (a refused path is reported, not an error); 2 = usage.

AUTHORITY: READ_ONLY_ADVISORY until AGENTS.md 27.0.0 is ACTIVE — no broker, no network, no send, no DB. The
``--apply`` path removes only this agent's own scratch under the allowed roots, after the checks above.
MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "AgentScratchCleanup@v1"
#: Allowed scratch roots (never the root itself, never outside them). Mirrors the disk-governance namespace.
SCRATCH_ROOTS = ("~/.cache/agent-tmp", "~/.cache/rtc", "/tmp")
#: Mirrors config/disk_hygiene_rules.json ``never_touch`` + ``protected_paths``. If that file changes, this list
#: must be updated too — it must be at least as strict, never looser.
NEVER_TOUCH_NAMES = {
    "db_backups", "persistent-state", "llama-cpp-vulkan", ".ssh", ".config", ".docker",
    "docker", ".gnupg", ".aws", ".n8n", "n8n_data", "n8n-data",
}
NEVER_TOUCH_GLOBS = (
    ".env", ".env.*", "*.env", "*credential*", "*cookie*", "*token*", "*secret*",
    "*.pem", "*.key", "id_rsa*", "id_ed25519*",
)
PROTECTED_SUFFIXES = (
    "trade-ai-v12-rebuild",       # the dev repo (cron / units execute from it)
    "tradeai-exact-main-20260827",  # release-prep clone
    "trade-ai-releases/train-checkout",
    "trade-ai-releases/portfolio-server/CURRENT",
)
_SLUG_RE = re.compile(r"[^a-z0-9_.-]+")
SIZE_CAP_ENTRIES = 100_000
SIZE_CAP_BYTES = 10 * 1024**3  # stop counting past 10 GiB; report ">capped"


class CleanupError(ValueError):
    pass


# ── identity ────────────────────────────────────────────────────────────────────────────────────────────────────────


def slug(value: Any) -> str:
    s = _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return (s or "unknown")[:24]


def env_session(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    for key in ("AGENT_CLAIM_SESSION", "CLAUDE_SESSION_ID", "CODEX_SESSION_ID", "CURSOR_SESSION_ID"):
        if env.get(key):
            return env[key][:120]
    return None


def default_scratch_roots(home: Path) -> list[Path]:
    out: list[Path] = []
    for p in SCRATCH_ROOTS:
        out.append(Path(os.path.expanduser(p)) if not p.startswith("~/") else home / p[2:])
    return out


def auto_candidates(home: Path, task_slug: Optional[str], session_slug: Optional[str]) -> list[Path]:
    out: list[Path] = []
    base = home / ".cache" / "agent-tmp"
    for name in (task_slug, session_slug):
        if name:
            out.append(base / name)
    return out


# ── path predicates ──────────────────────────────────────────────────────────────────────────────────────────────────


def _real(p: Path) -> Path:
    try:
        return Path(os.path.realpath(p))
    except OSError:
        return Path(os.path.abspath(p))


def is_within(child: Path, parent: Path) -> bool:
    c, p = os.path.abspath(child), os.path.abspath(parent)
    return c == p or c.startswith(p.rstrip("/") + "/")


def allowed_scratch_reason(path: Path, roots: Iterable[Path]) -> Optional[str]:
    """Why ``path`` is NOT an allowed scratch candidate, else None. Symlinks are never allowed."""
    if path.is_symlink():
        return "symlink"
    real = _real(path)
    for root in roots:
        r = _real(root)
        if is_within(real, r) and not is_within(r, real):  # strictly inside the root, never the root itself
            return None
    return "outside_scratch_root"


def never_touch_reason(path: Path, home: Path) -> Optional[str]:
    """Why ``path`` is on the never-touch / protected list, else None (checks the raw path; symlinks never resolved)."""
    cand = Path(os.path.abspath(path))
    # protected home-relative suffixes (dev repo, release-prep, served CURRENT)
    try:
        rel = cand.relative_to(home)
        for suffix in PROTECTED_SUFFIXES:
            suf = Path(suffix)
            if is_within(cand, home / suf) or is_within(home / suf, cand):
                return f"protected:{suffix}"
        parts = rel.parts
    except ValueError:
        parts = cand.parts
    for part in parts:
        if part in NEVER_TOUCH_NAMES:
            return f"never_touch_name:{part}"
        for g in NEVER_TOUCH_GLOBS:
            if fnmatch.fnmatch(part.lower(), g.lower()):
                return f"never_touch_glob:{g}:{part}"
    return None


# ── host facts (read only) ───────────────────────────────────────────────────────────────────────────────────────────


def process_refs(proc_root: Path = Path("/proc")) -> set[str]:
    """Realpaths of every live process cwd and every absolute open fd target. An unreadable process yields nothing
    (it is not proof of absence — callers treat a refusal as unknown, never as clear)."""
    out: set[str] = set()
    try:
        names = os.listdir(proc_root)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        try:
            out.add(os.path.realpath(os.readlink(proc_root / name / "cwd")))
        except OSError:
            pass
        try:
            for fd in os.listdir(proc_root / name / "fd"):
                try:
                    target = os.readlink(proc_root / name / "fd" / fd)
                    if target.startswith("/"):
                        out.add(os.path.realpath(target))
                except OSError:
                    continue
        except OSError:
            continue
    return out


def in_use_by(path: Path, refs: Iterable[str]) -> Optional[str]:
    real = os.path.realpath(path)
    for c in refs:
        if is_within(Path(c), Path(real)) or is_within(Path(real), Path(c)):
            return c
    return None


# ── git ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def git_layout(path: Path) -> Optional[dict[str, Any]]:
    """{kind: git_worktree|git_clone, main_repo} or None when ``path`` is not a git work tree."""
    dot = path / ".git"
    if dot.is_symlink():
        return None
    if dot.is_dir():
        return {"kind": "git_clone", "main_repo": path}
    if dot.is_file():
        try:
            line = dot.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not line.startswith("gitdir:"):
            return None
        gitdir = Path(line.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (path / gitdir).resolve()
        common = gitdir
        try:
            rel = (gitdir / "commondir").read_text(encoding="utf-8").strip()
            common = (gitdir / rel).resolve()
        except OSError:
            pass
        main_repo = common.parent if common.name == ".git" else common
        return {"kind": "git_worktree", "main_repo": main_repo}
    return None


def _git(path: Path, *args: str, timeout: float = 300) -> tuple[int, str]:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        p = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(path), *args],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, p.stdout


# ── evaluate ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def evaluate(
    path: Path,
    *,
    home: Path,
    roots: Iterable[Path],
    refs: Iterable[str],
    live_worktrees: Iterable[Path],
) -> dict[str, Any]:
    """One scratch candidate against every check. Returns {path, kind, exists, reasons, candidate, how}."""
    reasons: list[str] = []
    kind = "missing"
    how: Optional[str] = None
    if not os.path.lexists(path):
        reasons.append("missing")
        return {"path": str(path), "kind": kind, "exists": False, "reasons": reasons,
                "candidate": False, "how": how}
    ar = allowed_scratch_reason(path, roots)
    if ar:
        reasons.append(ar)
    nt = never_touch_reason(path, home)
    if nt:
        reasons.append(nt)
    lay = git_layout(path)
    if lay is not None:
        if lay["kind"] == "git_clone":
            kind = "git_clone"
            reasons.append("standalone_git_clone")
        else:
            kind = "git_worktree"
            how = f"git worktree remove (main {lay['main_repo']})"
    else:
        kind = "dir" if path.is_dir() else "file"
        how = "rmtree" if kind == "dir" else "unlink"
    for wt in live_worktrees:
        if is_within(path, wt) or is_within(wt, path):
            reasons.append(f"live_claim_worktree:{wt}")
            break
    use = in_use_by(path, refs)
    if use:
        reasons.append(f"in_use_by_process:{use}")
    return {"path": str(path), "kind": kind, "exists": True, "reasons": reasons,
            "candidate": not reasons, "how": how}


def size_bytes(path: Path) -> Optional[int]:
    """Bounded size estimate (lstat only, no symlink follow); None when it cannot be fully measured."""
    total = 0
    entries = 0
    stack: list[Path] = [path]
    while stack:
        cur = stack.pop()
        if entries >= SIZE_CAP_ENTRIES or total > SIZE_CAP_BYTES:
            return None  # ">capped"
        try:
            st = cur.lstat()
        except OSError:
            return None
        if cur.is_symlink():
            continue
        if st.st_mode & 0o170000 == 0o040000:  # directory
            try:
                stack.extend(Path(e.path) for e in os.scandir(cur))
            except OSError:
                return None
        else:
            total += st.st_size
        entries += 1
    return total


def remove_item(path: Path, kind: str, main_repo: Optional[Path]) -> tuple[bool, str]:
    """Remove ONE item; (ok, how). A git worktree goes through ``git worktree remove`` (never --force)."""
    if not os.path.lexists(path):
        return False, "gone"
    if path.is_symlink():
        return False, "symlink"
    if kind == "git_worktree" and main_repo is not None:
        rc, _ = _git(main_repo, "worktree", "remove", str(path))
        if rc != 0 or os.path.lexists(path):
            return False, f"git_worktree_remove_rc:{rc}"
        return True, "git worktree remove"
    if kind == "dir":
        shutil.rmtree(path)
        return True, "rmtree"
    if kind == "file":
        path.unlink()
        return True, "unlink"
    return False, f"unknown_kind:{kind}"


# ── board (read only) ────────────────────────────────────────────────────────────────────────────────────────────────


def live_claim_view(claims_dir: Optional[Path]) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Live (active) claims and a warning. Reads local coordination files only; never GitHub, never a write."""
    try:
        from scripts.lib import agent_claim_board as B
    except ImportError:
        return [], "claim_board_unavailable"
    board = B.ClaimBoard(claims_dir)
    try:
        views, bad = board.views()
    except Exception as exc:  # noqa: BLE001 - a board problem is reported, never fatal
        return [], f"claim_board_read_failed:{type(exc).__name__}"
    live = []
    for v in views:
        if v.doc.get("status") != "active":
            continue
        live.append({"claim_id": v.claim_id, "task": v.doc.get("task"), "worktree": v.doc.get("worktree"),
                     "session": v.doc.get("session"), "paths": v.doc.get("paths") or []})
    warn = f"unreadable:{','.join(bad)}" if bad else None
    return live, warn


def _fmt_size(n: Optional[int]) -> str:
    if n is None:
        return ">capped"
    if n >= 1024**3:
        return f"{n / 1024**3:.2f}G"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f}M"
    return f"{n}B"


def run(
    *,
    home: Path,
    claims_dir: Optional[Path],
    proc_root: Path,
    task: Optional[str],
    claim: Optional[str],
    session: Optional[str],
    scratch: list[str],
    apply: bool,
) -> int:
    roots = default_scratch_roots(home)
    refs = process_refs(proc_root)
    live, board_warn = live_claim_view(claims_dir)

    task_slug: Optional[str] = None
    session_slug = slug(session) if session else None
    own_worktrees: list[Path] = []
    live_worktrees: list[Path] = []

    if claim:
        matched = next((c for c in live if c["claim_id"] == claim), None)
        if matched is None:
            print(json.dumps({"ok": False, "error": f"claim {claim!r} not active on the board"}))
            return 1
        task_slug = slug(matched["task"])
        if matched["worktree"]:
            own_worktrees.append(Path(matched["worktree"]))
        live_worktrees = own_worktrees[:]
        if not session:
            session = matched["session"]
            session_slug = slug(session)
    else:
        for c in live:
            wt = c.get("worktree")
            if wt:
                wtp = Path(wt)
                live_worktrees.append(wtp)
                if session and c.get("session") == session:
                    own_worktrees.append(wtp)
        if task:
            task_slug = slug(task)

    candidates = auto_candidates(home, task_slug, session_slug)
    for s in scratch:
        for part in s.split(os.pathsep):
            if part.strip():
                candidates.append(Path(os.path.expanduser(part.strip())))

    rows = []
    for p in candidates:
        r = evaluate(p, home=home, roots=roots, refs=refs, live_worktrees=live_worktrees)
        if r["candidate"]:
            r["size_bytes"] = size_bytes(p)
        rows.append(r)

    would_remove = [r for r in rows if r["candidate"]]
    refused = [r for r in rows if not r["candidate"]]
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "apply" if apply else "dry_run",
        "home": str(home),
        "task": task_slug,
        "session": session_slug,
        "scratch_roots": [str(r) for r in roots],
        "candidates": rows,
        "would_remove": [r["path"] for r in would_remove],
        "refused": [{"path": r["path"], "reasons": r["reasons"]} for r in refused],
        "board_warning": board_warn,
    }

    if apply:
        removed: list[dict[str, Any]] = []
        for r in would_remove:
            p = Path(r["path"])
            lay = git_layout(p)
            # Re-validate immediately before removal: gone / symlink / never-touch / in-use all refuse.
            if not os.path.lexists(p):
                removed.append({"path": r["path"], "how": "skip:gone"})
                continue
            if p.is_symlink() or never_touch_reason(p, home) or in_use_by(p, refs):
                removed.append({"path": r["path"], "how": "skip:revalidation_refused"})
                continue
            kind = r["kind"]
            main_repo = Path(lay["main_repo"]) if lay and lay["kind"] == "git_worktree" else None
            ok, how = remove_item(p, kind, main_repo)
            removed.append({"path": r["path"], "kind": kind, "how": how, "ok": ok})
        result["removed"] = removed
        result["removed_count"] = sum(1 for x in removed if x.get("ok"))

    if apply:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"agent_scratch_cleanup dry-run  home={home}")
        if board_warn:
            print(f"  WARN: {board_warn}")
        if not would_remove:
            print("  (no candidate scratch: nothing to remove)")
        for r in would_remove:
            print(f"  would delete: {_fmt_size(r.get('size_bytes'))}  {r['kind']:<12} {r['path']}")
        for r in refused:
            print(f"  refused: {r['path']}  ({'; '.join(r['reasons'])})")
        if would_remove:
            print("  --apply would remove these (report-only until AGENTS.md 27.0.0 is ACTIVE)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="remove candidates (default is dry-run)")
    g.add_argument("--dry-run", action="store_true", help="print what would be deleted, delete nothing (default)")
    ap.add_argument("--claim", help="claim id (reads the task/worktree from the board)")
    ap.add_argument("--task", help="task slug/id used to derive the scratch dir name")
    ap.add_argument("--session", default=None, help="session id (default AGENT_CLAIM_SESSION)")
    ap.add_argument("--scratch", action="append", default=None, help="explicit scratch path (repeatable, os.pathsep-separated)")
    ap.add_argument("--claims-dir", default=None)
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--proc-root", help=argparse.SUPPRESS)  # tests
    a = ap.parse_args(argv)

    home = Path(a.home) if a.home else Path.home()
    claims_dir = Path(a.claims_dir) if a.claims_dir else None
    proc_root = Path(a.proc_root) if a.proc_root else Path("/proc")
    session = a.session or env_session()
    scratch = list(a.scratch or []) + [p for p in os.environ.get("AGENT_SCRATCH_DIRS", "").split(os.pathsep) if p]
    if not (a.claim or a.task or session or scratch):
        print("error: give --claim, --task, --session (or AGENT_CLAIM_SESSION), or --scratch", file=sys.stderr)
        return 2
    return run(
        home=home, claims_dir=claims_dir, proc_root=proc_root, task=a.task, claim=a.claim,
        session=session, scratch=scratch, apply=bool(a.apply),
    )


if __name__ == "__main__":
    raise SystemExit(main())
