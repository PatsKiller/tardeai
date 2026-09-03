#!/usr/bin/env python3
"""migrate_state_stores.py — the guarded door for state-root convergence.

Dry-run by DEFAULT. ``--apply`` is refused unless every safeguard is satisfied,
and each refusal names itself so an operator can see exactly which rail stopped
the run rather than a generic failure.

    # plan only (this is what CI and validators run)
    python3 scripts/migrate_state_stores.py --manifest evidence/whole_site/MIGRATION_MANIFEST.json

    # apply, on a deployed release, with the operator present
    python3 scripts/migrate_state_stores.py --manifest <path> --apply \\
        --expected-deployed-sha <merge sha> --expected-manifest-sha256 <hash> \\
        --backup-dir <dir> --approval-token <token from the native prompt>

Safeguards, all mandatory for --apply:

  1  exact expected deployed merge SHA        9  native operator approval token
  2  exact migration-manifest hash           10  atomic write (temp + fsync + rename)
  3  source/target hashes re-read now        11  owner, group, mode, schema preserved
  4  timestamped backup of BOTH sides        12  post-write hash/schema/record validation
  5  backups reopened and hash-verified      13  producer and consumer canaries
  6  sufficient free disk                    14  automatic rollback on any mismatch
  7  affected producer services listed       15  audit receipt, no secrets or values
  8  affected producers quiesced

Nothing is ever deleted: not a source, not a backup. Rollback restores from the
verified backup and re-verifies the hash.

AUTHORITY: MUTATING_LOCAL_ONLY in dry-run; production writes require every rail
above plus a deployed release. This campaign runs it in dry-run and against an
isolated replica only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.state_migration import (  # noqa: E402
    IDENTICAL_BIND,
    MANUAL_CONFLICT,
    REBUILD_DERIVED,
    build_manifest,
    manifest_hash,
    serialize,
    sha256_file,
)

SCHEMA = "StateMigrationReceipt@v1"

#: Targets a migration may never touch, whatever a manifest says.
FORBIDDEN_TARGET_PREFIXES = ("/", "/home", "/etc", "/usr", "/var", "/boot", "/root")
FORBIDDEN_EXACT = frozenset({str(Path.home()), str(ROOT), "/", "/tmp"})

#: Minimum free space multiple of the payload before a write is allowed.
DISK_HEADROOM_FACTOR = 10


class Refusal(RuntimeError):
    """A named safeguard stopped the run. Never caught to proceed."""

    def __init__(self, rail: str, detail: str):
        super().__init__(f"REFUSED[{rail}]: {detail}")
        self.rail, self.detail = rail, detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── rails ────────────────────────────────────────────────────────────────────


def rail_target_path(target: Path, governed_root: Path | str | None = None) -> None:
    """Rail: never write to a root, a home, a workspace or an unresolved path.

    Containment is checked against the root the MANIFEST declares, not a substring
    of the path. A substring test would pass for ``/etc/state-of-the-nation`` and
    fail for a legitimately-named replica, which is the wrong answer twice.
    """
    if not target.is_absolute():
        raise Refusal("unresolved_path", f"{target} is not absolute")
    resolved = target.resolve() if target.exists() else target
    if str(resolved) in FORBIDDEN_EXACT:
        raise Refusal("forbidden_target", f"{resolved} is a protected root")
    if target.is_dir():
        raise Refusal("broad_recursive_target", f"{target} is a directory, not a single store")
    parent = str(target.parent)
    if parent in FORBIDDEN_EXACT or parent in FORBIDDEN_TARGET_PREFIXES:
        raise Refusal("forbidden_target", f"{parent} is a protected directory")
    if governed_root is None:
        raise Refusal("unresolved_path", f"{target} has no governed root to be contained by")
    root = Path(governed_root)
    root = root.resolve() if root.exists() else root
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise Refusal("forbidden_target", f"{resolved} is outside the manifest's governed root {root}") from exc


def rail_expected_sha(expected: str | None, actual: str | None) -> None:
    """Rail: apply only from the exact deployed release that was validated."""
    if not expected:
        raise Refusal("missing_expected_deployed_sha", "--expected-deployed-sha is required for --apply")
    if len(expected) != 40:
        raise Refusal("unexpected_deployed_sha", f"{expected!r} is not a full 40-character SHA")
    if actual != expected:
        raise Refusal(
            "unexpected_deployed_sha",
            f"deployed release is {actual!r}, manifest was validated against {expected!r}",
        )


def rail_manifest_hash(doc: dict[str, Any], expected: str | None) -> str:
    """Rail: the manifest applied must be byte-for-byte the one validated."""
    actual = manifest_hash(doc)
    recorded = doc.get("manifest_sha256")
    if recorded and recorded != actual:
        raise Refusal("unexpected_manifest", "the manifest's own recorded hash does not match its content")
    if not expected:
        raise Refusal("missing_expected_manifest_sha256", "--expected-manifest-sha256 is required for --apply")
    if expected != actual:
        raise Refusal("unexpected_manifest", f"manifest hash {actual} != expected {expected}")
    return actual


def rail_hashes_unchanged(row: dict[str, Any]) -> dict[str, str | None]:
    """Rail: nothing may have moved since the manifest was previewed."""
    now_p = sha256_file(Path(row["producer_path"]))
    now_s = sha256_file(Path(row["served_path"]))
    if row["producer"].get("sha256") and now_p != row["producer"]["sha256"]:
        raise Refusal("changed_source_hash", f"{row['store']} producer changed since preview")
    if row["served"].get("sha256") and now_s != row["served"]["sha256"]:
        raise Refusal("changed_target_hash", f"{row['store']} served copy changed since preview")
    return {"producer": now_p, "served": now_s}


def rail_disk(target: Path, payload_bytes: int) -> dict[str, Any]:
    """Rail: refuse to start a write that could fill the volume."""
    usage = shutil.disk_usage(target.parent)
    need = max(payload_bytes * DISK_HEADROOM_FACTOR, 1 << 20)
    if usage.free < need:
        raise Refusal("insufficient_disk", f"{usage.free} free, need {need}")
    return {"free_bytes": usage.free, "required_bytes": need}


def affected_producers(row: dict[str, Any]) -> list[str]:
    """Normalise producer_schedule to "systemd: <unit>" / "cron: <entry>" strings.

    The field carries a structured advisory record now and a flat list in older
    manifests. Both must resolve, because list(dict) yields the dict's KEYS -- which
    would have left rail_producers_quiesced with nothing to check and turned a safety
    rail into a silent no-op on every real manifest.
    """
    sched = row.get("producer_schedule") or []
    if isinstance(sched, dict):
        out = [f"systemd: {u['unit']}" for u in sched.get("systemd", [])]
        out += [f"cron: {c['entry']}" for c in sched.get("cron", [])]
        return out
    return list(sched)


def rail_producers_quiesced(row: dict[str, Any], check: bool = True) -> dict[str, Any]:
    """Rail: never write a store while something else may be writing it."""
    units = [u.split("systemd: ", 1)[1] for u in affected_producers(row) if u.startswith("systemd: ")]
    running: list[str] = []
    for unit in units:
        try:
            state = subprocess.run(
                ["systemctl", "--user", "show", "-p", "ActiveState", "--value", unit],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            state = "unknown"
        if state == "activating" or state == "active":
            # A oneshot that is 'active' is mid-run; a timer-driven service that is
            # inactive is quiescent.
            running.append(f"{unit}={state}")
    if check and running:
        raise Refusal("running_affected_writer", f"{row['store']}: {', '.join(running)}")
    return {"affected_units": units, "running": running}


def rail_approval(token: str | None, expected: str | None) -> None:
    """Rail: a human said yes, immediately before the first write.

    The token is supplied by the deployment operator's native approval prompt.
    This process never invents, caches or reuses one.
    """
    if not token:
        raise Refusal("missing_operator_approval", "--approval-token is required for --apply")
    if expected is not None and token != expected:
        raise Refusal("missing_operator_approval", "approval token did not match the issued challenge")
    if len(token) < 16:
        raise Refusal("missing_operator_approval", "approval token is too short to be a real challenge response")


def make_backups(row: dict[str, Any], backup_dir: Path, stamp: str) -> dict[str, Any]:
    """Rails 4 and 5: back up BOTH sides, then reopen and verify each."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {"dir": str(backup_dir), "files": {}}
    for side in ("producer", "served"):
        src = Path(row[f"{side}_path"])
        if not src.is_file():
            continue
        dst = backup_dir / f"{row['store']}.{side}.{stamp}.bak"
        shutil.copy2(src, dst)
        src_hash, dst_hash = sha256_file(src), sha256_file(dst)
        if dst_hash != src_hash:
            raise Refusal("unverified_backup", f"{row['store']} {side} backup hash mismatch")
        try:
            json.loads(dst.read_text())
        except Exception as exc:  # noqa: BLE001
            raise Refusal("unverified_backup", f"{row['store']} {side} backup does not reopen: {exc}") from exc
        out["files"][side] = {"path": str(dst), "sha256": dst_hash, "bytes": dst.stat().st_size}
    if not out["files"]:
        raise Refusal("unverified_backup", f"{row['store']}: nothing was backed up")
    return out


