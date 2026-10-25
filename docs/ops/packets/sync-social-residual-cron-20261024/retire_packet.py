"""Offline one-line cron candidate builder; never invokes a scheduler or process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


SPEC = Path(__file__).with_name("target.json")
PLAN_SCHEMA = "SyncSocialResidualCronPlan@v1"


class Refused(ValueError):
    """Snapshot or candidate differs from the reviewed exact one-line operation."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def target() -> tuple[bytes, bytes, str]:
    raw = SPEC.read_bytes()
    spec = json.loads(raw)
    if spec.get("schema") != "SyncSocialResidualCronTarget@v1" or spec.get("lane_id") != "sync-social-to-intelligence":
        raise Refused("unexpected target schema/lane")
    line = spec["target_line"].encode("ascii")
    prefix = spec["retired_prefix"].encode("ascii")
    if not line or b"\n" in line or b"\r" in line or not prefix.startswith(b"# RETIRED "):
        raise Refused("target must be one exact line and marker must be a RETIRED comment")
    if not prefix.endswith(b" ") or b"\n" in prefix or b"\r" in prefix:
        raise Refused("invalid comment prefix")
    return line, prefix, digest(raw)


def prepare(snapshot: bytes) -> tuple[bytes, dict]:
    """Preserve all bytes except one prefix; missing, drifted and duplicate targets refuse."""
    if b"\0" in snapshot:
        raise Refused("NUL byte in snapshot")
    line, prefix, spec_sha = target()
    parts = snapshot.split(b"\n")
    bodies = [p[:-1] if p.endswith(b"\r") else p for p in parts]
    active = [i for i, p in enumerate(bodies) if p == line]
    retired = [i for i, p in enumerate(bodies) if p == prefix + line]
    if len(active) > 1 or len(retired) > 1 or (active and retired):
        raise Refused("ambiguous target: duplicate active/retired exact lines")
    if len(active) == 1 and not retired:
        index = active[0]
        parts[index] = prefix + parts[index]
        candidate = b"\n".join(parts)
        status = "PLAN_READY"
        changed = 1
    elif not active and len(retired) == 1:
        index = retired[0]
        candidate = snapshot
        status = "ALREADY_RETIRED_IN_SNAPSHOT"
        changed = 0
    else:
        raise Refused("exact residual line absent; old flocked or other command variants are not this target")
    return candidate, {
        "schema": PLAN_SCHEMA,
        "status": status,
        "lane_id": "sync-social-to-intelligence",
        "target_spec_sha256": spec_sha,
        "target_line_sha256": digest(line),
        "retired_prefix": prefix.decode("ascii"),
        "snapshot_sha256": digest(snapshot),
        "candidate_sha256": digest(candidate),
        "changed_lines": changed,
        "line_number_in_snapshot": index + 1,
        "change": "PREFIX_ONE_EXACT_LINE_ONLY" if changed else "NONE",
        "n8n_acceptance": "NOT_MEASURED",
    }


def verify(snapshot: bytes, candidate: bytes, receipt: dict, installed: bytes | None = None) -> dict:
    expected, truth = prepare(snapshot)
    if candidate != expected:
        raise Refused("candidate is not the exact comment-only transformation of the snapshot")
    if any(receipt.get(k) != value for k, value in truth.items()):
        raise Refused("plan receipt no longer matches snapshot/candidate/target")
    if installed is not None and installed != candidate:
        raise Refused("installed read-back differs from the exact verified candidate; no automatic restoration")
    return {
        **truth,
        "verification": "INSTALLED_READBACK_MATCHES" if installed is not None else "OFFLINE_CANDIDATE_MATCHES",
        "scope": "one exact cron comment; not n8n execution or business-output acceptance",
    }


def stamp(value: str | None) -> str:
    now = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise Refused("observation time must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def private_write(path: Path, data: bytes) -> None:
    # Refuse overwrite. Backups and captured cron state may contain private environment declarations.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="offline: read a supplied snapshot, never crontab")
    plan.add_argument("--snapshot", type=Path, required=True)
    plan.add_argument("--out-dir", type=Path, required=True)
    plan.add_argument("--observed-at")
    check = sub.add_parser("verify", help="offline: prove exact candidate and optional supplied read-back")
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--receipt", type=Path, required=True)
    check.add_argument("--installed", type=Path)
    check.add_argument("--verified-out", type=Path)
    args = ap.parse_args(argv)
    try:
        before = args.snapshot.read_bytes()
        if args.command == "plan":
            candidate, receipt = prepare(before)
            receipt["observed_at"] = stamp(args.observed_at)
            # Validate everything before creating a packet directory.
            args.out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            private_write(args.out_dir / "crontab.before", before)
            private_write(args.out_dir / "crontab.candidate", candidate)
            private_write(args.out_dir / "plan.json", (json.dumps(receipt, indent=2) + "\n").encode())
            line, prefix, _ = target()
            # Zero context: display only the reviewed target, never surrounding cron/env lines.
            n = receipt["line_number_in_snapshot"]
            diff = (f"--- crontab.before\n+++ crontab.candidate\n@@ -{n} +{n} @@\n"
                    + "-" + line.decode() + "\n+" + prefix.decode() + line.decode() + "\n") if receipt["changed_lines"] else ""
            private_write(args.out_dir / "target-only.diff", diff.encode())
            print(json.dumps(receipt, sort_keys=True))
        else:
            result = verify(before, args.candidate.read_bytes(), json.loads(args.receipt.read_text()),
                            args.installed.read_bytes() if args.installed else None)
            if args.verified_out:
                result["verified_at"] = stamp(None)
                private_write(args.verified_out, (json.dumps(result, indent=2) + "\n").encode())
            print(json.dumps(result, sort_keys=True))
    except (Refused, OSError, KeyError, UnicodeError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
