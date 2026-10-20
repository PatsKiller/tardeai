#!/usr/bin/env python3
"""disk_hygiene.py — repeatable, rule-based disk reclaim plan (destructive apply is unsupported).

Operator, 2026-10-18: "a script with rules that's repeatable, n8n should run this weekly; and also monitor when a
threshold is over 80%, fix and move to n8n where monitored." Measured that morning: root 89% (394G/468G); n8n was
not the cause (DB 37 MB). The space sat in ~500 stale repo clones / linked worktrees directly under $HOME, under
~/worktrees and under the dev repo's .claude/worktrees, in an archive of old release tarballs, and in caches.

Every threshold, path and keep-count is in ``config/disk_hygiene_rules.json``; this file holds the rules' LOGIC only.

RULES (a path is a candidate only when its rule says so; everything else is reported with the reasons it was kept)
  G  git clone / linked worktree under a configured root. Candidate ONLY if ALL hold:
       owned (origin URL matches owned_remote_patterns; another application's repo is never touched, AGENTS §24.4),
       not protected (dev repo, ~/tradeai-exact-main-20260827, CURRENT), not on the never-touch list,
       not referenced by the crontab, a systemd unit / drop-in or a release pointer file,
       no running process has its cwd inside it (/proc/*/cwd),
       working tree clean INCLUDING untracked files (git status --porcelain --untracked-files=all is empty),
       no commit that is on no remote branch (HEAD; for a clone also every local branch, and no stash),
       HEAD merged into origin/main (ancestor), or its upstream branch is gone AND `git cherry` shows every commit
       patch-equivalent in origin/main,
       no ignored file whose name looks like a credential (.env, *token*, *cookie* ...),
       not a locked worktree, and idle longer than idle_days (newest of the dir, its top-level entries, and the
       gitdir's HEAD / index / logs/HEAD).
     A linked worktree is removed with ``git -C <main repo> worktree remove <path>`` (never --force, never rm -rf);
     a standalone clone is removed (rmtree) only under the same checks.
  R  releases: keep the CURRENT target, every pointer-file target, the previous served release, the newest N, any
     in-use / referenced entry, and everything while an archive's ``hold_until`` date has not passed.
  C  caches (optional, default disabled): entries older than X days.
  NEVER-TOUCH (enforced here, before every planning rule and during read-only revalidation): db_backups, persistent-state,
     llama-cpp-vulkan (report only), .ssh, .config, docker / n8n volumes, and any .env / credential / cookie /
     token path.

MODES
    python3 scripts/disk_hygiene.py                     # plan (default): manifest JSON + LaneRunReceipt, deletes nothing
    python3 scripts/disk_hygiene.py --dry-run           # print the plan only: no manifest, no receipt, no write at all
    python3 scripts/disk_hygiene.py --report            # plan + a human summary on stdout
    python3 scripts/disk_hygiene.py --apply           # unsupported: refuses without reading rules or writing state

ACTIVE policy supplies no destructive maintenance authority. ``--apply`` and the
public ``apply()`` API always refuse; caller tokens cannot enable them. Plans and
read-only verification remain available. A future policy decision alone does not
re-enable deletion: it would require a separately reviewed authority implementation.

Exit: 0 = plan written (or dry run printed); 1 = rules / home unreadable, a write
failed, or an apply refusal; 2 = usage.

MBI_BEHAVIOR = 0. No broker, no network, no send, no DB. Never reads a credential file (credential-like names are
only matched, never opened).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_last_receipt as R  # noqa: E402

LANE_ID = "disk-hygiene"
APPLY_LANE_ID = "disk-hygiene-apply"
SCRIPT = "scripts/disk_hygiene.py"
RULES_PATH = ROOT / "config" / "disk_hygiene_rules.json"
RULES_SCHEMA = "DiskHygieneRules@v1"
MANIFEST_SCHEMA = "DiskHygieneManifest@v1"
APPLY_SCHEMA = "DiskHygieneApplyReport@v1"
#: Fixed in code (not config) so the n8n env allowlist inventory stays a literal, statically checked read.
GRANT_ENV = "TRADEAI_DISK_HYGIENE_GRANT"
#: Set by scripts/n8n_run_executor.py on every child it spawns: --apply refuses under it.
RUN_ID_ENV = "TRADEAI_RUN_ID"
SKIP_DEPENDENCY = "dependency_unavailable"
DOT_GIT = ".git"


class RulesError(ValueError):
    pass


# ── rules ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _expand(p: str, home: Path) -> Path:
    if p == "~":
        return home
    if p.startswith("~/"):
        return home / p[2:]
    return Path(p)


def load_rules(path: Optional[Path] = None, *, home: Optional[Path] = None) -> dict[str, Any]:
    """The rules document with every path expanded; raises RulesError when unreadable or incomplete."""
    p = Path(path) if path else RULES_PATH
    try:
        raw = p.read_bytes()
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RulesError(f"rules_unreadable:{type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != RULES_SCHEMA:
        raise RulesError("rules_schema")
    for key in ("protected_paths", "never_touch", "git", "releases", "caches", "references", "manifest", "apply"):
        if not isinstance(doc.get(key), dict):
            raise RulesError(f"rules_missing:{key}")
    h = Path(home) if home else _expand(str(doc.get("home") or "~"), Path.home())
    doc["_home"] = h
    doc["_sha256"] = hashlib.sha256(raw).hexdigest()
    doc["_path"] = str(p)
    x = lambda s: _expand(str(s), h)  # noqa: E731
    doc["_protected"] = [x(s) for s in doc["protected_paths"].get("paths") or []]
    nt = doc["never_touch"]
    doc["_never_paths"] = [x(s) for s in nt.get("paths") or []]
    doc["_never_names"] = set(nt.get("names") or [])
    doc["_never_globs"] = list(nt.get("name_globs") or [])
    doc["_report_only"] = [{**r, "_path": x(r["path"])} for r in nt.get("report_only") or []]
    doc["_git_roots"] = [{**r, "_path": x(r["path"])} for r in doc["git"].get("roots") or []]
    doc["_owned_res"] = [re.compile(s) for s in doc["git"].get("owned_remote_patterns") or []]
    rel = doc["releases"]
    doc["_release_roots"] = [{**r, "_path": x(r["path"])} for r in rel.get("roots") or []]
    doc["_pointer_dir"] = x(rel["pointer_dir"]) if rel.get("pointer_dir") else None
    doc["_cache_rules"] = [{**r, "_path": x(r["path"])} for r in doc["caches"].get("rules") or []]
    ref = doc["references"]
    doc["_unit_dirs"] = [x(s) for s in ref.get("systemd_unit_dirs") or []]
    doc["_proc_root"] = Path(ref.get("proc_root") or "/proc")
    for key in ("idle_days", "main_ref"):
        if key not in doc["git"]:
            raise RulesError(f"rules_missing:git.{key}")
    for key in ("manifest_max_age_hours", "max_items_per_run", "max_bytes_per_run", "kinds_enabled"):
        if key not in doc["apply"]:
            raise RulesError(f"rules_missing:apply.{key}")
    return doc


# ── path predicates ────────────────────────────────────────────────────────────────────────────────────────────────


def _real(p: Path) -> Path:
    try:
        return Path(os.path.realpath(p))
    except OSError:
        return Path(os.path.abspath(p))


def is_within(child: Path, parent: Path) -> bool:
    c, p = os.path.abspath(child), os.path.abspath(parent)
    return c == p or c.startswith(p.rstrip("/") + "/")


def never_touch_reason(path: Path, rules: Mapping[str, Any]) -> Optional[str]:
    """Why ``path`` is on the hard never-touch list, else None. Checked on the raw and the resolved path: equal to /
    inside / containing a never-touch path, a never-touch component name, or a credential-like component name."""
    home = rules["_home"]
    for cand in {Path(os.path.abspath(path)), _real(path)}:
        for nt in rules["_never_paths"]:
            for ntp in {Path(os.path.abspath(nt)), _real(nt)}:
                if is_within(cand, ntp):
                    return f"never_touch_path:{ntp}"
                if is_within(ntp, cand):
                    return f"contains_never_touch_path:{ntp}"
        try:
            parts = cand.relative_to(home).parts if is_within(cand, home) else cand.parts
        except ValueError:
            parts = cand.parts
        for part in parts:
            if part in rules["_never_names"]:
                return f"never_touch_name:{part}"
            for g in rules["_never_globs"]:
                if fnmatch.fnmatch(part.lower(), g.lower()):
                    return f"never_touch_glob:{g}:{part}"
    return None


def protected_reason(path: Path, rules: Mapping[str, Any], *, own_work_tree: bool = False) -> Optional[str]:
    """Why ``path`` is protected, else None: equal to or containing a protected path, or inside one. A separate git
    work tree nested inside a protected repo (``<dev repo>/.claude/worktrees/<agent>``, its own ``.git`` file) is
    not the protected repo, so with ``own_work_tree`` only equality / containment protect it."""
    for cand in {Path(os.path.abspath(path)), _real(path)}:
        for pp in rules["_protected"]:
            for pr in {Path(os.path.abspath(pp)), _real(pp)}:
                if str(cand) == str(pr) or is_within(pr, cand):
                    return f"protected:{pp}"
                if is_within(cand, pr) and not own_work_tree:
                    return f"protected:{pp}"
    return None


# ── host facts (read only) ─────────────────────────────────────────────────────────────────────────────────────────


def process_cwds(proc_root: Path) -> set[str]:
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
            continue
    return out


def reference_texts(rules: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(source, text) for the crontab, every systemd unit / drop-in file in the configured dirs, and the release
    pointer files. Read-only; a source that cannot be read is listed with an empty text and noted in the manifest."""
    out: list[tuple[str, str]] = []
    cmd = rules["references"].get("crontab_cmd")
    if cmd:
        try:
            proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=30)
            out.append(("crontab", proc.stdout if proc.returncode == 0 else ""))
        except (OSError, subprocess.SubprocessError):
            out.append(("crontab:unreadable", ""))
    for d in rules["_unit_dirs"]:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and (p.suffix in (".service", ".timer", ".conf", ".path", ".socket", ".target")):
                try:
                    out.append((f"systemd:{p}", p.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    pd = rules.get("_pointer_dir")
    if pd and pd.is_dir():
        for name in rules["releases"].get("pointer_files") or []:
            p = pd / name
            try:
                out.append((f"pointer:{p}", p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
        for name in rules["releases"].get("pointer_symlinks") or []:
            p = pd / name
            if p.is_symlink():
                out.append((f"pointer:{p}", os.path.realpath(p)))
    return out


def referenced_by(path: Path, refs: Iterable[tuple[str, str]]) -> Optional[str]:
    variants = {os.path.abspath(path), os.path.realpath(path)}
    pats = [re.compile(re.escape(v.rstrip("/")) + r"(?=$|[/\s'\";:,)=])", re.M) for v in variants]
    for source, text in refs:
        if text and any(p.search(text) for p in pats):
            return source
    return None


def in_use_by(path: Path, cwds: Iterable[str]) -> Optional[str]:
    real = os.path.realpath(path)
    for c in cwds:
        if is_within(Path(c), Path(real)):
            return c
    return None


def du_bytes(path: Path, timeout_s: float) -> Optional[int]:
    """Disk usage (bytes) like ``du -sB1``; None when du fails or times out (never a guess)."""
    try:
        proc = subprocess.run(["du", "-s", "-B1", "-x", str(path)], capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(proc.stdout.split()[0])
    except (IndexError, ValueError):
        return None


def newest_mtime(path: Path, extra: Iterable[Path] = ()) -> float:
    """Newest mtime of the dir itself, its top-level entries (lstat) and any ``extra`` paths."""
    best = 0.0
    try:
        best = os.lstat(path).st_mtime
        with os.scandir(path) as it:
            for e in it:
                try:
                    best = max(best, e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    continue
    except OSError:
        pass
    for p in extra:
        try:
            best = max(best, os.lstat(p).st_mtime)
        except OSError:
            continue
    return best


def last_reflog_ts(path: Path) -> float:
    """Timestamp of the newest reflog entry (``<old> <new> <who> <unix-ts> <tz>`` TAB ``<msg>``); 0.0 when absent."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 8192))
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return 0.0
    for line in reversed(tail):
        head = line.split("\t", 1)[0].split()
        if len(head) >= 2 and head[-2].isdigit():
            return float(head[-2])
    return 0.0


# ── git ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _git(path: Path, *args: str, timeout: float = 60) -> tuple[int, str]:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        p = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return p.returncode, p.stdout


def git_layout(path: Path) -> Optional[dict[str, Any]]:
    """{kind: git_worktree|git_clone, gitdir, common_dir, main_repo} or None when ``path`` is not a git work tree."""
    dot = path / DOT_GIT
    if dot.is_symlink():
        return None
    if dot.is_dir():
        return {"kind": "git_clone", "gitdir": dot, "common_dir": dot, "main_repo": path}
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
        main_repo = common.parent if common.name == DOT_GIT else common
        return {"kind": "git_worktree", "gitdir": gitdir, "common_dir": common, "main_repo": main_repo}
    return None


def evaluate_git(path: Path, rules: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    """One clone / worktree against rule G. Returns {path, kind, candidate, reasons[], evidence{}, fingerprint{}}."""
    g = rules["git"]
    to = float(g.get("git_timeout_s") or 60)
    out: dict[str, Any] = {"path": str(path), "category": "git", "rule": "G", "reasons": [], "evidence": {}}
    reasons: list[str] = out["reasons"]
    ev: dict[str, Any] = out["evidence"]
    if path.is_symlink():
        out.update(kind="symlink", candidate=False)
        reasons.append("symlink")
        return out
    lay = git_layout(path)
    if lay is None:
        out.update(kind="not_git", candidate=False)
        reasons.append("not_git")
        return out
    out["kind"] = lay["kind"]
    out["main_repo"] = str(lay["main_repo"])
    hard = never_touch_reason(path, rules) or protected_reason(path, rules, own_work_tree=True)
    if hard:
        reasons.append(hard)
        out["candidate"] = False
        return out
    rc, url = _git(path, "config", "--get", "remote.origin.url", timeout=to)
    url = url.strip()
    ev["origin"] = re.sub(r"//[^@/]+@", "//", url)  # never record userinfo
    if not url or not any(r.search(url) for r in rules["_owned_res"]):
        reasons.append("not_owned_repo")
        out["candidate"] = False
        return out
    if lay["kind"] == "git_worktree" and (Path(lay["gitdir"]) / "locked").exists():
        reasons.append("worktree_locked")
    use = in_use_by(path, ctx["cwds"])
    if use:
        reasons.append("in_use_cwd")
        ev["in_use_cwd"] = use
    ref = referenced_by(path, ctx["refs"])
    if ref:
        reasons.append("referenced")
        ev["referenced_by"] = ref
    rc, head = _git(path, "rev-parse", "--verify", "-q", "HEAD", timeout=to)
    head = head.strip()
    ev["head"] = head or None
    if rc != 0 or not head:
        reasons.append("no_head")
    rc, status = _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none", timeout=to)
    if rc != 0:
        reasons.append("status_failed")
    elif status.strip():
        lines = status.splitlines()
        ev["status_lines"] = len(lines)
        if any(not ln.startswith("??") for ln in lines):
            reasons.append("dirty")
        if any(ln.startswith("??") for ln in lines):
            reasons.append("untracked")
        ev["status_sample"] = [ln[3:] for ln in lines[:3]]
    if head:
        rc, unpushed = _git(path, "rev-list", "--max-count=1", "HEAD", "--not", "--remotes", timeout=to)
        if rc != 0:
            reasons.append("unpushed_check_failed")
        elif unpushed.strip():
            reasons.append("unpushed_commits")
        if lay["kind"] == "git_clone":
            rc, other = _git(path, "rev-list", "--max-count=1", "--branches", "--not", "--remotes", timeout=to)
            if rc != 0 or other.strip():
                reasons.append("unpushed_local_branch")
            rc, stash = _git(path, "rev-parse", "--verify", "-q", "refs/stash", timeout=to)
            if stash.strip():
                reasons.append("has_stash")
        main_ref = str(g["main_ref"])
        rc, _ = _git(path, "merge-base", "--is-ancestor", "HEAD", main_ref, timeout=to)
        merged = rc == 0
        ev["merged"] = "ancestor" if merged else None
        if not merged:
            rc_u, up = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", timeout=to)
            rc_b, br = _git(path, "symbolic-ref", "-q", "--short", "HEAD", timeout=to)
            upstream_cfg = ""
            if rc_b == 0 and br.strip():
                _, upstream_cfg = _git(path, "config", "--get", f"branch.{br.strip()}.merge", timeout=to)
            gone = bool(upstream_cfg.strip()) and rc_u != 0
            if gone:
                rc_c, cherry = _git(path, "cherry", main_ref, "HEAD", timeout=to)
                if rc_c == 0 and cherry.strip() and all(ln.startswith("-") for ln in cherry.splitlines()):
                    merged = True
                    ev["merged"] = "upstream_gone_patch_equivalent"
        if not merged:
            reasons.append("not_merged")
    rc, ignored = _git(path, "ls-files", "--others", "--ignored", "--exclude-standard", timeout=to)
    if rc == 0:
        hits = []
        lines = ignored.splitlines()
        if len(lines) > int(g.get("ignored_listing_max_lines") or 200000):
            reasons.append("ignored_listing_too_large")
        skip_dirs = list(g.get("ignored_scan_skip_dirs") or [])
        skip_suffixes = tuple(g.get("ignored_scan_skip_suffixes") or ())
        for ln in lines:
            # vendored / generated trees (node_modules/.../token-map.js, .venv/.../cookies.py, bytecode of a TRACKED
            # source file) are not credentials: measured 2026-10-18, they were 100% of the false hits
            parts = Path(ln).parts
            if (skip_suffixes and ln.endswith(skip_suffixes)) or any(
                fnmatch.fnmatch(part, sd) for part in parts[:-1] for sd in skip_dirs
            ):
                continue
            for part in parts:
                if any(fnmatch.fnmatch(part.lower(), gl.lower()) for gl in rules["_never_globs"]):
                    hits.append(ln)
                    break
            if len(hits) >= 5:
                break
        if hits:
            reasons.append("ignored_credential_like")
            ev["ignored_credential_like"] = hits[:5]
        ev["ignored_files"] = len(lines)
    else:
        reasons.append("ignored_listing_failed")
    gitdir = Path(lay["gitdir"])
    # logs/HEAD's MTIME is not activity (a reflog expire / gc rewrites every reflog at once: measured 2026-10-18,
    # 400+ reflogs share one 2026-10-12 22:33 mtime); its newest ENTRY timestamp is.
    activity = max(newest_mtime(path, [gitdir / "HEAD", gitdir / "index"]), last_reflog_ts(gitdir / "logs" / "HEAD"))
    idle_days = (ctx["now"].timestamp() - activity) / 86400.0 if activity else None
    ev["last_activity"] = datetime.fromtimestamp(activity, timezone.utc).isoformat() if activity else None
    ev["idle_days"] = round(idle_days, 2) if idle_days is not None else None
    if idle_days is None or idle_days <= float(g["idle_days"]):
        reasons.append("recent_activity")
    out["fingerprint"] = {"head": head or None, "last_activity": ev["last_activity"], "kind": lay["kind"]}
    out["candidate"] = not reasons
    return out


def discover_git_dirs(rules: Mapping[str, Any]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for root in rules["_git_roots"]:
        base: Path = root["_path"]
        depth = int(root.get("depth") or 1)
        if not base.is_dir():
            continue
        frontier = [base]
        for _ in range(depth):
            nxt = []
            for d in frontier:
                try:
                    entries = sorted(os.scandir(d), key=lambda e: e.name)
                except OSError:
                    continue
                for e in entries:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    p = Path(e.path)
                    if os.path.lexists(p / DOT_GIT):
                        key = os.path.abspath(p)
                        if key not in seen:
                            seen.add(key)
                            out.append(p)
                    else:
                        nxt.append(p)
            frontier = nxt
    return out


# ── releases / caches ──────────────────────────────────────────────────────────────────────────────────────────────


def _sort_key(p: Path, rx: Optional[re.Pattern]) -> tuple[str, float]:
    m = rx.search(p.name) if rx else None
    try:
        mt = os.lstat(p).st_mtime
    except OSError:
        mt = 0.0
    return (m.group(1) if m else "", mt)


def served_release_targets(rules: Mapping[str, Any]) -> dict[str, str]:
    """{realpath: why} for the CURRENT symlink target(s) and every pointer-file target."""
    out: dict[str, str] = {}
    pd = rules.get("_pointer_dir")
    if not pd:
        return out
    for name in rules["releases"].get("pointer_symlinks") or []:
        p = pd / name
        if p.is_symlink() or p.exists():
            out[os.path.realpath(p)] = f"pointer_symlink:{name}"
    for name in rules["releases"].get("pointer_files") or []:
        try:
            text = (pd / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("/"):
                out.setdefault(os.path.realpath(line), f"pointer_file:{name}")
    return out


def evaluate_releases(rules: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    rx_s = rules["releases"].get("sort_key_regex")
    rx = re.compile(rx_s) if rx_s else None
    served = served_release_targets(rules)
    today: date = ctx["now"].date()
    results: list[dict[str, Any]] = []
    for root in rules["_release_roots"]:
        base: Path = root["_path"]
        if not base.is_dir():
            continue
        want_dir = root.get("entry_kind", "dir") == "dir"
        entries = []
        for e in sorted(os.scandir(base), key=lambda e: e.name):
            if e.is_symlink() or not fnmatch.fnmatch(e.name, root.get("glob") or "*"):
                continue
            if want_dir != e.is_dir(follow_symlinks=False):
                continue
            entries.append(Path(e.path))
        entries.sort(key=lambda p: _sort_key(p, rx))
        keep_newest = (
            {os.path.abspath(p) for p in entries[-int(root.get("keep_newest") or 0) :]}
            if int(root.get("keep_newest") or 0)
            else set()
        )
        current_key = None
        for p in entries:
            if served.get(os.path.realpath(p), "").startswith("pointer_symlink"):
                current_key = _sort_key(p, rx)
        previous = None
        if root.get("previous_served") and current_key is not None:
            older = [p for p in entries if _sort_key(p, rx) < current_key]
            previous = os.path.abspath(older[-1]) if older else None
        hold = root.get("hold_until")
        for p in entries:
            reasons: list[str] = []
            r = {
                "path": str(p),
                "kind": "release_dir" if want_dir else "release_file",
                "category": "releases",
                "rule": "R",
                "reasons": reasons,
                "evidence": {"root": str(base)},
            }
            hard = never_touch_reason(p, rules) or protected_reason(p, rules)
            if hard:
                reasons.append(hard)
            if os.path.realpath(p) in served:
                reasons.append(served[os.path.realpath(p)])
            if previous and os.path.abspath(p) == previous:
                reasons.append("previous_served")
            if os.path.abspath(p) in keep_newest:
                reasons.append("keep_newest")
            if hold and today < date.fromisoformat(str(hold)):
                reasons.append(f"hold_until:{hold}")
                r["evidence"]["hold_reason"] = root.get("hold_reason")
            use = in_use_by(p, ctx["cwds"]) if want_dir else None
            if use:
                reasons.append("in_use_cwd")
            ref = referenced_by(p, ctx["refs"])
            if ref:
                reasons.append("referenced")
                r["evidence"]["referenced_by"] = ref
            try:
                mt = os.lstat(p).st_mtime
            except OSError:
                mt = 0.0
            r["fingerprint"] = {"mtime": mt, "kind": r["kind"]}
            r["candidate"] = not reasons
            results.append(r)
    return results


def evaluate_caches(rules: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for c in rules["_cache_rules"]:
        if not c.get("enabled"):
            continue
        base: Path = c["_path"]
        if not base.is_dir():
            continue
        frontier = [base]
        for _ in range(int(c.get("item_depth") or 1)):
            nxt = []
            for d in frontier:
                try:
                    nxt.extend(Path(e.path) for e in os.scandir(d) if not e.is_symlink())
                except OSError:
                    continue
            frontier = nxt
        cutoff = ctx["now"].timestamp() - float(c["older_than_days"]) * 86400.0
        for p in sorted(frontier):
            reasons: list[str] = []
            hard = None
            # cache roots themselves are report_only; entries below them are judged by the never-touch names/globs
            for part in p.relative_to(base).parts:
                if part in rules["_never_names"] or any(
                    fnmatch.fnmatch(part.lower(), g.lower()) for g in rules["_never_globs"]
                ):
                    hard = f"never_touch_name:{part}"
            if hard:
                reasons.append(hard)
            mt = _newest_tree_mtime(p)
            if mt > cutoff:
                reasons.append("recent_activity")
            r = {
                "path": str(p),
                "kind": "cache_entry",
                "category": "cache",
                "rule": "C",
                "reasons": reasons,
                "evidence": {"cache_root": str(base), "newest_mtime": mt},
                "fingerprint": {"mtime": mt, "kind": "cache_entry"},
                "candidate": not reasons,
            }
            results.append(r)
    return results


def _newest_tree_mtime(p: Path) -> float:
    best = 0.0
    try:
        best = os.lstat(p).st_mtime
    except OSError:
        return best
    if p.is_dir() and not p.is_symlink():
        for dirpath, dirnames, filenames in os.walk(p):
            for n in dirnames + filenames:
                try:
                    best = max(best, os.lstat(os.path.join(dirpath, n)).st_mtime)
                except OSError:
                    continue
    return best


# ── plan ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def build_context(rules: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    return {"now": now, "cwds": process_cwds(rules["_proc_root"]), "refs": reference_texts(rules)}


def _item_id(path: str) -> str:
    return "dh-" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def plan(rules: Mapping[str, Any], now: datetime, *, measure: bool = True) -> dict[str, Any]:
    """Evaluate every rule; returns the manifest document (nothing written, nothing deleted)."""
    home: Path = rules["_home"]
    if not home.is_dir():
        raise RulesError("home_unreadable")
    ctx = build_context(rules, now)
    results = [evaluate_git(p, rules, ctx) for p in discover_git_dirs(rules)]
    results += evaluate_releases(rules, ctx)
    results += evaluate_caches(rules, ctx)
    results = [r for r in results if r.get("kind") not in ("not_git",)]
    report_only = [
        {"path": str(r["_path"]), "category": r.get("category"), "why": r.get("why")}
        for r in rules["_report_only"]
        if r["_path"].exists()
    ]
    if measure:
        to = float(rules["git"].get("size_timeout_s") or 600)
        workers = max(1, int(rules["git"].get("size_workers") or 4))
        targets = [Path(r["path"]) for r in results] + [Path(r["path"]) for r in report_only]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            sizes = dict(zip(map(str, targets), pool.map(lambda p: du_bytes(p, to), targets)))
        for r in results + report_only:
            r["size_bytes"] = sizes.get(r["path"])
    for r in results:
        r["id"] = _item_id(r["path"])
    items = [r for r in results if r.get("candidate")]
    excluded = [r for r in results if not r.get("candidate")]
    return {
        "schema": MANIFEST_SCHEMA,
        "generated_at": now.isoformat(),
        "host": socket.gethostname(),
        "home": str(home),
        "rules_path": rules["_path"],
        "rules_sha256": rules["_sha256"],
        "mode": "plan",
        "reference_sources": sorted({s.split(":", 1)[0] for s, _ in ctx["refs"]}),
        "process_cwds": len(ctx["cwds"]),
        "items": items,
        "excluded": excluded,
        "report_only": report_only,
        "totals": totals(items, excluded, report_only),
    }


def _gb(n: Optional[int]) -> float:
    return round((n or 0) / 1024**3, 2)


def totals(items: list, excluded: list, report_only: list) -> dict[str, Any]:
    by_kind: dict[str, dict[str, Any]] = {}
    for r in items:
        k = by_kind.setdefault(f"{r['rule']}:{r['kind']}", {"count": 0, "bytes": 0})
        k["count"] += 1
        k["bytes"] += r.get("size_bytes") or 0
    by_reason: dict[str, dict[str, Any]] = {}
    for r in excluded:
        for reason in sorted({x.split(":", 1)[0] for x in r["reasons"]}):
            k = by_reason.setdefault(reason, {"count": 0, "bytes": 0})
            k["count"] += 1
            k["bytes"] += r.get("size_bytes") or 0
    return {
        "candidates": len(items),
        "reclaimable_bytes": sum(r.get("size_bytes") or 0 for r in items),
        "reclaimable_gb": _gb(sum(r.get("size_bytes") or 0 for r in items)),
        "unmeasured_candidates": sum(1 for r in items if r.get("size_bytes") is None),
        "by_kind": by_kind,
        "excluded": len(excluded),
        "excluded_bytes": sum(r.get("size_bytes") or 0 for r in excluded),
        "excluded_by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1]["bytes"])),
        "report_only": {r["path"]: r.get("size_bytes") for r in report_only},
    }


def human_summary(m: Mapping[str, Any], top_n: int) -> str:
    t = m["totals"]
    lines = [
        f"disk_hygiene plan  generated_at {m['generated_at']}  host {m['host']}  home {m['home']}",
        f"rules {m['rules_path']} sha256 {m['rules_sha256'][:12]}  references {','.join(m['reference_sources'])}"
        f"  process cwds {m['process_cwds']}",
        "",
        f"CANDIDATES {t['candidates']}  reclaimable {t['reclaimable_gb']} GB"
        f"  (unmeasured {t['unmeasured_candidates']})",
    ]
    for k, v in sorted(t["by_kind"].items()):
        lines.append(f"  {k:<28} {v['count']:>5}  {_gb(v['bytes']):>8.2f} GB")
    lines += ["", f"LARGEST {top_n} CANDIDATES"]
    for r in sorted(m["items"], key=lambda r: -(r.get("size_bytes") or 0))[:top_n]:
        ev = r.get("evidence") or {}
        lines.append(
            f"  {_gb(r.get('size_bytes')):>7.2f} GB  {r['kind']:<13} {r['path']}"
            f"  idle {ev.get('idle_days')}d merged {ev.get('merged')}"
        )
    lines += [
        "",
        f"EXCLUDED {t['excluded']}  ({_gb(t['excluded_bytes'])} GB) by reason"
        " (an entry with several reasons counts under each)",
    ]
    for k, v in t["excluded_by_reason"].items():
        lines.append(f"  {k:<32} {v['count']:>5}  {_gb(v['bytes']):>8.2f} GB")
    only: dict[str, dict[str, Any]] = {}
    for r in m["excluded"]:
        if len(r["reasons"]) == 1:
            k = only.setdefault(r["reasons"][0].split(":", 1)[0], {"count": 0, "bytes": 0})
            k["count"] += 1
            k["bytes"] += r.get("size_bytes") or 0
    lines += ["", "EXCLUDED BY A SINGLE REASON (what one fix would release)"]
    for k, v in sorted(only.items(), key=lambda kv: -kv[1]["bytes"]):
        lines.append(f"  {k:<32} {v['count']:>5}  {_gb(v['bytes']):>8.2f} GB")
    blockers: dict[str, int] = {}
    for r in m["excluded"]:
        for s in (r.get("evidence") or {}).get("status_sample") or []:
            blockers[s] = blockers.get(s, 0) + 1
    lines += ["", "MOST COMMON DIRTY / UNTRACKED PATHS (first 3 status lines per tree)"]
    for s, n in sorted(blockers.items(), key=lambda kv: -kv[1])[:10]:
        lines.append(f"  {n:>5}  {s}")
    lines += ["", "REPORT ONLY (never deleted)"]
    for p, b in t["report_only"].items():
        lines.append(f"  {_gb(b):>8.2f} GB  {p}")
    return "\n".join(lines) + "\n"


def manifest_dir(rules: Mapping[str, Any], state_root: Optional[Path]) -> Path:
    return R.runtime_dir(state_root).parent.parent / rules["manifest"]["dir"]


def write_manifest(m: Mapping[str, Any], rules: Mapping[str, Any], state_root: Optional[Path]) -> Path:
    from scripts.lib.atomic_json_store import atomic_write_json

    d = manifest_dir(rules, state_root)
    stamp = datetime.fromisoformat(m["generated_at"]).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"disk_hygiene_manifest_{stamp}.json"
    atomic_write_json(path, m, indent=1)
    atomic_write_json(d / rules["manifest"]["latest_name"], m, indent=1)
    return path


def lane_output(m: Optional[Mapping[str, Any]], written: bool) -> dict[str, Any]:
    if m is None or not written:
        return {
            "produced_count": 0,
            "attempted_count": 0,
            "skipped_reasons": {SKIP_DEPENDENCY: 1},
            "empty_reason": None,
        }
    t = m["totals"]
    return {
        "produced_count": 1,
        "attempted_count": 1,
        "skipped_reasons": {},
        "empty_reason": None,
        "output_evidence": [
            {
                "kind": "file",
                "candidates": t["candidates"],
                "reclaimable_bytes": t["reclaimable_bytes"],
                "excluded": t["excluded"],
            }
        ],
    }


# ── apply ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def revalidate(item: Mapping[str, Any], rules: Mapping[str, Any], ctx: Mapping[str, Any]) -> tuple[bool, str]:
    """Re-run the item's rule NOW; (ok, why). Anything different from the manifest -> skip."""
    p = Path(item["path"])
    if not os.path.lexists(p):
        return False, "gone"
    if p.is_symlink():
        return False, "now_symlink"
    hard = never_touch_reason(p, rules) or protected_reason(
        p, rules, own_work_tree=item.get("kind") in ("git_worktree", "git_clone")
    )
    if hard:
        return False, hard
    kind = item.get("kind")
    if kind not in set(rules["apply"]["kinds_enabled"]):
        return False, f"kind_disabled:{kind}"
    if kind in ("git_worktree", "git_clone"):
        fresh = evaluate_git(p, rules, ctx)
    elif kind in ("release_dir", "release_file"):
        fresh = next((r for r in evaluate_releases(rules, ctx) if r["path"] == item["path"]), None)
    elif kind == "cache_entry":
        fresh = next((r for r in evaluate_caches(rules, ctx) if r["path"] == item["path"]), None)
    else:
        return False, f"unknown_kind:{kind}"
    if fresh is None:
        return False, "no_longer_listed"
    if not fresh.get("candidate"):
        return False, "rule_now_fails:" + ",".join(fresh.get("reasons") or [])
    if fresh.get("fingerprint") != item.get("fingerprint"):
        return False, "changed_since_manifest"
    return True, "ok"


def remove_item(item: Mapping[str, Any]) -> tuple[bool, str]:
    p = Path(item["path"])
    kind = item["kind"]
    if kind == "git_worktree":
        rc, _ = _git(Path(item["main_repo"]), "worktree", "remove", str(p), timeout=600)
        if rc != 0 or os.path.lexists(p):
            return False, f"git_worktree_remove_rc:{rc}"
        return True, "git worktree remove"
    if kind in ("git_clone", "release_dir", "cache_entry"):
        if p.is_symlink() or not p.is_dir():
            return False, "not_a_dir"
        shutil.rmtree(p)
        return True, "rmtree"
    if kind == "release_file":
        if p.is_symlink() or not p.is_file():
            return False, "not_a_file"
        p.unlink()
        return True, "unlink"
    return False, f"unknown_kind:{kind}"


def apply(
    manifest_path: Path, rules: Mapping[str, Any], now: datetime, *, grant: Optional[str], run_id: Optional[str]
) -> dict[str, Any]:
    """Return a hold; ACTIVE policy supplies no destructive maintenance authority.

    Keep the call signature for existing readers. A caller token, including a
    real grant for an unrelated action, cannot enable this operation.
    """
    return {
        "schema": APPLY_SCHEMA,
        "started_at": now.isoformat(),
        "manifest": str(manifest_path),
        "removed": [],
        "skipped": [],
        "refused": "n8n_executor_never_applies" if run_id else "destructive_apply_unsupported_by_active_policy",
    }


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        return None
    return d if d.tzinfo else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--plan", action="store_true", help="the default: write the manifest + receipt, delete nothing")
    g.add_argument("--dry-run", action="store_true", help="print the plan only; writes nothing at all")
    g.add_argument(
        "--apply", action="store_true", help="unsupported under ACTIVE policy; always refuses without effects"
    )
    ap.add_argument("--report", action="store_true", help="also print the human summary")
    ap.add_argument("--manifest", help="--apply: manifest path (default: the latest)")
    ap.add_argument("--rules", help="rules file (default config/disk_hygiene_rules.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / resolver)")
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: aware ISO 8601
    ap.add_argument("--no-measure", action="store_true", help=argparse.SUPPRESS)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if a.apply:
        print(json.dumps({"mode": "apply", "ok": False, "refused": "destructive_apply_unsupported_by_active_policy"}))
        return 1
    wall_start = datetime.now(timezone.utc)  # receipt started_at: the real start, not the injectable logical clock
    now = _parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    state_root = Path(a.state_root) if a.state_root else None
    try:
        rules = load_rules(Path(a.rules) if a.rules else None, home=Path(a.home) if a.home else None)
    except RulesError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        if not a.dry_run and not a.apply:
            R.write_lane_receipt(
                LANE_ID,
                ok=False,
                exit_code=1,
                started_at=wall_start,
                script=SCRIPT,
                summary={"error": str(exc)},
                path=R.receipt_path(LANE_ID, state_root),
                output=lane_output(None, False),
            )
        return 1

    try:
        m = plan(rules, now, measure=not a.no_measure)
    except RulesError as exc:
        m, err = None, str(exc)
    else:
        err = None
    if a.dry_run:
        if m is None:
            print(json.dumps({"dry_run": True, "ok": False, "error": err}))
            return 1
        R.dry_run_report(
            LANE_ID,
            {"totals": m["totals"]},
            would_write=[str(manifest_dir(rules, state_root))],
            receipt=R.receipt_path(LANE_ID, state_root),
        )
        if a.report:
            print(human_summary(m, int(rules["manifest"].get("top_n") or 20)))
        return 0
    path = None
    if m is not None:
        try:
            path = write_manifest(m, rules, state_root)
        except OSError as exc:
            err = f"manifest_write_failed:{type(exc).__name__}"
    ok = path is not None
    summary = {"manifest": str(path) if path else None, "error": err}
    if m is not None:
        summary.update(
            {
                "candidates": m["totals"]["candidates"],
                "reclaimable_bytes": m["totals"]["reclaimable_bytes"],
                "excluded": m["totals"]["excluded"],
            }
        )
    written = R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=wall_start,
        script=SCRIPT,
        summary=summary,
        error=err,
        path=R.receipt_path(LANE_ID, state_root),
        output=lane_output(m, ok),
    )
    print(json.dumps({"mode": "plan", "ok": ok, "receipt": str(written) if written else None, **summary}))
    if a.report and m is not None:
        print(human_summary(m, int(rules["manifest"].get("top_n") or 20)))
    return 0 if ok and written else 1


if __name__ == "__main__":
    raise SystemExit(main())