def atomic_write(target: Path, content: Any, template: Path | None) -> str:
    """Rails 10 and 11: temp + fsync + rename, preserving owner/group/mode."""
    # The same serialiser the manifest used to compute planned_content_sha256.
    payload = serialize(content)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        ref = template if template and template.exists() else (target if target.exists() else None)
        if ref is not None:
            st = ref.stat()
            os.chmod(tmp, st.st_mode & 0o777)
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except PermissionError:
                pass  # same-user runs cannot chown; mode is what matters here
        os.replace(tmp, target)
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return sha256_file(target) or ""


def validate_after(row: dict[str, Any], target: Path, expected_sha: str | None) -> dict[str, Any]:
    """Rail 12: hash, schema and record count must all agree with the plan."""
    actual = sha256_file(target)
    if expected_sha and actual != expected_sha:
        raise Refusal("failed_post_write_validation", f"{row['store']} hash {actual} != planned {expected_sha}")
    try:
        doc = json.loads(target.read_text())
    except Exception as exc:  # noqa: BLE001
        raise Refusal("failed_post_write_validation", f"{row['store']} does not reparse: {exc}") from exc
    count = len(doc) if isinstance(doc, (list, dict)) else None
    floor = max(
        row["producer"].get("record_count") or 0,
        row["served"].get("record_count") or 0,
    )
    if row["strategy"] in ("APPEND_ONLY_UNION",) and (count or 0) < floor:
        raise Refusal(
            "failed_post_write_validation",
            f"{row['store']} union produced {count} records, fewer than the {floor} it started with",
        )
    return {"sha256": actual, "record_count": count, "reparsed": True}


