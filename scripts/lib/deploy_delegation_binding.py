"""Deploy-delegation release binding for the host ``deploy_on_main`` poller (AGENTS.md §25.10, §24.8).

The poller runs ``cio_phase2_exact_main_deploy.sh`` prepare+promote, whose preflight
(``scripts/release_grant_preflight.py``) refuses unless a ``release-write`` grant names the
SHA. Under 24.0.0 the poller's authority is the operator's armed standing **deploy**
delegation, not a per-SHA grant; without this module the poller only ever promoted when a
human-requested grant happened to exist (refused every poll from 2026-10-27 13:34Z).

This binding is accepted (``matched_by: deploy_delegation``) ONLY when every condition holds:

1. ``prepare`` or ``promote``; no emergency / train / campaign variable is set (those paths
   keep their own grant rules unchanged).
2. A poller ticket exists at ``<release_window state dir>/deploy_delegation_ticket.json``
   (``DeployDelegationTicket@v1``), written by the poller only while it holds
   GlobalReleaseLock, naming exactly this SHA, younger than ``TICKET_TTL_S``, and the
   ``TRADEAI_DEPLOY_DELEGATION_NONCE`` in this process's environment hashes to its nonce.
3. The ticket's pid is an ancestor of this process, runs inside the poller's systemd unit
   (``tradeai-deploy-on-main.service`` cgroup), and holds the GlobalReleaseLock flock
   (``/proc/locks``).
4. STOP latch is ABSENT; the host deploy delegation file is ``ACTIVE`` with
   ``scope: promote_only`` (the lab ``TRADEAI_DEPLOY_DELEGATION_SOFT`` switch never counts).
5. The SHA equals ``origin/main`` in the canonical checkout and main's required push checks
   are green for that exact SHA.

Agents, n8n and Mergify cannot satisfy (2)-(3): they are not the poller unit's process
holding the lock. Same-uid processes are not a hard security boundary on this host
(see feedback: guard grants are not enforced for Claude Code); this is fail-closed
attribution, the same standard as the rest of the release path. Emergency is unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

TICKET_SCHEMA = "DeployDelegationTicket@v1"
TICKET_NAME = "deploy_delegation_ticket.json"
TICKET_ENV = "TRADEAI_DEPLOY_DELEGATION_TICKET"
NONCE_ENV = "TRADEAI_DEPLOY_DELEGATION_NONCE"
TICKET_TTL_S = 1200  # prepare + promote inside one poller run (unit TimeoutStartSec=900)
POLLER_UNIT = "tradeai-deploy-on-main.service"
MATCHED_BY = "deploy_delegation"
#: Any of these means a different release path; the delegation never binds it.
FOREIGN_PATH_ENV = ("TRADEAI_EMERGENCY_RELEASE_SHA", "TRADEAI_RELEASE_TRAIN_SHA", "TRADEAI_RELEASE_CAMPAIGN")


@dataclass(frozen=True)
class DelegationVerdict:
    allowed: bool
    reason: str
    matched_by: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "DeployDelegationBinding@v1", "allowed": self.allowed, "reason": self.reason,
                "matched_by": list(self.matched_by), "detail": dict(self.detail)}


def _refuse(reason: str, **detail: Any) -> DelegationVerdict:
    return DelegationVerdict(False, reason, [], detail)


def _hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def ticket_path(state_dir: Path) -> Path:
    return Path(state_dir) / TICKET_NAME


# ── issued by the poller (inside GlobalReleaseLock) ──────────────────────────────────────────────


def issue_ticket(state_dir: Path, sha: str, *, pid: Optional[int] = None, now: Optional[float] = None) -> tuple[Path, str]:
    """Write the one-run ticket; return (path, nonce). The nonce travels only in the child env."""
    nonce = secrets.token_hex(24)
    path = ticket_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": TICKET_SCHEMA,
        "sha": sha,
        "pid": int(pid if pid is not None else os.getpid()),
        "created_at": float(now if now is not None else time.time()),
        "nonce_sha256": _hash_nonce(nonce),
        "unit": POLLER_UNIT,
    }
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(body, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return path, nonce


def revoke_ticket(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


# ── host readers (injectable for tests) ─────────────────────────────────────────────────────────


def proc_ancestors(pid: int) -> list[int]:
    """pid, its parent, … up to 1 (read from /proc)."""
    out: list[int] = []
    cur = int(pid)
    for _ in range(128):
        out.append(cur)
        if cur <= 1:
            break
        try:
            stat = Path(f"/proc/{cur}/stat").read_text(encoding="utf-8")
            cur = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def proc_cgroup(pid: int) -> str:
    try:
        return Path(f"/proc/{int(pid)}/cgroup").read_text(encoding="utf-8")
    except OSError:
        return ""


def flock_holders(lock_path: Path) -> set[int]:
    """Pids /proc/locks lists as holding a FLOCK WRITE on lock_path's inode."""
    try:
        st = os.stat(lock_path)
        text = Path("/proc/locks").read_text(encoding="utf-8")
    except OSError:
        return set()
    holders: set[int] = set()
    for line in text.splitlines():
        parts = line.split()
        # "1: FLOCK  ADVISORY  WRITE 1234 fd:01:5678 0 EOF" (blocked waiters carry "->")
        if "->" in parts or len(parts) < 6 or parts[1] != "FLOCK" or parts[3] != "WRITE":
            continue
        try:
            pid = int(parts[4])
            maj, minr, ino = parts[5].split(":")
            if int(ino) == st.st_ino and int(maj, 16) == os.major(st.st_dev) and int(minr, 16) == os.minor(st.st_dev):
                holders.add(pid)
        except ValueError:
            continue
    return holders


