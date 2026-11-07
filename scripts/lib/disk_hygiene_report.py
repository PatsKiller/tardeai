"""disk_hygiene_report.py — bounded, READ-ONLY candidate report for agent scratch and releases (LQ-20261107-277).

Why it exists. Rule T measures ``~/.cache/agent-tmp/<owner>`` as ONE entry: one fresh file anywhere in an owner's
tree keeps the whole owner alive, and the recursive activity scan over millions of entries is what made the
lane overrun its slot. This report works one level down (``<owner>/<entry>``), proves "idle" with an early-exit
walk that stops at the first entry newer than the cutoff, sizes with ``du`` under a per-dir timeout, and stops at a
wall deadline. Nothing here deletes, moves or writes: it returns a dict. Any removal stays in disk_hygiene's
reviewed apply path, which asks :func:`live_claim_hold` before it touches an item.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "DiskHygieneCandidateReport@v1"
OLDER_THAN_H = 6.0
RELEASE_KEEP = 5
CLAIM_STALE_H = 2.0  # agent_claim_board.DEFAULT_STALE_HOURS: a heartbeat older than this is not a live claim
DEADLINE_S = 40.0
WALK_WORKERS = 16
DU_TIMEOUT_S = 12.0
WALK_ENTRY_CAP = 400_000
#: the agent harness keeps its own scratchpad under <owner>/tmp: the running session's, never a candidate.
HARNESS_ENTRIES = frozenset({"tmp"})
RELEASE_TS = re.compile(r"(\d{8}-\d{6})")
#: a worker session's own dir (cc-deepseek-5, cx-openai-2): its children are the entries. Any other top-level dir is an entry itself.
OWNER_RE = re.compile(r"^(cc|cx)-[a-z]+(-\d+)?$")


class ClaimsUnreadable(RuntimeError):
    pass


def _ts(text: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def live_claims(claims_dir: Path, now: float, stale_hours: float = CLAIM_STALE_H) -> list[dict]:
    """Active AgentClaim@v1 documents whose heartbeat is within ``stale_hours``. A missing dir is no claims; an
    unreadable or malformed claim file raises :class:`ClaimsUnreadable` (unknown never means 'no claim')."""
    if not claims_dir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(claims_dir.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ClaimsUnreadable(f"{p.name}:{type(exc).__name__}") from exc
        if not isinstance(doc, dict) or doc.get("schema") != "AgentClaim@v1":
            continue  # board state documents live here too
        if doc.get("status") != "active":
            continue
        beat = _ts(doc.get("heartbeat_at")) or _ts(doc.get("started_at"))
        if beat is None or now - beat <= stale_hours * 3600:
            out.append({"claim_id": doc.get("claim_id"), "session": doc.get("session"),
                        "agent": doc.get("agent"), "paths": [x for x in (doc.get("paths") or []) if isinstance(x, str)]})
    return out


def owner_claims(owner: str, live: Iterable[dict]) -> list[str]:
    """Claim ids whose session is this owner dir or one of its sub-sessions (``cc-deepseek-6`` holds
    ``cc-deepseek-6-hermes-test``). Over-holding is the safe direction."""
    return [c["claim_id"] for c in live
            if isinstance(c.get("session"), str) and (c["session"] == owner or c["session"].startswith(owner + "-"))]


def live_claim_hold(path: Path, home: Path, live: Iterable[dict]) -> Optional[str]:
    """Why a live claim forbids touching ``path`` (None when none does). Applies to the scratch owner dir and to any
    absolute path a live claim names (equal, inside or containing it)."""
    live = list(live)
    root = home / ".cache" / "agent-tmp"
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = None
    if rel is not None and rel.parts:
        ids = owner_claims(rel.parts[0], live)
        if ids:
            return "owner_holds_live_claim:" + ids[0]
    p = os.path.abspath(path)
    for c in live:
        for raw in c.get("paths") or []:
            q = os.path.abspath(os.path.expanduser(raw)) if raw.startswith(("/", "~")) else None
            if q and (p == q or p.startswith(q + os.sep) or q.startswith(p + os.sep)):
                return "path_in_live_claim:" + str(c.get("claim_id"))
    return None


def idle_proof(path: Path, cutoff: float, deadline: float) -> tuple[Optional[float], str, int]:
    """(newest_mtime_seen, verdict, allocated_bytes). 'idle' = a COMPLETE walk found nothing newer than ``cutoff``;
    'active' = the first newer entry stopped the walk; 'unproven' = entry cap or deadline hit before it finished.
    Symlinks are never followed. Bytes are st_blocks*512 summed during the same walk (hardlinks count per link),
    so sizing costs no second pass."""
    try:
        st0 = os.lstat(path)
    except OSError:
        return None, "unproven", 0
    newest, total = st0.st_mtime, st0.st_blocks * 512
    if newest > cutoff:
        return newest, "active", 0
    if not stat.S_ISDIR(st0.st_mode):
        return newest, "idle", total  # a plain file entry: its own mtime is the whole proof
    stack, seen = [str(path)], 0
    while stack:
        if time.monotonic() > deadline or seen > WALK_ENTRY_CAP:
            return newest, "unproven", total
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    seen += 1
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    total += st.st_blocks * 512
                    newest = max(newest, st.st_mtime, st.st_ctime if st.st_ctime > cutoff else 0.0)
                    if newest > cutoff:
                        return newest, "active", 0
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
        except OSError:
            return newest, "unproven", total
    return newest, "idle", total


def du_kib(path: Path, timeout_s: float = DU_TIMEOUT_S) -> Optional[int]:
    try:
        r = subprocess.run(["du", "-skx", "--", str(path)], capture_output=True, text=True, timeout=timeout_s)
        return int(r.stdout.split()[0]) if r.stdout.split() else None
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def _process_cwds(proc_root: Path) -> set[str]:
    out: set[str] = set()
    try:
        for p in proc_root.iterdir():
            if p.name.isdigit():
                try:
                    out.add(os.readlink(p / "cwd"))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def _in_use(path: Path, cwds: Iterable[str]) -> bool:
    s = os.path.abspath(path)
    return any(c == s or c.startswith(s + os.sep) for c in cwds)


def _size_rows(rows: list[dict], deadline: float, workers: int = 6) -> None:
    def one(r):
        if time.monotonic() > deadline:
            r["size_kib"], r["size_note"] = None, "deadline"
        else:
            r["size_kib"] = du_kib(Path(r["path"]), min(DU_TIMEOUT_S, max(1.0, deadline - time.monotonic())))
            if r["size_kib"] is None:
                r["size_note"] = "du_timeout"
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, rows))


def agent_tmp_report(home: Path, claims_dir: Path, now: float, *, older_than_h: float = OLDER_THAN_H,
                     never_touch=None, proc_root: Path = Path("/proc"), deadline_s: float = DEADLINE_S,
                     stale_hours: float = CLAIM_STALE_H) -> dict:
    """Candidates: ``<owner>/<entry>`` under agent-tmp, idle for ``older_than_h`` by a complete walk, owner with no live
    claim, no process in it, not harness scratch, not never-touch. Everything else is listed under ``held`` with a reason."""
    t0 = time.monotonic()
    deadline = t0 + deadline_s
    root = home / ".cache" / "agent-tmp"
    cutoff = now - older_than_h * 3600
    rep: dict[str, Any] = {"schema": SCHEMA, "section": "agent_tmp", "root": str(root), "older_than_h": older_than_h,
                           "dry_only": True, "candidates": [], "held": [], "unproven": [], "not_scanned": []}
    try:
        live = live_claims(claims_dir, now, stale_hours)
    except ClaimsUnreadable as exc:
        rep["error"] = "claims_unreadable:" + str(exc)
        return rep
    rep["live_claim_count"] = len(live)
    if not root.is_dir() or root.is_symlink():
        rep["error"] = "agent_tmp_root_unavailable"
        return rep
    cwds = _process_cwds(proc_root)
    entries: list[Path] = []
    rep["loose_files"] = 0
    for top in sorted(root.iterdir()):
        if top.is_symlink() or not top.is_dir():
            rep["loose_files"] += 1
            continue
        if not OWNER_RE.match(top.name):
            entries.append(top)
            continue
        try:
            entries += sorted(top.iterdir())
        except OSError:
            rep["held"].append({"path": str(top), "why": "owner_unreadable"})
    todo: list[dict] = []
    for p in entries:
        owner = p.parent.name
        row = {"owner": owner if OWNER_RE.match(owner) and p.parent == root / owner else "(root)", "entry": p.name, "path": str(p)}
        if p.is_symlink():
            rep["held"].append({**row, "why": "symlink"})
        elif p.name in HARNESS_ENTRIES:
            rep["held"].append({**row, "why": "harness_scratch"})
        elif never_touch and never_touch(p):
            rep["held"].append({**row, "why": "never_touch"})
        elif live_claim_hold(p, home, live):
            rep["held"].append({**row, "why": live_claim_hold(p, home, live)})
        elif _in_use(p, cwds):
            rep["held"].append({**row, "why": "in_use_cwd"})
        else:
            todo.append(row)

    def _mt(r):
        try:
            return os.lstat(r["path"]).st_mtime
        except OSError:
            return 0.0
    todo.sort(key=_mt)  # oldest first: the likeliest idle dirs are proven before the deadline

    def prove(row):
        if time.monotonic() > deadline:
            return row, None, "not_scanned", 0
        newest, verdict, size = idle_proof(Path(row["path"]), cutoff, deadline)
        return row, newest, verdict, size

    with ThreadPoolExecutor(max_workers=WALK_WORKERS) as pool:
        results = list(pool.map(prove, todo))
    cands: list[dict] = []
    for row, newest, verdict, size in results:
        if verdict == "idle":
            row["size_kib"] = size // 1024
            row["idle_h"] = round((now - (newest or 0)) / 3600.0, 1)
            cands.append(row)
        elif verdict == "active":
            rep["held"].append({**row, "why": "active_within_%gh" % older_than_h})
        elif verdict == "unproven":
            rep["unproven"].append({**row, "size_kib": size // 1024})
        else:
            rep["not_scanned"].append(row)
    cands.sort(key=lambda r: -(r.get("size_kib") or 0))
    rep["candidates"] = cands
    rep["candidate_kib"] = sum(r.get("size_kib") or 0 for r in cands)
    rep["by_owner_kib"] = {}
    for r in cands:
        rep["by_owner_kib"][r["owner"]] = rep["by_owner_kib"].get(r["owner"], 0) + (r.get("size_kib") or 0)
    rep["elapsed_s"] = round(time.monotonic() - t0, 1)
    return rep


def release_report(home: Path, claims_dir: Path, now: float, *, keep: int = RELEASE_KEEP,
                   root: Optional[Path] = None, proc_root: Path = Path("/proc"), deadline_s: float = DEADLINE_S,
                   stale_hours: float = CLAIM_STALE_H) -> dict:
    """Release dirs beyond the newest ``keep`` (by the timestamp in the name), never the CURRENT target, never one a
    process is running in, never one a live claim names. Report only."""
    t0 = time.monotonic()
    deadline = t0 + deadline_s
    root = root or home / "trade-ai-releases" / "portfolio-server"
    rep: dict[str, Any] = {"schema": SCHEMA, "section": "releases", "root": str(root), "keep_newest": keep,
                           "dry_only": True, "candidates": [], "held": []}
    try:
        live = live_claims(claims_dir, now, stale_hours)
    except ClaimsUnreadable as exc:
        rep["error"] = "claims_unreadable:" + str(exc)
        return rep
    if not root.is_dir():
        rep["error"] = "release_root_unavailable"
        return rep
    current = os.path.realpath(root / "CURRENT") if (root / "CURRENT").exists() else None
    rep["current"] = current
    dirs = [e for e in sorted(root.iterdir()) if e.is_dir() and not e.is_symlink() and RELEASE_TS.search(e.name)]
    dirs.sort(key=lambda p: (RELEASE_TS.search(p.name).group(1), p.name))
    newest = {str(p) for p in dirs[-keep:]} if keep > 0 else set()
    cwds = _process_cwds(proc_root)
    cands: list[dict] = []
    for p in dirs:
        row = {"entry": p.name, "path": str(p)}
        if os.path.realpath(p) == current:
            rep["held"].append({**row, "why": "current"})
        elif str(p) in newest:
            rep["held"].append({**row, "why": "keep_newest_%d" % keep})
        elif _in_use(p, cwds):
            rep["held"].append({**row, "why": "in_use_cwd"})
        elif live_claim_hold(p, home, live):
            rep["held"].append({**row, "why": live_claim_hold(p, home, live)})
        else:
            cands.append(row)
    _size_rows(cands, deadline)
    rep["candidates"] = cands
    rep["candidate_kib"] = sum(r.get("size_kib") or 0 for r in cands)
    rep["elapsed_s"] = round(time.monotonic() - t0, 1)
    return rep


def build_report(home: Path, claims_dir: Path, *, now: Optional[float] = None, never_touch=None, **kw) -> dict:
    now = time.time() if now is None else now
    t0 = time.monotonic()
    a = agent_tmp_report(home, claims_dir, now, never_touch=never_touch, **kw)
    r = release_report(home, claims_dir, now, **{k: v for k, v in kw.items() if k in ("proc_root", "stale_hours")})
    return {"schema": SCHEMA, "dry_only": True, "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "agent_tmp": a, "releases": r, "elapsed_s": round(time.monotonic() - t0, 1)}
