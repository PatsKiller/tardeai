#!/usr/bin/env python3
"""Release STOP from Command Center: SET-only writer of the release-window STOP latch (2026-10-21).

Release Train v2, Phase 2 STOP pulled forward on purpose (operator: "a Command Center view of what is queued and what
has been processed, with a kill button"). This module writes the SAME latch that ``scripts/release_window.py`` obeys:
``State(STATE_DIR).latch`` = ``<TRADEAI_RELEASE_WINDOW_STATE_DIR>/STOP.json``. The runner refuses every window while
that file holds a non-empty JSON object (``Runner._preconditions``: ``REFUSED_STOP_LATCHED``).

What it does, and nothing else:
  * ``request_stop``  SETS the latch. It never clears, archives or overwrites a readable latch (an existing STOP —
    e.g. a rollback latch the runner wrote — is kept byte-for-byte and reported ALREADY_STOPPED). The latch is
    serialised by ``release_window.State.write`` and published with ``os.link`` so it can never replace a latch the
    runner wrote in the same instant. A present-but-unreadable latch (which main's reader treats as ABSENT, the
    fail-open Phase 0 fixes) is archived beside the receipts, never deleted, and replaced by a readable STOP.
  * ``status``  reads the latch back (SET / ABSENT / UNREADABLE), whether a window run currently holds the runner's
    flock (from /proc/locks — read-only, never takes the lock), and the audit tail.
  * Every attempt, accepted, replayed or refused, appends one row to ``cc_stop/audit.jsonl`` (append-only, fsync).
  * Idempotency: one record per ``idempotency_key`` (stored by sha256); a replay returns the first result and writes
    no second latch; the same key with a different reason is refused 409.

There is NO resume or clear here (operator decision D3, 2026-10-21): resume is host-CLI-only,
``python3 scripts/release_window.py clear-stop --reason "..."``. Any clear/resume shaped request is refused.

This is the RELEASE stop. It is separate from the trading kill switches (/api/v2/execution/kill-switches/*) and never
reads or writes them; stopping releases does not change trading containment, stops or monitoring.

Authority: the caller (api_v2) supplies the actor from the AUTHENTICATED cc_auth principal (``tailnet:<login>``) and
the CSRF verdict of the request; this module refuses without both. Nothing here touches git, GitHub, a release
directory, systemd, a broker or a credential.

CLI (independent host path, same writer):  python3 scripts/lib/release_train_stop.py status
                                            python3 scripts/lib/release_train_stop.py stop --reason TEXT
"""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve()
for _p in (str(_HERE.parents[1]), str(_HERE.parents[2])):  # scripts/ and the repo root
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # served release: PYTHONPATH=<release>/scripts
    import release_window as RW  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - imported as scripts.lib.release_train_stop
    from scripts import release_window as RW  # type: ignore[no-redef]

SCHEMA_STATUS = "ReleaseTrainStopStatus@v1"
SCHEMA_RESULT = "ReleaseTrainStopResult@v1"
STATE_DIR_ENV = "TRADEAI_RELEASE_WINDOW_STATE_DIR"
RESUME_COMMAND = 'python3 scripts/release_window.py clear-stop --reason "<why it is safe to resume>"'
RESUME_POLICY = (
    "Resume is host-CLI-only (operator decision D3, 2026-10-21). Command Center can only SET a STOP; "
    "there is no clear or resume endpoint."
)
KILL_SWITCH_NOTE = (
    "Release STOP only. The trading kill switch is separate and is not read or changed; trading "
    "containment, stops and monitoring keep running."
)
CC_SOURCE = "command_center"
REASON_MIN, REASON_MAX = 8, 500
IDEM_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
# Body keys that ask for the opposite direction. Their presence refuses the request outright.
CLEARING_KEYS = frozenset(
    {
        "clear",
        "clear_stop",
        "resume",
        "unstop",
        "unlatch",
        "unpause",
        "release",
        "reset",
        "disarm",
        "cancel_stop",
        "lift",
    }
)
AUDIT_TAIL = 20


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def state_dir() -> Path:
    """The runner's state dir, resolved at call time (same env and default as release_window.STATE_DIR)."""
    env = os.environ.get(STATE_DIR_ENV)
    return Path(env) if env else RW.STATE_DIR