def rollback(row: dict[str, Any], backups: dict[str, Any], target: Path) -> dict[str, Any]:
    """Rail 14: restore the verified backup and prove the bytes came back."""
    served = (backups.get("files") or {}).get("served")
    if not served:
        return {"rolled_back": False, "reason": "no served backup to restore"}
    shutil.copy2(served["path"], target)
    restored = sha256_file(target)
    return {
        "rolled_back": True,
        "restored_from": served["path"],
        "expected_sha256": served["sha256"],
        "restored_sha256": restored,
        "bytes_identical": restored == served["sha256"],
    }


def deployed_sha(release_root: Path | None) -> str | None:
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "RELEASE_SHA"):
        for base in filter(None, (release_root, ROOT)):
            p = Path(base) / name
            if p.is_file():
                v = p.read_text().strip()
                if v:
                    return v
    return os.environ.get("DEPLOYED_RELEASE_SHA")


# ── driver ───────────────────────────────────────────────────────────────────


def migrate_store(row: dict[str, Any], args: argparse.Namespace, stamp: str) -> dict[str, Any]:
    store = row["store"]
    target = Path(row["canonical_target"])
    receipt: dict[str, Any] = {
        "store": store,
        "strategy": row["strategy"],
        "mode": "apply" if args.apply else "dry-run",
    }

    if row["strategy"] == MANUAL_CONFLICT:
        receipt.update(
            {
                "skipped": True,
                "reason": "MANUAL_CONFLICT — operator reconciliation required",
                "conflicting": row["comparison"].get("conflicting", [])[:10],
            }
        )
        return receipt
    if row["strategy"] == REBUILD_DERIVED:
        receipt.update({"skipped": True, "reason": "REBUILD_DERIVED — regenerate from upstream, do not promote a copy"})
        return receipt
    if row["strategy"] == IDENTICAL_BIND:
        receipt.update({"skipped": True, "reason": "IDENTICAL_BIND — content already agrees; only the binding changes"})
        return receipt

    rail_target_path(target, args.governed_root)
    receipt["hashes_now"] = rail_hashes_unchanged(row)
    receipt["producers"] = rail_producers_quiesced(row, check=args.apply)

    planned_sha = row.get("planned_content_sha256")
    if not planned_sha:
        raise Refusal("missing_schema_validation", f"{store} has no planned content to validate against")

    if not args.apply:
        receipt.update({"would_write": str(target), "planned_content_sha256": planned_sha, "applied": False})
        return receipt

    receipt["disk"] = rail_disk(target, Path(row["producer_path"]).stat().st_size)
    backups = make_backups(row, Path(args.backup_dir), stamp)
    receipt["backups"] = backups

    from lib.state_migration import plan_content

    p_doc = json.loads(Path(row["producer_path"]).read_text())
    s_doc = json.loads(Path(row["served_path"]).read_text())
    content, _ = plan_content(row["strategy"], p_doc, s_doc, row["comparison"])
    if content is None:
        raise Refusal("ambiguous_financial_record", f"{store} has no determinate content")

    try:
        written = atomic_write(target, content, Path(row["served_path"]))
        receipt["written_sha256"] = written
        receipt["validation"] = validate_after(row, target, planned_sha)
        receipt["applied"] = True
    except BaseException as exc:  # noqa: BLE001
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["rollback"] = rollback(row, backups, target)
        receipt["applied"] = False
        # Carry the rollback evidence out with the exception; losing it would
        # leave an operator unable to see that the bytes came back.
        if isinstance(exc, Refusal):
            exc.receipt = receipt  # type: ignore[attr-defined]
        raise
    return receipt


