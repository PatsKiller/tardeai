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

Shared-additive paths (``config/agent_claim_shared_paths.json``: docs/INDEX.md, the CC v3 package.json build line,
...): files nearly every PR appends one row to, merged mechanically (regenerate / union / append). A claim on one never
conflicts with another session's claim, and the pre-commit gate treats a staged shared file as covered by any own
active claim. The rest of the change still needs a claim. Missing config means no shared paths (exclusive default).

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
    from scripts.lib import agent_claim_lifecycle as LC
    from scripts.lib import agent_claim_worklog as WL
    from scripts.lib.agent_file_lease import canonicalize_claim_path
except ImportError:  # scripts/ on sys.path (api_v2 inside portfolio_server)
    from lib import agent_claim_lifecycle as LC  # type: ignore[no-redef]
    from lib import agent_claim_worklog as WL  # type: ignore[no-redef]
    from lib.agent_file_lease import canonicalize_claim_path  # type: ignore[no-redef]

SCHEMA = "AgentClaim@v1"
BOARD_SCHEMA = "AgentClaimBoard@v1"
CHECK_SCHEMA = "AgentClaimCheck@v1"
HISTORY_NAME = "claims_history.jsonl"
LOCK_NAME = ".claim.lock"
DEFAULT_STALE_HOURS = 2.0
DEFAULT_COMPACT_DAYS = 7.0
HOLD_MAX_DAYS = 30.0  # a claim held on the board for its PR (pr_open/ci_green/merged) is archived after this anyway
MERGED_UNRELEASED_WARN_DAYS = 3.0
OVERRIDE_SCHEMA = "AgentClaimOverride@v1"
ENV_OVERRIDE = "TRADEAI_CLAIM_OVERRIDE"
ENFORCE_POLICY_VERSION = (20, 0, 0)
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
    """Overlapping (mine, theirs) pairs that CONFLICT. A pair where either side is a shared-additive path
    (``config/agent_claim_shared_paths.json``) never conflicts: two sessions may both claim docs/INDEX.md, and a
    claim on ``docs/**`` does not collide with another session's claim on docs/INDEX.md."""
    shared = shared_paths()
    theirs_l = list(theirs)
    return [(m, t) for m in mine for t in theirs_l if m not in shared and t not in shared and patterns_overlap(m, t)]


# --------------------------------------------------------------------------------------------- shared-additive

SHARED_SCHEMA = "AgentClaimSharedPaths@v1"
ENV_SHARED = "TRADEAI_AGENT_CLAIM_SHARED_PATHS"
SHARED_CONFIG = Path(__file__).resolve().parents[2] / "config" / "agent_claim_shared_paths.json"


def shared_config_path() -> Path:
    env = os.environ.get(ENV_SHARED)
    return Path(env).expanduser() if env else SHARED_CONFIG


@lru_cache(maxsize=8)
def _load_shared(path: str, mtime_ns: int) -> dict[str, dict[str, Any]]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != SHARED_SCHEMA:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for e in doc.get("paths") or []:
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            continue
        try:
            canon = canonical_pattern(e["path"])
        except (ClaimError, ValueError):
            continue
        if is_glob(canon):  # exact paths only: a glob would make a whole tree conflict-free
            continue
        out[canon] = {k: e.get(k) for k in ("path", "merge", "how", "reason")}
    return out


def shared_path_entries() -> dict[str, dict[str, Any]]:
    """Canonical shared-additive path -> its config entry. Missing/unreadable/invalid config -> {} (all exclusive)."""
    p = shared_config_path()
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return {}
    return _load_shared(str(p), mtime)


def shared_paths() -> frozenset[str]:
    return frozenset(shared_path_entries())


