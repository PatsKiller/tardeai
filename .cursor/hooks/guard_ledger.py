#!/usr/bin/env python3
"""Canonical transactional approval ledger.

All grant/revoke/consume/init/recovery paths MUST go through this module.
Never truncate grants.json in place. Never jq-redirect onto the canonical path.

Lock file is $APPROVALS_DIR/.grants.lock (NOT grants.json): the ledger is
replaced by atomic rename, so locking the replaced inode is wrong.

States: MISSING | VALID_EMPTY | VALID_NONEMPTY | ZERO_BYTE | MALFORMED | UNREADABLE
ZERO_BYTE is CORRUPT, not EMPTY. Empty valid is {}.

Schema v2 (2026-10-21, Release Train v2 Phase 0 item 3) -- one row per GRANT, not per tier:

    {"<tier>@<grant_id>": {"tier", "grant_id", "expires", "uses", "reason", "created_at",
                           "status": "active" | "revoked" | "replaced", ...}}

v1 stored doc[tier] = record, so a new grant silently replaced the active one and nothing
recorded which grant a use was taken from. v2 keeps every row (exhausted, expired, revoked
and replaced rows stay as attribution evidence; nothing is dropped) and enforces ONE ACTIVE
GRANT PER TIER: `grant` refuses while one is active unless `--replace` is given, which closes
the old row (status "replaced", uses 0, replaced_by=<new key>). Consumers may name the exact
row (`consume --grant-id`). A tier with more than one active row -- reachable only by a hand
edit or a mixed-version writer -- is AMBIGUOUS: nothing is consumed from it, it is absent from
`active`, it projects as an inactive placeholder, and `doctor` fails. Grants are never unioned
into more authority.

The key carries the tier so that a v1 copy of this module (an older release) keeps the tier
when it re-serializes the file, and its doc.get(tier) finds nothing: an old reader fails
CLOSED on a v2 file, never open. Closed rows carry uses 0 for the same reason.

A v1 entry ({"<tier>": record}) is migrated ON READ and written as a v2 row on the next
mutation; the v1 bytes are first copied to grants.json.v1-archive.<ts>.<id> (never dropped).

Rows closed more than ARCHIVE_AFTER_DAYS (90) ago -- revoked, replaced, exhausted or expired -- move
to the append-only grants.archive.jsonl next to the ledger (`archive`; also run fail-soft after every
`bin/guard grant`). `lookup` and `consume`/`revoke --grant-id` report an archived id as archived.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA_VERSION = 2
SCHEMA_NAME = "GuardLedger@v2"
LEDGER_NAME = "grants.json"
LOCK_NAME = ".grants.lock"
AUDIT_LOCK_NAME = ".audit.lock"
V1_ARCHIVE_PREFIX = LEDGER_NAME + ".v1-archive."
# Closed-row archive (operator 2026-10-21): rows closed more than ARCHIVE_AFTER_DAYS ago move, under the
# ledger lock, to this append-only JSONL next to the ledger. Never deleted; a lookup of an archived id says
# "archived", never "missing".
ARCHIVE_NAME = "grants.archive.jsonl"
ARCHIVE_SCHEMA = "GuardLedgerArchive@v1"
ARCHIVE_AFTER_DAYS = 90
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

# v1 grant record: {expires:int, uses:int (-1 unlimited or >=0), reason:str, created_at?:int, grant_id?:str}
# v2 row (key "<tier>@<grant_id>"): the v1 fields plus tier, status and the optional fields below.
_INT_FIELDS = ("expires", "uses")
_STR_FIELDS = ("reason",)
KEY_SEP = "@"
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_REPLACED = "replaced"
STATUSES = (STATUS_ACTIVE, STATUS_REVOKED, STATUS_REPLACED)
CLOSED_STATUSES = (STATUS_REVOKED, STATUS_REPLACED)
GRANT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}")
_REMOTE_REQUEST_RE = re.compile(r"\[remote_request_id=([0-9A-Za-z_-]{4,64})\b")
# Optional v2 row fields and their types. Anything else on a row is dropped by the cleaner.
_OPT_INT = ("closed_at", "closed_uses", "exhausted_at")
_OPT_STR = ("replaced_by", "remote_request_id", "migrated_from", "closed_reason")


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


# --------------------------------------------------------------------------- schema


def _legal_tier(tier: Any) -> bool:
    return (isinstance(tier, str) and bool(tier) and "/" not in tier and not tier.startswith(".")
            and KEY_SEP not in tier and tier.strip() == tier)


def row_key(tier: str, grant_id: str) -> str:
    return f"{tier}{KEY_SEP}{grant_id}"


def _legacy_grant_id(tier: str, rec: dict[str, Any]) -> str:
    """Deterministic id for a v1 record that carried none: stable across reads (uses excluded)."""
    basis = json.dumps([tier, rec.get("created_at"), rec.get("expires"), rec.get("reason") or ""],
                       sort_keys=True, default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def remote_request_id_from_reason(reason: str) -> str | None:
    """The Telegram callback paths append "[remote_request_id=<id> ...]" to the reason."""
    m = _REMOTE_REQUEST_RE.search(reason or "")
    return m.group(1) if m else None


def _clean_record(key: str, rec: Any) -> dict[str, Any]:
    """The v1 field checks, shared by v1 entries and v2 rows."""
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
    return cleaned


def parse_document(data: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Any ledger document (v1, v2 or mixed) -> (v2 rows by key, tiers migrated from v1).

    Migration is in memory only and drops nothing. A v1 entry becomes the row
    "<tier>@<its grant_id>" (a deterministic id when it had none), migrated_from="v1".
    """
    if data is None:
        raise LedgerError("invalid_schema", "ledger document is null")
    if isinstance(data, list):
        raise LedgerError("invalid_schema", "ledger document must be an object, not an array")
    if not isinstance(data, dict):
        raise LedgerError("invalid_schema", f"ledger document must be an object, got {type(data).__name__}")
    rows: dict[str, dict[str, Any]] = {}
    legacy: list[tuple[str, dict[str, Any]]] = []
    for key, rec in data.items():
        if not isinstance(key, str) or not key or "/" in key or key.startswith("."):
            raise LedgerError("invalid_schema", f"illegal grant key: {key!r}")
        if KEY_SEP not in key:
            if not _legal_tier(key):
                raise LedgerError("invalid_schema", f"illegal grant key: {key!r}")
            legacy.append((key, _clean_record(key, rec)))
            continue
        tier, gid = key.split(KEY_SEP, 1)
        if not _legal_tier(tier) or not GRANT_ID_RE.fullmatch(gid):
            raise LedgerError("invalid_schema", f"illegal grant row key: {key!r}")
        cleaned = _clean_record(key, rec)
        if cleaned.get("grant_id") != gid:
            raise LedgerError("invalid_schema", f"row {key!r} grant_id does not match its key")
        if rec.get("tier") not in (None, tier):
            raise LedgerError("invalid_schema", f"row {key!r} tier does not match its key")
        status = rec.get("status", STATUS_ACTIVE)
        if status not in STATUSES:
            raise LedgerError("invalid_schema", f"row {key!r} has unknown status {status!r}")
        cleaned["tier"] = tier
        cleaned["status"] = status
        for f in _OPT_INT:
            if rec.get(f) is not None:
                try:
                    cleaned[f] = int(rec[f])
                except (TypeError, ValueError):
                    raise LedgerError("invalid_schema", f"row {key!r} {f} must be int") from None
        for f in _OPT_STR:
            if rec.get(f) is not None:
                if not isinstance(rec[f], str):
                    raise LedgerError("invalid_schema", f"row {key!r} {f} must be a string")
                cleaned[f] = rec[f]
        if status in CLOSED_STATUSES and cleaned["uses"] != 0:
            raise LedgerError("invalid_schema", f"closed row {key!r} must carry uses 0")
        rows[key] = cleaned
    migrated: list[str] = []
    for tier, cleaned in legacy:
        gid = cleaned.get("grant_id") or ""
        if not GRANT_ID_RE.fullmatch(gid):
            gid = _legacy_grant_id(tier, cleaned)
        key = row_key(tier, gid)
        if key in rows:  # a v2 row already owns that id: keep both, never drop
            gid = "v1-" + _legacy_grant_id(tier, cleaned)[:29]
            key = row_key(tier, gid)
        row = {**cleaned, "grant_id": gid, "tier": tier, "status": STATUS_ACTIVE, "migrated_from": "v1"}
        rrid = remote_request_id_from_reason(row["reason"])
        if rrid:
            row["remote_request_id"] = rrid
        rows[key] = row
        migrated.append(tier)
    return rows, migrated