def _state(root: Optional[Path]) -> "RW.State":
    return RW.State(Path(root) if root is not None else state_dir())


def _cc_dir(state: "RW.State") -> Path:
    return state.root / "cc_stop"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── latch read-back (the runner's semantics) ──────────────────────────────────────────────────────


def read_latch(state: "RW.State") -> tuple[str, Optional[dict]]:
    """("SET", body) | ("ABSENT", None) | ("UNREADABLE", {"error", "path"}).

    SET means exactly what release_window.Runner._preconditions refuses on: ``State.read`` returns a non-empty JSON
    object. A present path that is not that is UNREADABLE (main's reader treats it as absent; Phase 0 makes the
    runner fail closed). Uses the runner's own ``read_latch`` when the served release has it.
    """
    fail_closed = getattr(state, "read_latch", None)
    if callable(fail_closed):
        status, body = fail_closed()
        if status == "SET" and not body:
            return "UNREADABLE", {"error": "latch is an empty object", "path": str(state.latch)}
        return status, body
    if not os.path.lexists(state.latch):
        return "ABSENT", None
    body = state.read(state.latch)
    if isinstance(body, dict) and body:
        return "SET", body
    return "UNREADABLE", {"error": "latch present but not a non-empty JSON object", "path": str(state.latch)}


def window_run_lock(state: "RW.State") -> str:
    """HELD when a release_window run holds its flock on <state>/.lock, FREE when not, UNKNOWN when unreadable.

    Read-only: parses /proc/locks for the lock file's device and inode. Never opens or locks the file (taking even a
    shared lock could make a starting window refuse REFUSED_BUSY).
    """
    lock = state.root / ".lock"
    try:
        st = os.stat(lock)
    except FileNotFoundError:
        return "FREE"
    except OSError:
        return "UNKNOWN"
    try:
        text = Path("/proc/locks").read_text(encoding="utf-8")
    except OSError:
        return "UNKNOWN"
    want = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[1] != "FLOCK":
            continue
        try:
            major, minor, inode = parts[5].split(":")
            if (int(major, 16), int(minor, 16), int(inode)) == want:
                return "HELD"
        except ValueError:
            continue
    return "FREE"


def _audit_path(state: "RW.State") -> Path:
    return _cc_dir(state) / "audit.jsonl"


def _audit(state: "RW.State", row: dict) -> None:
    path = _audit_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def audit_tail(state: "RW.State", n: int = AUDIT_TAIL) -> list[dict]:
    try:
        lines = _audit_path(state).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"unparseable_audit_row": line[:200]})
    return out


def phase_for(latch_status: str, lock: str) -> str:
    """stopped | settling | running | unknown — the controller-side states the UI shows after a request."""
    if latch_status == "SET":
        return "settling" if lock == "HELD" else ("stopped" if lock == "FREE" else "unknown")
    if latch_status == "UNREADABLE":
        return "unknown"
    return "running"


def status(root: Optional[Path] = None, *, now: Optional[datetime] = None) -> dict:
    state = _state(root)
    now = now or utc_now()
    latch_status, body = read_latch(state)
    lock = window_run_lock(state)
    mtime = None
    try:
        mtime = iso(datetime.fromtimestamp(os.stat(state.latch).st_mtime, timezone.utc))
    except OSError:
        pass
    reader_note = None
    if latch_status == "UNREADABLE" and not callable(getattr(state, "read_latch", None)):
        reader_note = (
            "The served release_window.py reads an unreadable latch as ABSENT (fail-open, Phase 0 item 4). "
            "Press STOP to replace it with a readable latch; the unreadable file is archived, not deleted."
        )
    return {
        "schema": SCHEMA_STATUS,
        "as_of": iso(now),
        "state_dir": str(state.root),
        "latch": {"status": latch_status, "body": body, "path": str(state.latch), "mtime": mtime},
        "window_run_lock": lock,
        "phase": phase_for(latch_status, lock),
        "runner_reader": "fail_closed" if callable(getattr(state, "read_latch", None)) else "main_fail_open",
        "reader_note": reader_note,
        "audit_tail": audit_tail(state),
        "resume": {"policy": RESUME_POLICY, "command": RESUME_COMMAND},
        "separate_from_trading_kill_switch": True,
        "kill_switch_note": KILL_SWITCH_NOTE,
    }


