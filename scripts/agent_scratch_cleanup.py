#!/usr/bin/env python3
"""agent_scratch_cleanup.py — an agent removes ITS OWN scratch when a task ends.

Design: ``docs/designs/DSN-20261030-disk-governance-process.md``. This is the agent self-cleanup leg of the
repeatable disk-governance process: the contract "if an agent writes caches, it cleans them up afterwards",
enforced at claim-close / takeover / session-end (``scripts/agent_claim.py`` hooks this, report-only until the
operator ratifies AGENTS.md 27.0.0 §0 rule-6 exception (c)).

An agent's own scratch is, by construction (DELIVERY_LIFECYCLE.md "Build")::

    TMPDIR=$HOME/.cache/agent-tmp/<task>

Explicit ``--scratch`` paths must also be inside that task/session namespace; they cannot name another task.

REMOVAL IS REFUSED unless EVERY check passes. A path is a candidate only when it is:
  * inside the authorized ``~/.cache/agent-tmp`` task/session namespace and NOT the root
    itself, and NOT a symlink (symlinks are never followed and never removed);
  * free of protected descendants, symlinks and unreadable entries — the protected names / globs mirror
    ``config/disk_hygiene_rules.json`` (db_backups, persistent-state, models, .ssh, .config, .docker, .gnupg,
    .aws, .n8n, the dev repo, CURRENT; any .env / credential / cookie / token / key name);
  * bound to its exact recorded task and session, with canonical observed MERGED or abandoned/CLOSED PR
    completion (ending source custody alone is never completion; unknown/no-PR completion stays refused);
  * not referenced by any active claim worktree, path or active worklog;
  * not the cwd or an open fd of any live process (``/proc/<pid>/cwd``, ``/proc/<pid>/fd``);
  * only when the claim board is readable — an unreadable board refuses every candidate, because the absence
    of a recorded worktree is not proof that a path is unclaimed.
All git repositories and linked worktrees, including nested ones, are refused; governed workspace close handles them.
Missing/unreadable process or claim evidence refuses deletion rather than reporting an empty reference set.

Modes (the default is dry-run: it prints exactly what it would delete and deletes nothing):
    python3 scripts/agent_scratch_cleanup.py [--claim ID | --task T] [--scratch PATH ...]
    python3 scripts/agent_scratch_cleanup.py --apply [same]

Exit: 0 = plan printed / apply finished (a refused path is reported, not an error); 2 = usage.

AUTHORITY: READ_ONLY_ADVISORY until AGENTS.md 27.0.0 is ACTIVE — no broker, no network, no send, no DB. The
``--apply`` path removes only the named task/session's scratch in agent-tmp, after the checks above.
MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "AgentScratchCleanup@v1"
#: Allowed scratch roots (never the root itself, never outside them). Mirrors the disk-governance namespace.
SCRATCH_ROOTS = ("~/.cache/agent-tmp",)
#: Mirrors config/disk_hygiene_rules.json ``never_touch`` + ``protected_paths``. If that file changes, this list
#: must be updated too — it must be at least as strict, never looser.
NEVER_TOUCH_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "db_backups",
    "persistent-state",
    "llama-cpp-vulkan",
    ".ssh",
    ".config",
    ".docker",
    "docker",
    ".gnupg",
    ".aws",
    ".n8n",
    "n8n_data",
    "n8n-data",
}
NEVER_TOUCH_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    "*credential*",
    "*cookie*",
    "*token*",
    "*secret*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
)
PROTECTED_SUFFIXES = (
    "trade-ai-v12-rebuild",  # the dev repo (cron / units execute from it)
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
    if task_slug and session_slug:
        out.append(base / session_slug / task_slug)
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
    """Refuse aliases and anything outside the strict namespace; roots cannot authorize their parent."""
    path = Path(os.path.abspath(path))
    for root in roots:
        root = Path(os.path.abspath(root))
        if not is_within(path, root) or path == root:
            continue
        # An ancestor symlink is as unsafe as a candidate symlink. Never traverse it.
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink():
                return "symlink"
            if ancestor == root.parent.parent:
                break
        if is_within(_real(path), _real(root)) and _real(path) != _real(root):
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
    """Return inspected references, or refuse when any process cannot be inspected."""
    out: set[str] = set()
    try:
        names = os.listdir(proc_root)
        for name in names:
            if not name.isdigit():
                continue
            pid = proc_root / name
            out.add(os.path.realpath(os.readlink(pid / "cwd")))
            for fd in os.listdir(pid / "fd"):
                target = os.readlink(pid / "fd" / fd)
                if target.startswith("/"):
                    out.add(os.path.realpath(target))
    except OSError as exc:
        raise CleanupError(f"process_inspection_failed:{type(exc).__name__}") from exc
    return out


def in_use_by(path: Path, refs: Iterable[str]) -> Optional[str]:
    """A live process reference INSIDE ``path``, else None.

    Only a cwd/fd *inside* the candidate makes it in use. An ancestor reference (a shell sitting in ``$HOME``
    or ``/tmp``) must not refuse every candidate below it: refusal is about what the process could lose, not
    about what it can merely see.
    """
    real = os.path.realpath(path)
    for c in refs:
        if is_within(Path(c), Path(real)):
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
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, p.stdout


# ── evaluate ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def protected_tree_reason(path: Path, home: Path) -> Optional[str]:
    """Inspect names and lstat metadata only; never read a protected file or follow a symlink."""
    pending = [path]
    inspected = 0
    try:
        while pending:
            item = pending.pop()
            inspected += 1
            if inspected > SIZE_CAP_ENTRIES:
                return "tree_inspection_capped"
            mode = item.lstat().st_mode
            if stat.S_ISLNK(mode):
                return "protected_descendant:symlink"
            protected = never_touch_reason(item, home)
            if protected:
                return "protected_descendant:" + protected
            if stat.S_ISDIR(mode):
                with os.scandir(item) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
            elif not stat.S_ISREG(mode):
                return "protected_descendant:special_file"
    except OSError as exc:
        return f"tree_inspection_failed:{type(exc).__name__}"
    return None


def referenced_by_claim(path: Path, claims: Iterable[dict[str, Any]], home: Path) -> Optional[str]:
    """Claim paths and canonical active worklogs can hold a directory or any descendant."""
    for claim in claims:
        values = list(claim.get("paths") or [])
        text = claim.get("reference_text") or ""
        # Markdown/backtick/quoted absolute and home-relative paths, including ancestor references.
        values.extend(re.findall(r"(?:~/|/)[^\s`\"'<>()[\]{}]+", text))
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.rstrip(",;:.")
            if value.startswith("~/"):
                ref = home / value[2:]
            else:
                ref = Path(value)
                if not ref.is_absolute():
                    ref = Path(claim.get("worktree") or ROOT) / ref
            # Globs conservatively hold their fixed prefix, never silently discard an unknown match.
            prefix = re.split(r"[*?\[]", str(ref), maxsplit=1)[0].rstrip("/")
            ref = Path(os.path.abspath(prefix or "/"))
            try:
                resolved = ref.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise CleanupError(f"claim_reference_unreadable:{type(exc).__name__}") from exc
            if is_within(path, ref) or is_within(ref, path) or is_within(path, resolved) or is_within(resolved, path):
                return str(claim.get("claim_id") or "unknown")
        # Also protect exact candidate names containing spaces in prose.
        relative = "~/" + str(path.relative_to(home)) if is_within(path, home) else str(path)
        for spelling in (str(path), relative):
            if re.search(re.escape(spelling) + r"(?=$|[/\s`\"'),;:.])", text):
                return str(claim.get("claim_id") or "unknown")
    return None


def evaluate(
    path: Path,
    *,
    home: Path,
    roots: Iterable[Path],
    refs: Iterable[str],
    live_worktrees: Iterable[Path],
    live_claims: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """One scratch candidate against every check. Returns {path, kind, exists, reasons, candidate, how}."""
    reasons: list[str] = []
    kind = "missing"
    how: Optional[str] = None
    if not os.path.lexists(path):
        reasons.append("missing")
        return {"path": str(path), "kind": kind, "exists": False, "reasons": reasons, "candidate": False, "how": how}
    ar = allowed_scratch_reason(path, [home / ".cache" / "agent-tmp"]) or allowed_scratch_reason(path, roots)
    if ar:
        reasons.append(ar)
    nt = never_touch_reason(path, home)
    if nt:
        reasons.append(nt)
    tree_reason = protected_tree_reason(path, home) if not reasons else None
    if tree_reason:
        reasons.append(tree_reason)
    lay = git_layout(path) if not reasons else None
    if lay is not None:
        if lay["kind"] == "git_clone":
            kind = "git_clone"
            reasons.append("standalone_git_clone")
        else:
            kind = "git_worktree"
            reasons.append("registered_worktree_requires_governed_close")
    else:
        kind = "dir" if path.is_dir() else "file"
        how = "rmtree" if kind == "dir" else "unlink"
    for wt in live_worktrees:
        if is_within(path, wt) or is_within(wt, path):
            reasons.append(f"live_claim_worktree:{wt}")
            break
    try:
        holder = referenced_by_claim(path, live_claims, home)
        if holder:
            reasons.append(f"live_claim_reference:{holder}")
    except CleanupError as exc:
        reasons.append(str(exc))
    use = in_use_by(path, refs)
    if use:
        reasons.append(f"in_use_by_process:{use}")
    return {"path": str(path), "kind": kind, "exists": True, "reasons": reasons, "candidate": not reasons, "how": how}


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
    """Remove one prevalidated plain scratch item; repositories require governed workspace close."""
    if not os.path.lexists(path):
        return False, "gone"
    if path.is_symlink():
        return False, "symlink"
    if kind == "git_worktree":
        return False, "registered_worktree_requires_governed_close"
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
        if not board.dir.is_dir() or board.dir.is_symlink():
            return [], "claim_directory_unavailable"
        with os.scandir(board.dir) as entries:
            list(entries)  # missing/unreadable is not an authoritative empty board
        views, bad = board.views()
    except Exception as exc:  # noqa: BLE001 - a board problem is reported, never fatal
        return [], f"claim_board_read_failed:{type(exc).__name__}"
    live = []
    for v in views:
        if v.doc.get("status") != "active":
            continue
        paths = v.doc.get("paths") or []
        if not isinstance(paths, list) or any(not isinstance(value, str) for value in paths):
            return [], "claim_paths_unreadable"
        log = B.WL.path_for(board.dir, v.claim_id)
        try:
            try:
                mode = log.lstat().st_mode
            except FileNotFoundError:
                body = ""
            else:
                if stat.S_ISLNK(mode):
                    return [], "worklog_symlink"
                body = log.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return [], f"worklog_read_failed:{type(exc).__name__}"
        live.append(
            {
                "claim_id": v.claim_id,
                "task": v.doc.get("task"),
                "worktree": v.doc.get("worktree"),
                "session": v.doc.get("session"),
                "paths": paths,
                "reference_text": json.dumps(v.doc) + "\n" + body,
            }
        )
    warn = f"unreadable:{','.join(bad)}" if bad else None
    return live, warn


def completion_evidence(
    path: Path,
    *,
    home: Path,
    claims_dir: Optional[Path],
    task: Optional[str],
    session: Optional[str],
    claim: Optional[str],
) -> tuple[list[str], Optional[str]]:
    """Read task completion from canonical claims and observed PR lifecycle records.

    Releasing source custody (DONE/ABANDONED) is not feature completion. In particular,
    abandoning a claim on an open PR cannot authorize removal of that PR's work.
    No caller-supplied completion flag or declared lifecycle stage grants deletion.
    """
    if not task or not session:
        return [], "task_completion_identity_unresolved"
    base = home / ".cache" / "agent-tmp"
    task_roots = (base / slug(task), base / slug(session) / slug(task))
    if not any(is_within(path, root) for root in task_roots):
        return [], "task_completion_namespace_mismatch"
    try:
        from scripts.lib import agent_claim_board as B

        board = B.ClaimBoard(claims_dir)
        if not board.dir.is_dir() or board.dir.is_symlink():
            return [], "task_completion_board_unavailable"
        docs, bad = board.read_all()
        if bad:
            return [], "task_completion_board_unreadable"
        matches = [
            doc
            for doc in docs
            if doc.get("task") == task
            and doc.get("session") == session
            and (claim is None or doc.get("claim_id") == claim)
        ]
        if not matches:
            return [], "task_completion_not_recorded"
        completed = []
        for doc in matches:
            if doc.get("status") not in ("done", "abandoned") or B.parse_iso(doc.get("ended_at")) is None:
                return [], "task_completion_not_recorded"
            number = B.LC.pr_number(doc.get("pr"))
            if not number or isinstance(doc.get("pr"), bool):
                return [], "task_completion_pr_unresolved"
            # A related live source holder means the task/feature is still being worked on,
            # even when it did not explicitly list this scratch directory.
            if any(
                other.get("status") == "active"
                and (other.get("branch") == doc.get("branch") or B.LC.pr_number(other.get("pr")) == number)
                for other in docs
            ):
                return [], "task_completion_related_work_active"
            directory = board.dir / B.LC.LIFECYCLE_DIRNAME
            sidecar = directory / (str(doc["claim_id"]) + ".json")
            if directory.is_symlink() or sidecar.is_symlink():
                return [], "task_completion_observation_unavailable"
            observation = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(observation, dict) or (
                observation.get("schema") != B.LC.LIFECYCLE_SCHEMA
                or observation.get("claim_id") != doc["claim_id"]
                or B.LC.pr_number(observation.get("pr_number")) != number
                or B.parse_iso(observation.get("observed_at")) is None
                or re.fullmatch(r"[0-9a-f]{40}", str(doc.get("head_sha") or "")) is None
                or re.fullmatch(r"[0-9a-f]{40}", str(observation.get("head_sha") or "")) is None
                or observation.get("head_sha") != doc.get("head_sha")
            ):
                return [], "task_completion_observation_unbound"
            merged = (
                observation.get("pr_state") == "merged"
                and re.fullmatch(r"[0-9a-f]{40}", str(observation.get("merge_sha") or "")) is not None
                and B.parse_iso(observation.get("merged_at")) is not None
            )
            abandoned = (
                doc.get("status") == "abandoned"
                and observation.get("pr_state") == "closed"
                and not observation.get("merge_sha")
                and B.parse_iso(observation.get("closed_at")) is not None
            )
            if not (merged or abandoned):
                return [], "task_completion_not_observed"
            completed.append(str(doc["claim_id"]))
        return completed, None
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return [], f"task_completion_evidence_unavailable:{type(exc).__name__}"


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
    process_warn = None
    try:
        refs = process_refs(proc_root)
    except CleanupError as exc:
        refs, process_warn = set(), str(exc)
    live, board_warn = live_claim_view(claims_dir)

    task_name = task
    task_slug: Optional[str] = None
    session_slug = slug(session) if session else None

    if claim:
        matched = next((c for c in live if c["claim_id"] == claim), None)
        if matched is None:
            print(json.dumps({"ok": False, "error": f"claim {claim!r} not active on the board"}))
            return 1
        task_name = matched["task"]
        task_slug = slug(task_name)
        if session and session != matched["session"]:
            print(json.dumps({"ok": False, "error": "claim_session_mismatch"}))
            return 1
        if not session:
            session = matched["session"]
            session_slug = slug(session)
    elif task:
        task_slug = slug(task)

    # EVERY live claim's worktree is protected, whichever way the target was named. Naming --claim must not
    # narrow this guard to that one claim: a session scratch dir can hold another live claim's worktree, and
    # that worktree is never this agent's to remove (§0 rule 6(c), §24.13).
    live_worktrees = [Path(c["worktree"]) for c in live if c.get("worktree")]

    owned = auto_candidates(home, task_slug, session_slug)
    candidates = list(owned)
    for s in scratch:
        for part in s.split(os.pathsep):
            if part.strip():
                value = part.strip()
                candidates.append(home / value[2:] if value.startswith("~/") else Path(value))

    rows = []
    for p in dict.fromkeys(candidates):
        r = evaluate(p, home=home, roots=roots, refs=refs, live_worktrees=live_worktrees, live_claims=live)
        if r["candidate"] and not any(is_within(p, owner) for owner in owned):
            r["candidate"] = False
            r["reasons"].append("task_or_session_ownership_unresolved")
        if r["candidate"]:
            completed, problem = completion_evidence(
                p,
                home=home,
                claims_dir=claims_dir,
                task=task_name,
                session=session,
                claim=claim,
            )
            r["completion_claims"] = completed
            if problem:
                r["candidate"] = False
                r["reasons"].append(problem)
        if r["candidate"]:
            r["size_bytes"] = size_bytes(p)
        rows.append(r)

    would_remove = [r for r in rows if r["candidate"]]
    refused = [r for r in rows if not r["candidate"]]

    if board_warn or process_warn:
        # An unreadable claim board is not proof that no claim references a path. Fail closed: no candidate
        # may be reported removable (or removed) until the board can be read again.
        for r in rows:
            if r["candidate"]:
                r["candidate"] = False
                r["reasons"].append(f"claim_board_unavailable:{board_warn}" if board_warn else process_warn)
        would_remove = []
        refused = rows
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
        "process_warning": process_warn,
    }

    if apply:
        removed: list[dict[str, Any]] = []
        for r in would_remove:
            p = Path(r["path"])
            # Re-read both evidence sources and the whole candidate immediately before removal.
            try:
                latest_refs = process_refs(proc_root)
                latest_claims, warning = live_claim_view(claims_dir)
                if warning:
                    raise CleanupError(warning)
                check = evaluate(
                    p,
                    home=home,
                    roots=roots,
                    refs=latest_refs,
                    live_worktrees=[Path(c["worktree"]) for c in latest_claims if c.get("worktree")],
                    live_claims=latest_claims,
                )
            except CleanupError as exc:
                removed.append({"path": r["path"], "how": f"skip:evidence_unavailable:{exc}"})
                continue
            if not check["candidate"]:
                removed.append({"path": r["path"], "how": "skip:revalidation_refused", "reasons": check["reasons"]})
                continue
            completed, problem = completion_evidence(
                p,
                home=home,
                claims_dir=claims_dir,
                task=task_name,
                session=session,
                claim=claim,
            )
            if problem:
                removed.append({"path": r["path"], "how": "skip:completion_revalidation_refused", "reasons": [problem]})
                continue
            lay = git_layout(p)
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
        if board_warn or process_warn:
            print(f"  WARN: {board_warn or process_warn}")
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
    ap.add_argument(
        "--scratch", action="append", default=None, help="explicit scratch path (repeatable, os.pathsep-separated)"
    )
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
        home=home,
        claims_dir=claims_dir,
        proc_root=proc_root,
        task=a.task,
        claim=a.claim,
        session=session,
        scratch=scratch,
        apply=bool(a.apply),
    )


if __name__ == "__main__":
    raise SystemExit(main())
