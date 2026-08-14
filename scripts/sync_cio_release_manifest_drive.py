#!/usr/bin/env python3
"""sync_cio_release_manifest_drive.py — fail-closed Drive replace of RELEASE_MANIFEST.json.

Default is DRY / no write. ``--apply`` is required to mutate Drive.

Hard rules:
  * Exact Drive file ID ``1yGys5GswSQWNzimGvTZh71I1sC9EtUaM`` (no name discovery)
  * Requires ``--expected-local-sha`` (sha256 of local manifest bytes)
  * Requires ``--expected-remote-main-sha`` (git origin/main full SHA)
  * ``GOG_KEYRING_PASSWORD`` must already be in the environment
  * Never print the password; never accept a CLI password
  * Missing password → BLOCKED_SECRET_NOT_AVAILABLE (nonzero)
  * On apply: replace file, re-download, verify sha256

Authority: READ_ONLY_ADVISORY unless ``--apply`` is explicitly passed.
This module never sets server env, never sends Telegram, never deploys.
Dry path does not call gog (no write, no download).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL = REPO / "docs" / "investment-office" / "RELEASE_MANIFEST.json"
CANONICAL_DRIVE_FILE_ID = "1yGys5GswSQWNzimGvTZh71I1sC9EtUaM"
CANONICAL_FILE_ID = CANONICAL_DRIVE_FILE_ID
DEFAULT_ACCOUNT = "john@jwwhiting.com"
PASSWORD_ENV = "GOG_KEYRING_PASSWORD"
BLOCKED_SECRET = "BLOCKED_SECRET_NOT_AVAILABLE"
AUTHORITY = "READ_ONLY_ADVISORY"

# Injected in tests. Production uses subprocess.run.
GogRunner = Callable[[list[str], dict[str, str]], subprocess.CompletedProcess]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def origin_main_sha(repo: Path = REPO) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:
        pass
    return ""


def password_present() -> bool:
    # Presence only — never return or print the value.
    return bool((os.environ.get(PASSWORD_ENV) or "").strip())


def default_gog_runner(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, env=env)


def _gog_env() -> dict[str, str]:
    # Inherit the process env (password already present). Do not add CLI secret flags.
    return dict(os.environ)


def _receipt(**fields: Any) -> dict[str, Any]:
    out = {
        "authority": AUTHORITY,
        "at": _now_iso(),
        "canonical_file_id": CANONICAL_DRIVE_FILE_ID,
        "wrote": False,
    }
    out.update(fields)
    return out


def _print_receipt(receipt: dict[str, Any]) -> None:
    # Never include secret values. Only SET/MISSING for the password key.
    safe = dict(receipt)
    safe["password_env"] = "SET" if password_present() else "MISSING"
    print(json.dumps(safe, indent=2, default=str))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fail-closed Drive sync for CIO RELEASE_MANIFEST.json (dry default).",
    )
    p.add_argument("--apply", action="store_true", help="Write to Drive (replace + verify). Default is dry.")
    p.add_argument("--file-id", default=CANONICAL_DRIVE_FILE_ID, help="Must equal the canonical Drive file ID.")
    p.add_argument("--expected-local-sha", required=True, help="sha256 of the local manifest file bytes.")
    p.add_argument(
        "--expected-remote-main-sha",
        "--expected-remote-main",
        dest="expected_remote_main_sha",
        required=True,
        help="Full git SHA of origin/main.",
    )
    p.add_argument("--local-path", default=str(DEFAULT_LOCAL), help="Local RELEASE_MANIFEST.json path.")
    p.add_argument("--account", default=DEFAULT_ACCOUNT, help="gog account email.")
    p.add_argument("--repo", default=str(REPO), help="Git repo used to resolve origin/main.")
    return p.parse_args(argv)


def run_sync(
    *,
    apply: bool,
    file_id: str,
    expected_local_sha: str,
    expected_remote_main_sha: str,
    local_path: Path,
    account: str = DEFAULT_ACCOUNT,
    repo: Path = REPO,
    gog_runner: Optional[GogRunner] = None,
    origin_sha_fn: Optional[Callable[[Path], str]] = None,
) -> tuple[int, dict[str, Any]]:
    """Execute dry (default) or apply path. Never prints GOG_KEYRING_PASSWORD."""
    runner = gog_runner or default_gog_runner
    git_sha_fn = origin_sha_fn or origin_main_sha

    if file_id != CANONICAL_DRIVE_FILE_ID:
        rec = _receipt(
            ok=False,
            error="WRONG_FILE_ID",
            status="BLOCKED_WRONG_FILE_ID",
            file_id=file_id,
            apply=bool(apply),
        )
        return 2, rec

    if not password_present():
        rec = _receipt(
            ok=False,
            error=BLOCKED_SECRET,
            status=BLOCKED_SECRET,
            apply=bool(apply),
            wrote=False,
        )
        return 2, rec

    path = Path(local_path)
    if not path.is_file():
        rec = _receipt(ok=False, error="LOCAL_MANIFEST_MISSING", status="LOCAL_MANIFEST_MISSING",
                       local_path=str(path), apply=bool(apply))
        return 2, rec

    local_sha = sha256_file(path)
    want_local = str(expected_local_sha or "").strip().lower()
    if local_sha.lower() != want_local:
        rec = _receipt(
            ok=False,
            error="LOCAL_SHA_MISMATCH",
            status="BLOCKED_LOCAL_SHA_MISMATCH",
            local_sha=local_sha,
            expected_local_sha=want_local,
            apply=bool(apply),
        )
        return 2, rec

    remote_main = str(git_sha_fn(Path(repo)) or "").strip()
    want_main = str(expected_remote_main_sha or "").strip()
    if not remote_main or remote_main != want_main:
        rec = _receipt(
            ok=False,
            error="REMOTE_MAIN_SHA_MISMATCH",
            status="BLOCKED_REMOTE_MAIN_SHA_MISMATCH",
            origin_main_sha=remote_main,
            expected_remote_main_sha=want_main,
            apply=bool(apply),
        )
        return 2, rec

    # Fail-closed: local manifest pin must agree with the expected main SHA.
    try:
        man = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        rec = _receipt(ok=False, error="LOCAL_MANIFEST_UNREADABLE", status="LOCAL_MANIFEST_UNREADABLE",
                       detail=type(e).__name__, apply=bool(apply))
        return 2, rec
    pin = str(man.get("origin_main_sha") or man.get("canonical_source_sha") or "").strip()
    if pin and pin != want_main:
        rec = _receipt(
            ok=False,
            error="MANIFEST_PIN_NE_REMOTE_MAIN",
            status="MANIFEST_PIN_NE_REMOTE_MAIN",
            manifest_pin=pin,
            expected_remote_main_sha=want_main,
            apply=bool(apply),
        )
        return 2, rec

    if not apply:
        rec = _receipt(
            ok=True,
            dry_run=True,
            apply=False,
            wrote=False,
            status="DRY_RUN",
            local_sha=local_sha,
            origin_main_sha=remote_main,
            file_id=file_id,
            local_path=str(path),
            action="would_replace_then_redownload_verify",
        )
        return 0, rec

    env = _gog_env()
    upload_cmd = [
        "gog", "drive", "upload", str(path),
        "--replace", file_id,
        "--account", account,
        "--no-input",
        "--force",
    ]
    up = runner(upload_cmd, env)
    if up.returncode != 0:
        rec = _receipt(
            ok=False,
            error="DRIVE_REPLACE_FAILED",
            status="UPLOAD_FAILED",
            apply=True,
            wrote=False,
            detail=(up.stderr or up.stdout or "")[:240],
        )
        return 2, rec

    # Re-download to a sibling temp and verify sha256 of the live object.
    verify_path = path.with_suffix(path.suffix + ".drive-verify")
    remote_sha = ""
    try:
        dl_cmd = [
            "gog", "drive", "download", file_id,
            "--out", str(verify_path),
            "--account", account,
            "--no-input",
        ]
        dl = runner(dl_cmd, env)
        if dl.returncode != 0 or not verify_path.is_file():
            rec = _receipt(
                ok=False,
                error="DRIVE_REDOWNLOAD_FAILED",
                status="DRIVE_REDOWNLOAD_FAILED",
                apply=True,
                wrote=True,
                detail=(dl.stderr or dl.stdout or "")[:240],
            )
            return 2, rec
        remote_sha = sha256_file(verify_path)
    finally:
        try:
            if verify_path.exists():
                verify_path.unlink()
        except OSError:
            pass

    if remote_sha.lower() != local_sha.lower():
        rec = _receipt(
            ok=False,
            error="POST_APPLY_SHA_MISMATCH",
            status="POST_WRITE_HASH_MISMATCH",
            apply=True,
            wrote=True,
            local_sha=local_sha,
            drive_sha=remote_sha,
        )
        return 2, rec

    rec = _receipt(
        ok=True,
        dry_run=False,
        apply=True,
        wrote=True,
        verified=True,
        status="SYNCED",
        local_sha=local_sha,
        drive_sha=remote_sha,
        origin_main_sha=remote_main,
        file_id=file_id,
    )
    return 0, rec


def run(
    *,
    apply: bool,
    file_id: str,
    expected_local_sha: str,
    expected_remote_main: str,
    account: str,
    local_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Compatibility wrapper used by older call sites."""
    _code, rec = run_sync(
        apply=apply,
        file_id=file_id,
        expected_local_sha=expected_local_sha,
        expected_remote_main_sha=expected_remote_main,
        local_path=Path(local_path or DEFAULT_LOCAL),
        account=account,
    )
    return rec


def main(argv: Optional[list[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # Never accept a CLI password in any form.
    for tok in raw:
        low = tok.lower()
        if (
            low in {"--password", "-p", "--gog-password"}
            or low.startswith("--password=")
            or "GOG_KEYRING_PASSWORD" in tok
        ):
            rec = _receipt(ok=False, error="CLI_PASSWORD_FORBIDDEN", status="BLOCKED_PASSWORD_ON_ARGV", apply=False)
            _print_receipt(rec)
            return 2
    args = parse_args(raw)
    code, rec = run_sync(
        apply=bool(args.apply),
        file_id=str(args.file_id),
        expected_local_sha=str(args.expected_local_sha),
        expected_remote_main_sha=str(args.expected_remote_main_sha),
        local_path=Path(args.local_path),
        account=str(args.account),
        repo=Path(args.repo),
    )
    _print_receipt(rec)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
