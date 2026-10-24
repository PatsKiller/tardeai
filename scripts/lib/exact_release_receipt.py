"""Canonical release receipt: observed CURRENT identity is separate from operation intent.

This is a readback/writer helper, not a release or authority mechanism. It never
executes an artifact, changes CURRENT, queries CI, or grants an action. The shell
release tool supplies its already-authorized operation and health result.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

SCHEMA = "CioExactMainDeployReceipt@v2"
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _text(path: Path, limit: int = 65536) -> str:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("oversized_artifact_metadata")
    return raw.decode("utf-8")


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate_metadata_key")
        out[key] = value
    return out


def _json(path: Path) -> dict:
    result = json.loads(_text(path), object_pairs_hook=_object)
    if not isinstance(result, dict):
        raise ValueError("metadata_not_object")
    return result


def _venv(directory: Path) -> tuple[dict | None, str]:
    """Read only the artifact's completion marker; ambient prepare env is irrelevant."""
    try:
        marker = {}
        for line in _text(directory / ".venv/.complete").splitlines():
            key, value = line.split("=", 1)
            if key in marker:
                raise ValueError("duplicate_venv_marker_key")
            marker[key] = value
        digest, version = marker["lock_sha256"], marker["python_version"]
        if not SHA256.fullmatch(digest) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("invalid_venv_marker")
        if marker["venv_id"] != f"py{version}-{digest[:12]}":
            raise ValueError("venv_id_mismatch")
        # The lock is data, never executed. Bound the read like other metadata.
        lock = _text(directory / "requirements.lock.txt", 16 * 1024 * 1024).encode("utf-8")
        if hashlib.sha256(lock).hexdigest() != digest:
            raise ValueError("venv_lock_mismatch")
        interpreter = directory / ".venv/bin/python"
        if not interpreter.is_file():
            raise ValueError("venv_interpreter_missing")
        return {
            "venv_id": marker["venv_id"],
            "lock_sha256": digest,
            "python_version": version,
            "venv_python": str(interpreter),
            "action": "observed",
        }, "AVAILABLE"
    except (OSError, ValueError, KeyError, UnicodeError):
        return None, "UNAVAILABLE"


def artifact_identity(directory: Path | None, releases_base: Path) -> dict[str, Any]:
    unavailable = {
        "availability": "UNAVAILABLE",
        "sha": None,
        "release_dir": None,
        "source_pr": None,
        "release_venv": None,
        "venv_availability": "UNAVAILABLE",
    }
    if directory is None:
        return {**unavailable, "reason": "artifact_missing"}
    try:
        resolved = directory.resolve(strict=True)
        if not resolved.is_dir() or resolved.parent != releases_base.resolve(strict=True):
            raise ValueError("artifact_outside_release_base")
        pins = [_text(resolved / name, 128).strip() for name in ("BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT")]
        if not all(SHA.fullmatch(pin) for pin in pins) or len(set(pins)) != 1:
            raise ValueError("artifact_pins_invalid_or_disagree")
        source_pr = None
        try:
            stamp = _json(resolved / "BUILD_STAMP.json")
            # Existing stamps have no PR. Only release-bound metadata may supply one.
            pr = stamp.get("source_pr")
            if stamp.get("build_sha") == pins[0] and isinstance(pr, (str, int)) and not isinstance(pr, bool):
                if re.fullmatch(r"[1-9][0-9]*", str(pr)):
                    source_pr = str(pr)
        except (OSError, ValueError, UnicodeError):
            pass
        venv, venv_status = _venv(resolved)
        return {
            "availability": "AVAILABLE",
            "sha": pins[0],
            "release_dir": str(resolved),
            "source_pr": source_pr,
            "release_venv": venv,
            "venv_availability": venv_status,
            "reason": None,
        }
    except (OSError, ValueError, RuntimeError, UnicodeError):
        return {**unavailable, "reason": "artifact_identity_unavailable"}


def _current_signature(current: Path) -> tuple:
    stat = current.lstat()
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, os.readlink(current)


def observed_identity(releases_base: Path) -> dict[str, Any]:
    current = releases_base / "CURRENT"
    try:
        before = _current_signature(current)
        result = artifact_identity(current, releases_base)
        if _current_signature(current) != before:
            raise ValueError("current_changed_during_readback")
        return result
    except (OSError, ValueError, RuntimeError):
        return {**artifact_identity(None, releases_base), "reason": "current_missing_or_changed"}


def _matches(observed: dict, directory: str, sha: str) -> bool:
    try:
        return (
            observed["availability"] == "AVAILABLE"
            and bool(SHA.fullmatch(sha))
            and observed["sha"] == sha
            and observed["release_dir"] == str(Path(directory).resolve(strict=True))
        )
    except (OSError, ValueError, RuntimeError):
        return False


