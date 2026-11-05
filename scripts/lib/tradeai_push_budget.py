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

Hands-off delivery (AGENTS.md 20.4.0, 2026-10-25; inert until 20.4.0 is ACTIVE on origin/main):

* budget 2 -> HANDS_OFF_BUDGET (5) per branch, read from ``origin/main:AGENTS.md`` through
  ``scripts/lib/hands_off_policy.py`` (never the pushing branch's own AGENTS.md, no env switch);
* TRADEAI_REMOTE_PUSH_OVERRIDE=1 past that budget is accepted WITHOUT a fresh interactive operator
  approval only for the coordinator (``coordinator_override``): TRADEAI_COORDINATOR_SESSION names a
  LIVE coordinator claim on the claim board (path ``coordination/COORDINATOR``), equals
  AGENT_CLAIM_SESSION when that is set, and the pushed branch carries an operator approval reference
  (an ``Operator-approval:`` line in its open PR's body, or in the note / worklog plan of the
  coordinator's own live claim on that branch). Otherwise the env override means what it meant
  before: the operator's explicit, interactive approval (AI_WORK_POLICY.md §3);
* every override that is USED (count at or past the budget) is appended to
  ``<git common dir>/tradeai-push-overrides.jsonl`` (``log_override``), with its source;
* a push that is not a fast-forward of the remote branch (a force push) or deletes a remote branch is
  refused whenever an override is used or 20.4.0 is ACTIVE (``force_push_refusals``) -- no override,
  coordinator or not, ever authorizes one.
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
HANDS_OFF_BUDGET = 5  # AGENTS.md 20.4.0 (hands-off delivery); only while 20.4.0 is ACTIVE on origin/main
OVERRIDE_LOG_NAME = "tradeai-push-overrides.jsonl"
OVERRIDE_LOG_SCHEMA = "TradeAIPushOverride@v1"
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


def budget_for(branch: str | None, now: datetime | None = None, *, hands_off: bool = False) -> int:
    """Authorized pushes allowed for `branch` at `now` before an override is needed.

    ``hands_off`` (AGENTS.md 20.4.0 ACTIVE on origin/main) raises the default to HANDS_OFF_BUDGET; a larger
    program window still wins."""
    floor = HANDS_OFF_BUDGET if hands_off else MAX_WITHOUT_OVERRIDE
    if not branch:
        return floor
    at = _now(now)
    for window in PROGRAM_WINDOWS:
        prefix = str(window["prefix"])
        if not branch.startswith(prefix) or len(branch) <= len(prefix):
            continue
        if at > datetime.fromisoformat(str(window["ends_at"])):
            continue
        return max(int(window["budget"]), floor)
    return floor


def remaining(count: int, *, branch: str | None = None, now: datetime | None = None, hands_off: bool = False) -> int:
    left = budget_for(branch, now, hands_off=hands_off) - int(count or 0)
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
    hands_off: bool = False,
) -> dict[str, Any]:
    budget = budget_for(branch, now, hands_off=hands_off)
    if not authorized:
        return {
            "allow": False,
            "reason": "UNAUTHORIZED",
            "count": count,
            "remaining": remaining(count, branch=branch, now=now, hands_off=hands_off),
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
        "remaining": remaining(count, branch=branch, now=now, hands_off=hands_off) if count < budget else 0,
        "budget": budget,
    }


def decide_push(
    branches: Iterable[str],
    *,
    authorized: bool,
    env_override: bool,
    grant_reason: str | None = None,
    now: datetime | None = None,
    hands_off: bool = False,
    coordinator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The hook's decision over every pushed branch: all must be allowed.

    ``coordinator`` is ``coordinator_override(...)``'s verdict: when it is ``ok`` and the env override is
    set, the override is the coordinator's (no fresh interactive approval needed under 20.4.0)."""
    override = bool(env_override) or grant_overrides_budget(grant_reason)
    if env_override:
        source = "coordinator" if (hands_off and coordinator and coordinator.get("ok")) else "env"
    else:
        source = "grant_reason"
    per = []
    for b in branches:
        c = count_for(b)
        per.append({**decide(authorized=authorized, override=override, count=c, branch=b, now=now,
                             hands_off=hands_off),
                    "branch": b, "state_count": c, "counter_key": counter_key(b)})
    blocked = next((d for d in per if not d["allow"]), None)
    head = blocked or (per[0] if per else decide(authorized=authorized, override=override, count=0,
                                                 hands_off=hands_off))
    return {"allow": blocked is None and bool(per), "reason": head["reason"], "branch": head.get("branch"),
            "state_count": head.get("state_count", 0), "budget": head["budget"], "override": override,
            "override_source": source if override else None,
            "override_used": any(d["reason"] == "OVERRIDE" for d in per),
            "hands_off": bool(hands_off), "branches": per}


# --------------------------------------------------------------------------- hands-off delivery (AGENTS.md 20.4.0)


def _hands_off_module():
    """scripts/lib/hands_off_policy.py, or None (a checkout without it is simply not hands-off)."""
    try:
        from scripts.lib import hands_off_policy as H  # type: ignore
    except ImportError:
        try:
            from lib import hands_off_policy as H  # type: ignore[no-redef]
        except ImportError:
            return None
    return H


def hands_off_state(ref: str = "origin/main") -> dict[str, Any]:
    """20.4.0 state from ``<ref>:AGENTS.md`` (main's ratified text, never this branch's own edit)."""
    H = _hands_off_module()
    if H is None:
        return {"active": False, "state": "UNAVAILABLE", "detail": "scripts/lib/hands_off_policy.py not present"}
    try:
        return H.policy_state_from_git(ref)
    except Exception as exc:  # fail closed: pre-20.4.0 behaviour
        return {"active": False, "state": "UNREADABLE", "detail": type(exc).__name__}


def _is_ancestor(old: str, new: str, runner=subprocess.run) -> bool | None:
    """True/False when git can tell; None when an object is missing (not fetched) or git fails."""
    try:
        cp = runner(["git", "merge-base", "--is-ancestor", old, new], capture_output=True, text=True,
                    timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode == 0:
        return True
    if cp.returncode == 1:
        return False
    return None


def force_push_refusals(refs: Iterable[dict[str, Any]], *, is_ancestor=_is_ancestor) -> list[dict[str, str]]:
    """Refs this push would rewrite or delete: a remote branch deletion, or a non-fast-forward update
    (the remote tip is not an ancestor of the pushed tip, or cannot be proven to be -- fetch first)."""
    out = []
    for r in refs:
        branch = str(r.get("branch") or "")
        if r.get("delete"):
            out.append({"branch": branch, "why": "deletes the remote branch"})
            continue
        remote = str(r.get("remote_sha") or "")
        if not remote or remote == ZERO_SHA:
            continue  # a new remote branch
        verdict = is_ancestor(remote, str(r.get("local_sha") or ""))
        if verdict is False:
            out.append({"branch": branch, "why": f"not a fast-forward of the remote tip {remote[:9]} (force push)"})
        elif verdict is None:
            out.append({"branch": branch,
                        "why": f"cannot prove a fast-forward of the remote tip {remote[:9]} (git fetch first)"})
    return out


def _gh_pr_bodies(branch: str, runner=subprocess.run) -> list[dict[str, Any]] | None:
    """Open PRs whose head is ``branch`` (GET only), or None when GitHub could not be read."""
    try:
        cp = runner(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,body,headRefName",
                     "--limit", "5"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    try:
        rows = json.loads(cp.stdout or "[]")
    except ValueError:
        return None
    return [r for r in rows if isinstance(r, dict) and r.get("headRefName") == branch]


def coordinator_override(
    branches: Iterable[str],
    *,
    env: dict[str, str] | None = None,
    claim_rows: list[dict[str, Any]] | None = None,
    pr_reader=_gh_pr_bodies,
    worklog_reader=None,
) -> dict[str, Any]:
    """May TRADEAI_REMOTE_PUSH_OVERRIDE stand without a fresh interactive operator approval? (20.4.0)

    ok only when ALL hold: TRADEAI_COORDINATOR_SESSION is set and names a LIVE coordinator claim on the claim
    board; AGENT_CLAIM_SESSION, when set, is that same session (the pushing session IS the coordinator); and EVERY
    pushed branch carries an operator approval reference -- an ``Operator-approval:`` line in its open PR's body,
    or in the note / worklog plan of the coordinator's own live claim on that branch."""
    env = dict(os.environ if env is None else env)
    H = _hands_off_module()
    session = (env.get("TRADEAI_COORDINATOR_SESSION") or "").strip()
    base: dict[str, Any] = {"ok": False, "session": session or None, "approvals": {}}
    if H is None:
        return {**base, "why": "hands_off_policy unavailable"}
    if not session:
        return {**base, "why": "TRADEAI_COORDINATOR_SESSION is not set"}
    pushing = (env.get("AGENT_CLAIM_SESSION") or "").strip()
    if pushing and pushing != session:
        return {**base, "why": f"AGENT_CLAIM_SESSION {pushing!r} is not the coordinator session"}
    if claim_rows is None:
        try:
            claim_rows = H._claim_rows(env.get("TRADEAI_AGENT_CLAIMS_DIR") or None)
        except Exception as exc:
            return {**base, "why": f"claim board unreadable ({type(exc).__name__})"}
    claim = H.coordinator_session_ok(session, claim_rows, live_only=True)
    if not claim:
        return {**base, "why": f"no LIVE coordinator claim ({H.COORDINATOR_CLAIM_PATH}) held by session {session!r}"}
    base["coordinator_claim"] = claim.get("claim_id")
    if worklog_reader is None:
        worklog_reader = H.default_worklog_reader(None)
    approvals: dict[str, dict[str, Any]] = {}
    for b in branches:
        ref, source = None, None
        prs = pr_reader(b)
        for pr in prs or []:
            ref = H.approval_ref(str(pr.get("body") or ""))
            if ref:
                source = f"pr#{pr.get('number')} body"
                break
        if not ref:
            ref = H.claim_plan_approval(claim_rows, session=session, branch=b, worklog_reader=worklog_reader)
            source = "claim plan" if ref else None
        if not ref:
            why = "GitHub unreadable and " if prs is None else ""
            return {**base, "approvals": approvals,
                    "why": f"branch {b!r}: {why}no Operator-approval: reference in its PR body or the coordinator's claim plan"}
        approvals[b] = {"ref": ref, "source": source}
    return {**base, "ok": True, "approvals": approvals, "why": "coordinator with operator approval reference"}


def override_log_path() -> Path:
    override = os.environ.get("TRADEAI_PUSH_OVERRIDE_LOG")
    if override:
        return Path(override)
    return state_path().parent / OVERRIDE_LOG_NAME


def log_override(record: dict[str, Any]) -> dict[str, Any]:
    """Append one TradeAIPushOverride@v1 line (fsynced, under the budget lock). Append-only; never rewritten."""
    path = override_log_path()
    row = {"schema": OVERRIDE_LOG_SCHEMA, "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           **record}
    with _locked(state_path()):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    return row


def hook_decision(
    push_refs_text: str | None,
    *,
    authorized: bool,
    env_override: bool,
    grant_reason: str | None = None,
    env: dict[str, str] | None = None,
    hands_off: dict[str, Any] | None = None,
    coordinator_fn=coordinator_override,
    force_fn=force_push_refusals,
) -> dict[str, Any]:
    """Everything the pre-push hook decides, in one place (the hook only prints and exits)."""
    env = dict(os.environ if env is None else env)
    state = hands_off if hands_off is not None else hands_off_state()
    active = bool(state.get("active"))
    branches = pushed_branches(push_refs_text)
    first = decide_push(branches, authorized=authorized, env_override=env_override, grant_reason=grant_reason,
                        hands_off=active)
    coord: dict[str, Any] | None = None
    if active and env_override and first.get("override_used"):
        coord = coordinator_fn(branches, env=env)
    d = decide_push(branches, authorized=authorized, env_override=env_override, grant_reason=grant_reason,
                    hands_off=active, coordinator=coord) if coord is not None else first
    d = {**d, "hands_off_state": {k: state.get(k) for k in ("state", "detail", "version", "source")},
         "coordinator": coord}
    if d["allow"] and (d.get("override_used") or active):
        refused = force_fn(parse_push_refs(push_refs_text))
        if refused:
            d = {**d, "allow": False, "reason": "FORCE_PUSH_REFUSED", "force": refused}
    return d
