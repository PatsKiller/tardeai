#!/usr/bin/env python3
"""tmp_hygiene.py — rule-based /tmp reclaim plan (inode-aware), with destructive apply unsupported as in disk_hygiene.

Incident 2026-10-19 ~13:40 ET: /tmp (tmpfs, 31G, 1,048,576 inodes) reached 97% INODES with 20G of bytes free, and
tools failed with ENOSPC. The files sat in ended Claude sessions' scratch dirs (/tmp/claude-<uid>/<project>/<uuid>/,
one held 207k files: git worktrees + pytest temp) and /tmp/pytest-of-<user> (57k); the disk monitor checked bytes
only and the disk_hygiene rules covered home-dir clones and releases only. Operator approved 2026-10-19: a daily
/tmp plan on n8n (lane ``tmp-hygiene``, 05:00 ET, live_arg --plan) and inode bands in disk_usage_monitor.py.

Every threshold, pattern and cap is in ``config/disk_hygiene_rules.json`` ``tmp``; this file holds the rules' LOGIC.

RULES (only these patterns are ever evaluated; every other /tmp entry is reported as excluded and never scanned)
  S  claude session scratch ``<root>/claude-<uid>/<project>/<uuid>/``. Candidate ONLY if ALL hold:
       owned by the running uid; not on the /tmp never-touch globs;
       the bounded scan of the tree completed (time / entry cap) and its newest mtime is older than idle_days;
       no process has its cwd inside (/proc/*/cwd) and no process holds an open fd inside (/proc/*/fd);
       its transcript ``~/.claude/projects/<project>/<uuid>.jsonl``, when present, was not modified within
       transcript_idle_days (the session ended);
       every git work tree inside is safe to drop: a REGISTERED linked worktree must be clean (untracked included)
       with no commit reachable only from its HEAD (it is removed with ``git -C <main repo> worktree remove``, never
       --force); a standalone clone must be clean with every branch pushed and no stash; a linked worktree whose
       gitdir is gone (unregistered) is plain files.
  P  pytest temp ``<root>/pytest-of-<user>/pytest-*`` (never the ``pytest-current`` symlink): owned, newest mtime of
     the tree older than older_than_days, no cwd and no open fd inside.
  NEVER-TOUCH: any /tmp entry that matches neither pattern (n8n-campaign-*, tradeai-*, momentum-*, ...) is never a
     candidate and never scanned; ``never_touch_globs`` is checked again on every candidate and at apply time. The
     current session's scratch is excluded by the idle / transcript / cwd / fd rules.

MODES (as disk_hygiene.py)
    python3 scripts/tmp_hygiene.py                 # plan (default): manifest JSON + LaneRunReceipt, deletes nothing
    python3 scripts/tmp_hygiene.py --dry-run       # print the plan only: no manifest, no receipt, no write at all
    python3 scripts/tmp_hygiene.py --report        # + a human summary
    python3 scripts/tmp_hygiene.py --apply       # unsupported: refuses without reading rules or writing state

The manifest is a DiskHygieneManifest@v1 with ``scope: "tmp"``; every item carries
``file_count`` and ``size_bytes``. Plans report reclaimable inodes alongside bytes.
ACTIVE policy supplies no destructive maintenance authority. ``--apply`` and the
public ``apply()`` API always refuse; caller tokens cannot enable them. A future
policy decision alone does not re-enable these paths.

Exit: 0 = plan written (or dry run printed); 1 = rules unreadable, a write failed, or an apply
refusal; 2 = usage. MBI_BEHAVIOR = 0. No broker, no network, no send, no DB.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pwd
import re
import shutil
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import disk_hygiene as DH  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402

LANE_ID = "tmp-hygiene"
APPLY_LANE_ID = "tmp-hygiene-apply"
SCRIPT = "scripts/tmp_hygiene.py"
SCOPE = "tmp"
KIND_SESSION = "tmp_claude_session"
KIND_PYTEST = "tmp_pytest_dir"
KINDS = (KIND_SESSION, KIND_PYTEST)
SKIP_DEPENDENCY = "dependency_unavailable"
#: Historical names retained for caller compatibility. Public apply never reads a grant
#: environment variable or treats a supplied value as authority.
GRANT_ENV = "TRADEAI_DISK_HYGIENE_GRANT"
RUN_ID_ENV = "TRADEAI_RUN_ID"


# ── rules ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def tmp_rules(rules: Mapping[str, Any], *, uid: Optional[int] = None, user: Optional[str] = None) -> dict[str, Any]:
    """The ``tmp`` section, validated, with {uid}/{user} substituted and ~ expanded; raises DH.RulesError."""
    t = rules.get("tmp")
    if not isinstance(t, dict):
        raise DH.RulesError("rules_missing:tmp")
    for key in ("root", "claude_scratch", "pytest", "never_touch_globs", "scan", "manifest_latest_name", "apply"):
        if key not in t:
            raise DH.RulesError(f"rules_missing:tmp.{key}")
    for key in ("manifest_max_age_hours", "max_items_per_run", "max_bytes_per_run", "max_files_per_run"):
        if key not in t["apply"]:
            raise DH.RulesError(f"rules_missing:tmp.apply.{key}")
    cs, py = t["claude_scratch"], t["pytest"]
    for key in ("dir_name", "session_regex", "idle_days", "transcripts_dir", "transcript_idle_days"):
        if key not in cs:
            raise DH.RulesError(f"rules_missing:tmp.claude_scratch.{key}")
    for key in ("dir_name", "entry_glob", "older_than_days"):
        if key not in py:
            raise DH.RulesError(f"rules_missing:tmp.pytest.{key}")
    uid = os.getuid() if uid is None else uid
    if user is None:
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = str(uid)
    sub = lambda s: str(s).replace("{uid}", str(uid)).replace("{user}", user)  # noqa: E731
    return {
        **t,
        "_root": Path(str(t["root"])),
        "_uid": uid,
        "_claude_dir": sub(cs["dir_name"]),
        "_session_re": re.compile(str(cs["session_regex"])),
        "_transcripts": DH._expand(str(cs["transcripts_dir"]), rules["_home"]),
        "_pytest_dir": sub(py["dir_name"]),
    }


# ── host facts (read only) ─────────────────────────────────────────────────────────────────────────────────────────


def process_open_paths(proc_root: Path) -> set[str]:
    """Targets of every readable /proc/<pid>/fd/<n> that is a path (sockets, pipes, anon inodes are skipped)."""
    out: set[str] = set()
    try:
        names = os.listdir(proc_root)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        fd_dir = proc_root / name / "fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd_dir / fd)
            except OSError:
                continue
            if target.endswith(" (deleted)"):
                target = target[: -len(" (deleted)")]
            if target.startswith("/"):
                out.add(target)
    return out


def held_open_by(path: Path, open_paths: set[str]) -> Optional[str]:
    variants = {os.path.abspath(path), os.path.realpath(path)}
    for p in open_paths:
        for v in variants:
            if DH.is_within(Path(p), Path(v)):
                return p
    return None


def tree_stats(path: Path, *, time_cap_s: float, max_entries: int) -> dict[str, Any]:
    """One bounded lstat walk (never follows a symlink, never leaves the device): entries below ``path`` (the inodes
    a removal frees, the root dir included), bytes allocated (st_blocks * 512) and the newest mtime. ``complete`` is
    False when the time or entry cap stopped the walk: then the numbers are lower bounds and the tree is never a
    candidate (idleness is unproven)."""
    deadline = time.monotonic() + time_cap_s
    try:
        st = os.lstat(path)
    except OSError:
        return {"files": 0, "bytes": 0, "newest_mtime": 0.0, "complete": False}
    files, size, newest, dev = 1, st.st_blocks * 512, st.st_mtime, st.st_dev
    stack = [str(path)]
    complete = True
    while stack:
        if files >= max_entries or time.monotonic() > deadline:
            complete = False
            break
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                if files >= max_entries:
                    complete = False
                    break
                try:
                    s = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                files += 1
                size += s.st_blocks * 512
                if s.st_mtime > newest:
                    newest = s.st_mtime
                if e.is_dir(follow_symlinks=False) and s.st_dev == dev:
                    stack.append(e.path)
    return {"files": files, "bytes": size, "newest_mtime": newest, "complete": complete}


def git_trees(path: Path, depth: int) -> list[Path]:
    """Directories within ``depth`` levels below ``path`` (``path`` included) that carry a ``.git`` entry; a git tree
    is not descended into."""
    out: list[Path] = []
    frontier = [path]
    for level in range(depth + 1):
        nxt: list[Path] = []
        for d in frontier:
            if os.path.lexists(d / DH.DOT_GIT):
                out.append(d)
                continue
            if level == depth:
                continue
            try:
                with os.scandir(d) as it:
                    nxt.extend(Path(e.path) for e in it if e.is_dir(follow_symlinks=False))
            except OSError:
                continue
        frontier = nxt
    return sorted(out)


def registered_worktree(path: Path, lay: Mapping[str, Any]) -> bool:
    """A linked worktree is registered when its gitdir still exists and points back at this tree's .git file."""
    gitdir = Path(lay["gitdir"])
    try:
        back = (gitdir / "gitdir").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return os.path.realpath(back) == os.path.realpath(path / DH.DOT_GIT)