def build_receipt(
    *,
    releases_base: Path,
    ok: bool,
    mode: str,
    health: str,
    rolled_back: bool,
    attempted_dir: str,
    attempted_sha: str,
    source_pr: str = "",
    prev_release: str = "",
    extra: str = "",
    pin_receipt: str = "",
    rollback_target: str = "",
    rollback_sha: str = "",
    rolled_from: str = "",
    ci_file: Path | None = None,
) -> tuple[dict, bool]:
    observed = observed_identity(releases_base)
    attempted = artifact_identity(Path(attempted_dir) if attempted_dir else None, releases_base)
    attempted_matches = _matches(attempted, attempted_dir, attempted_sha)
    rollback_matches = rolled_back and _matches(observed, rollback_target, rollback_sha)
    errors = []
    if ok and not attempted_matches:
        errors.append("attempted_artifact_identity_unavailable_or_mismatched")
    if ok and mode in {"promote", "rollback"} and not _matches(observed, attempted_dir, attempted_sha):
        errors.append("current_does_not_match_expected_target")
    if rolled_back and not rollback_matches:
        errors.append("rollback_target_not_observed")
    if mode not in {"prepare", "promote", "rollback"}:
        errors.append("unsupported_operation_mode")
    accepted = ok and not errors
    rec = {
        "schema": SCHEMA,
        "ok": accepted,
        "mode": mode,
        "health": health,
        "rolled_back": bool(rollback_matches),
        "prepared_ok": accepted if mode == "prepare" else None,
        "deployed_availability": observed["availability"],
        "deployed_unavailable_reason": observed["reason"],
        "content_sha": observed["sha"],
        "deployed_sha": observed["sha"],
        "source_pr": observed["source_pr"],
        "release_dir": observed["release_dir"],
        "release_venv": observed["release_venv"],
        "venv_availability": observed["venv_availability"],
        "attempted_target": {
            "sha": attempted_sha or None,
            "release_dir": attempted_dir or None,
            "source_pr": source_pr or None,
            "artifact_availability": attempted["availability"],
            "observed_sha": attempted["sha"],
            "identity_matches": attempted_matches,
        },
        "rollback": {
            "requested": rolled_back,
            "target_release": rollback_target or None,
            "target_sha": rollback_sha or None,
            "from_release": rolled_from or None,
        },
        "prev_release": prev_release or None,
        "extra": extra,
        "release_pin_receipt": pin_receipt or None,
        "readback_errors": errors,
        "at": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "script": "cio_phase2_exact_main_deploy.sh",
    }
    if ci_file:
        try:
            ci = _json(ci_file)
            if observed["sha"] and ci.get("candidate_sha") == observed["sha"]:
                rec["post_merge_ci"] = ci
            elif attempted_matches and ci.get("candidate_sha") == attempted_sha:
                rec["attempted_target"]["post_merge_ci"] = ci
        except (OSError, ValueError, UnicodeError):
            pass
    # False operation outcomes are still successfully recorded. Contradictory
    # success/rollback claims fail the caller after writing the truthful record.
    return rec, not errors


def _started(value: str) -> datetime | None:
    """The deploy script's start time (``date +%s.%N``); None when absent or not a sane epoch."""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if not (1_500_000_000 < ts < 4_000_000_000):
        return None
    return datetime.fromtimestamp(ts, timezone.utc)


HISTORY_SCHEMA = "CioExactMainDeployReceiptHistory@v1"
HISTORY_NAME = "deploy_receipt_history.jsonl"


def history_row(receipt: dict, started_at: str = "") -> dict:
    """The compact, append-only history row (scripts/lib/release_train_timing.py reads it). Release train Phase 7
    (2026-10-22): it carries the operation's measured duration (``--started-at`` to the receipt's ``at``), so the
    08:00 latest start and the 06:00 drain probe plan around measured promote and rollback times. The receipt itself
    keeps its exact v2 field set (report_lane_governance_packet.py pins it); the duration lives only here."""
    attempted = receipt.get("attempted_target") or {}
    started = _started(started_at)
    try:
        finished = datetime.fromisoformat(str(receipt.get("at")))
    except ValueError:
        finished = None
    duration = None
    if started and finished and started <= finished:
        duration = round((finished - started).total_seconds(), 1)
    return {
        "schema": HISTORY_SCHEMA,
        "at": receipt.get("at"),
        "mode": receipt.get("mode"),
        "ok": receipt.get("ok") is True,
        "health": receipt.get("health"),
        "rolled_back": receipt.get("rolled_back"),
        "sha": attempted.get("sha"),
        "deployed_sha": receipt.get("deployed_sha"),
        "started_at": started.isoformat() if started else None,
        "duration_s": duration,
        "extra": receipt.get("extra"),
    }


def append_history(path: Path, receipt: dict, started_at: str = "") -> bool:
    """Append one row (O_APPEND, fsync). Never rewrites or truncates; a failure is reported, not raised: a missing
    row only leaves a duration unmeasured, and every reader of the history fails closed on unmeasured."""
    raw = (json.dumps(history_row(receipt, started_at), sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def atomic_write(path: Path, receipt: dict) -> None:
    raw = (json.dumps(receipt, indent=2, allow_nan=False) + "\n").encode("utf-8")
    fd, temp = tempfile.mkstemp(prefix=".deploy-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases-base", required=True, type=Path)
    parser.add_argument("--receipt-file", required=True, type=Path)
    parser.add_argument("--ci-file", type=Path)
    for name in (
        "mode",
        "health",
        "attempted-dir",
        "attempted-sha",
        "source-pr",
        "prev-release",
        "extra",
        "pin-receipt",
        "rollback-target",
        "rollback-sha",
        "rolled-from",
        "started-at",
    ):
        parser.add_argument("--" + name, default="")
    parser.add_argument("--ok", choices=("true", "false"), required=True)
    parser.add_argument("--rolled-back", choices=("true", "false"), required=True)
    args = vars(parser.parse_args(argv))
    destination = args.pop("receipt_file")
    started_at = args.pop("started_at")
    args["ok"] = args["ok"] == "true"
    args["rolled_back"] = args["rolled_back"] == "true"
    receipt, valid = build_receipt(**args)
    atomic_write(destination, receipt)
    print("wrote deploy receipt", destination)
    history = Path(destination).parent / HISTORY_NAME
    if not append_history(history, receipt, started_at):
        print("WARN: deploy receipt history not appended", history)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
