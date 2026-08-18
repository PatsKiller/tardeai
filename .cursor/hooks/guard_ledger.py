#!/usr/bin/env python3
"""Canonical transactional approval ledger.

All grant/revoke/consume/init/recovery paths MUST go through this module.
Never truncate grants.json in place. Never jq-redirect onto the canonical path.

Lock file is $APPROVALS_DIR/.grants.lock (NOT grants.json): the ledger is
replaced by atomic rename, so locking the replaced inode is wrong.

States: MISSING | VALID_EMPTY | VALID_NONEMPTY | ZERO_BYTE | MALFORMED | UNREADABLE
ZERO_BYTE is CORRUPT, not EMPTY. Empty valid is {}.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA_VERSION = 1
LEDGER_NAME = "grants.json"
LOCK_NAME = ".grants.lock"
AUDIT_LOCK_NAME = ".audit.lock"
LEDGER_MODE = 0o600
DIR_MODE = 0o700
LOCK_MODE = 0o600

MISSING = "MISSING"
VALID_EMPTY = "VALID_EMPTY"
VALID_NONEMPTY = "VALID_NONEMPTY"
ZERO_BYTE = "ZERO_BYTE"
MALFORMED = "MALFORMED"
UNREADABLE = "UNREADABLE"

CORRUPT_STATES = {ZERO_BYTE, MALFORMED, UNREADABLE}
LEDGER_CORRUPT = "APPROVAL_LEDGER_CORRUPT"

# Grant record: {expires:int, uses:int (-1 unlimited or >=0), reason:str, created_at?:int, grant_id?:str}
_INT_FIELDS = ("expires", "uses")
_STR_FIELDS = ("reason",)


class LedgerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LedgerCorrupt(LedgerError):
    def __init__(self, state: str, message: str):
        super().__init__(LEDGER_CORRUPT, message)
        self.state = state


def approvals_dir() -> Path:
    raw = os.environ.get("GUARD_APPROVALS_DIR") or str(Path.home() / ".cursor" / "approvals")
    return Path(raw)


def ledger_path(adir: Path | None = None) -> Path:
    return (adir or approvals_dir()) / LEDGER_NAME


def lock_path(adir: Path | None = None) -> Path:
    return (adir or approvals_dir()) / LOCK_NAME


def audit_log_path() -> Path:
    return Path(os.environ.get("GUARD_AUDIT_LOG") or (Path.home() / "logs" / "cursor-agent-audit.jsonl"))


def audit_lock_path(adir: Path | None = None) -> Path:
    return (adir or approvals_dir()) / AUDIT_LOCK_NAME


def _crash(point: str) -> None:
    want = os.environ.get("GUARD_LEDGER_CRASH") or ""
    if want and want == point:
        raise SystemExit(90)


def ensure_dir(adir: Path) -> None:
    adir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    try:
        os.chmod(adir, DIR_MODE)
    except OSError:
        pass


@contextmanager
def _flock(path: Path, exclusive: bool = True) -> Iterator[int]:
    path.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, LOCK_MODE)
    try:
        os.fchmod(fd, LOCK_MODE)
    except OSError:
        pass
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def classify_ledger(path: Path) -> str:
    if path.is_symlink():
        return UNREADABLE
    if not path.exists():
        return MISSING
    try:
        if not path.is_file():
            return UNREADABLE
        size = path.stat().st_size
    except OSError:
        return UNREADABLE
    if size == 0:
        return ZERO_BYTE
    try:
        raw = path.read_bytes()
    except OSError:
        return UNREADABLE
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return MALFORMED
    try:
        validate_document(data)
    except LedgerError:
        return MALFORMED
    if data == {}:
        return VALID_EMPTY
    return VALID_NONEMPTY


def validate_document(data: Any) -> dict[str, Any]:
    if data is None:
        raise LedgerError("invalid_schema", "ledger document is null")
    if isinstance(data, list):
        raise LedgerError("invalid_schema", "ledger document must be an object, not an array")
    if not isinstance(data, dict):
        raise LedgerError("invalid_schema", f"ledger document must be an object, got {type(data).__name__}")
    out: dict[str, Any] = {}
    for key, rec in data.items():
        if not isinstance(key, str) or not key or "/" in key or key.startswith("."):
            raise LedgerError("invalid_schema", f"illegal grant key: {key!r}")
        if not isinstance(rec, dict):
            raise LedgerError("invalid_schema", f"grant {key!r} must be an object")
        if "expires" not in rec or "uses" not in rec:
            raise LedgerError("invalid_schema", f"grant {key!r} missing expires/uses")
        try:
            expires = int(rec["expires"])
            uses = int(rec["uses"])
        except (TypeError, ValueError):
            raise LedgerError("invalid_schema", f"grant {key!r} has non-integer expires/uses") from None
        if uses < -1:
            raise LedgerError("invalid_schema", f"grant {key!r} has negative uses other than -1")
        if expires < 0:
            raise LedgerError("invalid_schema", f"grant {key!r} has invalid expiry")
        reason = rec.get("reason", "")
        if reason is None:
            reason = ""
        if not isinstance(reason, str):
            raise LedgerError("invalid_schema", f"grant {key!r} reason must be a string")
        cleaned: dict[str, Any] = {"expires": expires, "uses": uses, "reason": reason}
        if "created_at" in rec:
            try:
                cleaned["created_at"] = int(rec["created_at"])
            except (TypeError, ValueError):
                raise LedgerError("invalid_schema", f"grant {key!r} created_at must be int") from None
        if "grant_id" in rec:
            if not isinstance(rec["grant_id"], str) or not rec["grant_id"]:
                raise LedgerError("invalid_schema", f"grant {key!r} grant_id must be a non-empty string")
            cleaned["grant_id"] = rec["grant_id"]
        out[key] = cleaned
    return out


def _fsync_file(fd: int) -> None:
    os.fsync(fd)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_replace(adir: Path, dest: Path, document: dict[str, Any]) -> None:
    """Write complete JSON to a same-dir temp, verify, fsync, rename, fsync dir."""
    validate_document(document)
    payload = (json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    # Re-parse before commit — refuse to replace with unreadable bytes.
    validate_document(json.loads(payload.decode("utf-8")))
    if dest.is_symlink():
        raise LedgerError("symlink", f"refusing to replace unexpected symlink ledger {dest}")
    if os.environ.get("GUARD_LEDGER_FAIL_WRITE") == "1":
        raise LedgerError("write_failed", "simulated temp-write failure")
    tmp = adir / f".{LEDGER_NAME}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, LEDGER_MODE)
    try:
        _crash("after_lock_temp_created")
        n = 0
        while n < len(payload):
            n += os.write(fd, payload[n:])
        os.fchmod(fd, LEDGER_MODE)
        _fsync_file(fd)
        _crash("after_temp_fsync")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(fd)
    try:
        # Verify the temp file independently of the write fd.
        verify = json.loads(tmp.read_text(encoding="utf-8"))
        validate_document(verify)
        _crash("before_rename")
        os.replace(str(tmp), str(dest))
        _crash("after_rename")
        _fsync_dir(adir)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def ledger_read(adir: Path | None = None, *, allow_corrupt: bool = False) -> tuple[str, dict[str, Any]]:
    adir = adir or approvals_dir()
    path = ledger_path(adir)
    state = classify_ledger(path)
    if state == MISSING:
        return state, {}
    if state in CORRUPT_STATES:
        if allow_corrupt:
            return state, {}
        raise LedgerCorrupt(state, f"{LEDGER_CORRUPT}: ledger is {state}")
    data = validate_document(json.loads(path.read_text(encoding="utf-8")))
    return state, data


def ledger_update_atomic(mutator: Callable[[dict[str, Any]], dict[str, Any]], adir: Path | None = None) -> dict[str, Any]:
    """Exclusive lock for the entire read-validate-mutate-replace transaction."""
    adir = adir or approvals_dir()
    ensure_dir(adir)
    dest = ledger_path(adir)
    with _flock(lock_path(adir), exclusive=True):
        _crash("after_lock")
        state = classify_ledger(dest)
        _crash("after_read")
        if state == MISSING:
            current: dict[str, Any] = {}
        elif state in CORRUPT_STATES:
            raise LedgerCorrupt(state, f"{LEDGER_CORRUPT}: ledger is {state}")
        else:
            current = validate_document(json.loads(dest.read_text(encoding="utf-8")))
        new_doc = validate_document(mutator(dict(current)))
        _atomic_replace(adir, dest, new_doc)
        return new_doc


def ledger_init_empty(adir: Path | None = None) -> dict[str, Any]:
    """Create a valid empty ledger if missing. Refuse to clobber corrupt/existing."""
    adir = adir or approvals_dir()
    ensure_dir(adir)
    dest = ledger_path(adir)
    with _flock(lock_path(adir), exclusive=True):
        state = classify_ledger(dest)
        if state in (VALID_EMPTY, VALID_NONEMPTY):
            _, data = ledger_read(adir)
            return data
        if state in CORRUPT_STATES:
            raise LedgerCorrupt(state, f"{LEDGER_CORRUPT}: refuse implicit init over {state}")
        _atomic_replace(adir, dest, {})
        return {}


def ledger_create_grant(tier: str, *, expires: int, uses: int, reason: str, adir: Path | None = None) -> dict[str, Any]:
    now = int(time.time())
    grant_id = uuid.uuid4().hex

    def mut(doc: dict[str, Any]) -> dict[str, Any]:
        doc[tier] = {
            "expires": int(expires),
            "uses": int(uses),
            "reason": str(reason),
            "created_at": now,
            "grant_id": grant_id,
        }
        return doc

    return ledger_update_atomic(mut, adir)


def ledger_consume_grant(tier: str, adir: Path | None = None) -> dict[str, Any]:
    """Atomically consume one use. Compare/update under exclusive lock."""
    result: dict[str, Any] = {"consumed": False}

    def mut(doc: dict[str, Any]) -> dict[str, Any]:
        rec = doc.get(tier)
        now = int(time.time())
        if not isinstance(rec, dict):
            return doc
        if int(rec.get("expires") or 0) <= now:
            doc.pop(tier, None)
            return doc
        uses = int(rec.get("uses") or 0)
        if uses == 0:
            doc.pop(tier, None)
            return doc
        if uses > 0:
            uses -= 1
            rec = dict(rec)
            rec["uses"] = uses
            if uses == 0:
                doc.pop(tier, None)
            else:
                doc[tier] = rec
            result["consumed"] = True
            result["uses_left"] = uses
            result["reason"] = rec.get("reason") or ""
            result["grant_id"] = rec.get("grant_id")
            result["consumption_id"] = uuid.uuid4().hex
            return doc
        if uses == -1:
            result["consumed"] = True
            result["uses_left"] = -1
            result["reason"] = rec.get("reason") or ""
            result["grant_id"] = rec.get("grant_id")
            result["consumption_id"] = uuid.uuid4().hex
            return doc
        return doc

    ledger_update_atomic(mut, adir)
    return result


def ledger_revoke(tier: str, adir: Path | None = None) -> dict[str, Any]:
    def mut(doc: dict[str, Any]) -> dict[str, Any]:
        doc.pop(tier, None)
        return doc

    return ledger_update_atomic(mut, adir)


def ledger_revoke_all(adir: Path | None = None) -> dict[str, Any]:
    def mut(_doc: dict[str, Any]) -> dict[str, Any]:
        return {}

    return ledger_update_atomic(mut, adir)


def ledger_list(adir: Path | None = None, *, now: int | None = None) -> dict[str, Any]:
    adir = adir or approvals_dir()
    with _flock(lock_path(adir), exclusive=True):
        state, data = ledger_read(adir)
    now = int(time.time() if now is None else now)
    active = {}
    for tier, rec in data.items():
        uses = int(rec["uses"])
        if int(rec["expires"]) > now and (uses < 0 or uses > 0):
            active[tier] = rec
    return {"state": state, "grants": data, "active": active}


def ledger_recover_empty(
    *,
    reason: str,
    incident: str,
    previous_size: int,
    previous_hash: str,
    operator: str,
    session: str,
    adir: Path | None = None,
) -> dict[str, Any]:
    """Conservative recovery: ACTIVE GRANTS = NONE. Valid empty {} via atomic writer.

    Does not infer grants from audit history. Overwrites ZERO_BYTE/MALFORMED only
    through this explicit operator path.
    """
    adir = adir or approvals_dir()
    ensure_dir(adir)
    dest = ledger_path(adir)
    with _flock(lock_path(adir), exclusive=True):
        state = classify_ledger(dest)
        _atomic_replace(adir, dest, {})
    audit_append(
        {
            "event": "ledger_recovery",
            "incident": incident,
            "previous_size": previous_size,
            "previous_hash": previous_hash,
            "previous_state": state,
            "recovered_to": VALID_EMPTY,
            "reason": reason,
            "operator": operator,
            "session": session,
            "recovery_policy": "ACTIVE_GRANTS_NONE",
        },
        adir=adir,
    )
    return {"state": VALID_EMPTY, "grants": {}}


def audit_append(payload: dict[str, Any], adir: Path | None = None) -> str:
    """Append exactly one complete JSON line under a dedicated audit lock."""
    adir = adir or approvals_dir()
    ensure_dir(adir)
    event_id = str(payload.get("event_id") or uuid.uuid4().hex)
    rec = dict(payload)
    rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    rec["event_id"] = event_id
    line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
    # Must parse as one object.
    json.loads(line)
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _flock(audit_lock_path(adir), exclusive=True):
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    return event_id


def doctor(adir: Path | None = None) -> dict[str, Any]:
    adir = adir or approvals_dir()
    dest = ledger_path(adir)
    state = classify_ledger(dest)
    schema_valid = state in {VALID_EMPTY, VALID_NONEMPTY, MISSING}
    mode = None
    try:
        if dest.exists():
            mode = oct(dest.stat().st_mode & 0o777)
    except OSError:
        mode = None
    active_count = 0
    if state in {VALID_EMPTY, VALID_NONEMPTY}:
        try:
            listed = ledger_list(adir)
            active_count = len(listed["active"])
        except LedgerError:
            schema_valid = False
    audit = audit_log_path()
    audit_readable = audit.is_file() and os.access(audit, os.R_OK)
    invalid_hist = 0
    if audit_readable:
        try:
            with audit.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 200000:
                        break
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        json.loads(s)
                    except json.JSONDecodeError:
                        invalid_hist += 1
        except OSError:
            audit_readable = False
    hooks_path = Path.home() / ".cursor" / "hooks.json"
    hooks_configured = hooks_path.is_file()
    fail_closed = None
    strreplace = False
    try:
        hooks = json.loads(hooks_path.read_text(encoding="utf-8")) if hooks_configured else {}
        pre = (hooks.get("hooks") or {}).get("preToolUse") or []
        read = (hooks.get("hooks") or {}).get("beforeReadFile") or []
        shell = (hooks.get("hooks") or {}).get("beforeShellExecution") or []
        fail_closed = all(
            bool(h.get("failClosed")) for h in [*pre, *read, *shell] if "guard-" in str(h.get("command", ""))
        )
        strreplace = any("StrReplace" in str(h.get("matcher", "")) for h in pre)
    except Exception:
        hooks_configured = False
    return {
        "ledger_path": str(dest),
        "ledger_status": state,
        "schema_valid": schema_valid,
        "file_mode": mode,
        "lock_path": str(lock_path(adir)),
        "active_grants_count": active_count,
        "audit_path": str(audit),
        "audit_readable": audit_readable,
        "audit_invalid_historical_rows": invalid_hist,
        "hooks_configured": hooks_configured,
        "failClosed": fail_closed,
        "StrReplace_protected": strreplace,
        "reader_fail_closed": True,
        "symlink": dest.is_symlink(),
        "ok": state in {VALID_EMPTY, VALID_NONEMPTY, MISSING} and not dest.is_symlink(),
    }


def _print_json(obj: Any, code: int = 0) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    return code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="guard_ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state")
    sub.add_parser("read")
    sub.add_parser("list")
    sub.add_parser("init")
    sub.add_parser("doctor")
    sub.add_parser("revoke-all")

    pg = sub.add_parser("grant")
    pg.add_argument("--tier", required=True)
    pg.add_argument("--expires", type=int, required=True)
    pg.add_argument("--uses", type=int, required=True)
    pg.add_argument("--reason", default="")

    pc = sub.add_parser("consume")
    pc.add_argument("--tier", required=True)

    pr = sub.add_parser("revoke")
    pr.add_argument("--tier", required=True)

    prec = sub.add_parser("recover")
    prec.add_argument("--reason", required=True)
    prec.add_argument("--incident", default="P0_GUARD_STATE_CORRUPTION")
    prec.add_argument("--previous-size", type=int, default=0)
    prec.add_argument("--previous-hash", default="")
    prec.add_argument("--operator", default=os.environ.get("USER", "operator"))
    prec.add_argument("--session", default=os.environ.get("GUARD_SESSION", ""))

    pa = sub.add_parser("audit")
    pa.add_argument("--payload", required=True, help="JSON object")

    args = p.parse_args(argv)
    adir = approvals_dir()
    try:
        if args.cmd == "state":
            return _print_json({"state": classify_ledger(ledger_path(adir)), "path": str(ledger_path(adir))})
        if args.cmd == "read":
            state, data = ledger_read(adir)
            return _print_json({"state": state, "grants": data})
        if args.cmd == "list":
            return _print_json(ledger_list(adir))
        if args.cmd == "init":
            return _print_json({"state": VALID_EMPTY, "grants": ledger_init_empty(adir)})
        if args.cmd == "doctor":
            d = doctor(adir)
            return _print_json(d, 0 if d.get("ok") else 2)
        if args.cmd == "grant":
            doc = ledger_create_grant(args.tier, expires=args.expires, uses=args.uses, reason=args.reason, adir=adir)
            return _print_json({"ok": True, "grants": doc})
        if args.cmd == "consume":
            r = ledger_consume_grant(args.tier, adir=adir)
            r["ok"] = True
            return _print_json(r, 0 if r.get("consumed") else 3)
        if args.cmd == "revoke":
            return _print_json({"ok": True, "grants": ledger_revoke(args.tier, adir=adir)})
        if args.cmd == "revoke-all":
            return _print_json({"ok": True, "grants": ledger_revoke_all(adir)})
        if args.cmd == "recover":
            return _print_json(
                ledger_recover_empty(
                    reason=args.reason,
                    incident=args.incident,
                    previous_size=args.previous_size,
                    previous_hash=args.previous_hash,
                    operator=args.operator,
                    session=args.session,
                    adir=adir,
                )
            )
        if args.cmd == "audit":
            payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                raise LedgerError("invalid_schema", "audit payload must be an object")
            eid = audit_append(payload, adir=adir)
            return _print_json({"ok": True, "event_id": eid})
    except LedgerCorrupt as e:
        return _print_json({"ok": False, "error": e.code, "state": e.state, "detail": e.message}, 2)
    except LedgerError as e:
        return _print_json({"ok": False, "error": e.code, "detail": e.message}, 1)
    return 1


if __name__ == "__main__":
    sys.exit(main())