def canonical_origin_main(root: Path) -> str:
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "refs/remotes/origin/main"],
                       capture_output=True, text=True, check=False)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def push_checks_green(sha: str) -> tuple[bool, list[str]]:
    from scripts.release_grant_preflight import collect_push_checks  # noqa: PLC0415

    ev = collect_push_checks(sha)
    return bool(ev.get("ok")), list(ev.get("errors") or [])[:10]


def read_delegation() -> tuple[bool, str]:
    """Strict: a real ACTIVE promote_only file. The lab soft switch never binds a release."""
    from scripts.lib.deploy_on_main import deploy_delegation_path  # noqa: PLC0415

    path = deploy_delegation_path()
    if not path.is_file():
        return False, "missing"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"unreadable:{type(exc).__name__}"
    if str(body.get("status") or "").upper() != "ACTIVE":
        return False, f"status:{body.get('status') or 'empty'}"
    if str(body.get("scope") or "") != "promote_only":
        return False, f"scope:{body.get('scope') or 'empty'}"
    return True, "ACTIVE"


def read_stop(state_dir: Path) -> tuple[bool, str]:
    from scripts.lib.release_control import LATCH_ABSENT, LATCH_NAME, read_latch  # noqa: PLC0415

    kind, _ = read_latch(Path(state_dir) / LATCH_NAME)
    return kind != LATCH_ABSENT, kind


# ── the decision ─────────────────────────────────────────────────────────────────────────────


def decide(
    action: str,
    sha: str,
    *,
    root: Path,
    state_dir: Path,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[float] = None,
    self_pid: Optional[int] = None,
    ancestors: Callable[[int], list[int]] = proc_ancestors,
    cgroup: Callable[[int], str] = proc_cgroup,
    lock_holders: Callable[[Path], set[int]] = flock_holders,
    stop: Callable[[Path], tuple[bool, str]] = read_stop,
    delegation: Callable[[], tuple[bool, str]] = read_delegation,
    origin_main: Callable[[Path], str] = canonical_origin_main,
    checks: Callable[[str], tuple[bool, list[str]]] = push_checks_green,
) -> DelegationVerdict:
    env = os.environ if env is None else env
    if action not in ("prepare", "promote"):
        return _refuse("action_not_bindable", action=action)
    foreign = [k for k in FOREIGN_PATH_ENV if env.get(k)]
    if foreign:
        return _refuse("foreign_release_path", env=foreign)
    raw_ticket, nonce = env.get(TICKET_ENV) or "", env.get(NONCE_ENV) or ""
    if not raw_ticket or not nonce:
        return _refuse("no_poller_ticket")
    expected = ticket_path(state_dir)
    try:
        if Path(raw_ticket).resolve() != expected.resolve():
            return _refuse("ticket_path_mismatch")
        body = json.loads(expected.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _refuse("ticket_unreadable", error=type(exc).__name__)
    if not isinstance(body, dict) or body.get("schema") != TICKET_SCHEMA:
        return _refuse("ticket_schema")
    if not hmac.compare_digest(str(body.get("nonce_sha256") or ""), _hash_nonce(nonce)):
        return _refuse("ticket_nonce_mismatch")
    if str(body.get("sha") or "") != sha or len(sha) != 40:
        return _refuse("ticket_sha_mismatch", ticket_sha=str(body.get("sha") or "")[:40])
    try:
        age = (now if now is not None else time.time()) - float(body.get("created_at"))
        pid = int(body.get("pid"))
    except (TypeError, ValueError):
        return _refuse("ticket_fields")
    if not 0 <= age <= TICKET_TTL_S:
        return _refuse("ticket_stale", age_s=round(age, 1))
    if pid not in ancestors(self_pid if self_pid is not None else os.getpid()):
        return _refuse("ticket_pid_not_ancestor", pid=pid)
    if POLLER_UNIT not in cgroup(pid):
        return _refuse("ticket_pid_not_poller_unit", pid=pid)
    from scripts.lib.release_control import GLOBAL_LOCK_NAME  # noqa: PLC0415

    if pid not in lock_holders(Path(state_dir) / GLOBAL_LOCK_NAME):
        return _refuse("global_release_lock_not_held_by_poller", pid=pid)
    stopped, stop_kind = stop(Path(state_dir))
    if stopped:
        return _refuse("stop_latched", latch=stop_kind)
    armed, arm = delegation()
    if not armed:
        return _refuse("delegation_not_armed", delegation=arm)
    main = origin_main(Path(root))
    if main != sha:
        return _refuse("sha_not_origin_main", origin_main=main[:40])
    green, errors = checks(sha)
    if not green:
        return _refuse("main_checks_not_green", errors=errors)
    return DelegationVerdict(True, "armed standing deploy delegation (poller ticket, lock held, STOP absent, "
                             "SHA == origin/main, required checks green)", [MATCHED_BY],
                             {"pid": pid, "ticket_age_s": round(age, 1)})


def decide_from_env(action: str, sha: str, *, root: Path) -> DelegationVerdict:
    from scripts.lib.deploy_on_main import state_dir  # noqa: PLC0415

    try:
        return decide(action, sha, root=root, state_dir=state_dir())
    except Exception as exc:  # noqa: BLE001 — fail closed, never raise into the preflight
        return _refuse("binding_error", error=f"{type(exc).__name__}: {str(exc)[:160]}")