def judge_git_tree(path: Path, to: float) -> dict[str, Any]:
    """{path, kind, main_repo, registered, reasons[]} for one git tree inside a scratch dir."""
    lay = DH.git_layout(path)
    if lay is None:
        return {"path": str(path), "kind": "not_git", "registered": False, "reasons": []}
    row: dict[str, Any] = {"path": str(path), "kind": lay["kind"], "main_repo": str(lay["main_repo"]), "reasons": []}
    if lay["kind"] == "git_worktree":
        row["registered"] = registered_worktree(path, lay)
        if not row["registered"]:
            return row  # its gitdir is gone: plain files, nothing for git to keep
        if (Path(lay["gitdir"]) / "locked").exists():
            row["reasons"].append("worktree_locked")
    else:
        row["registered"] = False
    rc, status = DH._git(
        path, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none", timeout=to
    )
    if rc != 0:
        row["reasons"].append("git_status_failed")
    elif status.strip():
        row["reasons"].append("git_tree_dirty")
    rc, head = DH._git(path, "rev-parse", "--verify", "-q", "HEAD", timeout=to)
    if rc == 0 and head.strip():
        rc, only = DH._git(path, "rev-list", "--max-count=1", "HEAD", "--not", "--branches", "--remotes", timeout=to)
        if lay["kind"] == "git_clone":
            rc, only = DH._git(
                path, "rev-list", "--max-count=1", "HEAD", "--branches", "--not", "--remotes", timeout=to
            )
            _, stash = DH._git(path, "rev-parse", "--verify", "-q", "refs/stash", timeout=to)
            if stash.strip():
                row["reasons"].append("git_stash")
        if rc != 0:
            row["reasons"].append("git_reachability_failed")
        elif only.strip():
            row["reasons"].append("git_unpushed_commits")
    return row