def validate_document(data: Any) -> dict[str, Any]:
    """Validate any ledger document; return it as v2 rows (v1 entries migrated in memory)."""
    rows, _ = parse_document(data)
    return rows


def row_is_active(row: dict[str, Any], now: int) -> bool:
    uses = int(row.get("uses") or 0)
    return (row.get("status", STATUS_ACTIVE) == STATUS_ACTIVE and int(row.get("expires") or 0) > now
            and (uses == -1 or uses > 0))


def active_rows(rows: dict[str, dict[str, Any]], tier: str, now: int) -> list[tuple[str, dict[str, Any]]]:
    return sorted(((k, r) for k, r in rows.items() if r.get("tier") == tier and row_is_active(r, now)),
                  key=lambda kr: (int(kr[1].get("created_at") or 0), kr[0]))


def ambiguous_tiers(rows: dict[str, dict[str, Any]], now: int) -> list[str]:
    return [t for t in sorted({r["tier"] for r in rows.values()}) if len(active_rows(rows, t, now)) > 1]


def project_by_tier(rows: dict[str, dict[str, Any]], now: int | None = None) -> dict[str, dict[str, Any]]:
    """The v1 view {tier: record} that tier-keyed readers expect.

    One record per tier: its single active row, else its newest row. A tier with more
    than one active row projects as an inactive AMBIGUOUS placeholder (expires 0, uses 0,
    no grant_id), so a reader that computes activity itself still gets nothing.
    """
    now = int(time.time() if now is None else now)
    out: dict[str, dict[str, Any]] = {}
    for tier in sorted({r["tier"] for r in rows.values()}):
        act = active_rows(rows, tier, now)
        if len(act) == 1:
            out[tier] = copy.deepcopy(act[0][1])
        elif len(act) > 1:
            out[tier] = {"expires": 0, "uses": 0, "tier": tier, "ambiguous": True,
                         "reason": "AMBIGUOUS_ACTIVE_GRANTS: " + ",".join(k for k, _ in act)
                         + " -- revoke all but one: bin/guard revoke <tier> --grant-id <id>"}
        else:
            newest = max(((k, r) for k, r in rows.items() if r["tier"] == tier),
                         key=lambda kr: (int(kr[1].get("created_at") or 0), int(kr[1].get("expires") or 0), kr[0]))
            out[tier] = copy.deepcopy(newest[1])
    return out