# ── STOP (set-only) ───────────────────────────────────────────────────────────────────────────────


def _refuse(state: "RW.State", http: int, code: str, message: str, base: dict) -> tuple[int, dict]:
    row = {**base, "event": "refused", "refusal": code, "message": message}
    try:
        _audit(state, row)
    except OSError as exc:  # the refusal stands even if the audit dir is unwritable
        row["audit_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return http, {
        "ok": False,
        "schema": SCHEMA_RESULT,
        "outcome": "REFUSED",
        "refusal": code,
        "error": message,
        "resume": {"policy": RESUME_POLICY, "command": RESUME_COMMAND},
    }


def clearing_request(body: Any) -> Optional[str]:
    """The reason a body asks for anything but SET (clear / resume / any action other than "stop"), else None."""
    if not isinstance(body, dict):
        return None
    action = body.get("action")
    if action is not None and str(action).strip().lower() != "stop":
        return f"action {str(action)[:40]!r} refused: this endpoint only sets a STOP"
    hit = sorted(k for k in body if str(k).strip().lower() in CLEARING_KEYS)
    if hit:
        return f"field {hit[0]!r} refused: this endpoint only sets a STOP"
    return None


def request_stop(
    *,
    actor: str,
    reason: Any,
    idempotency_key: Any,
    csrf_ok: bool,
    csrf_reason: str = "",
    body: Any = None,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    source: str = CC_SOURCE,
) -> tuple[int, dict]:
    """SET the release STOP latch. Returns (http_status, body). Never clears; never overwrites a readable latch."""
    state = _state(root)
    now = now or utc_now()
    requested_at = iso(now)
    key = idempotency_key if isinstance(idempotency_key, str) else ""
    base = {
        "at": requested_at,
        "actor": actor or "",
        "source": source,
        "state_dir": str(state.root),
        "idempotency_key_sha256": _sha(key) if key else None,
        "reason": (reason.strip()[:REASON_MAX] if isinstance(reason, str) else None),
    }
    if isinstance(body, dict) and "actor" in body:
        base["body_actor_ignored"] = True

    # Order: authority first (identity, CSRF), then direction, then input.
    if source == CC_SOURCE and not (actor or "").startswith("tailnet:"):
        return _refuse(
            state,
            403,
            "NO_OPERATOR_IDENTITY",
            "release STOP needs an authenticated operator identity (Tailscale); a service token, an "
            "unauthenticated or a report-only request is not one",
            base,
        )
    if source == CC_SOURCE and not csrf_ok:
        return _refuse(state, 403, "CSRF", csrf_reason or "csrf: same-origin proof required", base)
    clearing = clearing_request(body)
    if clearing:
        return _refuse(state, 400, "SET_ONLY", f"{clearing}. {RESUME_POLICY} Run: {RESUME_COMMAND}", base)
    if not isinstance(reason, str) or not (REASON_MIN <= len(reason.strip()) <= REASON_MAX):
        return _refuse(state, 400, "REASON_REQUIRED", f"reason text required ({REASON_MIN}-{REASON_MAX} chars)", base)
    if not IDEM_RE.fullmatch(key):
        return _refuse(
            state,
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "idempotency_key required: 16-128 chars of [A-Za-z0-9._:-] (one per button press)",
            base,
        )
    reason = reason.strip()

    cc = _cc_dir(state)
    (cc / "requests").mkdir(parents=True, exist_ok=True)
    lock_fh = open(cc / ".lock", "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        idem_path = cc / "requests" / f"{_sha(key)}.json"
        prior = state.read(idem_path)
        if prior:
            if prior.get("reason_sha256") != _sha(reason):
                return _refuse(
                    state,
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "this idempotency_key was already used with a different reason",
                    base,
                )
            latch_status, latch_body = read_latch(state)
            if latch_status != "SET":
                return _refuse(
                    state,
                    409,
                    "IDEMPOTENCY_KEY_SPENT",
                    "this key's STOP was applied and the latch has since been cleared on the host; "
                    "press STOP again (a new key) to stop again",
                    base,
                )
            result = {
                **prior["result"],
                "replayed": True,
                "phase": "acknowledged",
                "latch": {"status": latch_status, "body": latch_body, "path": str(state.latch)},
            }
            _audit(
                state,
                {
                    **base,
                    "event": "replayed",
                    "stop_id": prior["result"].get("stop_id"),
                    "latch_status_after": latch_status,
                },
            )
            return 200, result

        before, before_body = read_latch(state)
        stop_id = f"rts-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        archived_unreadable = None
        wrote = False
        if before == "UNREADABLE":
            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            state.windows.mkdir(parents=True, exist_ok=True)
            dest = state.windows / f"STOP-unreadable-{stamp}-{stop_id[-8:]}.json.archived"
            os.rename(state.latch, dest)  # never deleted: archived beside the receipts
            archived_unreadable = str(dest)
            before = "ABSENT"
        if before == "ABSENT":
            latch = {
                "latched_at": requested_at,
                "window_id": None,
                "outcome": "STOP_REQUESTED_OPERATOR",
                "candidate": None,
                "source": source,
                "actor": actor,
                "reason": reason,
                "stop_id": stop_id,
                "detail": (
                    "release windows halted by an operator STOP; resume is host-CLI-only: "
                    "scripts/release_window.py clear-stop --reason ..."
                ),
            }
            staged = cc / "latches" / f"{stop_id}.json"
            state.write(staged, latch)  # the runner's own serialiser (tmp + atomic replace)
            try:
                os.link(staged, state.latch)  # publish without ever replacing a concurrent latch
                wrote = True
            except FileExistsError:
                wrote = False  # the runner latched first: keep its latch
        after, after_body = read_latch(state)  # the acknowledgement IS this read-back
        acknowledged_at = iso(utc_now()) if after == "SET" else None
        outcome = (
            "STOP_SET"
            if wrote and after == "SET" and (after_body or {}).get("stop_id") == stop_id
            else "ALREADY_STOPPED"
            if after == "SET"
            else "STOP_NOT_CONFIRMED"
        )
        result = {
            "ok": after == "SET",
            "schema": SCHEMA_RESULT,
            "outcome": outcome,
            "phase": "acknowledged" if after == "SET" else "unconfirmed",
            "stop_id": stop_id if wrote else (after_body or {}).get("stop_id"),
            "actor": actor,
            "reason": reason,
            "requested_at": requested_at,
            "acknowledged_at": acknowledged_at,
            "latch": {"status": after, "body": after_body, "path": str(state.latch)},
            "archived_unreadable_latch": archived_unreadable,
            "replayed": False,
            "resume": {"policy": RESUME_POLICY, "command": RESUME_COMMAND},
            "separate_from_trading_kill_switch": True,
        }
        if after == "SET":
            state.write(idem_path, {"reason_sha256": _sha(reason), "result": result, "recorded_at": requested_at})
        _audit(
            state,
            {
                **base,
                "event": "stop_set" if outcome == "STOP_SET" else outcome.lower(),
                "stop_id": result["stop_id"],
                "latch_status_before": before if not archived_unreadable else "UNREADABLE",
                "latch_status_after": after,
                "acknowledged_at": acknowledged_at,
                "archived_unreadable_latch": archived_unreadable,
                "existing_latch_outcome": (before_body or {}).get("outcome") if outcome == "ALREADY_STOPPED" else None,
            },
        )
        return (200 if after == "SET" else 500), result
    finally:
        lock_fh.close()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Release STOP latch: status, or SET a stop (never clears).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("stop")
    s.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(), indent=2, sort_keys=True, default=str))
        return 0
    code, body = request_stop(
        actor=f"host-cli:{getpass.getuser()}",
        reason=args.reason,
        idempotency_key=f"cli-{uuid.uuid4().hex}",
        csrf_ok=True,
        source="host_cli",
    )
    print(json.dumps(body, indent=2, sort_keys=True, default=str))
    return 0 if code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
