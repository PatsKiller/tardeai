#!/usr/bin/env python3
"""disk_hygiene.py — repeatable, rule-based disk reclaim plan (and an operator-gated apply).

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
  NEVER-TOUCH (enforced here, before every rule and again at apply time): db_backups, persistent-state,
     llama-cpp-vulkan (report only), .ssh, .config, docker / n8n volumes, and any .env / credential / cookie /
     token path.

MODES
    python3 scripts/disk_hygiene.py                     # plan (default): manifest JSON + LaneRunReceipt, deletes nothing
    python3 scripts/disk_hygiene.py --dry-run           # print the plan only: no manifest, no receipt, no write at all
    python3 scripts/disk_hygiene.py --report            # plan + a human summary on stdout
    TRADEAI_DISK_HYGIENE_GRANT=<grant id> python3 scripts/disk_hygiene.py --apply [--manifest PATH]

``--apply`` requires a manifest written within apply.manifest_max_age_hours, a non-empty TRADEAI_DISK_HYGIENE_GRANT,
re-validates every item at apply time (skips it if ANYTHING changed: HEAD, activity mtime, a rule outcome), and
stops at apply.max_items_per_run / apply.max_bytes_per_run. The default path refuses the n8n executor.
The optional --standing path requires separately reviewed, enabled A/S/W rules, complete fresh evidence,
a <=2h manifest bound to exact rules/file SHA, and a hard 40GiB ceiling. Its config/admission remains an
operator-applied proposal; --standing --dry-run with offline evidence never collects live facts or deletes.
Manual --apply still requires its per-run grant. No configuration is enabled by this source change.

Exit: 0 = plan written (or dry run printed, or apply finished within caps); 1 = rules / home unreadable, a write
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
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_last_receipt as R  # noqa: E402
from scripts.lib import disk_hygiene_retention as SR  # noqa: E402

LANE_ID = "disk-hygiene"
APPLY_LANE_ID = "disk-hygiene-apply"
SCRIPT = "scripts/disk_hygiene.py"
RULES_PATH = ROOT / "config" / "disk_hygiene_rules.json"
RULES_SCHEMA = "DiskHygieneRules@v1"
MANIFEST_SCHEMA = "DiskHygieneManifest@v1"
APPLY_SCHEMA = "DiskHygieneApplyReport@v1"
#: Fixed in code (not config) so the n8n env allowlist inventory stays a literal, statically checked read.
GRANT_ENV = "TRADEAI_DISK_HYGIENE_GRANT"
#: Executor request identity; default --apply refuses it, separately reviewed --standing may admit it.
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
    standing = doc.get("standing_apply")
    if standing is not None:
        if not isinstance(standing, dict) or not isinstance(standing.get("enabled"), bool) or not isinstance(standing.get("rules"), list) or any(not isinstance(r, str) or r not in SR.RULE_KINDS for r in standing["rules"]) or len(set(standing["rules"])) != len(standing["rules"]):
            raise RulesError("standing_rules_shape")
        gb = standing.get("max_gb_per_run")
        if type(gb) not in (int, float) or not 0 < gb <= 40 or standing.get("byte_unit") != "GiB":
            raise RulesError("standing_cap_units")
        byte_cap = standing.get("max_bytes_per_run")
        if type(byte_cap) is not int or not 0 < byte_cap <= int(gb * 1024**3):
            raise RulesError("standing_byte_cap")
        if not isinstance(standing.get("approval"), dict) or not isinstance(standing.get("archive"), dict):
            raise RulesError("standing_rules_shape")
        if standing["approval"].get("status") == "APPROVED" and SR.aware(standing["approval"].get("approved_at")) is None:
            raise RulesError("standing_approval_timestamp")
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
    if proc.returncode != 0:
        return None  # du can print a partial total while failing on unreadable entries.
    try:
        measured = int(proc.stdout.split()[0])
        return measured if measured >= 0 else None
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


_UNIT_SUFFIXES = (".service", ".timer", ".path", ".socket", ".target", ".mount", ".slice", ".scope")
_UNIT_NAME = re.compile(r"^[A-Za-z0-9:_.@\\-]+$")


def _dropin_unit(path: Path) -> Optional[str]:
    """`<unit>.d` drop-in directory name → unit name, else None (only these may be sealed)."""
    name = path.name
    if not name.endswith(".d"):
        return None
    unit = name[:-2]
    return unit if unit.endswith(_UNIT_SUFFIXES) and _UNIT_NAME.match(unit) else None


def _sealed_dropin_evidence(path: Path, root: Path, home: Path, runner) -> dict:
    """Text for an unlistable drop-in directory, from the unit systemd actually loaded.

    `systemctl show` is a read-only manager query; it never starts, reloads or enables.
    It is admitted only when the manager proves the on-disk drop-ins equal what it
    loaded (NeedDaemonReload=no, LoadState=loaded) and every drop-in it loaded from
    this directory is a `.conf` file directly inside it. Anything else fails closed.
    """
    unit = _dropin_unit(path)
    scope = ["--user"] if root == home or home in root.parents else []
    command = ["systemctl", *scope, "show", "--no-pager", unit]
    proc = runner(command, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError("sealed_dropin_unreadable:" + str(path))
    props = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key not in props:
            props[key] = value
    if props.get("LoadState") != "loaded" or props.get("NeedDaemonReload") != "no":
        raise ValueError("sealed_dropin_not_loaded_or_stale:" + str(path))
    loaded = [Path(p) for p in (props.get("DropInPaths") or "").split()]
    if not any(p.parent == path for p in loaded):
        # An unreadable directory with nothing loaded from it is not provably empty.
        raise ValueError("sealed_dropin_not_loaded:" + str(path))
    if any(p.parent == path and p.suffix != ".conf" for p in loaded):
        raise ValueError("sealed_dropin_unexpected:" + str(path))
    return {"path": str(path), "text": proc.stdout, "source": "systemctl_show_loaded_unit", "unit": unit,
            "command": command}


def _process_exited(process: Path) -> bool:
    try:
        status = (process / "status").read_text(errors="replace")
    except FileNotFoundError:
        return not process.exists()
    state = next((line.split(":", 1)[1].split() for line in status.splitlines() if line.startswith("State:")), [])
    return bool(state) and state[0] in ("Z", "X")


def _opaque_process(process: Path) -> Optional[dict]:
    """Identity of a process whose references this user cannot read; None if it exited."""
    try:
        status = (process / "status").read_text(errors="replace")
    except FileNotFoundError:
        if process.exists():
            raise ValueError("process_reference_unknown")
        return None
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    uids = (fields.get("Uid") or "").split()
    if len(uids) < 2 or not all(u.isdigit() for u in uids):
        raise ValueError("process_identity_unknown")
    return {"pid": process.name, "opaque": True, "uid": int(uids[1]), "own_uid": int(uids[1]) == os.geteuid(),
            "comm": (fields.get("Name") or "").strip()[:64]}


def collect_standing_evidence(rules: Mapping[str, Any], now: datetime, *, github=None, runner=None) -> dict:
    """Fresh per-run READ-ONLY collection; unavailable evidence never becomes absence.

    Native runs use the sanctioned GitHub GET reader and local coordination files.
    Tests inject runner/reader and fixture proc/unit/coord roots. No grant, secret,
    schedule write, model or sender is involved. A refusal is not retried here.
    """
    runner = runner or subprocess.run
    doc = {"schema": SR.SCHEMA, "offline": False, "sources": {}}
    cfg = rules.get("standing_apply") or {}

    def capture(key, fn):
        try:
            data = fn()
            entry = {"complete": True, "captured_at": now.isoformat(), "data": data, "sha256": SR.digest(data)}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            entry = {"complete": False, "captured_at": now.isoformat(), "reason": key + "_unavailable",
                     "detail": (type(exc).__name__ + ":" + str(exc))[:300]}
        doc["sources"][key] = entry

    def cron():
        command = rules["references"].get("crontab_cmd")
        if command != ["crontab", "-l"]:
            raise ValueError("read_only_cron_command_required")
        proc = runner(command, capture_output=True, text=True, timeout=30)
        # crontab exit1 is ambiguous (no crontab vs refused access); never infer empty.
        if proc.returncode != 0:
            raise ValueError("cron_read_unavailable")
        return proc.stdout

    def units():
        out = []
        for root in rules["_unit_dirs"]:
            if not root.exists():
                continue
            sealed: list[Path] = []

            def walk_error(exc, root=root, sealed=sealed):
                # A root-owned 0700 drop-in directory (e.g. /etc/systemd/system/<unit>.d) cannot be
                # listed by this user. Its text is still known exactly from the loaded unit; any
                # other walk error stays fatal (unknown references never prove absence).
                path = Path(getattr(exc, "filename", "") or "")
                if isinstance(exc, PermissionError) and path != root and _dropin_unit(path):
                    sealed.append(path)
                    return
                raise exc

            for parent, _, names in os.walk(root, onerror=walk_error):
                for name in names:
                    path = Path(parent) / name
                    if path.suffix in (".service", ".timer", ".conf", ".path", ".socket", ".target"):
                        out.append({"path": str(path), "text": path.read_text()})
            for path in sealed:
                out.append(_sealed_dropin_evidence(path, root, rules["_home"], runner))
        return out

    def processes():
        out = []
        for process in rules["_proc_root"].iterdir():
            if not process.name.isdigit():
                continue
            cwd = None
            try:
                cwd = os.readlink(process / "cwd")
                fds = []
                for fd in (process / "fd").iterdir():
                    try:
                        target = os.readlink(fd)
                        if target.startswith("/"):
                            fds.append(target)
                    except FileNotFoundError:
                        pass  # a closed fd is no longer a live reference
                out.append({"pid": process.name, "cwd": cwd, "fds": fds})
            except FileNotFoundError:
                # Only disappearance of the PROCESS itself, or a zombie (exited, awaiting its
                # parent's wait(); the kernel has already released its cwd and every fd), proves it exited.
                if process.exists() and not _process_exited(process):
                    raise ValueError("process_reference_unknown")
            except PermissionError:
                # Another user's (or a non-dumpable) process: the kernel denies cwd/fd reads to this
                # user. It is recorded as OPAQUE, never as "no references": a preview lists it, and
                # apply refuses while any opaque process exists (SR.evidence_context applying=True).
                opaque = _opaque_process(process)
                if opaque is not None:
                    out.append(opaque | ({"cwd": cwd} if cwd else {}))
        return out

    def coordination():
        base = _expand(str(cfg.get("coordination_root") or "~/trade-ai-releases/persistent-state/data/coordination"), rules["_home"])
        claims_dir, worklogs = base / "claims", base / "worklogs"
        if not claims_dir.is_dir() or not worklogs.is_dir() or not (base / "handoffs" / "PROGRESS_LOG.md").is_file():
            raise ValueError("coordination_incomplete")
        live, active_ids, refs, live_logs = [], set(), [], []
        files = list(base.rglob("*.json")) + list(base.rglob("*.jsonl")) + list(base.rglob("*.md"))
        total = 0
        for path in files:
            if path.is_symlink():
                raise ValueError("coordination_symlink")
            size = path.stat().st_size
            total += size
            if size > 32 * 1024**2 or total > 128 * 1024**2:
                raise ValueError("coordination_scan_limit")
            text = path.read_text()
            refs += re.findall(r"/[^\s\"'`<>|=,;)\]}]+", text)
            if path.parent == claims_dir and path.suffix == ".json":
                claim = json.loads(text)
                if not isinstance(claim, dict) or claim.get("schema") != "AgentClaim@v1":
                    raise ValueError("claim_unreadable")
                if claim.get("status") == "active":
                    live.append(claim)
                    active_ids.add(claim.get("claim_id"))
        for path in worklogs.rglob("*.md"):
            if any(str(cid) in path.name for cid in active_ids) or now.timestamp() - path.stat().st_mtime <= 48 * 3600:
                live_logs += re.findall(r"/[^\s\"'`<>|=,;)\]}]+", path.read_text())
        return {"references": sorted(set(refs)), "live_claims": live, "live_worklogs": live_logs}

    def prs():
        reader = github
        if reader is None:
            from scripts.lib.agent_claim_lifecycle import GitHubReader
            reader = GitHubReader(repo=str(cfg.get("github_repo") or "PatsKiller/tardeai"), timeout_s=30)
        out = []
        for page in range(1, 21):
            rows, warning = reader.get(f"repos/{reader.repo}/pulls?state=open&per_page=100&page={page}")
            if warning or not isinstance(rows, list):
                raise ValueError("github_pr_state_unavailable")
            for row in rows:
                if not isinstance(row, dict) or row.get("state") != "open" or not isinstance(row.get("head"), dict) or not row["head"].get("ref"):
                    raise ValueError("github_pr_state_invalid")
                out.append({"number": row.get("number"), "branch": row["head"]["ref"], "state": "open"})
            if len(rows) < 100:
                return out
        raise ValueError("github_pr_page_limit")

    def pointers():
        base = rules.get("_pointer_dir")
        if base is None or not base.is_dir():
            raise ValueError("pointer_root_unavailable")
        out = []
        for name in rules["releases"].get("pointer_files", []) + rules["releases"].get("pointer_symlinks", []):
            path = base / name
            if path.is_symlink():
                out.append({"path": str(path), "target": os.path.realpath(path)})
            elif path.exists():
                out.append({"path": str(path), "text": path.read_text()})
        if not out:
            raise ValueError("release_pointers_unknown")
        return out

    for key, fn in (("cron", cron), ("units", units), ("processes", processes), ("coordination", coordination), ("prs", prs), ("pointers", pointers)):
        capture(key, fn)
    return doc


def standing_hard_reason(path: Path, kind: str, rules: Mapping[str, Any]) -> Optional[str]:
    """The only backup exception: a direct archived dump, never a directory/live dump.

    Keep all other secret/state/model protections. The reviewed configuration must
    name exactly this archive root; no configurable arbitrary never-touch bypass.
    """
    archive = rules["_home"] / "db_backups" / "archive"
    if kind != "archived_dump":
        return never_touch_reason(path, rules)
    configured = _expand(str((rules.get("standing_apply") or {}).get("archive", {}).get("path", "")), rules["_home"])
    if configured != archive or path.parent != archive or not path.is_file() or path.is_symlink():
        return "archive_exception_scope"
    if any(p.is_symlink() for p in (archive, archive.parent)) or path.resolve().parent != archive:
        return "archive_exception_symlink"
    narrowed = dict(rules)
    narrowed["_never_paths"] = [p for p in rules["_never_paths"] if p != archive.parent]
    narrowed["_never_names"] = set(rules["_never_names"]) - {"db_backups"}
    return never_touch_reason(path, narrowed)


def standing_results(rules: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict]:
    """Only A/S/W, with fresh complete coordination/process/PR references."""
    cfg = rules.get("standing_apply")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("rules"), list) or any(not isinstance(r, str) or r not in SR.RULE_KINDS for r in cfg["rules"]) or len(set(cfg["rules"])) != len(cfg["rules"]):
        raise RulesError("standing_rules_unconfigured")
    results = []

    def row(path: Path, rule: str, kind: str) -> dict:
        reasons = []
        if rule not in cfg["rules"]:
            reasons.append("rule_plan_only_not_authorized:" + rule)
        hard = standing_hard_reason(path, kind, rules) or protected_reason(path, rules, own_work_tree=kind == "git_worktree")
        if hard:
            reasons.append(hard)
        if path.is_symlink():
            reasons.append("symlink")
        reference = referenced_by(path, SR.record_refs(ctx, kind))
        if reference:
            reasons.append("referenced:" + reference)
        return {"path": str(path), "rule": rule, "kind": kind, "category": "standing", "reasons": reasons, "evidence": {}}

    archive = rules["_home"] / "db_backups" / "archive"
    files = []
    if archive.exists():
        if archive.is_symlink() or archive.parent.is_symlink():
            raise RulesError("archive_root_symlink")
        try:
            paths = sorted(archive.iterdir())
        except OSError as exc:
            raise RulesError("archive_unreadable") from exc
        for path in paths:
            item = row(path, "A", "archived_dump")
            if not fnmatch.fnmatch(path.name, "trade_ai_*.sql.gz") or not path.is_file() or re.search(r"(^|[._-])(part|partial|incomplete|hold)([._-]|$)", path.name, re.I):
                item["reasons"].append("not_completed_dump")
            try:
                st = path.lstat()
                item["fingerprint"] = {"mtime_ns": st.st_mtime_ns, "size": st.st_size, "inode": st.st_ino}
                item["evidence"] = {"mtime": st.st_mtime, "date_basis": "original_file_mtime_ET"}
                age = ctx["now"].timestamp() - st.st_mtime
                if age < 7200 or st.st_size <= 0:
                    item["reasons"].append("young_or_incomplete_dump")
                if st.st_nlink != 1:
                    item["reasons"].append("multiple_hardlinks")
            except OSError:
                item["reasons"].append("stat_unreadable")
            if not item["reasons"]:
                files.append({"path": str(path), "mtime": item["evidence"]["mtime"]})
            results.append(item)
        keep = SR.retention_days(files)
        for item in results:
            if item["path"] in keep:
                item["reasons"].append("daily_or_sunday_recovery_point")

    scratch = rules["_home"] / ".cache" / "rtc"
    if scratch.exists():
        if scratch.is_symlink():
            raise RulesError("rtc_root_symlink")
        try:
            paths = sorted(scratch.iterdir())
        except OSError as exc:
            raise RulesError("rtc_unreadable") from exc
        for path in paths:
            item = row(path, "S", "rtc_scratch")
            if not path.is_dir() or path.is_symlink():
                item["reasons"].append("not_scratch_directory")
            activity, why = SR.activity(path, protected=lambda p: p.name == DOT_GIT or p.is_symlink() or bool(never_touch_reason(p, rules)))
            if why:
                item["reasons"].append(why)
            if activity is None or ctx["now"].timestamp() - activity <= 7 * 86400:
                item["reasons"].append("scratch_not_older_than_7_days")
            item["fingerprint"] = {"activity": activity, "kind": "rtc_scratch"}
            results.append(item)

    agent_tmp = rules["_home"] / ".cache" / "agent-tmp"
    if agent_tmp.exists():
        if agent_tmp.is_symlink():
            raise RulesError("agent_tmp_root_symlink")
        try:
            paths = sorted(agent_tmp.iterdir())
        except OSError as exc:
            raise RulesError("agent_tmp_unreadable") from exc
        for path in paths:
            item = row(path, "T", "agent_scratch")
            if not path.is_dir() or path.is_symlink():
                item["reasons"].append("not_scratch_directory")
            activity, why = SR.activity(path, protected=lambda p: p.name == DOT_GIT or p.is_symlink() or bool(never_touch_reason(p, rules)))
            if why:
                item["reasons"].append(why)
            if activity is None or ctx["now"].timestamp() - activity <= 2 * 86400:
                item["reasons"].append("scratch_not_older_than_2_days")
            item["fingerprint"] = {"activity": activity, "kind": "agent_scratch"}
            results.append(item)

    for path in discover_git_dirs(rules):
        lay = git_layout(path)
        if not lay or lay["kind"] != "git_worktree":
            continue  # standing approval never removes standalone clones or their refs
        original = evaluate_git(path, rules, ctx)
        item = row(path, "W", "git_worktree")
        item["main_repo"] = original.get("main_repo")
        item["evidence"].update(original.get("evidence") or {})
        item["reasons"] += [r for r in original["reasons"] if r not in ("unpushed_commits", "not_merged", "recent_activity")]
        rc, branch = _git(path, "symbolic-ref", "-q", "HEAD")
        branch = branch.strip() if rc == 0 else None
        head = (original.get("fingerprint") or {}).get("head")
        if branch:
            brc, branch_head = _git(Path(lay["main_repo"]), "rev-parse", "--verify", branch)
            if not branch.startswith("refs/heads/") or brc != 0 or branch_head.strip() != head:
                item["reasons"].append("named_branch_not_preserved")
            if branch in json.dumps(ctx["snapshot"]["prs"]) or branch.removeprefix("refs/heads/") in json.dumps(ctx["snapshot"]["prs"]):
                item["reasons"].append("open_pr_branch")
        elif item["evidence"].get("merged") != "ancestor":
            item["reasons"].append("detached_not_ancestor")
        activity, why = SR.activity(path)
        git_activity, git_why = SR.activity(Path(lay["gitdir"]))
        activity = max(activity or 0, git_activity or 0)
        if git_why:
            item["reasons"].append(git_why)
        if why:
            item["reasons"].append(why)
        if not activity or ctx["now"].timestamp() - activity <= 48 * 3600:
            item["reasons"].append("worktree_not_untouched_48h")
        item["evidence"].update(branch=branch, branch_preserved=bool(branch), detached_ancestor=not branch and item["evidence"].get("merged") == "ancestor")
        item["fingerprint"] = {"head": head, "branch": branch, "activity": activity, "kind": "git_worktree"}
        results.append(item)
    for item in results:
        item["candidate"] = not item["reasons"]
        item["id"] = _item_id(item["path"])
    return results


def standing_plan(rules: Mapping[str, Any], now: datetime, evidence: Mapping, *, measure: bool = True) -> dict:
    try:
        ctx = SR.evidence_context(evidence, now)
    except ValueError as exc:
        raise RulesError(str(exc)) from exc
    rows = standing_results(rules, ctx)
    if measure:
        for item in rows:
            item["size_bytes"] = du_bytes(Path(item["path"]), 60)
    items, excluded = [r for r in rows if r["candidate"]], [r for r in rows if not r["candidate"]]
    return {"schema": MANIFEST_SCHEMA, "generated_at": now.isoformat(), "host": socket.gethostname(),
            "home": str(rules["_home"]), "rules_path": rules["_path"], "rules_sha256": rules["_sha256"],
            "mode": "plan", "scope": "standing", "offline": ctx["offline"], "evidence_sha256": ctx["evidence_sha256"],
            "reference_sources": list(SR.SOURCES), "process_cwds": len(ctx["cwds"]), "items": items,
            "excluded": excluded, "report_only": [], "totals": totals(items, excluded, []),
            "per_rule": SR.per_rule(items), "protected_excluded_bytes": sum(r.get("size_bytes") or 0 for r in excluded),
            "protected_excluded_unmeasured": sum(r.get("size_bytes") is None for r in excluded),
            "opaque_processes": _opaque_summary(ctx.get("opaque_processes") or []),
            "apply_admissible": not ctx["offline"] and not ctx.get("opaque_processes")}


def _opaque_summary(opaque: list) -> Optional[dict]:
    if not opaque:
        return None
    by_uid: dict[str, int] = {}
    for p in opaque:
        by_uid[str(p.get("uid"))] = by_uid.get(str(p.get("uid")), 0) + 1
    return {"count": len(opaque), "by_uid": dict(sorted(by_uid.items(), key=lambda kv: -kv[1])),
            "own_uid": sorted({str(p.get("comm")) for p in opaque if p.get("own_uid")}),
            "effect": "preview only: apply refuses (evidence_opaque_processes) while any process is opaque"}


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
    opaque = m.get("opaque_processes")
    if opaque:
        lines[2:2] = [f"OPAQUE PROCESSES {opaque['count']} (cwd/fds not readable by this user; by uid {opaque['by_uid']};"
                      f" own uid: {', '.join(opaque['own_uid']) or 'none'}) -> {opaque['effect']}"]
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
        prune_rc, _ = _git(Path(item["main_repo"]), "worktree", "prune", timeout=60)
        return True, "git worktree remove" + ("; prune_failed" if prune_rc else "; prune")
    if kind in ("git_clone", "release_dir", "cache_entry", "rtc_scratch", "agent_scratch"):
        if p.is_symlink() or not p.is_dir():
            return False, "not_a_dir"
        shutil.rmtree(p)
        return True, "rmtree"
    if kind in ("release_file", "archived_dump"):
        if p.is_symlink() or not p.is_file():
            return False, "not_a_file"
        p.unlink()
        return True, "unlink"
    return False, f"unknown_kind:{kind}"


def disk_usage_sample(home: Path) -> dict:
    """After-attempt filesystem usage, separate from the later monitor poll."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        stat = os.statvfs(home)
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
        available = stat.f_bavail * stat.f_frsize
        pct = 100 * used / (used + available) if used + available else None
        return {"used_pct": pct, "measured_at": ts, "filesystem_path": str(home)}
    except OSError:
        return {"used_pct": None, "measured_at": ts, "reason": "statvfs_unavailable"}