def is_shared(path: str) -> bool:
    try:
        return canonical_pattern(path) in shared_paths()
    except (ClaimError, ValueError):
        return False


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
    lifecycle: dict[str, Any] = field(default_factory=dict)

    @property
    def claim_id(self) -> str:
        return str(self.doc.get("claim_id"))

    @property
    def stage(self) -> str:
        return str(self.lifecycle.get("stage") or "claimed")

    @property
    def blocking(self) -> bool:
        """Live and still holding its files. A claim at merged/released has freed its files."""
        return self.state == "live" and self.lifecycle.get("locks_held", True) is not False


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
        observer: "LC.LifecycleObserver | None" = None,
    ):
        self.dir = Path(claims_dir).expanduser() if claims_dir else default_claims_dir()
        self.stale_after = timedelta(
            hours=stale_after_hours if stale_after_hours is not None else default_stale_hours()
        )
        self.compact_after = timedelta(days=compact_after_days)
        self._now = now or utc_now
        self.history = Path(history_path) if history_path else self.dir / HISTORY_NAME
        # Lifecycle observations: sidecar cache files plus (API) in-memory observations; ``observer`` (CLI) is
        # consulted only to refresh claims that block a request, and by sync/compact.
        self.observer = observer
        self.extra_obs: dict[str, dict[str, Any]] = {}

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

    def observations(self) -> dict[str, dict[str, Any]]:
        side = LC.read_sidecars(self.dir)
        for cid, o in self.extra_obs.items():
            side[cid] = LC.merge_obs(side.get(cid), o)
        return side

    def views(self) -> tuple[list[ClaimView], list[str]]:
        docs, bad = self.read_all()
        obs = self.observations() if docs else {}
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
            out.append(
                ClaimView(
                    d,
                    state,
                    age,
                    Path(d["_path"]),
                    takeovers.get(str(d["claim_id"]), []),
                    LC.effective(d, obs.get(str(d["claim_id"]))),
                )
            )
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
        worktree: str | None = None,
        head_sha: str | None = None,
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
                    canon,
                    vendor=vendor,
                    session=session,
                    agent=agent,
                    task=task,
                    branch=branch,
                    pr=pr,
                    note=note,
                    extra={
                        k: v
                        for k, v in (("worktree", clip(worktree, 400)), ("head_sha", head_sha))
                        if v and (k != "head_sha" or LC.SHA_RE.match(v))
                    },
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
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        views, _bad = self.views()
        blocking = self.conflicts(canon, session=session, views=views)
        if blocking and self.refresh_claims([r["claim_id"] for r in blocking]):
            views, _bad = self.views()  # a holder's PR may have merged since: merged claims free their files
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
            **dict(extra or {}),
        }
        if doc.get("head_sha"):
            doc["logged_sha"] = doc["head_sha"]  # commits after this are appended to the worklog by heartbeat
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
        head_sha: str | None = None,
        worktree: str | None = None,
        logged_sha: str | None = None,
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
        if head_sha and LC.SHA_RE.match(head_sha):
            d["head_sha"] = head_sha
            d["head_sha_at"] = d["heartbeat_at"]
        if worktree:
            d["worktree"] = clip(worktree, 400)
        if logged_sha and LC.SHA_RE.match(logged_sha):
            d["logged_sha"] = logged_sha
        _replace_own(v.path, d)
        return d

    def extend(self, claim_id: str, paths: Iterable[str], *, session: str | None) -> dict[str, Any]:
        """``claim --add``: add paths to an own active claim; refused if they overlap another live session's claim."""
        canon = []
        for p in paths:
            c = canonical_pattern(p)
            if c not in canon:
                canon.append(c)
        if not canon:
            raise ClaimError("--add needs at least one path")
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / LOCK_NAME, "a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                v = self._own(claim_id, session, force=False)
                if v.doc.get("status") != "active" or v.taken_over_by:
                    raise ClaimError(f"claim {claim_id} is not an active claim of this session; --add refused")
                blocking = self.conflicts(canon, session=session, exclude_ids=[claim_id])
                if blocking and self.refresh_claims([r["claim_id"] for r in blocking]):
                    blocking = self.conflicts(canon, session=session, exclude_ids=[claim_id])
                if blocking:
                    raise ClaimConflict(describe_conflicts(blocking), blocking)
                d = {k: val for k, val in v.doc.items() if not k.startswith("_")}
                added = [c for c in canon if c not in d["paths"]]
                if len(d["paths"]) + len(added) > MAX_PATHS:
                    raise ClaimError(f"too many paths (> {MAX_PATHS})")
                d["paths"] = list(d["paths"]) + added
                d["heartbeat_at"] = iso(self.now())
                _replace_own(v.path, d)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        if added:
            wl = self.worklog(claim_id)
            if wl.exists():
                try:
                    wl.change("claim extended: " + ", ".join(added))
                except (OSError, WL.WorklogError):
                    pass
        return d

    def worklog(self, claim_id: str) -> "WL.Worklog":
        return WL.Worklog(self.dir, claim_id, now=self.now)

    def _wl_status(self, claim_id: str, text: str, *, auto: bool = False, at: str | None = None) -> None:
        wl = self.worklog(claim_id)
        if wl.exists():
            try:
                wl.status(text, auto=auto, at=at)
            except (OSError, WL.WorklogError):
                pass  # a worklog problem never breaks the claim operation; the board reports the file state

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
        summary: str | None = None,
        require_summary: bool = False,
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
        wl = self.worklog(claim_id)
        if summary is not None or (require_summary and wl.exists()):
            if not (summary or "").strip():
                raise ClaimError("release needs a final summary line for the worklog (--summary '...')")
            if wl.exists():
                wl.final_summary(summary or "", status)
        _replace_own(v.path, d)
        return d

    # -- lifecycle ----------------------------------------------------------------------------------

    def stage(
        self,
        claim_id: str,
        stage: str,
        *,
        session: str | None,
        pr: str | int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Owner declares ``building`` or ``pr_open`` (with a PR). Later stages need evidence (sync)."""
        if stage not in LC.DECLARABLE:
            raise ClaimError(
                f"stage {stage!r} cannot be declared; declare one of {', '.join(LC.DECLARABLE)} "
                "(ci_green, merged and released are observed from GitHub and release receipts: run sync)"
            )
        v = self._own(claim_id, session, force=False)
        if v.doc.get("status") != "active":
            raise ClaimError(f"claim {claim_id} is {v.doc.get('status')}; stage refused")
        if v.taken_over_by:
            raise ClaimError(f"claim {claim_id} was taken over by {', '.join(v.taken_over_by)}; stage refused")
        if stage == "pr_open" and pr in (None, "") and not v.doc.get("pr"):
            raise ClaimError("stage pr_open needs --pr N (or a PR already on the claim)")
        if pr not in (None, "") and LC.pr_number(pr) is None:
            raise ClaimError(f"bad PR {pr!r}; pass the PR number")
        d = {k: val for k, val in v.doc.items() if not k.startswith("_")}
        now = iso(self.now())
        stages = dict(d.get("stages") or {})
        stages.setdefault("claimed", d.get("started_at"))
        stages.setdefault(stage, now)
        if stage == "pr_open":
            stages.setdefault("building", now)
        d["stages"] = stages
        d["stage"] = stage
        d["heartbeat_at"] = now
        if pr not in (None, ""):
            d["pr"] = clip(pr, 40)
        if note is not None:
            d["note"] = clip(note, MAX_NOTE)
        _replace_own(v.path, d)
        self._wl_status(claim_id, f"stage {stage}" + (f" (PR {d['pr']})" if stage == "pr_open" and d.get("pr") else ""))
        return d

    def refresh_claims(self, claim_ids: Iterable[str] | None = None, *, write: bool = True) -> dict[str, Any]:
        """Observe claims (all that need it, or ``claim_ids``) with ``self.observer``; persist to the sidecars."""
        if self.observer is None:
            return {}
        docs, _bad = self.read_all()
        want = set(claim_ids) if claim_ids is not None else None
        docs = [d for d in docs if want is None or d.get("claim_id") in want]
        before = self.observations()
        got, warning = self.observer.observe(docs, before)
        if write and got and self.dir.is_dir():
            LC.write_sidecars(self.dir, got)
            for cid, o in got.items():  # observed stage changes go to the worklog, marked (auto)
                old = (before.get(cid) or {}).get("stages") or {}
                for st in LC.STAGES:
                    at = (o.get("stages") or {}).get(st)
                    if at and st not in old:
                        extra = ""
                        if st == "merged" and o.get("merge_sha"):
                            extra = f" (PR #{o.get('pr_number')} merge {str(o['merge_sha'])[:9]})"
                        elif st == "released" and o.get("released"):
                            extra = f" ({o['released'].get('basis')}, sha {str(o['released'].get('sha'))[:9]})"
                        elif st == "pr_open" and o.get("pr_number"):
                            extra = f" (PR #{o.get('pr_number')})"
                        self._wl_status(cid, f"stage {st} observed{extra}", auto=True, at=at)
        else:
            for cid, o in got.items():
                self.extra_obs[cid] = LC.merge_obs(self.extra_obs.get(cid), o)
        self.last_observe_warning = warning
        return got

    def sync(self, *, apply: bool) -> dict[str, Any]:
        """Auto-advance: observe every claim that needs it; dry run reports the stage changes, apply persists."""
        before = {v.claim_id: v.stage for v in self.views()[0]}
        got = self.refresh_claims(write=apply)
        after = {v.claim_id: v for v in self.views()[0]}
        changes = []
        for cid, v in after.items():
            if before.get(cid) != v.stage:
                changes.append(
                    {
                        "claim_id": cid,
                        "from": before.get(cid),
                        "to": v.stage,
                        "locks_released": before.get(cid) not in LC.FREE_STAGES and v.stage in LC.FREE_STAGES,
                    }
                )
        return {
            "schema": "AgentClaimSync@v1",
            "mode": "apply" if apply else "dry_run",
            "at": iso(self.now()),
            "claims_dir": str(self.dir),
            "observed": len(got),
            "github_warning": getattr(self, "last_observe_warning", None),
            "changes": changes,
            "written": sorted(got) if apply else [],
        }

    # -- compaction ---------------------------------------------------------------------------------

    def compact_plan(self) -> list[dict[str, Any]]:
        """Claims eligible for archive: done/abandoned or stale, with last activity > compact_after."""
        now = self.now()
        plan = []
        for v in self.views()[0]:
            lc = v.lifecycle
            released_at = parse_iso((lc.get("stages") or {}).get("released"))
            last = (
                released_at
                or parse_iso(v.doc.get("ended_at"))
                or parse_iso(v.doc.get("heartbeat_at"))
                or parse_iso(v.doc.get("started_at"))
            )
            if last is None:
                continue
            if v.state == "live" and v.stage != "released":
                continue
            # Work with a PR stays on the board until it is released (or its PR closed unmerged), up to HOLD_MAX_DAYS.
            if v.stage in LC.HOLD_STAGES and lc.get("pr_state") != "closed":
                if now - last <= timedelta(days=HOLD_MAX_DAYS):
                    continue
            if now - last <= self.compact_after:
                continue
            plan.append(
                {
                    "claim_id": v.claim_id,
                    "state": v.state,
                    "stage": v.stage,
                    "last_activity": iso(last),
                    "age_days": round((now - last).total_seconds() / 86400, 2),
                    "path": str(v.path),
                }
            )
        return plan

    def compact(self, *, apply: bool) -> dict[str, Any]:
        if self.observer is not None:  # bring stages up to date first (a released claim becomes eligible)
            self.refresh_claims(write=apply)
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
                    side = LC.lifecycle_dir(self.dir) / f"{item['claim_id']}.json"
                    try:
                        side_doc = json.loads(side.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        side_doc = None
                    rec = {
                        "schema": "AgentClaimArchive@v1",
                        "archived_at": iso(self.now()),
                        "state_at_archive": item["state"],
                        "stage_at_archive": item.get("stage"),
                        "sha256": digest,
                        "claim": doc,
                        "lifecycle": side_doc,
                        "worklog_archive": str(WL.archive_dir(self.dir) / f"{item['claim_id']}{WL.SUFFIX}")
                        if WL.path_for(self.dir, item["claim_id"]).is_file()
                        else None,
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
                        try:  # the worklog is moved to worklog_archive/, never deleted
                            moved = WL.archive(self.dir, item["claim_id"])
                        except OSError as exc:
                            moved = {"error": type(exc).__name__}
                        if moved:
                            result.setdefault("worklogs_archived", []).append({"claim_id": item["claim_id"], **moved})
                        if side_doc is not None:  # its observation cache is in the same archive line
                            try:
                                side.unlink()
                            except FileNotFoundError:
                                pass
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

    def board(
        self, *, include_finished: bool = True, limit: int = 200, lifecycle_meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        views, bad = self.views()
        order = {"live": 0, "stale": 1, "done": 2, "abandoned": 3}
        views.sort(
            key=lambda v: (order.get(v.state, 9), -(parse_iso(v.doc.get("heartbeat_at")) or self.now()).timestamp())
        )
        counts = {k: 0 for k in order}
        stage_counts = {k: 0 for k in LC.ALL_STAGES}
        for v in views:
            counts[v.state] = counts.get(v.state, 0) + 1
            stage_counts[v.stage] = stage_counts.get(v.stage, 0) + 1
        now = self.now()
        # "Finished" = released or abandoned, or done with nothing left to track (no PR awaiting release).
        rows = [
            public_row(v, now)
            for v in views
            if include_finished
            or not (v.stage in ("released", "abandoned") or (v.state == "done" and v.stage not in LC.HOLD_STAGES))
        ]
        return {
            "schema": BOARD_SCHEMA,
            "as_of": iso(self.now()),
            "claims_dir": str(self.dir),
            "dir_present": self.dir.is_dir(),
            "stale_after_hours": round(self.stale_after.total_seconds() / 3600, 3),
            "compact_after_days": round(self.compact_after.total_seconds() / 86400, 3),
            "counts": counts,
            "stages": list(LC.ALL_STAGES),
            "stage_counts": stage_counts,
            "stage_help": dict(LC.STAGE_HELP),
            "lifecycle": lifecycle_meta or {"observed_at": None, "warning": "GitHub not consulted by this reader"},
            "unreadable": bad,
            "shared_paths": shared_path_entries(),  # claims on these never conflict; rows list them under shared_paths
            "truncated": len(rows) > limit,
            "claims": rows[:limit],
        }


# --------------------------------------------------------------------------------------------- render


def row_warnings(v: ClaimView, now: datetime) -> list[str]:
    """Why a card needs a look, most urgent first. Empty when nothing is wrong."""
    lc = v.lifecycle
    out: list[str] = []
    hb_h = None if v.heartbeat_age_s is None else v.heartbeat_age_s / 3600
    if v.taken_over_by:
        out.append(f"taken over by {', '.join(v.taken_over_by)}")
    if v.state == "stale" and lc.get("locks_held") and not v.taken_over_by:
        out.append(
            f"stale: no heartbeat for {hb_h:.1f} h; its files are no longer protected"
            if hb_h is not None
            else "stale: no heartbeat"
        )
    if lc.get("pr_state") == "closed":
        out.append("PR closed without merging")
    ci = lc.get("ci") or {}
    if lc.get("pr_state") == "open" and ci.get("state") == "failing":
        out.append("CI failing: " + ", ".join(ci.get("failing") or [])[:160])
    merged = parse_iso((lc.get("stages") or {}).get("merged"))
    if v.stage == "merged" and merged and (now - merged).total_seconds() > MERGED_UNRELEASED_WARN_DAYS * 86400:
        out.append(f"merged {(now - merged).days} d ago and not live yet")
    return out


def public_row(v: ClaimView, now: datetime | None = None) -> dict[str, Any]:
    d = v.doc
    lc = v.lifecycle
    now = now or utc_now()
    started = parse_iso(d.get("started_at"))
    end = parse_iso((lc.get("stages") or {}).get("released")) or parse_iso(d.get("ended_at"))
    age_s = ((end or now) - started).total_seconds() if started else None
    warns = row_warnings(v, now)
    return {
        "stage": v.stage,
        "stages": dict(lc.get("stages") or {}),
        "locks_held": bool(v.blocking),
        "pr_number": lc.get("pr_number"),
        "pr_url": lc.get("pr_url"),
        "pr_state": lc.get("pr_state"),
        "pr_draft": lc.get("pr_draft"),
        "pr_base": lc.get("pr_base"),
        "head_sha": lc.get("head_sha"),
        "merge_sha": lc.get("merge_sha"),
        "ci": lc.get("ci"),
        "released": lc.get("released"),
        "observed_at": lc.get("observed_at"),
        "observe_warnings": lc.get("observe_warnings") or [],
        "age_minutes": None if age_s is None else round(age_s / 60, 1),
        "stale_warning": warns[0] if warns else None,
        "warnings": warns,
        "worktree": d.get("worktree"),
        "worktree_head_sha": d.get("head_sha"),  # recorded at claim/heartbeat (head_sha above is the PR head)
        "worklog": WL.board_summary(v.path.parent, v.claim_id, now),
        "claim_id": v.claim_id,
        "state": v.state,
        "status": d.get("status"),
        "vendor": d.get("vendor"),
        "session": d.get("session"),
        "agent": d.get("agent"),
        "task": d.get("task"),
        "paths": list(d.get("paths") or []),
        "shared_paths": [p for p in d.get("paths") or [] if p in shared_paths()],
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


# --------------------------------------------------------------------------------------------- pre-commit gate

POLICY_ACTIVE, POLICY_NOT_ACTIVE, POLICY_UNREADABLE = "ACTIVE", "NOT_ACTIVE", "UNREADABLE"
_VERSION_ROW_RE = r"^\|\s*{v}\s*\|[^|]*\|\s*([^|]*)\|"


def _semver(v: str | None) -> tuple[int, int, int] | None:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def claim_policy_state(
    agents_md: Path | str, required: tuple[int, int, int] = ENFORCE_POLICY_VERSION
) -> dict[str, Any]:
    """Is AGENTS.md at ``required`` or later AND ACTIVE? (the ``or_later`` reading of policy_state).

    ACTIVE needs all three: the control block's Policy-Version >= required, its Status ACTIVE, and that version's
    version-history row beginning with ACTIVE. Read at call time, no cache, no environment override. Unreadable or
    unparseable is not active (the gate then only warns)."""
    req = ".".join(map(str, required))
    try:
        text = Path(agents_md).read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "state": POLICY_UNREADABLE,
            "enforce": False,
            "required": req,
            "version": None,
            "detail": f"{agents_md}: {type(exc).__name__}",
        }
    block = re.search(r"```\n(Policy-Version:.*?)```", text, re.DOTALL)
    fields: dict[str, str] = {}
    for line in (block.group(1) if block else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
    version, status = fields.get("Policy-Version"), fields.get("Status", "")
    sv = _semver(version)
    base = {"required": req, "version": version, "header_status": status or None}
    if sv is None:
        return {
            **base,
            "state": POLICY_UNREADABLE,
            "enforce": False,
            "detail": "no Policy-Version in the control block",
        }
    if sv < required:
        return {**base, "state": POLICY_NOT_ACTIVE, "enforce": False, "detail": f"AGENTS.md {version} is below {req}"}
    if not status.upper().startswith("ACTIVE"):
        return {
            **base,
            "state": POLICY_NOT_ACTIVE,
            "enforce": False,
            "detail": f"AGENTS.md {version} header is {status!r}",
        }
    row = re.search(_VERSION_ROW_RE.format(v=re.escape(version or "")), text, re.M)
    if not row or not row.group(1).strip().upper().startswith("ACTIVE"):
        return {
            **base,
            "state": POLICY_NOT_ACTIVE,
            "enforce": False,
            "detail": f"AGENTS.md {version} version-history row is not ACTIVE",
        }
    return {**base, "state": POLICY_ACTIVE, "enforce": True, "detail": f"AGENTS.md {version} ACTIVE (>= {req})"}


def log_override(board: ClaimBoard, record: Mapping[str, Any]) -> None:
    """Append one AgentClaimOverride@v1 line to claims_history.jsonl (fsynced, under the history lock)."""
    board.history.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"schema": OVERRIDE_SCHEMA, **record}, sort_keys=True) + "\n"
    with open(board.history.with_name(board.history.name + ".lock"), "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            fd = os.open(str(board.history), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def precommit_gate(
    board: ClaimBoard,
    paths: Iterable[str],
    *,
    session: str | None,
    vendor: str | None,
    branch: str | None,
    agents_md: Path | str,
    override: str | None = None,
) -> dict[str, Any]:
    """The staged-file gate. Below AGENTS.md 20.0.0 ACTIVE: report and exit 0. From 20.0.0 ACTIVE: exit 1 when a
    staged file is held by another session's live claim or is not covered by one of this session's own claims,
    unless ``TRADEAI_CLAIM_OVERRIDE=<reason>`` is set -- then exit 0 and the bypass is logged to the history."""
    policy = claim_policy_state(agents_md)
    enforce = bool(policy.get("enforce"))
    res: dict[str, Any] = {
        "schema": "AgentClaimPrecommit@v1",
        "at": iso(board.now()),
        "mode": "enforce" if enforce else "warn",
        "policy": policy,
        "session": session,
        "branch": branch,
        "conflicts": [],
        "uncovered": [],
        "worklog_issues": [],
        "override": None,
        "exit_code": 0,
        "messages": [],
    }
    msgs = res["messages"]
    try:
        staged = [canonical_pattern(p) for p in paths]
        rows = board.conflicts(staged, session=session, branch=branch)
        if rows and board.refresh_claims([r["claim_id"] for r in rows]):
            rows = board.conflicts(staged, session=session, branch=branch)
        views = board.views()[0]
        own = [
            v
            for v in views
            if ClaimBoard._is_mine(v.doc, session, branch)
            and v.doc.get("status") == "active"
            and not v.taken_over_by
            and v.lifecycle.get("locks_held", True) is not False
        ]
        # A shared-additive staged file (docs/INDEX.md, ...) is covered by ANY own active claim: the committer must
        # still hold a claim for the change, but need not have listed the shared file in it.
        shared = shared_paths()
        uncovered = [
            p
            for p in staged
            if not (own if p in shared else any(patterns_overlap(p, q) for v in own for q in v.doc.get("paths") or []))
        ]
        # Worklog discipline: every own claim covering a staged file needs a plan and an agent entry in the last 2 h.
        now = board.now()
        worklog_issues = []
        for v in own:
            if not any(patterns_overlap(p, q) for p in staged for q in v.doc.get("paths") or []):
                continue
            w = WL.board_summary(board.dir, v.claim_id, now)
            why = None
            if not w.get("exists"):
                why = "has no worklog"
            elif not w.get("plan_total"):
                why = "worklog has no plan (agent_claim.py plan <id> '<step>')"
            elif w.get("last_entry_age_minutes") is None or w["last_entry_age_minutes"] > WL.FRESH_HOURS * 60:
                why = f"no worklog entry in the last {WL.FRESH_HOURS:g} h (plan/done/note/blocker)"
            if why:
                worklog_issues.append({"claim_id": v.claim_id, "issue": why})
    except (ClaimError, ValueError, OSError) as exc:
        msgs.append(f"agent-claim: gate could not evaluate ({type(exc).__name__}: {exc})")
        if not enforce:
            return res
        res["exit_code"] = 1
        if override:
            try:
                log_override(
                    board,
                    {
                        "at": res["at"],
                        "reason": clip(override, MAX_NOTE),
                        "session": session,
                        "vendor": vendor,
                        "branch": branch,
                        "error": type(exc).__name__,
                        "policy_version": policy.get("version"),
                    },
                )
                res["exit_code"] = 0
                msgs.append(f"OVERRIDE: {ENV_OVERRIDE} set -- commit allowed; logged to {board.history}")
                return res
            except OSError:
                pass
        msgs.append(
            f"BLOCK: AGENTS.md {policy.get('version')} is ACTIVE and the claim gate failed closed; "
            f"set {ENV_OVERRIDE}=<reason> to bypass (logged)"
        )
        return res
    res["conflicts"], res["uncovered"], res["worklog_issues"] = rows, uncovered, worklog_issues
    tag = "BLOCK" if enforce else "WARN"
    for w in worklog_issues:
        msgs.append(f"{tag}: claim {w['claim_id']} {w['issue']}")
    for r in rows:
        held = ", ".join(sorted({o["held"] for o in r.get("overlaps") or []}))
        mine = ", ".join(sorted({o["path"] for o in r.get("overlaps") or []}))
        msgs.append(
            f"{tag}: {mine} held by {r.get('vendor')}/{r.get('agent') or '-'} session {r.get('session')} on branch "
            f"{r.get('branch') or '?'} since {r.get('started_at')} (claim {r.get('claim_id')}; claimed {held}; "
            f"task: {r.get('task')})"
        )
    if uncovered:
        msgs.append(
            f"{tag}: no claim of this session ({session or 'no AGENT_CLAIM_SESSION'}, branch {branch or '?'}) covers: "
            + ", ".join(uncovered[:20])
            + (f" +{len(uncovered) - 20}" if len(uncovered) > 20 else "")
        )
        msgs.append("       claim them first: python3 scripts/agent_claim.py claim --task '...' --paths <files>")
    if not rows and not uncovered and not worklog_issues:
        return res
    if not enforce:
        msgs.append(
            f"agent-claim: warn-only ({policy.get('detail')}); commit continues. "
            f"From AGENTS.md 20.0.0 ACTIVE this blocks."
        )
        return res
    reason = clip(override, MAX_NOTE) if override else None
    if reason:
        record = {
            "at": res["at"],
            "reason": reason,
            "session": session,
            "vendor": vendor,
            "branch": branch,
            "host": clip(socket.gethostname(), 80),
            "policy_version": policy.get("version"),
            "paths": staged[:MAX_PATHS],
            "uncovered": uncovered[:MAX_PATHS],
            "worklog_issues": worklog_issues,
            "conflicts": [
                {k: r.get(k) for k in ("claim_id", "vendor", "session", "branch", "started_at")} for r in rows
            ],
        }
        try:
            log_override(board, record)
        except OSError as exc:
            msgs.append(
                f"BLOCK: {ENV_OVERRIDE} set but the override could not be logged ({type(exc).__name__}); "
                "an unlogged bypass is refused"
            )
            res["exit_code"] = 1
            return res
        res["override"] = record
        msgs.append(f"OVERRIDE: {ENV_OVERRIDE}={reason!r} -- commit allowed; logged to {board.history}")
        return res
    msgs.append(
        f"agent-claim: commit blocked (AGENTS.md {policy.get('version')} ACTIVE). Coordinate with the holder, "
        f"claim your files, or set {ENV_OVERRIDE}=<reason> (logged)."
    )
    res["exit_code"] = 1
    return res


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


_API_OBSERVER: "LC.CachedObserver | None" = None


def _api_observer() -> "LC.CachedObserver":
    global _API_OBSERVER
    if _API_OBSERVER is None:
        repo = LC.default_repo()
        _API_OBSERVER = LC.CachedObserver(lambda: LC.LifecycleObserver(LC.GitHubReader(repo), LC.ReleaseReader()))
        _API_OBSERVER.repo = repo  # type: ignore[attr-defined]
    return _API_OBSERVER


def board_view(
    claims_dir: Path | str | None = None,
    *,
    include_finished: bool = True,
    observer: "LC.CachedObserver | None" = None,
    background: bool = True,
    worklog: str | None = None,
) -> dict[str, Any]:
    """Read-only projection served by GET /api/v2/coordination/claims. Never creates the directory and never writes:
    lifecycle observations come from the sidecar cache plus an in-memory cache refreshed in a background thread
    (GitHub GETs with a timeout; a request never waits on GitHub)."""
    board = ClaimBoard(claims_dir)
    if worklog is not None:  # ?worklog=<claim_id>: one claim's worklog text (live file, else its archive)
        found = WL.read_any(board.dir, worklog) if valid_claim_id(worklog) else None
        return {
            "schema": "AgentClaimWorklog@v1",
            "claim_id": worklog,
            "found": found is not None,
            "path": found[0] if found else None,
            "text": found[1] if found else None,
            "summary": WL.summarize(found[1]) if found else None,
        }
    docs, _bad = board.read_all()
    cache = observer or _api_observer()
    obs, meta = cache.snapshot(docs, LC.read_sidecars(board.dir) if docs else {}, background=background)
    board.extra_obs = obs
    meta["repo"] = getattr(cache, "repo", None)
    out = board.board(include_finished=include_finished, lifecycle_meta=meta)
    try:  # the task board (additive): free / taken / in_progress / done
        try:
            from scripts.lib import agent_task_board as TB
        except ImportError:
            from lib import agent_task_board as TB  # type: ignore[no-redef]
        out["task_board"] = TB.TaskBoard(board).board()
    except Exception as exc:  # noqa: BLE001 - the claim board must still render
        out["task_board"] = {"error": type(exc).__name__, "tasks": []}
    return out
