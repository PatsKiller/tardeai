"""Local-only remote-push budget. State lives under the git COMMON dir, never in source.

v2 (2026-10-21, Release Train v2 Phase 0 item 3). v1 kept one counter in the per-worktree
git dir (`git rev-parse --absolute-git-dir`, i.e. `.git/worktrees/<name>/` for a linked
worktree), keyed on the checked-out branch, and reset it whenever HEAD's branch changed. A
fresh worktree -- or a branch switch -- therefore started at 0 pushes. v2:

* keys every counter on (`git rev-parse --git-common-dir`, pushed branch), stored in ONE file
  in the common dir, so every worktree of the repository shares it;
* takes the pushed branch from the pre-push hook's stdin refs (`<local ref> <local sha>
  <remote ref> <remote sha>`), not from HEAD -- `git push origin other-branch` is counted
  against other-branch; HEAD is only the fallback when no refs are given;
* never resets: v1 files (the common-dir one and every `worktrees/*/` one) are read-only
  floors, added to the v2 count of the branch they name -- an older hook still running in
  another worktree keeps counting;
* a guard git-push grant no longer lifts the cap by itself: only a grant whose reason says
  "override" (or the operator's TRADEAI_REMOTE_PUSH_OVERRIDE=1) does (grant_overrides_budget).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

MAX_WITHOUT_OVERRIDE = 2
STATE_NAME = "tradeai-push-budget.json"          # v1 name: read-only legacy floor
STATE_NAME_V2 = "tradeai-push-budget.v2.json"
LOCK_NAME_V2 = "tradeai-push-budget.v2.lock"
SCHEMA_V2 = "TradeAIPushBudget@v2"
# The v2 counter file is private state of the pre-push hook: this module both writes and reads it, and no other
# component consumes it (2026-10-21, guard grant mechanics).
NO_CONSUMER_REASON = "private state of the pre-push budget hook; written and read only by this module"
ZERO_SHA = "0" * 40

# Time-boxed program exceptions to the default budget (AI_WORK_POLICY.md §3/§17).
# A branch gets `budget` authorized pushes only when its name starts with `prefix`
# (exact, case-sensitive, no glob), has at least one character after the prefix,
# and `now` is not later than `ends_at`. Everything else gets MAX_WITHOUT_OVERRIDE.
PROGRAM_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "prefix": "n8nmat/",
        "budget": 4,
        "ends_at": "2026-10-12T23:59:59-04:00",
        "policy": "AGENTS.md 4.1.0 §23.13",
    },
)

_OVERRIDE_WORD = re.compile(r"(?<![A-Za-z0-9_])override(?![A-Za-z0-9_])", re.IGNORECASE)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()


def git_dir() -> Path:
    """The per-worktree git dir (v1 location; kept for callers and legacy reads)."""
    return Path(_git("rev-parse", "--absolute-git-dir"))


def common_dir() -> Path:
    """The repository's common git dir: identical for every worktree of the repository."""
    try:
        out = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    except (subprocess.CalledProcessError, OSError):
        out = _git("rev-parse", "--git-common-dir")
    p = Path(out)
    if not p.is_absolute():
        p = Path(_git("rev-parse", "--show-toplevel")) / p
    return p.resolve()


def current_branch() -> str:
    try:
        return _git("rev-parse", "--abbrev-ref", "HEAD")
    except (subprocess.CalledProcessError, OSError):
        return "HEAD"


def state_path() -> Path:
    override = os.environ.get("TRADEAI_PUSH_BUDGET_PATH")
    if override:
        return Path(override)
    return common_dir() / STATE_NAME_V2


def _common_key() -> str:
    override = os.environ.get("TRADEAI_PUSH_BUDGET_PATH")
    if override:
        return str(Path(override).resolve().parent)
    return str(common_dir())


def counter_key(branch: str, common: str | None = None) -> str:
    """The counter's identity: git common dir + pushed branch."""
    return f"{common if common is not None else _common_key()}#{branch}"


# --------------------------------------------------------------------------- pushed refs


def branch_of_ref(remote_ref: str) -> str:
    ref = str(remote_ref or "").strip()
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def parse_push_refs(text: str | None) -> list[dict[str, Any]]:
    """git's pre-push stdin: one `<local ref> <local sha> <remote ref> <remote sha>` per line."""
    refs = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        refs.append({
            "local_ref": local_ref, "local_sha": local_sha, "remote_ref": remote_ref, "remote_sha": remote_sha,
            "branch": branch_of_ref(remote_ref), "delete": local_sha == ZERO_SHA,
        })
    return refs


def pushed_branches(text: str | None) -> list[str]:
    """Branches this push writes, from the hook's stdin; HEAD's branch only when stdin names none."""
    out: list[str] = []
    for r in parse_push_refs(text):
        if r["branch"] and r["branch"] not in out:
            out.append(r["branch"])
    return out or [current_branch()]


# --------------------------------------------------------------------------- state


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _legacy_paths(state: Path) -> list[Path]:
    """Every v1 counter file this repository may hold. Read-only; never rewritten or removed."""
    paths: list[Path] = []
    if os.environ.get("TRADEAI_PUSH_BUDGET_PATH"):
        paths.append(state)  # tests point the override at a file that may still be v1
        return paths
    try:
        cdir = common_dir()
    except (subprocess.CalledProcessError, OSError):
        return paths
    paths.append(cdir / STATE_NAME)
    wt = cdir / "worktrees"
    if wt.is_dir():
        paths.extend(sorted(wt.glob(f"*/{STATE_NAME}")))
    return paths


