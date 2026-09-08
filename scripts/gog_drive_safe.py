#!/usr/bin/env python3
"""Safe wrapper around ``gog drive`` mutations.

Modes:
  plan     — read-only plan (never invokes gog)
  execute  — real upload with mandatory post-write **remote** hash verification
  refuse-check — validate argv and exit 0 only if safe; used by tests

Never treat ``gog … -n/--dry-run`` as a dry-run proof for the observed gog version.
Does not perform Drive mutations unless mode=execute.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.lib.drive_mutation_safety import (
    DriveSafetyError,
    DriveWritePlan,
    build_upload_plan,
    execute_upload,
    sanitize_or_refuse,
    sha256_file,
)


def _parse_uploaded_id(stdout: str) -> str | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        doc = json.loads(text)
        if isinstance(doc, dict):
            return doc.get("id") or doc.get("fileId") or doc.get("file_id")
    except json.JSONDecodeError:
        pass
    m = re.search(r'"id"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else None


def _remote_sha256_via_download(
    file_id: str,
    *,
    gog_bin: str,
    account: str | None,
    runner,
) -> dict:
    """Read-only remote verification: download bytes and hash locally."""
    with tempfile.TemporaryDirectory(prefix="gog-drive-readback-") as td:
        dest = Path(td) / "remote.bin"
        argv = [gog_bin, "drive", "download", file_id, str(dest), "--no-input", "--json"]
        if account:
            argv.extend(["--account", account])
        proc = runner(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not dest.is_file():
            raise DriveSafetyError(
                f"remote readback download failed: exit={proc.returncode} "
                f"stderr={(proc.stderr or '')[:500]}"
            )
        return {
            "id": file_id,
            "sha256": sha256_file(dest),
            "bytes": dest.stat().st_size,
            "readback_method": "gog_drive_download",
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)

    plan = sub.add_parser("plan", help="Read-only upload plan (no gog)")
    plan.add_argument("local_path", type=Path)
    plan.add_argument("--account")
    plan.add_argument("--parent", dest="parent_id")
    plan.add_argument("--replace", dest="replace_id")
    plan.add_argument("--name")

    ex = sub.add_parser("execute", help="Execute a planned upload (invokes gog)")
    ex.add_argument("local_path", type=Path)
    ex.add_argument("--account", required=True)
    ex.add_argument("--parent", dest="parent_id")
    ex.add_argument("--replace", dest="replace_id")
    ex.add_argument("--name")
    ex.add_argument("--gog-bin", default="gog")
    ex.add_argument(
        "--i-understand-this-mutates-drive",
        action="store_true",
        required=True,
        help="Required acknowledgement that execute mutates Drive",
    )

    chk = sub.add_parser("refuse-check", help="Refuse unsafe argv (for tests/CI)")
    chk.add_argument("argv", nargs=argparse.REMAINDER, help="Full gog argv after --")

    args = p.parse_args(argv)

    try:
        if args.mode == "plan":
            doc = build_upload_plan(
                args.local_path,
                account=args.account,
                parent_id=args.parent_id,
                replace_id=args.replace_id,
                name=args.name,
            )
            print(json.dumps(doc.to_dict(), indent=2, sort_keys=True))
            return 0
        if args.mode == "execute":
            plan_doc = build_upload_plan(
                args.local_path,
                account=args.account,
                parent_id=args.parent_id,
                replace_id=args.replace_id,
                name=args.name,
            )
            uploaded: dict[str, str | None] = {"id": args.replace_id, "stdout": ""}

            def runner(argv, **kwargs):
                proc = subprocess.run(list(argv), capture_output=True, text=True, check=False)
                uploaded["stdout"] = proc.stdout or ""
                parsed = _parse_uploaded_id(uploaded["stdout"])
                if parsed:
                    uploaded["id"] = parsed
                return proc

            def readback(plan_obj: DriveWritePlan):
                file_id = uploaded.get("id") or plan_obj.replace_id
                if not file_id:
                    raise DriveSafetyError(
                        "remote readback requires uploaded file id (upload JSON id or --replace)"
                    )
                return _remote_sha256_via_download(
                    str(file_id),
                    gog_bin=args.gog_bin,
                    account=args.account,
                    runner=subprocess.run,
                )

            receipt = execute_upload(
                plan_doc, gog_bin=args.gog_bin, runner=runner, readback=readback
            )
            print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True, default=str))
            return 0 if receipt.ok else 1
        if args.mode == "refuse-check":
            raw = list(args.argv or [])
            if raw and raw[0] == "--":
                raw = raw[1:]
            sanitize_or_refuse(raw)
            print(json.dumps({"ok": True, "argv": raw}))
            return 0
    except DriveSafetyError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
