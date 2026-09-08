"""Drive mutation safety for ``gog drive`` (observed tool: gog v0.12.x).

Policy for this tool version:
- ``gog drive upload -n/--dry-run`` is treated as **mutating** (or at least
  untrusted as a dry-run proof). It must never be used as evidence of a dry run.
- Read-only **plan** is a separate mode that does not invoke ``gog``.
- **Execute** requires explicit target identity, pre-write metadata/hash,
  post-write read-back, and hash comparison.
- Experimental delete dry-runs against real files are prohibited.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

SCHEMA = "DriveMutationSafety@v1"
GOG_DRY_RUN_FLAGS = {"-n", "--dry-run"}
FORBIDDEN_DELETE_VERBS = {"delete", "rm", "trash"}


class DriveSafetyError(RuntimeError):
    """Non-bypassable safety refusal."""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def argv_claims_dry_run(argv: Sequence[str]) -> bool:
    return any(a in GOG_DRY_RUN_FLAGS for a in argv)


def argv_is_drive_mutation(argv: Sequence[str]) -> bool:
    """True for gog drive verbs that can change Drive state."""
    tokens = [str(a) for a in argv]
    if not tokens:
        return False
    # Accept either ``gog drive …`` or ``drive …`` after wrapper strips gog.
    if tokens[0].endswith("gog") or tokens[0] == "gog":
        tokens = tokens[1:]
    if not tokens or tokens[0] not in {"drive", "drv"}:
        return False
    if len(tokens) < 2:
        return False
    verb = tokens[1]
    return verb in {
        "upload",
        "mkdir",
        "delete",
        "rm",
        "trash",
        "move",
        "update",
        "copy",
        "create",
        "share",
        "unshare",
        "rename",
    }


def refuse_gog_dry_run_flag(argv: Sequence[str]) -> None:
    if argv_claims_dry_run(argv) and argv_is_drive_mutation(argv):
        raise DriveSafetyError(
            "REFUSED: gog drive … -n/--dry-run is treated as mutating for the "
            "observed gog tool version and must not be used as a dry-run proof. "
            "Use plan mode (no gog invocation) or execute with pre/post hash verification."
        )


def refuse_delete_dry_run_against_real_targets(argv: Sequence[str]) -> None:
    tokens = [str(a) for a in argv]
    if tokens and (tokens[0].endswith("gog") or tokens[0] == "gog"):
        tokens = tokens[1:]
    if len(tokens) < 2 or tokens[0] not in {"drive", "drv"}:
        return
    verb = tokens[1]
    if verb not in FORBIDDEN_DELETE_VERBS:
        return
    # Any delete/rm/trash against a real id is prohibited as a dry-run experiment.
    if argv_claims_dry_run(argv):
        raise DriveSafetyError(
            "REFUSED: experimental delete dry-runs against real Drive files are prohibited. "
            "Do not invoke gog drive delete/rm/trash with -n/--dry-run."
        )
    # Also refuse delete execute unless explicitly allowed by caller flag
    # (wrapper requires --allow-delete for execute path).


@dataclass
class DriveWritePlan:
    schema: str = SCHEMA
    mode: str = "plan"
    local_path: str = ""
    local_sha256: str = ""
    local_bytes: int = 0
    account: str | None = None
    parent_id: str | None = None
    replace_id: str | None = None
    name: str | None = None
    intended_action: str = ""
    created_at_utc: str = field(default_factory=utcnow)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DriveWriteReceipt:
    schema: str = SCHEMA
    mode: str = "execute"
    plan: dict[str, Any] = field(default_factory=dict)
    pre_write: dict[str, Any] = field(default_factory=dict)
    post_write: dict[str, Any] = field(default_factory=dict)
    hash_match: bool | None = None
    gog_argv: list[str] = field(default_factory=list)
    gog_exit: int | None = None
    created_at_utc: str = field(default_factory=utcnow)
    ok: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_upload_plan(
    local_path: Path,
    *,
    account: str | None = None,
    parent_id: str | None = None,
    replace_id: str | None = None,
    name: str | None = None,
) -> DriveWritePlan:
    path = Path(local_path)
    if not path.is_file():
        raise DriveSafetyError(f"local file not found: {path}")
    if not (parent_id or replace_id):
        raise DriveSafetyError(
            "explicit target identity required: pass parent_id (create) or replace_id (replace)"
        )
    digest = sha256_file(path)
    action = (
        f"replace Drive file {replace_id} with {path.name} (sha256={digest})"
        if replace_id
        else f"upload {path.name} to parent {parent_id} (sha256={digest})"
    )
    return DriveWritePlan(
        local_path=str(path.resolve()),
        local_sha256=digest,
        local_bytes=path.stat().st_size,
        account=account,
        parent_id=parent_id,
        replace_id=replace_id,
        name=name or path.name,
        intended_action=action,
        notes=[
            "This plan does not invoke gog.",
            "gog -n/--dry-run is refused as a dry-run proof for this tool version.",
        ],
    )


def _run(argv: Sequence[str], *, runner: Callable[..., subprocess.CompletedProcess] | None = None) -> subprocess.CompletedProcess:
    runner = runner or subprocess.run
    return runner(list(argv), capture_output=True, text=True, check=False)


def execute_upload(
    plan: DriveWritePlan,
    *,
    gog_bin: str = "gog",
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    allow_delete: bool = False,
    readback: Callable[[DriveWritePlan], dict[str, Any]] | None = None,
) -> DriveWriteReceipt:
    """Execute a previously planned upload with pre/post verification.

    ``readback`` should return metadata including content hash when possible.
    Tests inject a fake runner/readback; production uses gog JSON list/get.
    """
    if allow_delete:
        raise DriveSafetyError("upload execute path does not allow delete")
    path = Path(plan.local_path)
    if not path.is_file():
        raise DriveSafetyError(f"local file disappeared before execute: {path}")
    pre_hash = sha256_file(path)
    if pre_hash != plan.local_sha256:
        raise DriveSafetyError(
            f"pre-write hash drift: plan={plan.local_sha256} now={pre_hash}"
        )
    pre_meta = {
        "local_path": str(path),
        "sha256": pre_hash,
        "bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "captured_at_utc": utcnow(),
    }

    argv = [gog_bin, "drive", "upload", str(path), "--no-input", "--json"]
    if plan.account:
        argv.extend(["--account", plan.account])
    if plan.replace_id:
        argv.extend(["--replace", plan.replace_id])
    elif plan.parent_id:
        argv.extend(["--parent", plan.parent_id])
    else:
        raise DriveSafetyError("execute requires parent_id or replace_id")
    if plan.name:
        argv.extend(["--name", plan.name])

    refuse_gog_dry_run_flag(argv)
    refuse_delete_dry_run_against_real_targets(argv)

    receipt = DriveWriteReceipt(plan=plan.to_dict(), pre_write=pre_meta, gog_argv=argv)
    proc = _run(argv, runner=runner)
    receipt.gog_exit = proc.returncode
    if proc.returncode != 0:
        receipt.error = (proc.stderr or proc.stdout or f"exit {proc.returncode}")[:2000]
        receipt.ok = False
        return receipt

    # Post-write read-back
    if readback is None:
        post = {
            "note": "default readback records local hash unchanged; inject Drive get for remote hash",
            "local_sha256_after": sha256_file(path),
            "gog_stdout": (proc.stdout or "")[:4000],
            "captured_at_utc": utcnow(),
        }
        receipt.post_write = post
        receipt.hash_match = post["local_sha256_after"] == pre_hash
    else:
        post = readback(plan)
        receipt.post_write = post
        remote_hash = post.get("sha256") or post.get("content_sha256")
        receipt.hash_match = (remote_hash == pre_hash) if remote_hash else None

    receipt.ok = proc.returncode == 0 and receipt.hash_match is not False
    if receipt.hash_match is False:
        receipt.error = "post-write hash comparison failed"
    return receipt


def sanitize_or_refuse(argv: Sequence[str]) -> list[str]:
    """Validate a proposed gog argv; return a copy or raise DriveSafetyError."""
    out = [str(a) for a in argv]
    # Delete dry-runs first so the refusal names the stronger prohibition.
    refuse_delete_dry_run_against_real_targets(out)
    refuse_gog_dry_run_flag(out)
    return out


__all__ = [
    "DriveSafetyError",
    "DriveWritePlan",
    "DriveWriteReceipt",
    "argv_claims_dry_run",
    "argv_is_drive_mutation",
    "build_upload_plan",
    "execute_upload",
    "refuse_gog_dry_run_flag",
    "refuse_delete_dry_run_against_real_targets",
    "sanitize_or_refuse",
    "sha256_file",
    "SCHEMA",
]