def find_row(rows: dict[str, dict[str, Any]], grant_id: str) -> tuple[str, dict[str, Any]] | None:
    for k, r in rows.items():
        if r.get("grant_id") == grant_id:
            return k, r
    return None


def _close_row(row: dict[str, Any], status: str, now: int, why: str, replaced_by: str | None = None) -> None:
    row["closed_uses"] = int(row.get("uses") or 0)
    row["uses"] = 0
    row["status"] = status
    row["closed_at"] = now
    row["closed_reason"] = why
    if replaced_by:
        row["replaced_by"] = replaced_by


# --------------------------------------------------------------------------- storage


def _fsync_file(fd: int) -> None:
    os.fsync(fd)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _serialize_rows(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Canonical on-disk form: v2 rows only, every key "<tier>@<grant_id>"."""
    out: dict[str, Any] = {}
    for key, row in rows.items():
        if KEY_SEP not in key:
            raise LedgerError("invalid_schema", f"refusing to write a v1 key {key!r}")
        out[key] = dict(row)
    parsed, migrated = parse_document(out)
    if migrated or set(parsed) != set(out):
        raise LedgerError("invalid_schema", "serialized document did not round-trip")
    return out


def _atomic_replace(adir: Path, dest: Path, document: dict[str, Any]) -> None:
    """Write complete JSON to a same-dir temp, verify, fsync, rename, fsync dir."""
    document = _serialize_rows(validate_document(document))
    payload = (json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    # Re-parse before commit -- refuse to replace with unreadable bytes.
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


def _archive_v1(adir: Path, raw: bytes) -> Path:
    """Copy the pre-migration bytes aside before the first v2 write (rule 6: never drop)."""
    dest = adir / f"{V1_ARCHIVE_PREFIX}{time.strftime('%Y%m%dT%H%M%S')}.{uuid.uuid4().hex[:8]}"
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, LEDGER_MODE)
    try:
        n = 0
        while n < len(raw):
            n += os.write(fd, raw[n:])
        _fsync_file(fd)
    finally:
        os.close(fd)
    _fsync_dir(adir)
    return dest


def ledger_read_rows(adir: Path | None = None, *, allow_corrupt: bool = False
                     ) -> tuple[str, dict[str, dict[str, Any]]]:
    """(state, v2 rows by key). v1 entries are migrated in memory; the file is not touched."""
    adir = adir or approvals_dir()
    path = ledger_path(adir)
    state = classify_ledger(path)
    if state == MISSING:
        return state, {}
    if state in CORRUPT_STATES:
        if allow_corrupt:
            return state, {}
        raise LedgerCorrupt(state, f"{LEDGER_CORRUPT}: ledger is {state}")
    return state, validate_document(json.loads(path.read_text(encoding="utf-8")))


def ledger_read(adir: Path | None = None, *, allow_corrupt: bool = False) -> tuple[str, dict[str, Any]]:
    """(state, {tier: record}) -- the v1 view, one record per tier (see project_by_tier)."""
    state, rows = ledger_read_rows(adir, allow_corrupt=allow_corrupt)
    return state, project_by_tier(rows)


def ledger_update_rows(mutator: Callable[[dict[str, dict[str, Any]]], dict[str, dict[str, Any]] | None],
                       adir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Exclusive lock for the entire read-validate-mutate-replace transaction, on v2 rows.

    The file is rewritten only when the rows changed or a v1 entry has to be migrated;
    in the latter case the v1 bytes are archived first.
    """
    adir = adir or approvals_dir()
    ensure_dir(adir)
    dest = ledger_path(adir)
    with _flock(lock_path(adir), exclusive=True):
        _crash("after_lock")
        state = classify_ledger(dest)
        _crash("after_read")
        raw = b""
        migrated: list[str] = []
        if state == MISSING:
            current: dict[str, dict[str, Any]] = {}
        elif state in CORRUPT_STATES:
            raise LedgerCorrupt(state, f"{LEDGER_CORRUPT}: ledger is {state}")
        else:
            raw = dest.read_bytes()
            current, migrated = parse_document(json.loads(raw.decode("utf-8")))
        before = copy.deepcopy(current)
        result = mutator(current)
        new_rows = validate_document(current if result is None else result)
        if state != MISSING and new_rows == before and not migrated:
            return new_rows
        if migrated and raw:
            _archive_v1(adir, raw)
        _atomic_replace(adir, dest, new_rows)
        return new_rows


def ledger_update_atomic(mutator: Callable[[dict[str, Any]], dict[str, Any]], adir: Path | None = None) -> dict[str, Any]:
    """v1-compatible transaction: the mutator sees and returns the {tier: record} view.

    Kept for callers written against v1 (scripts/lib/fabric_grant.py). Changes are mapped
    back onto rows by grant_id: an edited record updates expires/uses/reason of THAT row;
    a record with a new or missing grant_id is a new grant that replaces the tier's active
    row (the explicit v1 semantics of writing doc[tier]); a tier the mutator removed has
    its active row revoked. An AMBIGUOUS tier may not be changed through this view.
    """
    now = int(time.time())

    def mut(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        view = project_by_tier(rows, now)
        before = copy.deepcopy(view)
        after = mutator(copy.deepcopy(view))
        if not isinstance(after, dict):
            raise LedgerError("invalid_schema", "mutator must return an object")
        for tier, rec in after.items():
            if not _legal_tier(tier):
                raise LedgerError("invalid_schema", f"illegal grant key: {tier!r}")
            prev = before.get(tier)
            if prev is not None and rec == prev:
                continue
            if prev is not None and prev.get("ambiguous"):
                raise LedgerError("ambiguous_active_grants", f"{tier}: resolve the ambiguity before editing")
            cleaned = _clean_record(tier, rec)
            gid = cleaned.get("grant_id")
            hit = find_row(rows, gid) if gid else None
            if hit and hit[1]["tier"] == tier:
                row = hit[1]
                row.update({k: cleaned[k] for k in ("expires", "uses", "reason")})
                continue
            new_gid = gid if gid and GRANT_ID_RE.fullmatch(gid) and not hit else uuid.uuid4().hex
            key = row_key(tier, new_gid)
            for k, r in active_rows(rows, tier, now):
                _close_row(r, STATUS_REPLACED, now, "replaced via v1 view", replaced_by=key)
            rows[key] = {**cleaned, "grant_id": new_gid, "tier": tier, "status": STATUS_ACTIVE,
                         "created_at": int(cleaned.get("created_at") or now)}
        for tier in before:
            if tier not in after and not before[tier].get("ambiguous"):
                for _, r in active_rows(rows, tier, now):
                    _close_row(r, STATUS_REVOKED, now, "removed via v1 view")
        return rows

    return project_by_tier(ledger_update_rows(mut, adir), now)


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


# --------------------------------------------------------------------------- grant / consume / revoke


def ledger_create_grant_row(tier: str, *, expires: int, uses: int, reason: str, adir: Path | None = None,
                            replace: bool = False, remote_request_id: str | None = None) -> dict[str, Any]:
    """Create one grant row. Refuses while the tier has an active grant unless replace=True.

    Returns {"grant_id", "key", "replaced": [keys closed by this grant], "grants": v1 view}.
    """
    if not _legal_tier(tier):
        raise LedgerError("invalid_tier", f"illegal tier: {tier!r}")
    now = int(time.time())
    grant_id = uuid.uuid4().hex
    key = row_key(tier, grant_id)
    rrid = remote_request_id or remote_request_id_from_reason(reason)
    replaced: list[str] = []

    def mut(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        act = active_rows(rows, tier, now)
        if act and not replace:
            ids = ", ".join(r["grant_id"] for _, r in act)
            raise LedgerError(
                "active_grant_exists",
                f"an active {tier} grant exists (grant_id={ids}); refuse to replace it silently -- "
                f"pass --replace to supersede it, or revoke it first (bin/guard revoke {tier})")
        for k, r in act:
            _close_row(r, STATUS_REPLACED, now, "replaced by explicit --replace", replaced_by=key)
            replaced.append(k)
        row: dict[str, Any] = {
            "tier": tier,
            "grant_id": grant_id,
            "expires": int(expires),
            "uses": int(uses),
            "reason": str(reason),
            "created_at": now,
            "status": STATUS_ACTIVE,
        }
        if rrid:
            row["remote_request_id"] = str(rrid)
        rows[key] = row
        return rows

    rows = ledger_update_rows(mut, adir)
    return {"grant_id": grant_id, "key": key, "replaced": replaced, "grants": project_by_tier(rows, now)}


def ledger_create_grant(tier: str, *, expires: int, uses: int, reason: str, adir: Path | None = None,
                        replace: bool = False, remote_request_id: str | None = None) -> dict[str, Any]:
    """v1 signature: returns the {tier: record} view after the grant."""
    return ledger_create_grant_row(tier, expires=expires, uses=uses, reason=reason, adir=adir,
                                   replace=replace, remote_request_id=remote_request_id)["grants"]


def ledger_consume_grant(tier: str, adir: Path | None = None, *, grant_id: str | None = None) -> dict[str, Any]:
    """Atomically consume one use from THE active grant of `tier`. Compare/update under exclusive lock.

    With grant_id, only that exact row may be consumed; another active row of the tier is a
    refusal (grant_id_mismatch), never a substitute. A tier with more than one active row is
    refused (ambiguous_active_grants). The result names the row consumed.
    """
    result: dict[str, Any] = {"consumed": False, "tier": tier}

    def mut(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        now = int(time.time())
        if grant_id is not None and find_row(rows, grant_id) is None:
            arch = archived_record(grant_id, adir)
            if arch is not None:  # tripwire: an archived grant is reported as archived, never as missing
                result.update({"error": "grant_archived", "requested_grant_id": grant_id,
                               "archived_at": arch.get("archived_at"), "archived_tier": arch.get("tier")})
                return rows
        act = active_rows(rows, tier, now)
        if not act:
            result["error"] = "no_active_grant"
            return rows
        if len(act) > 1:
            result["error"] = "ambiguous_active_grants"
            result["active_grant_ids"] = [r["grant_id"] for _, r in act]
            return rows
        key, row = act[0]
        if grant_id is not None and row["grant_id"] != grant_id:
            result["error"] = "grant_id_mismatch"
            result["active_grant_id"] = row["grant_id"]
            result["requested_grant_id"] = grant_id
            return rows
        uses = int(row["uses"])
        if uses > 0:
            uses -= 1
            row["uses"] = uses  # an exhausted row stays as attribution evidence
            if uses == 0:
                row["exhausted_at"] = now  # starts the archive clock (ARCHIVE_AFTER_DAYS)
        result.update({
            "consumed": True,
            "uses_left": uses,
            "reason": row.get("reason") or "",
            "grant_id": row["grant_id"],
            "key": key,
            "consumption_id": uuid.uuid4().hex,
        })
        return rows

    ledger_update_rows(mut, adir)
    return result


def ledger_revoke(tier: str, adir: Path | None = None, *, grant_id: str | None = None) -> dict[str, Any]:
    """Close the tier's open rows (or only the exact grant_id). Rows are kept, with uses 0."""
    now = int(time.time())

    def mut(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if grant_id is not None:
            hit = find_row(rows, grant_id)
            if hit is None and archived_record(grant_id, adir) is not None:
                raise LedgerError("grant_archived", f"grant {grant_id} is archived in {ARCHIVE_NAME} (closed > "
                                  f"{ARCHIVE_AFTER_DAYS} days); there is nothing to revoke")
            if hit is None or hit[1]["tier"] != tier:
                raise LedgerError("unknown_grant_id", f"no {tier} grant with id {grant_id}")
            if hit[1]["status"] == STATUS_ACTIVE:
                _close_row(hit[1], STATUS_REVOKED, now, "revoked by grant id")
            return rows
        for r in rows.values():
            if r["tier"] == tier and row_is_active(r, now):
                _close_row(r, STATUS_REVOKED, now, "revoked by tier")
        return rows

    return project_by_tier(ledger_update_rows(mut, adir), now)


def ledger_revoke_all(adir: Path | None = None) -> dict[str, Any]:
    now = int(time.time())

    def mut(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        for r in rows.values():
            if row_is_active(r, now):
                _close_row(r, STATUS_REVOKED, now, "revoke-all")
        return rows

    return project_by_tier(ledger_update_rows(mut, adir), now)


# --------------------------------------------------------------------------- closed-row archive


def archive_path(adir: Path | None = None) -> Path:
    return (adir or approvals_dir()) / ARCHIVE_NAME


def row_closed_at(row: dict[str, Any], now: int) -> int | None:
    """When a row stopped being a grant, or None while it is still active.

    revoked/replaced: closed_at. Exhausted: the earlier of exhausted_at and expiry (expiry alone when
    an older row never recorded exhaustion -- the conservative, later bound). Expired: expires.
    """
    if row_is_active(row, now):
        return None
    expires = int(row.get("expires") or 0)
    if row.get("status") in CLOSED_STATUSES:
        return int(row.get("closed_at") or expires)
    if int(row.get("uses") or 0) == 0 and row.get("exhausted_at") is not None:
        return min(int(row["exhausted_at"]), expires)
    return expires


def read_archive(adir: Path | None = None) -> tuple[dict[str, dict[str, Any]], int]:
    """(grant_id -> archive record, torn line count). A torn line (crash mid-append) is skipped, not fatal."""
    path = archive_path(adir)
    out: dict[str, dict[str, Any]] = {}
    torn = 0
    if not path.is_file():
        return out, 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except json.JSONDecodeError:
                torn += 1
                continue
            if isinstance(rec, dict) and rec.get("grant_id"):
                out.setdefault(str(rec["grant_id"]), rec)
    return out, torn


def archived_record(grant_id: str, adir: Path | None = None) -> dict[str, Any] | None:
    return read_archive(adir)[0].get(str(grant_id))


def ledger_lookup(grant_id: str, adir: Path | None = None, *, now: int | None = None) -> dict[str, Any]:
    """Where a grant id is: active | inactive (in the ledger) | archived | missing. The archive tripwire:
    an id moved to the archive is reported as archived, never as missing."""
    now = int(time.time() if now is None else now)
    _, rows = ledger_read_rows(adir)
    hit = find_row(rows, grant_id)
    if hit is not None:
        return {"grant_id": grant_id, "status": "active" if row_is_active(hit[1], now) else "inactive",
                "key": hit[0], "tier": hit[1]["tier"], "row": hit[1]}
    arch = archived_record(grant_id, adir)
    if arch is not None:
        return {"grant_id": grant_id, "status": "archived", "key": arch.get("key"), "tier": arch.get("tier"),
                "archived_at": arch.get("archived_at"), "closed_at": arch.get("closed_at"),
                "archive_path": str(archive_path(adir))}
    return {"grant_id": grant_id, "status": "missing"}


def ledger_archive_closed(adir: Path | None = None, *, now: int | None = None,
                          days: int = ARCHIVE_AFTER_DAYS, dry_run: bool = False) -> dict[str, Any]:
    """Move rows closed more than `days` ago from the ledger to the append-only archive.

    Under the ledger lock: (1) append every due row not already archived (one fsynced write, after a
    newline if a previous append was torn); (2) atomically rewrite the ledger without them. A crash
    between (1) and (2) leaves the rows in both places; the next run sees them archived, appends
    nothing, and finishes (2). Nothing is ever deleted.
    """
    now = int(time.time() if now is None else now)
    cutoff = now - int(days) * 86400
    adir = adir or approvals_dir()
    out: dict[str, Any] = {"dry_run": dry_run, "days": int(days), "cutoff": cutoff, "due": [], "appended": 0,
                           "removed_from_ledger": 0, "archive_path": str(archive_path(adir))}

    def due_keys(rows: dict[str, dict[str, Any]]) -> list[str]:
        keys = []
        for k, r in rows.items():
            c = row_closed_at(r, now)
            if c is not None and c < cutoff:  # strictly more than `days` ago
                keys.append(k)
        return sorted(keys)

    if dry_run:
        _, rows = ledger_read_rows(adir)
        out["due"] = due_keys(rows)
        return out

    def mut(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        due = due_keys(rows)
        out["due"] = due
        if not due:
            return rows
        archived, _ = read_archive(adir)
        lines = []
        for k in due:
            r = rows[k]
            if r["grant_id"] in archived:
                continue  # appended by an earlier, interrupted run
            lines.append(json.dumps({"schema": ARCHIVE_SCHEMA, "key": k, "grant_id": r["grant_id"],
                                     "tier": r["tier"], "closed_at": row_closed_at(r, now), "archived_at": now,
                                     "row": r}, separators=(",", ":"), sort_keys=True) + "\n")
        if lines:
            path = archive_path(adir)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, LEDGER_MODE)
            try:
                os.fchmod(fd, LEDGER_MODE)
                prefix = ""
                size = os.fstat(fd).st_size
                if size:
                    with path.open("rb") as fh:
                        fh.seek(size - 1)
                        if fh.read(1) != b"\n":
                            prefix = "\n"  # isolate a torn tail from the new records
                payload = (prefix + "".join(lines)).encode("utf-8")
                n = 0
                while n < len(payload):
                    n += os.write(fd, payload[n:])
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_dir(adir)
        out["appended"] = len(lines)
        _crash("archive_after_append")
        for k in due:
            rows.pop(k)
        out["removed_from_ledger"] = len(due)
        return rows

    ledger_update_rows(mut, adir)
    if out["removed_from_ledger"]:
        try:
            audit_append({"event": "ledger-archive", "archived": out["due"], "appended": out["appended"],
                          "days": int(days)}, adir=adir)
        except OSError:
            pass
    return out


def ledger_list(adir: Path | None = None, *, now: int | None = None) -> dict[str, Any]:
    """{state, schema, grants: v1 view, active: {tier: row} (unambiguous only), ambiguous, rows}."""
    adir = adir or approvals_dir()
    with _flock(lock_path(adir), exclusive=True):
        state, rows = ledger_read_rows(adir)
        legacy: list[str] = []
        if state not in (MISSING,):
            try:
                _, legacy = parse_document(json.loads(ledger_path(adir).read_text(encoding="utf-8")))
            except (OSError, ValueError, LedgerError):
                legacy = []
    now = int(time.time() if now is None else now)
    amb = ambiguous_tiers(rows, now)
    active = {}
    for tier in sorted({r["tier"] for r in rows.values()}):
        act = active_rows(rows, tier, now)
        if len(act) == 1:
            active[tier] = copy.deepcopy(act[0][1])
    return {"state": state, "schema": SCHEMA_NAME, "grants": project_by_tier(rows, now), "active": active,
            "ambiguous": amb, "rows": rows, "legacy_v1_tiers": legacy}


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


def validate_rows(rows: dict[str, dict[str, Any]], now: int | None = None) -> dict[str, Any]:
    """Grant-mechanics invariants over v2 rows. Pure; used by `doctor`."""
    now = int(time.time() if now is None else now)
    violations: list[str] = []
    ids: dict[str, str] = {}
    for key, r in rows.items():
        gid = r.get("grant_id")
        if gid in ids:
            violations.append(f"duplicate_grant_id:{gid}:{ids[gid]},{key}")
        ids[str(gid)] = key
        if r.get("status") == STATUS_REPLACED:
            by = r.get("replaced_by")
            if not by or by not in rows:
                violations.append(f"replaced_by_missing:{key}")
            elif rows[by].get("tier") != r.get("tier"):
                violations.append(f"replaced_by_other_tier:{key}")
        if r.get("status") in CLOSED_STATUSES and int(r.get("uses") or 0) != 0:
            violations.append(f"closed_row_with_uses:{key}")
    amb = ambiguous_tiers(rows, now)
    violations.extend(f"ambiguous_active_grants:{t}" for t in amb)
    return {
        "rows_total": len(rows),
        "rows_active": sum(1 for r in rows.values() if row_is_active(r, now)),
        "ambiguous_tiers": amb,
        "invariant_violations": violations,
        "one_active_per_tier": not amb,
    }


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
    grant_checks: dict[str, Any] = {"rows_total": 0, "rows_active": 0, "ambiguous_tiers": [],
                                    "invariant_violations": [], "one_active_per_tier": True}
    legacy: list[str] = []
    if state in {VALID_EMPTY, VALID_NONEMPTY}:
        try:
            listed = ledger_list(adir)
            active_count = len(listed["active"])
            legacy = list(listed.get("legacy_v1_tiers") or [])
            grant_checks = validate_rows(listed["rows"])
        except LedgerError:
            schema_valid = False
    archives = sorted(p.name for p in adir.glob(V1_ARCHIVE_PREFIX + "*")) if adir.is_dir() else []
    archived, archive_torn = read_archive(adir) if adir.is_dir() else ({}, 0)
    archive_info: dict[str, Any] = {"archive_path": str(archive_path(adir)), "archive_count": len(archived),
                                    "archive_torn_lines": archive_torn, "archivable_rows": 0,
                                    "archive_pending_removal": 0}
    if state in {VALID_EMPTY, VALID_NONEMPTY} and schema_valid:
        try:
            _, drows = ledger_read_rows(adir)
            archive_info["archivable_rows"] = len(ledger_archive_closed(adir, dry_run=True)["due"])
            archive_info["archive_pending_removal"] = sum(1 for r in drows.values() if r["grant_id"] in archived)
        except LedgerError:
            pass
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
        "schema": SCHEMA_NAME,
        "schema_valid": schema_valid,
        "legacy_v1_tiers_pending_migration": legacy,
        "v1_archives": archives,
        **archive_info,
        "file_mode": mode,
        "lock_path": str(lock_path(adir)),
        "active_grants_count": active_count,
        **grant_checks,
        "audit_path": str(audit),
        "audit_readable": audit_readable,
        "audit_invalid_historical_rows": invalid_hist,
        "hooks_configured": hooks_configured,
        "failClosed": fail_closed,
        "StrReplace_protected": strreplace,
        "reader_fail_closed": True,
        "symlink": dest.is_symlink(),
        "ok": (state in {VALID_EMPTY, VALID_NONEMPTY, MISSING} and schema_valid and not dest.is_symlink()
               and not grant_checks["invariant_violations"]),
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
    pg.add_argument("--replace", action="store_true",
                    help="close the tier's active grant (status replaced) instead of refusing")
    pg.add_argument("--remote-request-id", default=None)

    pc = sub.add_parser("consume")
    pc.add_argument("--tier", required=True)
    pc.add_argument("--grant-id", default=None, help="consume only this exact grant row")

    parc = sub.add_parser("archive", help=f"move rows closed > {ARCHIVE_AFTER_DAYS} days ago to {ARCHIVE_NAME}")
    parc.add_argument("--days", type=int, default=ARCHIVE_AFTER_DAYS)
    parc.add_argument("--dry-run", action="store_true")

    plk = sub.add_parser("lookup")
    plk.add_argument("--grant-id", required=True)

    pr = sub.add_parser("revoke")
    pr.add_argument("--tier", required=True)
    pr.add_argument("--grant-id", default=None, help="revoke only this exact grant row")

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
            out = ledger_create_grant_row(args.tier, expires=args.expires, uses=args.uses, reason=args.reason,
                                          adir=adir, replace=args.replace,
                                          remote_request_id=args.remote_request_id)
            return _print_json({"ok": True, **out})
        if args.cmd == "consume":
            r = ledger_consume_grant(args.tier, adir=adir, grant_id=args.grant_id)
            r["ok"] = True
            return _print_json(r, 0 if r.get("consumed") else 3)
        if args.cmd == "archive":
            if args.days < ARCHIVE_AFTER_DAYS:
                raise LedgerError("invalid_days", f"--days below {ARCHIVE_AFTER_DAYS} is not allowed")
            return _print_json({"ok": True, **ledger_archive_closed(adir, days=args.days, dry_run=args.dry_run)})
        if args.cmd == "lookup":
            r = ledger_lookup(args.grant_id, adir)
            return _print_json({"ok": True, **r}, 0 if r["status"] != "missing" else 3)
        if args.cmd == "revoke":
            return _print_json({"ok": True, "grants": ledger_revoke(args.tier, adir=adir, grant_id=args.grant_id)})
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