def apply(
    manifest_path: Path, rules: Mapping[str, Any], now: datetime, *, grant: Optional[str], run_id: Optional[str],
    standing: bool = False, evidence: Optional[Mapping] = None, manifest_sha256: Optional[str] = None,
    progress_sink=None
) -> dict[str, Any]:
    rep: dict[str, Any] = {
        "schema": APPLY_SCHEMA,
        "started_at": now.isoformat(),
        "manifest": str(manifest_path),
        "run_id": run_id,
        "removed": [],
        "skipped": [],
        "refused": None,
    }
    def finish():
        if standing:
            rep.setdefault("per_rule", None)
            rep.setdefault("held_bytes", None)
            rep.setdefault("planned_bytes", None)
            rep.setdefault("unmeasured_planned_items", None)
            rep["operator_digest"] = SR.operator_digest(rep)
            rep["finished_at"] = datetime.now(timezone.utc).isoformat()
        return rep

    cfg = rules.get("standing_apply") or {}
    if run_id and not standing:
        rep["refused"] = "n8n_executor_never_applies"
        return finish()
    approval = cfg.get("approval") or {}
    if standing and (approval.get("status") != "APPROVED" or not cfg.get("approved_by") or cfg.get("approved_by") != approval.get("approved_by") or not approval.get("approved_at")):
        rep["refused"] = "standing_approval_pending"
        return finish()
    if standing and run_id and cfg.get("enabled") is not True:
        rep["refused"] = "standing_apply_disabled"
        return finish()
    if not grant and not (standing and run_id):
        rep["refused"] = f"{GRANT_ENV}_missing"
        return finish()
    rep["grant"] = grant[:120] if grant else None
    rep["authorization"] = "reviewed_standing" if standing and run_id else "manual_per_run"
    try:
        raw_manifest = Path(manifest_path).read_bytes()
        m = json.loads(raw_manifest)
    except (OSError, json.JSONDecodeError):
        rep["refused"] = "manifest_unreadable"
        return finish()
    if not isinstance(m, dict) or m.get("schema") != MANIFEST_SCHEMA:
        rep["refused"] = "manifest_schema"
        return finish()
    try:
        gen = datetime.fromisoformat(m["generated_at"])
        if not gen.tzinfo:
            raise ValueError("naive")
    except (KeyError, ValueError, TypeError):
        rep["refused"] = "manifest_generated_at"
        return finish()
    age_h = (now - gen).total_seconds() / 3600.0
    rep["manifest_age_h"] = round(age_h, 2)
    age_limit = min(2.0, float(rules["apply"]["manifest_max_age_hours"]), float(cfg.get("manifest_max_age_hours", 2)) if standing else 2.0)
    if age_h < 0 or age_h > age_limit:
        rep["refused"] = "manifest_stale"
        return finish()
    if m.get("home") != str(rules["_home"]):
        rep["refused"] = "manifest_home_mismatch"
        return finish()
    if m.get("rules_sha256") != rules["_sha256"]:
        rep["refused"] = "manifest_rules_sha_mismatch"
        return finish()
    if standing:
        try:
            actual_rules = load_rules(Path(rules["_path"]), home=rules["_home"])
        except RulesError:
            rep["refused"] = "rules_recheck_unreadable"
            return finish()
        if actual_rules["_sha256"] != rules["_sha256"]:
            rep["refused"] = "rules_changed_before_apply"
            return finish()
    rep["manifest_sha256"] = hashlib.sha256(raw_manifest).hexdigest()
    if standing:
        if manifest_sha256 != rep["manifest_sha256"]:
            rep["refused"] = "manifest_sha_mismatch"
            return finish()
        if m.get("scope") != "standing":
            rep["refused"] = "manifest_scope"
            return finish()
        try:
            ctx = SR.evidence_context(evidence, now, applying=True)
            if m.get("offline") is not False or m.get("evidence_sha256") != ctx["evidence_sha256"]:
                raise ValueError("manifest_evidence_mismatch")
        except (ValueError, TypeError) as exc:
            rep["refused"] = str(exc) if isinstance(exc, ValueError) else "evidence_missing"
            return finish()
        max_items = min(int(rules["apply"]["max_items_per_run"]), int(cfg.get("max_items_per_run", 150)))
        max_bytes = min(SR.MAX_BYTES, int(float(cfg["max_gb_per_run"]) * 1024**3), int(cfg["max_bytes_per_run"]))
        rep["per_rule"] = SR.per_rule(m.get("items") or [])
        rep["protected_excluded_bytes"] = m.get("protected_excluded_bytes")
        rep["protected_excluded_unmeasured"] = m.get("protected_excluded_unmeasured")
        rep["run_id"] = run_id or "manual:" + rep["manifest_sha256"]
    else:
        ctx = build_context(rules, now)
        max_items = int(rules["apply"]["max_items_per_run"])
        max_bytes = int(rules["apply"]["max_bytes_per_run"])
    done_bytes = 0
    attempt_clock = time.monotonic()
    for item in m.get("items") or []:
        effective_now = now + timedelta(seconds=time.monotonic() - attempt_clock)
        if (effective_now - gen).total_seconds() > age_limit * 3600:
            rep["refused"] = "manifest_stale_during_apply"
            break
        try:
            live_rules = load_rules(Path(rules["_path"]), home=rules["_home"])
        except RulesError:
            rep["refused"] = "rules_recheck_unreadable"
            break
        if live_rules["_sha256"] != rules["_sha256"]:
            rep["refused"] = "rules_changed_during_apply"
            break
        size = item.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            rep["skipped"].append({"path": item.get("path"), "why": "size_unknown"})
            continue
        if standing and (item.get("rule") not in cfg["rules"] or SR.RULE_KINDS.get(item.get("rule")) != item.get("kind")):
            rep["skipped"].append({"path": item.get("path"), "why": "standing_rule_not_listed"})
            continue
        if len(rep["removed"]) >= max_items:
            rep["skipped"].append({"path": item["path"], "why": "item_cap"})
            continue
        if done_bytes + size > max_bytes:
            rep["skipped"].append({"path": item["path"], "why": "byte_cap"})
            continue
        if standing:
            validation_now = now + timedelta(seconds=time.monotonic() - attempt_clock)
            if (validation_now - gen).total_seconds() > age_limit * 3600:
                rep["refused"] = "manifest_stale_during_apply"
                break
            try:
                refreshed = collect_standing_evidence(rules, validation_now)
                ctx = SR.evidence_context(refreshed, validation_now, applying=True)
            except (RulesError, ValueError):
                rep["refused"] = "evidence_recheck_unavailable"
                break
            try:
                current_rules = load_rules(Path(rules["_path"]), home=rules["_home"])
            except RulesError:
                rep["refused"] = "rules_recheck_unreadable"
                break
            if current_rules["_sha256"] != rules["_sha256"]:
                rep["refused"] = "rules_changed_during_apply"
                break
            if run_id and (current_rules.get("standing_apply") or {}).get("enabled") is not True:
                rep["refused"] = "standing_apply_disabled"
                break
            try:
                current_manifest_sha = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
            except OSError:
                current_manifest_sha = None
            if current_manifest_sha != rep["manifest_sha256"]:
                rep["refused"] = "manifest_changed_during_apply"
                break
            try:
                fresh = next((r for r in standing_results(rules, ctx) if r["path"] == item["path"] and r["kind"] == item["kind"]), None)
            except (RulesError, OSError):
                rep["refused"] = "standing_revalidation_unavailable"
                break
            ok = bool(fresh and fresh["candidate"] and fresh.get("fingerprint") == item.get("fingerprint"))
            why = "standing_revalidation_failed"
            if ok:
                size = du_bytes(Path(item["path"]), 60)
                if size is None or size < 0:
                    ok, why = False, "size_unknown"
                elif done_bytes + size > max_bytes:
                    ok, why = False, "byte_cap_remeasured"
        else:
            ok, why = revalidate(item, rules, ctx)
        if not ok:
            rep["skipped"].append({"path": item["path"], "why": why})
            continue
        if standing:
            if progress_sink is None:
                rep["refused"] = "durable_progress_writer_missing"
                break
            rep["pending_removal"] = {"path": item["path"], "rule": item["rule"], "bytes": size,
                                      "fingerprint": item.get("fingerprint"), "status": "PENDING_NOT_PROVEN_REMOVED"}
            try:
                progress_sink(rep)
            except OSError:
                rep["refused"] = "progress_write_failed_before_removal"
                break
        try:
            ok, how = remove_item(item)
        except OSError as exc:
            ok, how = False, f"error:{type(exc).__name__}"
        if ok:
            done_bytes += size
            rep["removed"].append({"path": item["path"], "kind": item["kind"], "rule": item.get("rule"), "bytes": size, "how": how,
                                   "revalidation_evidence_sha256": ctx.get("evidence_sha256")})
            if standing:
                rep["pending_removal"] = None
                try:
                    progress_sink(rep)
                except OSError:
                    rep["refused"] = "progress_write_failed_after_removal"
                    break
                if "prune_failed" in how:
                    rep["refused"] = "worktree_prune_failed"
                    break
        else:
            rep["skipped"].append({"path": item["path"], "why": how})
            if standing:
                rep["refused"] = "removal_failed"
                break
    if standing:
        rep["per_rule"] = SR.per_rule(m.get("items") or [], rep["removed"])
        rep["planned_bytes"] = sum(r["planned_bytes"] for r in rep["per_rule"].values())
        rep["unmeasured_planned_items"] = sum(r["unmeasured_planned_items"] for r in rep["per_rule"].values())
        rep["held_bytes"] = max(0, rep["planned_bytes"] - done_bytes)
        rep["held_gb"] = rep["held_bytes"] / 1024**3
        rep["post_apply_usage"] = disk_usage_sample(rules["_home"])
        rep["operator_digest"] = SR.operator_digest(rep)
    rep["reclaimed_bytes"] = done_bytes
    rep["reclaimed_gb"] = _gb(done_bytes)
    rep["finished_at"] = datetime.now(timezone.utc).isoformat()
    return finish()


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
    g.add_argument("--apply", action="store_true", help=f"delete manifest items (manual path needs {GRANT_ENV}; --standing is separately reviewed)")
    ap.add_argument("--standing", action="store_true", help="optional reviewed A/S/W rules only (disabled until operator review)")
    ap.add_argument("--evidence-snapshot", help="hashed authorized source capture; offline snapshots support previews only")
    ap.add_argument("--manifest-sha256", help="--standing --apply: exact manifest file SHA256")
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

    evidence = None
    rep = None
    evidence_error = None
    if a.standing:
        cfg = rules.get("standing_apply") or {}
        approval = cfg.get("approval") or {}
        if a.apply and (approval.get("status") != "APPROVED" or not cfg.get("approved_by") or cfg.get("approved_by") != approval.get("approved_by") or not approval.get("approved_at")):
            evidence_error = "standing_approval_pending"
        elif a.apply and os.environ.get(RUN_ID_ENV) and cfg.get("enabled") is not True:
            evidence_error = "standing_apply_disabled"
        elif a.evidence_snapshot:
            try:
                evidence = json.loads(_expand(str(a.evidence_snapshot), rules["_home"]).read_text())
            except (OSError, ValueError, TypeError):
                evidence_error = "evidence_snapshot_unreadable"
        else:
            evidence = collect_standing_evidence(rules, now)
        if evidence_error and not a.apply:
            print(json.dumps({"ok": False, "error": evidence_error}))
            return 1

    if a.apply:
        mpath = Path(a.manifest) if a.manifest else manifest_dir(rules, state_root) / rules["manifest"]["latest_name"]
        if a.standing and not a.manifest and evidence_error is None:
            # A fresh native run plans first; it still applies an exact digest-bound manifest.
            try:
                fresh = standing_plan(rules, now, evidence)
                mpath = write_manifest(fresh, rules, state_root)
                a.manifest_sha256 = hashlib.sha256(mpath.read_bytes()).hexdigest()
            except (RulesError, OSError) as exc:
                evidence_error = str(exc) if isinstance(exc, RulesError) else "manifest_write_failed"
        if evidence_error:
            rep = {"schema": APPLY_SCHEMA, "run_id": os.environ.get(RUN_ID_ENV), "started_at": wall_start.isoformat(),
                   "finished_at": datetime.now(timezone.utc).isoformat(), "refused": evidence_error,
                   "removed": [], "skipped": [], "per_rule": None, "held_bytes": None, "planned_bytes": None,
                   "unmeasured_planned_items": None}
            rep["operator_digest"] = SR.operator_digest(rep)
        else:
            from scripts.lib.atomic_json_store import atomic_write_json
            progress_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(os.environ.get(RUN_ID_ENV) or now.strftime("%Y%m%dT%H%M%SZ")))[:120]
            progress_path = manifest_dir(rules, state_root) / f"disk_hygiene_standing_progress_{progress_id}.json"
            rep = apply(mpath, rules, now, grant=os.environ.get(GRANT_ENV), run_id=os.environ.get(RUN_ID_ENV),
                        standing=a.standing, evidence=evidence, manifest_sha256=a.manifest_sha256,
                        progress_sink=(lambda current: atomic_write_json(progress_path, current, indent=1)) if a.standing else None)
        from scripts.lib.atomic_json_store import atomic_write_json

        if rep.get("refused") != "n8n_executor_never_applies":
            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            atomic_write_json(manifest_dir(rules, state_root) / f"disk_hygiene_apply_{stamp}.json", rep, indent=1)
            if a.standing:
                report_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(rep.get("run_id") or stamp))[:120]
                atomic_write_json(manifest_dir(rules, state_root) / f"disk_hygiene_standing_apply_{stamp}_{report_id}.json", rep, indent=1)
                atomic_write_json(manifest_dir(rules, state_root) / "disk_hygiene_standing_apply_latest.json", rep, indent=1)
            receipt_lane = LANE_ID if a.standing and os.environ.get(RUN_ID_ENV) else APPLY_LANE_ID
            R.write_lane_receipt(
                receipt_lane,
                ok=not rep.get("refused"),
                exit_code=0 if not rep.get("refused") else 1,
                started_at=wall_start,
                script=SCRIPT,
                summary={
                    "refused": rep.get("refused"),
                    "removed": len(rep["removed"]),
                    "skipped": len(rep["skipped"]),
                    "reclaimed_bytes": rep.get("reclaimed_bytes"),
                    "per_rule": rep.get("per_rule"), "operator_digest": rep.get("operator_digest"),
                },
                path=R.receipt_path(receipt_lane, state_root),
                output={"produced_count": 1 if not rep.get("refused") else 0, "attempted_count": 1,
                        "skipped_reasons": {SKIP_DEPENDENCY: 1} if rep.get("refused") else {},
                        "empty_reason": None, "output_evidence": [{"kind": "file", "ref": str(manifest_dir(rules, state_root) / "disk_hygiene_standing_apply_latest.json")}]} if a.standing else None,
            )
        print(
            json.dumps(
                {k: rep.get(k) for k in ("refused", "manifest_age_h", "reclaimed_gb")}
                | {"removed": len(rep["removed"]), "skipped": len(rep["skipped"])}
            )
        )
        return 1 if rep.get("refused") else 0

    try:
        m = standing_plan(rules, now, evidence, measure=not a.no_measure) if a.standing else plan(rules, now, measure=not a.no_measure)
    except RulesError as exc:
        m, err = None, str(exc)
    else:
        err = None
    if a.dry_run:
        if m is None:
            out = {"dry_run": True, "ok": False, "error": err}
            missing = (err or "").partition(":")[2]
            source = ((evidence or {}).get("sources") or {}).get(missing) if a.standing and isinstance(evidence, dict) else None
            if isinstance(source, dict) and source.get("detail"):
                out["detail"] = source["detail"]  # which evidence was unavailable, so the operator can act
            print(json.dumps(out))
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
                "per_rule": m.get("per_rule"), "scope": m.get("scope"),
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