# ── evaluation ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _never_glob(path: Path, t: Mapping[str, Any]) -> Optional[str]:
    rel = os.path.relpath(path, t["_root"])
    for part in Path(rel).parts:
        for g in t["never_touch_globs"]:
            if fnmatch.fnmatch(part, g):
                return f"never_touch_glob:{g}"
    return None


def _common(path: Path, kind: str, rule: str, t: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    """The checks every /tmp candidate shares; returns the item dict with ``reasons`` and ``evidence`` started."""
    out: dict[str, Any] = {
        "path": str(path),
        "kind": kind,
        "category": "tmp",
        "rule": rule,
        "reasons": [],
        "evidence": {},
    }
    reasons: list[str] = out["reasons"]
    if path.is_symlink():
        reasons.append("symlink")
        return out
    hard = _never_glob(path, t) or DH.never_touch_reason(path, ctx["rules"])
    if hard:
        reasons.append(hard)
    try:
        if os.lstat(path).st_uid != t["_uid"]:
            reasons.append("not_owned")
    except OSError:
        reasons.append("gone")
        return out
    scan = t["scan"]
    st = tree_stats(path, time_cap_s=float(scan["time_cap_s"]), max_entries=int(scan["max_entries"]))
    out["file_count"] = st["files"]
    out["size_bytes"] = st["bytes"]
    newest = st["newest_mtime"]
    out["evidence"]["newest_mtime"] = datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None
    out["evidence"]["idle_days"] = round((ctx["now"].timestamp() - newest) / 86400.0, 2) if newest else None
    if not st["complete"]:
        reasons.append("scan_incomplete")
    use = DH.in_use_by(path, ctx["cwds"])
    if use:
        reasons.append("in_use_cwd")
        out["evidence"]["in_use_cwd"] = use
    held = held_open_by(path, ctx["open_paths"])
    if held:
        reasons.append("open_fd")
        out["evidence"]["open_fd"] = held
    out["fingerprint"] = {"newest_mtime": newest, "file_count": st["files"], "kind": kind}
    return out


def evaluate_session(path: Path, project: str, t: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    cs = t["claude_scratch"]
    out = _common(path, KIND_SESSION, "S", t, ctx)
    reasons: list[str] = out["reasons"]
    if "fingerprint" not in out:
        out["candidate"] = False
        return out
    idle = out["evidence"]["idle_days"]
    if idle is None or idle <= float(cs["idle_days"]):
        reasons.append("recent_activity")
    transcript = t["_transcripts"] / project / f"{path.name}.jsonl"
    try:
        tm = os.stat(transcript).st_mtime
    except OSError:
        out["evidence"]["transcript"] = None
    else:
        t_idle = (ctx["now"].timestamp() - tm) / 86400.0
        out["evidence"]["transcript"] = {"path": str(transcript), "idle_days": round(t_idle, 2)}
        if t_idle <= float(cs["transcript_idle_days"]):
            reasons.append("session_transcript_live")
    trees = []
    to = float(ctx["rules"]["git"].get("git_timeout_s") or 60)
    for g in git_trees(path, int(cs.get("worktree_search_depth") or 3)):
        row = judge_git_tree(g, to)
        trees.append(row)
        reasons.extend(r for r in row["reasons"] if r not in reasons)
    out["git_trees"] = trees
    out["candidate"] = not reasons
    return out


def evaluate_pytest(path: Path, t: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    out = _common(path, KIND_PYTEST, "P", t, ctx)
    if "fingerprint" not in out:
        out["candidate"] = False
        return out
    idle = out["evidence"]["idle_days"]
    if idle is None or idle <= float(t["pytest"]["older_than_days"]):
        out["reasons"].append("recent_activity")
    out["candidate"] = not out["reasons"]
    return out


def _dirs(path: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return sorted(it, key=lambda e: e.name)
    except OSError:
        return []


def evaluate_tmp(t: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every rule over ``t['_root']``. Entries matching no rule are listed as excluded (never scanned)."""
    root: Path = t["_root"]
    results: list[dict[str, Any]] = []
    cs_on = bool(t["claude_scratch"].get("enabled", True))
    py_on = bool(t["pytest"].get("enabled", True))

    def untouched(p: str, reason: str) -> None:
        results.append(
            {
                "path": p,
                "kind": "tmp_untouched",
                "category": "tmp",
                "rule": "N",
                "reasons": [reason],
                "evidence": {},
                "candidate": False,
                "file_count": None,
                "size_bytes": None,
            }
        )

    for top in _dirs(root):
        tp = Path(top.path)
        glob = _never_glob(tp, t)
        if top.name == t["_claude_dir"] and cs_on and not top.is_symlink():
            for proj in _dirs(tp):
                if not proj.is_dir(follow_symlinks=False):
                    continue
                for sess in _dirs(Path(proj.path)):
                    sp = Path(sess.path)
                    if sess.is_dir(follow_symlinks=False) and t["_session_re"].fullmatch(sess.name):
                        results.append(evaluate_session(sp, proj.name, t, ctx))
        elif top.name == t["_pytest_dir"] and py_on and not top.is_symlink():
            for e in _dirs(tp):
                if e.is_symlink():
                    continue  # pytest-current
                if e.is_dir(follow_symlinks=False) and fnmatch.fnmatch(e.name, t["pytest"]["entry_glob"]):
                    results.append(evaluate_pytest(Path(e.path), t, ctx))
        else:
            untouched(str(tp), glob or "no_tmp_rule")
    return results


def build_context(rules: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    proc = rules["_proc_root"]
    return {"now": now, "rules": rules, "cwds": DH.process_cwds(proc), "open_paths": process_open_paths(proc)}


def totals(items: list, excluded: list) -> dict[str, Any]:
    by_kind: dict[str, dict[str, Any]] = {}
    for r in items:
        k = by_kind.setdefault(f"{r['rule']}:{r['kind']}", {"count": 0, "bytes": 0, "files": 0})
        k["count"] += 1
        k["bytes"] += r.get("size_bytes") or 0
        k["files"] += r.get("file_count") or 0
    by_reason: dict[str, dict[str, Any]] = {}
    for r in excluded:
        for reason in sorted({x.split(":", 1)[0] for x in r["reasons"]}):
            k = by_reason.setdefault(reason, {"count": 0, "bytes": 0, "files": 0})
            k["count"] += 1
            k["bytes"] += r.get("size_bytes") or 0
            k["files"] += r.get("file_count") or 0
    rb = sum(r.get("size_bytes") or 0 for r in items)
    return {
        "candidates": len(items),
        "reclaimable_bytes": rb,
        "reclaimable_gb": DH._gb(rb),
        "reclaimable_files": sum(r.get("file_count") or 0 for r in items),
        "unmeasured_candidates": 0,
        "by_kind": by_kind,
        "excluded": len(excluded),
        "excluded_bytes": sum(r.get("size_bytes") or 0 for r in excluded),
        "excluded_files": sum(r.get("file_count") or 0 for r in excluded),
        "excluded_by_reason": dict(sorted(by_reason.items(), key=lambda kv: (-kv[1]["files"], kv[0]))),
    }


def statvfs_inodes(root: Path) -> Optional[dict[str, Any]]:
    try:
        st = os.statvfs(root)
    except OSError:
        return None
    if not st.f_files:
        return None
    used = st.f_files - st.f_ffree
    return {"inodes_total": st.f_files, "inodes_used": used, "inodes_used_pct": round(used / st.f_files * 100, 2)}


def plan(rules: Mapping[str, Any], t: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Evaluate every /tmp rule; returns the manifest document (nothing written, nothing deleted)."""
    if not t["_root"].is_dir():
        raise DH.RulesError("tmp_root_unreadable")
    ctx = build_context(rules, now)
    results = evaluate_tmp(t, ctx)
    untouched_rows = [r for r in results if r["kind"] == "tmp_untouched"]
    results = [r for r in results if r["kind"] != "tmp_untouched"]
    for r in results:
        r["id"] = DH._item_id(r["path"])
    items = [r for r in results if r.get("candidate")]
    excluded = [r for r in results if not r.get("candidate")]
    # entries no rule matches are never scanned: counted by reason, listed (never-touch globs first) up to a cap, so
    # a /tmp with thousands of loose files keeps the manifest small
    by_reason: dict[str, int] = {}
    for r in untouched_rows:
        key = r["reasons"][0].split(":", 1)[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    listed = sorted(untouched_rows, key=lambda r: (not r["reasons"][0].startswith("never_touch"), r["path"]))
    untouched = {
        "total": len(untouched_rows),
        "by_reason": dict(sorted(by_reason.items())),
        "entries": [
            {"path": r["path"], "reason": r["reasons"][0]} for r in listed[: int(t.get("untouched_list_max") or 200)]
        ],
    }
    tot = totals(items, excluded)
    tot["untouched"] = untouched["total"]
    tot["untouched_by_reason"] = untouched["by_reason"]
    return {
        "schema": DH.MANIFEST_SCHEMA,
        "scope": SCOPE,
        "generated_at": now.isoformat(),
        "host": socket.gethostname(),
        "home": str(rules["_home"]),
        "tmp_root": str(t["_root"]),
        "rules_path": rules["_path"],
        "rules_sha256": rules["_sha256"],
        "mode": "plan",
        "process_cwds": len(ctx["cwds"]),
        "process_open_paths": len(ctx["open_paths"]),
        "filesystem": statvfs_inodes(t["_root"]),
        "items": items,
        "excluded": excluded,
        "untouched": untouched,
        "report_only": [],
        "totals": tot,
    }


def _k(n: Optional[int]) -> str:
    return f"{(n or 0) / 1000:.1f}k"


def human_summary(m: Mapping[str, Any], top_n: int) -> str:
    t = m["totals"]
    fs = m.get("filesystem") or {}
    lines = [
        f"tmp_hygiene plan  generated_at {m['generated_at']}  host {m['host']}  root {m['tmp_root']}",
        f"rules {m['rules_path']} sha256 {m['rules_sha256'][:12]}  process cwds {m['process_cwds']}"
        f"  open paths {m['process_open_paths']}",
        f"filesystem inodes {fs.get('inodes_used')} of {fs.get('inodes_total')} used ({fs.get('inodes_used_pct')}%)",
        "",
        f"CANDIDATES {t['candidates']}  reclaimable {_k(t['reclaimable_files'])} inodes, {t['reclaimable_gb']} GB",
    ]
    for k, v in sorted(t["by_kind"].items()):
        lines.append(f"  {k:<26} {v['count']:>5}  {_k(v['files']):>9} inodes  {DH._gb(v['bytes']):>7.2f} GB")
    lines += ["", f"LARGEST {top_n} CANDIDATES BY INODES"]
    for r in sorted(m["items"], key=lambda r: -(r.get("file_count") or 0))[:top_n]:
        ev = r.get("evidence") or {}
        wt = sum(1 for g in r.get("git_trees") or [] if g.get("registered"))
        lines.append(
            f"  {_k(r.get('file_count')):>9}  {DH._gb(r.get('size_bytes')):>6.2f} GB  {r['kind']:<18}"
            f" {r['path']}  idle {ev.get('idle_days')}d  registered worktrees {wt}"
        )
    lines += [
        "",
        f"EXCLUDED {t['excluded']}  ({_k(t['excluded_files'])} inodes) by reason"
        " (an entry with several reasons counts under each)",
    ]
    for k, v in t["excluded_by_reason"].items():
        lines.append(f"  {k:<26} {v['count']:>5}  {_k(v['files']):>9} inodes  {DH._gb(v['bytes']):>7.2f} GB")
    for r in sorted(m["excluded"], key=lambda r: -(r.get("file_count") or 0))[:top_n]:
        ev = r.get("evidence") or {}
        lines.append(
            f"  {_k(r.get('file_count')):>9}  {r['path']}  idle {ev.get('idle_days')}d  " + ",".join(r["reasons"])
        )
    u = m.get("untouched") or {}
    lines += ["", f"UNTOUCHED /tmp ENTRIES {u.get('total')} (no rule matches: never scanned, never a candidate)"]
    for k, v in (u.get("by_reason") or {}).items():
        lines.append(f"  {k:<26} {v:>5}")
    shown = [e for e in u.get("entries") or [] if e["reason"].startswith("never_touch")]
    lines += [f"  never-touch globs matched ({len(shown)} listed):"]
    for e in shown:
        lines.append(f"    {e['reason']:<34} {e['path']}")
    return "\n".join(lines) + "\n"


def write_manifest(
    m: Mapping[str, Any], rules: Mapping[str, Any], t: Mapping[str, Any], state_root: Optional[Path]
) -> Path:
    from scripts.lib.atomic_json_store import atomic_write_json

    d = DH.manifest_dir(rules, state_root)
    stamp = datetime.fromisoformat(m["generated_at"]).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"tmp_hygiene_manifest_{stamp}.json"
    atomic_write_json(path, m, indent=1)
    atomic_write_json(d / t["manifest_latest_name"], m, indent=1)
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
                "reclaimable_files": t["reclaimable_files"],
                "excluded": t["excluded"],
            }
        ],
    }


# ── apply ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def revalidate(item: Mapping[str, Any], t: Mapping[str, Any], ctx: Mapping[str, Any]) -> tuple[bool, str, Any]:
    """Re-run the item's rule NOW; (ok, why, fresh item). Anything different from the manifest -> skip."""
    p = Path(item["path"])
    if not os.path.lexists(p):
        return False, "gone", None
    if p.is_symlink():
        return False, "now_symlink", None
    if not DH.is_within(p, t["_root"]) or os.path.abspath(p) == os.path.abspath(t["_root"]):
        return False, "outside_tmp_root", None
    kind = item.get("kind")
    if kind == KIND_SESSION:
        rel = Path(os.path.relpath(p, t["_root"])).parts
        if len(rel) != 3 or rel[0] != t["_claude_dir"] or not t["_session_re"].fullmatch(rel[2]):
            return False, "pattern_mismatch", None
        fresh = evaluate_session(p, rel[1], t, ctx)
    elif kind == KIND_PYTEST:
        rel = Path(os.path.relpath(p, t["_root"])).parts
        if len(rel) != 2 or rel[0] != t["_pytest_dir"] or not fnmatch.fnmatch(rel[1], t["pytest"]["entry_glob"]):
            return False, "pattern_mismatch", None
        fresh = evaluate_pytest(p, t, ctx)
    else:
        return False, f"unknown_kind:{kind}", None
    if not fresh.get("candidate"):
        return False, "rule_now_fails:" + ",".join(fresh.get("reasons") or []), None
    if fresh.get("fingerprint") != item.get("fingerprint"):
        return False, "changed_since_manifest", None
    return True, "ok", fresh


def remove_item(fresh: Mapping[str, Any]) -> tuple[bool, str]:
    """Registered linked worktrees first, each with ``git -C <main repo> worktree remove`` (never --force); any
    failure stops before a single plain file is removed from the rest of the tree. Then rmtree (symlinks unlinked,
    never followed)."""
    p = Path(fresh["path"])
    n = 0
    for g in fresh.get("git_trees") or []:
        if g.get("kind") == "git_worktree" and g.get("registered"):
            rc, _ = DH._git(Path(g["main_repo"]), "worktree", "remove", g["path"], timeout=600)
            if rc != 0 or os.path.lexists(g["path"]):
                return False, f"git_worktree_remove_rc:{rc}:{g['path']}"
            n += 1
    if p.is_symlink() or not p.is_dir():
        return False, "not_a_dir"
    shutil.rmtree(p)
    return True, f"git worktree remove x{n} + rmtree" if n else "rmtree"


def apply(
    manifest_path: Path,
    rules: Mapping[str, Any],
    t: Mapping[str, Any],
    now: datetime,
    *,
    grant: Optional[str],
    run_id: Optional[str],
) -> dict[str, Any]:
    """Return a hold; ACTIVE policy supplies no destructive maintenance authority.

    Keep the call signature for existing readers. A caller token, including a
    real grant for an unrelated action, cannot enable this operation.
    """
    return {
        "schema": DH.APPLY_SCHEMA,
        "scope": SCOPE,
        "started_at": now.isoformat(),
        "manifest": str(manifest_path),
        "removed": [],
        "skipped": [],
        "refused": "n8n_executor_never_applies" if run_id else "destructive_apply_unsupported_by_active_policy",
    }


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--plan", action="store_true", help="the default: write the manifest + receipt, delete nothing")
    g.add_argument("--dry-run", action="store_true", help="print the plan only; writes nothing at all")
    g.add_argument(
        "--apply", action="store_true", help="unsupported under ACTIVE policy; always refuses without effects"
    )
    ap.add_argument("--report", action="store_true", help="also print the human summary")
    ap.add_argument("--manifest", help="--apply: manifest path (default: the latest /tmp manifest)")
    ap.add_argument("--rules", help="rules file (default config/disk_hygiene_rules.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / resolver)")
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: aware ISO 8601
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if a.apply:
        print(json.dumps({"mode": "apply", "ok": False, "refused": "destructive_apply_unsupported_by_active_policy"}))
        return 1
    wall_start = datetime.now(timezone.utc)
    now = DH._parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    state_root = Path(a.state_root) if a.state_root else None
    try:
        rules = DH.load_rules(Path(a.rules) if a.rules else None, home=Path(a.home) if a.home else None)
        t = tmp_rules(rules)
    except (DH.RulesError, KeyError, TypeError, ValueError, re.error) as exc:
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
        m = plan(rules, t, now)
    except DH.RulesError as exc:
        m, err = None, str(exc)
    else:
        err = None
    top_n = int(rules["manifest"].get("top_n") or 20)
    if a.dry_run:
        if m is None:
            print(json.dumps({"dry_run": True, "ok": False, "error": err}))
            return 1
        R.dry_run_report(
            LANE_ID,
            {"totals": m["totals"]},
            would_write=[str(DH.manifest_dir(rules, state_root))],
            receipt=R.receipt_path(LANE_ID, state_root),
        )
        if a.report:
            print(human_summary(m, top_n))
        return 0
    path = None
    if m is not None:
        try:
            path = write_manifest(m, rules, t, state_root)
        except OSError as exc:
            err = f"manifest_write_failed:{type(exc).__name__}"
    ok = path is not None
    summary: dict[str, Any] = {"manifest": str(path) if path else None, "error": err}
    if m is not None:
        summary.update(
            {k: m["totals"][k] for k in ("candidates", "reclaimable_bytes", "reclaimable_files", "excluded")}
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
        print(human_summary(m, top_n))
    return 0 if ok and written else 1


if __name__ == "__main__":
    raise SystemExit(main())
