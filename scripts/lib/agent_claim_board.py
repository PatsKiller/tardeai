"""Multi-vendor agent claim board: who is working on which files, one JSON file per claim.

Operator-approved design (2026-10-22). Vendor-neutral: Claude, Codex and Cursor sessions are equal
peers; there is no master agent and no coordinator process. Every agent reads the same directory and
refuses to start on files another live session has claimed.

Store (``claims_dir``; default ``~/trade-ai-releases/persistent-state/data/coordination/claims/``,
override ``--claims-dir`` or ``TRADEAI_AGENT_CLAIMS_DIR``)::

    <claims_dir>/<claim_id>.json        one AgentClaim@v1 per claim, owned by the session that made it
    <claims_dir>/claims_history.jsonl   append-only archive written by ``compact`` (the durable copy)

No shared-file writes on the claim path. A claim file is created atomically: written to a unique temp
opened ``O_CREAT|O_EXCL``, fsynced, then ``os.link``-ed to its final name (``link`` fails instead of
clobbering, so two writers can never overwrite one claim). Heartbeat / release rewrite only the
caller's own file (temp + ``os.replace``). Only ``compact`` touches the history file, under an flock.

Mutual exclusion (two agents claiming overlapping paths at the same instant): scan + create run under an
flock on ``<claims_dir>/.claim.lock`` (an empty file, never written). As a fallback for a filesystem that
ignores flock, each claimant also re-scans after writing. If an overlapping live claim from another session sorts earlier by
``(started_at, claim_id)``, the later claimant withdraws its own claim (status ``abandoned``, note
``lost race``) and reports the conflict. Every claimant computes the same order, so at most one of
any overlapping set stays active.

Stale: an ``active`` claim with no heartbeat for ``stale_after_hours`` (default 2) no longer blocks.
A new claim over it records ``takeover_of``; the stale owner's next heartbeat is refused.

Compaction (``compact``): ``done`` / ``abandoned`` claims, and ``active`` claims stale for more than
``compact_after_days`` (default 7), are appended to ``claims_history.jsonl`` (fsynced, read back), and
only then is the claim file removed. Looking up a compacted claim id answers from the history: the
archived path trips loudly instead of reading as "never existed".

Paths are repo-relative POSIX paths or globs (``*`` within a segment, ``**`` across segments, ``?``,
``[...]``). Claiming a directory claims everything under it. Overlap between two globs is decided
conservatively (may report overlap for two globs that share no real file; never misses a real one
within the supported syntax).

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY for every agent action it gates — it writes coordination
files only; no broker, no DB, no Telegram, no scheduler, no remote.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:  # repo root on sys.path
    from scripts.lib.agent_file_lease import canonicalize_claim_path
except ImportError:  # scripts/ on sys.path (api_v2 inside portfolio_server)
    from lib.agent_file_lease import canonicalize_claim_path  # type: ignore[no-redef]

SCHEMA = "AgentClaim@v1"
BOARD_SCHEMA = "AgentClaimBoard@v1"
CHECK_SCHEMA = "AgentClaimCheck@v1"
HISTORY_NAME = "claims_history.jsonl"
LOCK_NAME = ".claim.lock"
DEFAULT_STALE_HOURS = 2.0
DEFAULT_COMPACT_DAYS = 7.0
STATUSES = ("active", "done", "abandoned")
VENDORS_KNOWN = ("claude", "codex", "cursor")  # display hint only; any vendor string is accepted
MAX_CLAIM_FILES_READ = 2000
MAX_NOTE = 500
MAX_TEXT = 300
MAX_PATHS = 200
ENV_DIR = "TRADEAI_AGENT_CLAIMS_DIR"
ENV_STALE = "TRADEAI_AGENT_CLAIMS_STALE_HOURS"
ENV_SESSION = "AGENT_CLAIM_SESSION"
ENV_VENDOR = "AGENT_CLAIM_VENDOR"
ENV_AGENT = "AGENT_CLAIM_AGENT"

_CLAIM_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-z0-9_.-]{1,24}-[0-9a-f]{8}$")
_SLUG_RE = re.compile(r"[^a-z0-9_.-]+")
_GLOB_CHARS = set("*?[")


class ClaimError(Exception):
    """A refused or invalid claim-board operation (usage, ownership, not found)."""


class ClaimConflict(ClaimError):
    """Paths overlap a live claim held by another session."""

    def __init__(self, message: str, conflicts: list[dict[str, Any]]):
        super().__init__(message)
        self.conflicts = conflicts


# --------------------------------------------------------------------------------------------- time


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------------------------- paths


def default_claims_dir() -> Path:
    env = os.environ.get(ENV_DIR)
    if env:
        return Path(env).expanduser()
    try:
        from scripts.lib.persistent_state_root import good_persistent_root
    except ImportError:
        try:
            from lib.persistent_state_root import good_persistent_root  # type: ignore[no-redef]
        except ImportError:  # pragma: no cover - both layouts ship the module
            return Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "coordination" / "claims"
    return Path(good_persistent_root()) / "data" / "coordination" / "claims"


def default_stale_hours() -> float:
    try:
        return float(os.environ.get(ENV_STALE) or DEFAULT_STALE_HOURS)
    except ValueError:
        return DEFAULT_STALE_HOURS


def is_glob(pattern: str) -> bool:
    return any(c in _GLOB_CHARS for c in pattern)


def canonical_pattern(p: str) -> str:
    """Repo-relative canonical form (no absolute, no ``..``, no control chars). Globs pass through."""
    canon = canonicalize_claim_path(p)
    if len(canon) > 400:
        raise ClaimError(f"path too long: {p[:60]!r}...")
    return canon


@lru_cache(maxsize=4096)
def _segment_regex(seg: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = seg.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = seg[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def _literal_prefix(seg: str) -> str:
    for i, c in enumerate(seg):
        if c in _GLOB_CHARS:
            return seg[:i]
    return seg


def _literal_suffix(seg: str) -> str:
    for i in range(len(seg) - 1, -1, -1):
        if seg[i] in _GLOB_CHARS or seg[i] == "]":
            return seg[i + 1 :]
    return seg


def _segments_may_intersect(a: str, b: str) -> bool:
    """Can one path segment match both patterns? Exact when either is literal; conservative otherwise."""
    if a == b:
        return True
    a_glob, b_glob = is_glob(a), is_glob(b)
    if not a_glob and not b_glob:
        return False
    if not a_glob:
        return bool(_segment_regex(b).match(a))
    if not b_glob:
        return bool(_segment_regex(a).match(b))
    pa, pb = _literal_prefix(a), _literal_prefix(b)
    if not (pa.startswith(pb) or pb.startswith(pa)):
        return False
    sa, sb = _literal_suffix(a), _literal_suffix(b)
    return sa.endswith(sb) or sb.endswith(sa)


def _dirlike(seg: str) -> bool:
    """Could this segment name a directory? A dot after the first character reads as a file name (x.py)."""
    return seg in ("", "**") or "." not in seg.lstrip(".")


@lru_cache(maxsize=8192)
def _intersect(
    a: tuple[str, ...],
    b: tuple[str, ...],
    a_eaten: bool = False,
    a_last: str = "",
    b_eaten: bool = False,
    b_last: str = "",
) -> bool:
    """Could some path fall under both segment patterns?

    A pattern that runs out claims everything beneath what it matched (a directory claim), so running out is an
    overlap -- conservatively, for a plain prefix (``scripts/lib`` vs ``scripts/lib/x.py``). When the other side's
    ``**`` ate the exhausted side's last segment, the remainder would have to live *below* that segment, which is
    only possible if it can be a directory (``apps/**/*.tsx`` does not overlap ``apps/x/y.ts``)."""
    if not a and not b:
        return True
    if not a:
        if all(seg == "**" for seg in b):
            return True
        return _dirlike(a_last) if a_eaten else True
    if not b:
        if all(seg == "**" for seg in a):
            return True
        return _dirlike(b_last) if b_eaten else True
    if a[0] == "**":
        return _intersect(a[1:], b, False, "**", b_eaten, b_last) or _intersect(a, b[1:], a_eaten, a_last, True, b[0])
    if b[0] == "**":
        return _intersect(a, b[1:], a_eaten, a_last, False, "**") or _intersect(a[1:], b, True, a[0], b_eaten, b_last)
    if not _segments_may_intersect(a[0], b[0]):
        return False
    return _intersect(a[1:], b[1:], False, a[0], False, b[0])


def patterns_overlap(a: str, b: str) -> bool:
    """True when a file could fall under both claims (exact, parent/child directory, or glob match)."""
    ca, cb = canonical_pattern(a), canonical_pattern(b)
    if ca == cb:
        return True
    return _intersect(tuple(ca.split("/")), tuple(cb.split("/")))


def overlapping_pairs(mine: Iterable[str], theirs: Iterable[str]) -> list[tuple[str, str]]:
    theirs_l = list(theirs)
    return [(m, t) for m in mine for t in theirs_l if patterns_overlap(m, t)]


# --------------------------------------------------------------------------------------------- identity


def detect_vendor(env: Mapping[str, str] | None = None) -> str:
    """Best-effort vendor hint from the environment. Every vendor is an equal peer; this is a label."""
    env = os.environ if env is None else env
    if env.get(ENV_VENDOR):
        return slug(env[ENV_VENDOR])
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if any(k.startswith("CODEX_") for k in env):
        return "codex"
    if any(k.startswith("CURSOR_") for k in env) or env.get("TERM_PROGRAM", "").lower() == "cursor":
        return "cursor"
    return "unknown"


def detect_session(env: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    for key in (ENV_SESSION, "CLAUDE_SESSION_ID", "CODEX_SESSION_ID", "CURSOR_SESSION_ID"):
        if env.get(key):
            return clip(env[key], 120)
    return None


def slug(value: str) -> str:
    s = _SLUG_RE.sub("-", str(value).strip().lower()).strip("-")
    return (s or "unknown")[:24]


def clip(value: Any, n: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).strip()
    return s[:n] if s else None


def current_branch(cwd: Path | str | None = None) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    b = out.stdout.strip()
    return b if out.returncode == 0 and b and b != "HEAD" else None


def new_claim_id(vendor: str, now: datetime) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{slug(vendor)}-{secrets.token_hex(4)}"


def valid_claim_id(claim_id: str) -> bool:
    return bool(_CLAIM_ID_RE.match(claim_id or ""))


# --------------------------------------------------------------------------------------------- store


@dataclass
class ClaimView:
    """A claim plus its derived state at ``now`` (live | stale | done | abandoned)."""

    doc: dict[str, Any]
    state: str
    heartbeat_age_s: float | None
    path: Path
    taken_over_by: list[str] = field(default_factory=list)

    @property
    def claim_id(self) -> str:
        return str(self.doc.get("claim_id"))

    @property
    def blocking(self) -> bool:
        return self.state == "live"


def _fsync_dir(d: Path) -> None:
    try:
        fd = os.open(str(d), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_exclusive(target: Path, doc: Mapping[str, Any]) -> None:
    """Create ``target`` atomically; FileExistsError if it already exists. Never clobbers."""
    tmp = target.parent / f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(str(tmp), str(target))  # atomic, fails with FileExistsError instead of replacing
    finally:
        try:
            os.unlink(str(tmp))  # our own temp only
        except FileNotFoundError:
            pass
    _fsync_dir(target.parent)


def _replace_own(target: Path, doc: Mapping[str, Any]) -> None:
    tmp = target.parent / f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(target))
    _fsync_dir(target.parent)


class ClaimBoard:
    def __init__(
        self,
        claims_dir: Path | str | None = None,
        *,
        stale_after_hours: float | None = None,
        compact_after_days: float = DEFAULT_COMPACT_DAYS,
        now: Callable[[], datetime] | None = None,
        history_path: Path | str | None = None,
    ):
        self.dir = Path(claims_dir).expanduser() if claims_dir else default_claims_dir()
        self.stale_after = timedelta(
            hours=stale_after_hours if stale_after_hours is not None else default_stale_hours()
        )
        self.compact_after = timedelta(days=compact_after_days)
        self._now = now or utc_now
        self.history = Path(history_path) if history_path else self.dir / HISTORY_NAME

    # -- reading ------------------------------------------------------------------------------------

    def now(self) -> datetime:
        return self._now()

    def claim_path(self, claim_id: str) -> Path:
        if not valid_claim_id(claim_id):
            raise ClaimError(f"bad claim id {claim_id!r}")
        return self.dir / f"{claim_id}.json"

    def read_all(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Every readable claim doc, plus a list of unreadable file names (reported, never dropped silently)."""
        if not self.dir.is_dir():
            return [], []
        docs: list[dict[str, Any]] = []
        bad: list[str] = []
        for i, p in enumerate(sorted(self.dir.glob("*.json"))):
            if i >= MAX_CLAIM_FILES_READ:
                bad.append(f"truncated_after_{MAX_CLAIM_FILES_READ}")
                break
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(d, dict) or d.get("schema") != SCHEMA or d.get("claim_id") != p.stem:
                    raise ValueError("not an AgentClaim@v1 named by its claim_id")
                d["_path"] = str(p)
                docs.append(d)
            except (OSError, ValueError):
                bad.append(p.name)
        return docs, bad

    def views(self) -> tuple[list[ClaimView], list[str]]:
        docs, bad = self.read_all()
        now = self.now()
        takeovers: dict[str, list[str]] = {}
        for d in docs:
            if d.get("status") == "active":
                for t in d.get("takeover_of") or []:
                    tid = t.get("claim_id") if isinstance(t, dict) else t
                    if tid:
                        takeovers.setdefault(str(tid), []).append(str(d["claim_id"]))
        out: list[ClaimView] = []
        for d in docs:
            hb = parse_iso(d.get("heartbeat_at")) or parse_iso(d.get("started_at"))
            age = (now - hb).total_seconds() if hb else None
            status = d.get("status")
            if status == "active":
                state = "live" if age is not None and age <= self.stale_after.total_seconds() else "stale"
                if takeovers.get(str(d["claim_id"])):
                    state = "stale"
            else:
                state = status if status in STATUSES else "abandoned"
            out.append(ClaimView(d, state, age, Path(d["_path"]), takeovers.get(str(d["claim_id"]), [])))
        return out, bad

    def get(self, claim_id: str) -> ClaimView:
        p = self.claim_path(claim_id)
        for v in self.views()[0]:
            if v.path == p:
                return v
        archived = self.find_in_history(claim_id)
        if archived is not None:
            raise ClaimError(
                f"claim {claim_id} was compacted into {self.history} (line {archived[0]}, status "
                f"{archived[1].get('status')!r}); it is archived and can no longer be changed"
            )
        raise ClaimError(f"claim {claim_id} not found in {self.dir}")

    def find_in_history(self, claim_id: str) -> tuple[int, dict[str, Any]] | None:
        if not self.history.is_file():
            return None
        found = None
        with self.history.open("r", encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if claim_id not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if (rec.get("claim") or {}).get("claim_id") == claim_id:
                    found = (n, rec.get("claim") or {})
        return found

    # -- conflicts ----------------------------------------------------------------------------------

    @staticmethod
    def _is_mine(doc: Mapping[str, Any], session: str | None, branch: str | None) -> bool:
        if session and doc.get("session") == session:
            return True
        if branch and doc.get("branch") == branch:
            return True
        return False

    def conflicts(
        self,
        paths: Iterable[str],
        *,
        session: str | None = None,
        branch: str | None = None,
        views: list[ClaimView] | None = None,
        exclude_ids: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """Live claims of OTHER sessions/branches that overlap ``paths``."""
        mine = [canonical_pattern(p) for p in paths]
        skip = set(exclude_ids)
        out = []
        for v in views if views is not None else self.views()[0]:
            if not v.blocking or v.claim_id in skip or self._is_mine(v.doc, session, branch):
                continue
            pairs = overlapping_pairs(mine, v.doc.get("paths") or [])
            if pairs:
                out.append(conflict_row(v, pairs))
        return out

    # -- writing ------------------------------------------------------------------------------------

    def claim(
        self,
        *,
        vendor: str,
        session: str,
        agent: str | None,
        task: str,
        paths: Iterable[str],
        branch: str | None = None,
        pr: str | int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if not session:
            raise ClaimError("session is required (--session or AGENT_CLAIM_SESSION)")
        if not task or not str(task).strip():
            raise ClaimError("task is required")
        canon: list[str] = []
        for p in paths:
            c = canonical_pattern(p)
            if c not in canon:
                canon.append(c)
        if not canon:
            raise ClaimError("at least one path or glob is required")
        if len(canon) > MAX_PATHS:
            raise ClaimError(f"too many paths ({len(canon)} > {MAX_PATHS}); claim a directory or glob instead")

        self.dir.mkdir(parents=True, exist_ok=True)
        # Primary serialization: an flock on an empty lock file (never written) around scan + create, so two
        # claimants on this host cannot both pass the scan. The post-write re-scan below is the fallback for a
        # filesystem that ignores flock.
        with open(self.dir / LOCK_NAME, "a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._claim_locked(
                    canon, vendor=vendor, session=session, agent=agent, task=task, branch=branch, pr=pr, note=note
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _claim_locked(
        self,
        canon: list[str],
        *,
        vendor: str,
        session: str,
        agent: str | None,
        task: str,
        branch: str | None,
        pr: str | int | None,
        note: str | None,
    ) -> dict[str, Any]:
        views, _bad = self.views()
        blocking = self.conflicts(canon, session=session, views=views)
        if blocking:
            raise ClaimConflict(describe_conflicts(blocking), blocking)

        # Stale claims of other sessions that overlap: claimable, takeover recorded.
        takeover = []
        for v in views:
            if v.state != "stale" or v.doc.get("session") == session:
                continue
            if overlapping_pairs(canon, v.doc.get("paths") or []):
                takeover.append(
                    {
                        "claim_id": v.claim_id,
                        "vendor": v.doc.get("vendor"),
                        "session": v.doc.get("session"),
                        "agent": v.doc.get("agent"),
                        "branch": v.doc.get("branch"),
                        "heartbeat_at": v.doc.get("heartbeat_at"),
                    }
                )

        now = self.now()
        vendor_s = slug(vendor or "unknown")
        doc: dict[str, Any] = {
            "schema": SCHEMA,
            "claim_id": "",
            "vendor": vendor_s,
            "session": clip(session, 120),
            "agent": clip(agent, 120),
            "task": clip(task),
            "paths": canon,
            "branch": clip(branch, 200),
            "pr": clip(pr, 40) if pr not in (None, "") else None,
            "started_at": iso(now),
            "heartbeat_at": iso(now),
            "status": "active",
            "note": clip(note, MAX_NOTE),
            "host": clip(socket.gethostname(), 80),
            "takeover_of": takeover,
        }
        for _attempt in range(5):
            doc["claim_id"] = new_claim_id(vendor_s, now)
            try:
                _write_exclusive(self.claim_path(doc["claim_id"]), doc)
                break
            except FileExistsError:
                continue
        else:  # pragma: no cover - 32 random bits, five tries
            raise ClaimError("could not allocate a unique claim id")

        # Race resolution: an overlapping live claim from another session that sorts earlier wins.
        my_key = (doc["started_at"], doc["claim_id"])
        rivals = []
        for row in self.conflicts(canon, session=session, exclude_ids=[doc["claim_id"]]):
            if (row["started_at"] or "", row["claim_id"]) < my_key:
                rivals.append(row)
        if rivals:
            lost = dict(doc)
            lost["status"] = "abandoned"
            lost["ended_at"] = iso(self.now())
            lost["note"] = clip(
                f"lost race to {rivals[0]['claim_id']}" + (f"; {doc['note']}" if doc["note"] else ""), MAX_NOTE
            )
            _replace_own(self.claim_path(doc["claim_id"]), lost)
            raise ClaimConflict(describe_conflicts(rivals), rivals)
        return doc

    def _own(self, claim_id: str, session: str | None, force: bool) -> ClaimView:
        v = self.get(claim_id)
        owner = v.doc.get("session")
        if not force and (not session or owner != session):
            raise ClaimError(
                f"claim {claim_id} belongs to session {owner!r}, not {session!r} "
                "(pass the owning --session; --force records who overrode it)"
            )
        return v

    def heartbeat(
        self,
        claim_id: str,
        *,
        session: str | None,
        pr: str | int | None = None,
        note: str | None = None,
        branch: str | None = None,
    ) -> dict[str, Any]:
        v = self._own(claim_id, session, force=False)
        if v.doc.get("status") != "active":
            raise ClaimError(f"claim {claim_id} is {v.doc.get('status')}; heartbeat refused")
        if v.taken_over_by:
            raise ClaimError(
                f"claim {claim_id} went stale and was taken over by {', '.join(v.taken_over_by)}; "
                "stop and coordinate before touching these paths"
            )
        if v.state == "stale":
            # Heartbeat after going stale: allowed only when nobody overlapping took the paths meanwhile.
            others = self.conflicts(v.doc.get("paths") or [], session=v.doc.get("session"), exclude_ids=[claim_id])
            if others:
                raise ClaimConflict(
                    f"claim {claim_id} went stale and its paths are now claimed: " + describe_conflicts(others), others
                )
        d = {k: val for k, val in v.doc.items() if not k.startswith("_")}
        d["heartbeat_at"] = iso(self.now())
        if pr not in (None, ""):
            d["pr"] = clip(pr, 40)
        if note is not None:
            d["note"] = clip(note, MAX_NOTE)
        if branch:
            d["branch"] = clip(branch, 200)
        _replace_own(v.path, d)
        return d

    def release(
        self,
        claim_id: str,
        *,
        session: str | None,
        status: str = "done",
        note: str | None = None,
        pr: str | int | None = None,
        force: bool = False,
        released_by: str | None = None,
    ) -> dict[str, Any]:
        if status not in ("done", "abandoned"):
            raise ClaimError("release status must be done or abandoned")
        v = self._own(claim_id, session, force=force)
        if v.doc.get("status") != "active":
            raise ClaimError(f"claim {claim_id} is already {v.doc.get('status')}")
        d = {k: val for k, val in v.doc.items() if not k.startswith("_")}
        d["status"] = status
        d["ended_at"] = iso(self.now())
        if note is not None:
            d["note"] = clip(note, MAX_NOTE)
        if pr not in (None, ""):
            d["pr"] = clip(pr, 40)
        if force and session != v.doc.get("session"):
            d["released_by"] = clip(released_by or session or "unknown", 120)
        _replace_own(v.path, d)
        return d

    # -- compaction ---------------------------------------------------------------------------------

    def compact_plan(self) -> list[dict[str, Any]]:
        """Claims eligible for archive: done/abandoned or stale, with last activity > compact_after."""
        now = self.now()
        plan = []
        for v in self.views()[0]:
            last = (
                parse_iso(v.doc.get("ended_at"))
                or parse_iso(v.doc.get("heartbeat_at"))
                or parse_iso(v.doc.get("started_at"))
            )
            if last is None or v.state == "live":
                continue
            if now - last <= self.compact_after:
                continue
            plan.append(
                {
                    "claim_id": v.claim_id,
                    "state": v.state,
                    "last_activity": iso(last),
                    "age_days": round((now - last).total_seconds() / 86400, 2),
                    "path": str(v.path),
                }
            )
        return plan

    def compact(self, *, apply: bool) -> dict[str, Any]:
        plan = self.compact_plan()
        result: dict[str, Any] = {
            "schema": "AgentClaimCompaction@v1",
            "mode": "apply" if apply else "dry_run",
            "at": iso(self.now()),
            "claims_dir": str(self.dir),
            "history": str(self.history),
            "eligible": len(plan),
            "archived": 0,
            "removed": 0,
            "skipped": [],
            "items": plan,
        }
        if not apply or not plan:
            return result
        self.history.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.history.with_name(self.history.name + ".lock")
        with open(lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                for item in plan:
                    p = Path(item["path"])
                    try:
                        raw = p.read_bytes()
                        doc = json.loads(raw)
                    except (OSError, ValueError) as exc:
                        result["skipped"].append({"claim_id": item["claim_id"], "reason": type(exc).__name__})
                        continue
                    digest = hashlib.sha256(raw).hexdigest()
                    rec = {
                        "schema": "AgentClaimArchive@v1",
                        "archived_at": iso(self.now()),
                        "state_at_archive": item["state"],
                        "sha256": digest,
                        "claim": doc,
                    }
                    line = json.dumps(rec, sort_keys=True) + "\n"
                    fd = os.open(str(self.history), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                    try:
                        os.write(fd, line.encode("utf-8"))
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    result["archived"] += 1
                    # Durable copy proven before the original goes: read it back.
                    if not self._history_has(item["claim_id"], digest):
                        result["skipped"].append({"claim_id": item["claim_id"], "reason": "archive_not_readable"})
                        continue
                    try:
                        if p.read_bytes() != raw:  # changed while archiving: keep the live file
                            result["skipped"].append({"claim_id": item["claim_id"], "reason": "changed_during_archive"})
                            continue
                        p.unlink()
                        result["removed"] += 1
                    except FileNotFoundError:
                        result["skipped"].append({"claim_id": item["claim_id"], "reason": "already_gone"})
                _fsync_dir(self.dir)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return result

    def _history_has(self, claim_id: str, digest: str) -> bool:
        try:
            with self.history.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if digest in line and claim_id in line:
                        rec = json.loads(line)
                        if rec.get("sha256") == digest and (rec.get("claim") or {}).get("claim_id") == claim_id:
                            return True
        except (OSError, ValueError):
            return False
        return False

    # -- read model (API / list) ---------------------------------------------------------------------

    def board(self, *, include_finished: bool = True, limit: int = 200) -> dict[str, Any]:
        views, bad = self.views()
        order = {"live": 0, "stale": 1, "done": 2, "abandoned": 3}
        views.sort(
            key=lambda v: (order.get(v.state, 9), -(parse_iso(v.doc.get("heartbeat_at")) or self.now()).timestamp())
        )
        counts = {k: 0 for k in order}
        for v in views:
            counts[v.state] = counts.get(v.state, 0) + 1
        rows = [public_row(v) for v in views if include_finished or v.state in ("live", "stale")]
        return {
            "schema": BOARD_SCHEMA,
            "as_of": iso(self.now()),
            "claims_dir": str(self.dir),
            "dir_present": self.dir.is_dir(),
            "stale_after_hours": round(self.stale_after.total_seconds() / 3600, 3),
            "compact_after_days": round(self.compact_after.total_seconds() / 86400, 3),
            "counts": counts,
            "unreadable": bad,
            "truncated": len(rows) > limit,
            "claims": rows[:limit],
        }


# --------------------------------------------------------------------------------------------- render


def public_row(v: ClaimView) -> dict[str, Any]:
    d = v.doc
    return {
        "claim_id": v.claim_id,
        "state": v.state,
        "status": d.get("status"),
        "vendor": d.get("vendor"),
        "session": d.get("session"),
        "agent": d.get("agent"),
        "task": d.get("task"),
        "paths": list(d.get("paths") or []),
        "branch": d.get("branch"),
        "pr": d.get("pr"),
        "started_at": d.get("started_at"),
        "heartbeat_at": d.get("heartbeat_at"),
        "ended_at": d.get("ended_at"),
        "heartbeat_age_minutes": None if v.heartbeat_age_s is None else round(v.heartbeat_age_s / 60, 1),
        "note": d.get("note"),
        "host": d.get("host"),
        "takeover_of": [t.get("claim_id") if isinstance(t, dict) else t for t in d.get("takeover_of") or []],
        "taken_over_by": list(v.taken_over_by),
    }


def conflict_row(v: ClaimView, pairs: list[tuple[str, str]]) -> dict[str, Any]:
    d = v.doc
    return {
        "source": "claim",
        "claim_id": v.claim_id,
        "vendor": d.get("vendor"),
        "session": d.get("session"),
        "agent": d.get("agent"),
        "task": d.get("task"),
        "branch": d.get("branch"),
        "pr": d.get("pr"),
        "started_at": d.get("started_at"),
        "heartbeat_at": d.get("heartbeat_at"),
        "overlaps": [{"path": a, "held": b} for a, b in pairs],
    }


def describe_conflicts(rows: list[dict[str, Any]]) -> str:
    parts = []
    for r in rows:
        held = ", ".join(sorted({o["held"] for o in r.get("overlaps") or []}))
        if r.get("source") == "draft_pr":
            parts.append(f"draft PR #{r.get('pr')} ({r.get('branch')}) changes {held}")
        else:
            who = f"{r.get('vendor')}/{r.get('agent') or r.get('session')}"
            parts.append(
                f"{who} holds {held} on branch {r.get('branch') or '?'} since {r.get('started_at')} "
                f"(claim {r.get('claim_id')}; task: {r.get('task')})"
            )
    return "; ".join(parts)


# --------------------------------------------------------------------------------------------- draft PRs


def draft_pr_conflicts(
    paths: Iterable[str],
    *,
    exclude_branch: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    timeout_s: float = 15.0,
    cwd: Path | str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Open draft PRs whose changed files overlap ``paths`` -- the fallback for cloud agents that cannot
    reach the host claims dir. Returns (conflicts, warning). Never raises: gh missing, offline or
    unauthenticated yields a warning, not a failure."""
    mine = [canonical_pattern(p) for p in paths]
    run = runner or subprocess.run
    cmd = [
        "gh",
        "pr",
        "list",
        "--draft",
        "--state",
        "open",
        "--limit",
        "100",
        "--json",
        "number,headRefName,title,author,url,files",
    ]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd)
    except FileNotFoundError:
        return [], "gh not installed: open draft PRs were not consulted"
    except subprocess.TimeoutExpired:
        return [], f"gh timed out after {timeout_s:g}s: open draft PRs were not consulted"
    except OSError as exc:
        return [], f"gh failed ({type(exc).__name__}): open draft PRs were not consulted"
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return (
            [],
            f"gh exited {proc.returncode} ({err[0][:120] if err else 'no stderr'}): open draft PRs were not consulted",
        )
    try:
        prs = json.loads(proc.stdout or "[]")
    except ValueError:
        return [], "gh returned unparseable JSON: open draft PRs were not consulted"
    out = []
    for pr in prs if isinstance(prs, list) else []:
        branch = pr.get("headRefName")
        if exclude_branch and branch == exclude_branch:
            continue
        files = []
        for f in pr.get("files") or []:
            fp = f.get("path") if isinstance(f, dict) else f
            if not fp:
                continue
            try:
                files.append(canonical_pattern(fp))
            except ValueError:
                continue
        pairs = overlapping_pairs(mine, files)
        if pairs:
            out.append(
                {
                    "source": "draft_pr",
                    "pr": pr.get("number"),
                    "branch": branch,
                    "title": clip(pr.get("title"), 160),
                    "author": (pr.get("author") or {}).get("login") if isinstance(pr.get("author"), dict) else None,
                    "url": pr.get("url"),
                    "overlaps": [{"path": a, "held": b} for a, b in pairs],
                }
            )
    return out, None


# --------------------------------------------------------------------------------------------- API


def board_view(claims_dir: Path | str | None = None, *, include_finished: bool = True) -> dict[str, Any]:
    """Read-only projection served by GET /api/v2/coordination/claims. Never creates the directory."""
    return ClaimBoard(claims_dir).board(include_finished=include_finished)