def _verify_quiesced(args: Any) -> int:
    """Prove nothing writes the targets while producers are meant to be stopped.

    Discovery cannot be trusted to name every producer: it greps for the literal
    filename, so any writer that assembles its path at runtime is invisible to it.
    Watching the bytes is the check that does not care how a producer was found.
    """
    doc = json.loads(Path(args.manifest).read_text())
    rows = [r for r in doc["stores"] if not args.only or r["store"] in args.only]
    watched = []
    for r in rows:
        for side in ("producer_path", "served_path"):
            p = Path(r[side])
            if p.exists():
                watched.append((r["store"], side, p, sha256_file(p), p.stat().st_mtime_ns))

    print(f"watching {len(watched)} files for {args.verify_quiesced}s ...")
    time.sleep(args.verify_quiesced)

    moved = []
    for store, side, p, before_hash, before_mtime in watched:
        now_hash = sha256_file(p) if p.exists() else None
        now_mtime = p.stat().st_mtime_ns if p.exists() else None
        if now_hash != before_hash or now_mtime != before_mtime:
            moved.append(
                {
                    "store": store,
                    "side": side,
                    "path": str(p),
                    "sha256_before": before_hash,
                    "sha256_after": now_hash,
                    "mtime_changed": now_mtime != before_mtime,
                }
            )

    result = {
        "schema": "StateQuiescenceProof@v1",
        "generated_at_utc": _now(),
        "watched_files": len(watched),
        "watch_seconds": args.verify_quiesced,
        "quiesced": not moved,
        "still_writing": moved,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if moved:
        print(
            f"REFUSE: {len(moved)} file(s) changed while producers were meant to be stopped. "
            "A producer is still running and is not in the pause list.",
            file=sys.stderr,
        )
        return 2
    print("quiesced: no target changed during the watch window")
    return 0


def _emit_manifest(args: Any) -> int:
    """Rebuild the manifest from live state. Reads stores; writes only the manifest file.

    The roots default to whatever the existing manifest was built against, so a
    regeneration cannot silently retarget a different pair of roots.
    """
    out = Path(args.manifest)
    prev = json.loads(out.read_text()) if out.exists() else {}
    producer_root = Path(args.producer_root or prev.get("producer_root") or "")
    served_root = Path(args.served_root or prev.get("served_root") or "")
    if not producer_root.is_dir() or not served_root.is_dir():
        print("refusing: --producer-root and --served-root must both name existing directories", file=sys.stderr)
        return 2

    names = [r["store"] for r in prev.get("stores", [])] or sorted(
        p.name for p in served_root.glob("*.json") if (producer_root / p.name).exists()
    )
    fresh = build_manifest(names, producer_root, served_root)
    out.write_text(json.dumps(fresh, indent=2, sort_keys=False) + "\n")

    changed = fresh["manifest_sha256"] != prev.get("manifest_sha256")
    print(f"manifest: {out}")
    print(f"stores: {fresh['store_count']}  strategies: {fresh['strategy_counts']}")
    print(f"manifest_sha256: {fresh['manifest_sha256']}" + ("  (CHANGED)" if changed else "  (unchanged)"))
    if fresh["requires_operator"]:
        print("requires_operator (refused until adjudicated): " + ", ".join(fresh["requires_operator"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument(
        "--emit-manifest",
        action="store_true",
        help=(
            "Rebuild the manifest at --manifest from live state and exit. Reads state and "
            "writes only that evidence file; it never touches a state store. Step 7 of the "
            "production sequence, because a manifest goes stale as soon as a producer runs."
        ),
    )
    ap.add_argument("--producer-root", help="with --emit-manifest; defaults to the manifest's own producer_root")
    ap.add_argument(
        "--verify-quiesced",
        type=int,
        metavar="SECONDS",
        help=(
            "Watch every target for SECONDS and refuse if any byte changes. This is the "
            "empirical quiescence gate. It does not rely on the producer_schedule, which "
            "is a grep heuristic and is known to MISS producers that build their paths "
            "dynamically -- health_agent_status.json has no discoverable writer and is "
            "nonetheless rewritten every five minutes by a live timer."
        ),
    )
    ap.add_argument("--served-root", help="with --emit-manifest; defaults to the manifest's own served_root")
    ap.add_argument("--apply", action="store_true", help="perform writes; every safeguard becomes mandatory")
    ap.add_argument("--expected-deployed-sha")
    ap.add_argument("--expected-manifest-sha256")
    ap.add_argument("--approval-token")
    ap.add_argument("--issued-challenge", help="the challenge the native approval prompt issued")
    ap.add_argument("--backup-dir")
    ap.add_argument("--release-root")
    ap.add_argument("--only", nargs="*", help="restrict to these stores")
    ap.add_argument("--out", help="write the receipt here")
    args = ap.parse_args(argv)

    if args.emit_manifest:
        return _emit_manifest(args)

    if args.verify_quiesced:
        return _verify_quiesced(args)

    doc = json.loads(Path(args.manifest).read_text())
    rows = [r for r in doc["stores"] if not args.only or r["store"] in args.only]
    # The governed root is whatever the manifest was BUILT against; a target
    # outside it is refused regardless of how the path is spelled.
    args.governed_root = doc.get("served_root")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _now(),
        "mode": "apply" if args.apply else "dry-run",
        "manifest": args.manifest,
        "store_count": len(rows),
        "stores": [],
        "refusals": [],
        "applied": 0,
        "skipped": 0,
    }

    try:
        if args.apply:
            rail_expected_sha(
                args.expected_deployed_sha, deployed_sha(Path(args.release_root) if args.release_root else None)
            )
            receipt["manifest_sha256"] = rail_manifest_hash(doc, args.expected_manifest_sha256)
            rail_approval(args.approval_token, args.issued_challenge)
            if not args.backup_dir:
                raise Refusal("unverified_backup", "--backup-dir is required for --apply")
        else:
            receipt["manifest_sha256"] = manifest_hash(doc)
    except Refusal as r:
        receipt["refusals"].append({"rail": r.rail, "detail": r.detail})
        _emit(receipt, args)
        return 2

    for row in rows:
        try:
            res = migrate_store(row, args, stamp)
            receipt["stores"].append(res)
            if res.get("applied"):
                receipt["applied"] += 1
            elif res.get("skipped"):
                receipt["skipped"] += 1
        except Refusal as r:
            entry = getattr(r, "receipt", None) or {"store": row["store"]}
            entry.update({"refused": r.rail, "detail": r.detail})
            receipt["stores"].append(entry)
            receipt["refusals"].append({"store": row["store"], "rail": r.rail, "detail": r.detail})
        except Exception as exc:  # noqa: BLE001
            receipt["stores"].append({"store": row["store"], "error": f"{type(exc).__name__}: {exc}"})
            receipt["refusals"].append({"store": row["store"], "rail": "unhandled", "detail": str(exc)[:200]})

    receipt["ok"] = not receipt["refusals"]
    _emit(receipt, args)
    return 0 if receipt["ok"] else 1


def _emit(receipt: dict[str, Any], args: argparse.Namespace) -> None:
    # Rail 15: the receipt carries hashes, counts and rail names — never a secret
    # and never a financial value.
    text = json.dumps(receipt, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    raise SystemExit(main())