def legacy_counts(state: Path | None = None) -> dict[str, int]:
    """Branch -> pushes recorded by v1 files (summed across worktrees)."""
    state = state or state_path()
    out: dict[str, int] = {}
    for p in _legacy_paths(state):
        data = _read_json(p)
        if not isinstance(data, dict) or data.get("schema") == SCHEMA_V2:
            continue
        branch = data.get("tranche_id") or data.get("last_branch")
        try:
            n = int(data.get("authorized_push_count") or 0)
        except (TypeError, ValueError):
            continue
        if branch and n > 0:
            out[str(branch)] = out.get(str(branch), 0) + n
    return out


def _load_v2(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if isinstance(data, dict) and data.get("schema") == SCHEMA_V2 and isinstance(data.get("counters"), dict):
        return data
    return {"schema": SCHEMA_V2, "counters": {}}


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / LOCK_NAME_V2
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _own_count(data: dict[str, Any], branch: str) -> int:
    rec = data["counters"].get(counter_key(branch)) or {}
    try:
        return int(rec.get("authorized_push_count") or 0)
    except (TypeError, ValueError):
        return 0


def count_for(branch: str) -> int:
    """Authorized pushes recorded for `branch` in this repository (all worktrees, v1 floors included)."""
    path = state_path()
    return _own_count(_load_v2(path), branch) + legacy_counts(path).get(branch, 0)


def load_state(branch: str | None = None) -> dict[str, Any]:
    """v1-shaped view for one branch (default: HEAD's) -- callers that print a status."""
    branch = branch or current_branch()
    rec = (_load_v2(state_path())["counters"].get(counter_key(branch)) or {})
    return {
        "tranche_id": branch,
        "counter_key": counter_key(branch),
        "authorized_push_count": count_for(branch),
        "last_push_at": rec.get("last_push_at"),
        "last_branch": branch if rec else None,
    }


def save_state(data: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def record_authorized_push(branch: str | None = None, *, sha: str | None = None) -> dict[str, Any]:
    """Count one authorized push of `branch` (default: HEAD's), under a lock, in the common dir."""
    branch = branch or current_branch()
    path = state_path()
    with _locked(path):
        data = _load_v2(path)
        if os.environ.get("TRADEAI_PUSH_BUDGET_PATH") and not _read_json(path) == data:
            # The override file still holds v1 content: carry its count once as this branch's floor
            # (the v1 file is replaced by v2 here, so the floor must move into the v2 row).
            for b, n in legacy_counts(path).items():
                key = counter_key(b)
                if key not in data["counters"]:
                    data["counters"][key] = {"branch": b, "authorized_push_count": n, "migrated_from": "v1"}
        key = counter_key(branch)
        rec = dict(data["counters"].get(key) or {})
        rec["branch"] = branch
        rec["authorized_push_count"] = int(rec.get("authorized_push_count") or 0) + 1
        rec["last_push_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if sha:
            rec["last_sha"] = sha
        data["counters"][key] = rec
        save_state(data)
    return load_state(branch)


# --------------------------------------------------------------------------- decision


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        # Naive datetimes are treated as UTC so the comparison never raises.
        return now.replace(tzinfo=timezone.utc)
    return now


def budget_for(branch: str | None, now: datetime | None = None) -> int:
    """Authorized pushes allowed for `branch` at `now` before an override is needed."""
    if not branch:
        return MAX_WITHOUT_OVERRIDE
    at = _now(now)
    for window in PROGRAM_WINDOWS:
        prefix = str(window["prefix"])
        if not branch.startswith(prefix) or len(branch) <= len(prefix):
            continue
        if at > datetime.fromisoformat(str(window["ends_at"])):
            continue
        return int(window["budget"])
    return MAX_WITHOUT_OVERRIDE


def remaining(count: int, *, branch: str | None = None, now: datetime | None = None) -> int:
    left = budget_for(branch, now) - int(count or 0)
    return left if left > 0 else 0


def grant_overrides_budget(reason: str | None) -> bool:
    """A guard git-push grant lifts the per-branch cap only when its reason says "override"."""
    return bool(_OVERRIDE_WORD.search(str(reason or "")))


def decide(
    *,
    authorized: bool,
    override: bool,
    count: int,
    branch: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    budget = budget_for(branch, now)
    if not authorized:
        return {
            "allow": False,
            "reason": "UNAUTHORIZED",
            "count": count,
            "remaining": remaining(count, branch=branch, now=now),
            "budget": budget,
        }
    if count >= budget and not override:
        return {
            "allow": False,
            "reason": "BUDGET_EXCEEDED",
            "count": count,
            "remaining": 0,
            "budget": budget,
        }
    return {
        "allow": True,
        "reason": "OVERRIDE" if (count >= budget and override) else "AUTHORIZED",
        "count": count,
        "remaining": remaining(count, branch=branch, now=now) if count < budget else 0,
        "budget": budget,
    }


def decide_push(
    branches: Iterable[str],
    *,
    authorized: bool,
    env_override: bool,
    grant_reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The hook's decision over every pushed branch: all must be allowed."""
    override = bool(env_override) or grant_overrides_budget(grant_reason)
    per = []
    for b in branches:
        c = count_for(b)
        per.append({**decide(authorized=authorized, override=override, count=c, branch=b, now=now),
                    "branch": b, "state_count": c, "counter_key": counter_key(b)})
    blocked = next((d for d in per if not d["allow"]), None)
    head = blocked or (per[0] if per else decide(authorized=authorized, override=override, count=0))
    return {"allow": blocked is None and bool(per), "reason": head["reason"], "branch": head.get("branch"),
            "state_count": head.get("state_count", 0), "budget": head["budget"], "override": override,
            "override_source": ("env" if env_override else "grant_reason") if override else None,
            "branches": per}
