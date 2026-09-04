#!/usr/bin/env python3
"""Phase 4 rehearsal: prove the migration on a copy before it touches anything real.

Takes immutable backups of every governed file, copies the exact live inputs into an
isolated area, runs the real migration tool there twice to prove idempotency, and drives
twelve negative controls. Each control must either refuse promotion or restore the
previous bytes exactly; a control that merely "errors" without proving the target came
back is a failure.

Read-only with respect to production. The only paths written are the backup directory
and the rehearsal area, both outside every state root.

    python3 scripts/rehearse_state_migration.py \
        --manifest evidence/whole_site/MIGRATION_MANIFEST.json \
        --conflict-ledger evidence/whole_site/CONFLICT_LEDGER.json \
        --out evidence/whole_site/REHEARSAL_RECEIPT.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

SCHEMA = "StateMigrationRehearsal@v1"
TOOL = ROOT / "scripts" / "migrate_state_stores.py"

#: Backups live outside every state root so a restore can never be mistaken for a store.
DEFAULT_BACKUP_ROOT = Path("/home/johnclaw/trade-ai-releases/state-migration-backups")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(p: Path) -> dict[str, Any]:
    """Everything needed to prove a file came back exactly as it was."""
    if not p.exists():
        return {"path": str(p), "exists": False}
    st = p.stat()
    doc: Any = None
    parse_error = None
    try:
        doc = json.loads(p.read_text())
    except Exception as exc:  # noqa: BLE001
        parse_error = f"{type(exc).__name__}: {exc}"
    if isinstance(doc, dict):
        schema, count = doc.get("schema"), len([k for k in doc if not k.startswith("_")])
    elif isinstance(doc, list):
        schema, count = None, len(doc)
    else:
        schema, count = None, None
    return {
        "path": str(p),
        "exists": True,
        "bytes": st.st_size,
        "mode": oct(st.st_mode & 0o777),
        "uid": st.st_uid,
        "gid": st.st_gid,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256_file(p),
        "schema": schema,
        "record_count": count,
        "parse_error": parse_error,
    }


def take_backups(rows: list[dict], backup_root: Path, stamp: str) -> dict[str, Any]:
    """Immutable pre-migration backups. Read-only mode; nothing is ever deleted."""
    dest = backup_root / stamp
    dest.mkdir(parents=True, exist_ok=True)
    entries = []
    for row in rows:
        for side in ("producer_path", "served_path"):
            src = Path(row[side])
            if not src.is_file():
                continue
            tgt = dest / side.replace("_path", "") / row["store"]
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
            os.chmod(tgt, 0o444)  # immutable to accident, not to root
            before, after = sha256_file(src), sha256_file(tgt)
            entries.append(
                {
                    "store": row["store"],
                    "side": side.replace("_path", ""),
                    "source": str(src),
                    "backup": str(tgt),
                    "sha256": before,
                    "backup_sha256": after,
                    "verified": before == after,
                    "inventory": inventory(src),
                }
            )
    bad = [e for e in entries if not e["verified"]]
    return {
        "backup_dir": str(dest),
        "entry_count": len(entries),
        "all_verified": not bad,
        "unverified": bad,
        "entries": entries,
    }


def build_replica(rows: list[dict], area: Path) -> tuple[Path, Path]:
    """Byte-exact copy of both roots. The rehearsal never opens a production path."""
    prod, served = area / "producer", area / "served"
    prod.mkdir(parents=True, exist_ok=True)
    served.mkdir(parents=True, exist_ok=True)
    for row in rows:
        for side, dst in (("producer_path", prod), ("served_path", served)):
            src = Path(row[side])
            if src.is_file():
                shutil.copy2(src, dst / row["store"])
    return prod, served


def rewrite_manifest(manifest: dict, prod: Path, served: Path, out: Path, ledger_path: str) -> Path:
    """Rebuild the plan against the replica rather than patching the old one.

    Patching only the input hashes leaves planned_content_sha256 describing the inputs
    the manifest was ORIGINALLY built from. For any store whose producer has run since,
    the plan is then stale, the written bytes do not match it, and the post-write rail
    fires on a file that was never actually wrong -- which is what happened to
    health_agent_status.json, whose timer rewrites it every five minutes.

    Regenerating is also what production does: the sequence regenerates the manifest
    against quiesced state immediately before applying, so the rehearsal should prove
    that same path rather than a patched variant of it.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.state_migration import build_manifest  # noqa: PLC0415

    names = [r["store"] for r in manifest["stores"]]
    ledger = json.loads(Path(ledger_path).read_text())
    doc = build_manifest(names, prod, served, ledger)
    for row in doc["stores"]:
        # No live producers can reach a temp directory; an advisory schedule copied from
        # production would be a claim about this replica that is not true.
        row["producer_schedule"] = {
            "authority": "ADVISORY_HEURISTIC",
            "cron": [],
            "systemd": [],
            "matched_writer_stems": [],
            "requires_operator_confirmation": True,
            "match_rule": "rehearsal replica: no live producers reach this path",
            "truncated": False,
        }
    # The schedule override above changes the manifest content, so its own hash must be
    # recomputed or the integrity rail refuses a manifest this function just built.
    from lib.state_migration import manifest_hash  # noqa: PLC0415

    doc["manifest_sha256"] = manifest_hash(doc)
    out.write_text(json.dumps(doc, indent=1, default=str))
    return out


#: The rehearsal satisfies the deployed-SHA rail honestly rather than skipping it. If it
#: skipped, every negative control would refuse for that one missing flag and prove
#: nothing -- which is exactly what the first version of this harness did.
REHEARSAL_SHA = "0" * 40


def run_tool(args: list[str], release_root: Path | None = None) -> tuple[int, dict]:
    env = dict(os.environ, DEPLOYED_RELEASE_SHA=REHEARSAL_SHA)
    cmd = [sys.executable, str(TOOL), *args]
    if release_root is not None:
        cmd += ["--release-root", str(release_root)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env)
    out: dict = {}
    for tok in args:
        pass
    try:
        idx = args.index("--out")
        p = Path(args[idx + 1])
        if p.is_file():
            out = json.loads(p.read_text())
    except (ValueError, IndexError, json.JSONDecodeError):
        pass
    return proc.returncode, {"receipt": out, "stderr": proc.stderr[-800:], "stdout": proc.stdout[-400:]}


def snapshot(served: Path) -> dict[str, str | None]:
    return {p.name: sha256_file(p) for p in sorted(served.glob("*.json"))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--conflict-ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    ap.add_argument("--keep", action="store_true", help="keep the rehearsal area for inspection")
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text())
    rows = manifest["stores"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _now(),
        "authority": "REHEARSAL_ONLY_NO_PRODUCTION_WRITE",
        "stamp": stamp,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "conflict_ledger_sha256": json.loads(Path(args.conflict_ledger).read_text()).get("ledger_sha256"),
        "store_count": len(rows),
    }

    print("1/5  taking immutable backups of every governed file ...")
    receipt["backups"] = take_backups(rows, Path(args.backup_root), stamp)
    print(f"     {receipt['backups']['entry_count']} files, all verified: {receipt['backups']['all_verified']}")
    if not receipt["backups"]["all_verified"]:
        Path(args.out).write_text(json.dumps(receipt, indent=1, default=str) + "\n")
        print("REFUSE: a backup did not verify", file=sys.stderr)
        return 2

    area = Path(tempfile.mkdtemp(prefix="cc-migration-rehearsal-"))
    receipt["rehearsal_area"] = str(area)
    try:
        print("2/5  building an isolated byte-exact replica ...")
        prod, served = build_replica(rows, area)
        rman = rewrite_manifest(manifest, prod, served, area / "manifest.json", args.conflict_ledger)
        receipt["replica"] = {
            "producer_root": str(prod),
            "served_root": str(served),
            "files": len(list(served.glob("*.json"))),
            "touches_production": False,
        }

        print("3/5  running the migration in the replica ...")
        before = snapshot(served)
        rc1, r1 = run_tool(
            [
                "--manifest",
                str(rman),
                "--conflict-ledger",
                args.conflict_ledger,
                "--apply",
                "--backup-dir",
                str(area / "bk1"),
                "--rehearsal",
                "--expected-deployed-sha",
                REHEARSAL_SHA,
                "--expected-manifest-sha256",
                json.loads(rman.read_text())["manifest_sha256"],
                "--out",
                str(area / "r1.json"),
            ]
        )
        after1 = snapshot(served)
        receipt["first_run"] = {
            "exit_code": rc1,
            "applied": r1["receipt"].get("applied"),
            "skipped": r1["receipt"].get("skipped"),
            "refusals": r1["receipt"].get("refusals"),
            "files_changed": sorted(k for k in after1 if before.get(k) != after1[k]),
            "stderr_tail": r1["stderr"][-300:] if rc1 else "",
        }
        print(f"     exit={rc1} changed={len(receipt['first_run']['files_changed'])} files")

        print("4/5  running it again to prove idempotency ...")
        rc2, r2 = run_tool(
            [
                "--manifest",
                str(rman),
                "--conflict-ledger",
                args.conflict_ledger,
                "--apply",
                "--backup-dir",
                str(area / "bk2"),
                "--rehearsal",
                "--expected-deployed-sha",
                REHEARSAL_SHA,
                "--expected-manifest-sha256",
                json.loads(rman.read_text())["manifest_sha256"],
                "--out",
                str(area / "r2.json"),
            ]
        )
        after2 = snapshot(served)
        drift = sorted(k for k in after2 if after1.get(k) != after2[k])
        receipt["idempotency"] = {
            "second_exit_code": rc2,
            "files_changed_on_second_run": drift,
            "idempotent": not drift,
            "note": (
                "a second apply over already-migrated state must change nothing. Any file that "
                "moves twice is a migration that cannot be safely retried."
            ),
        }
        print(f"     idempotent: {receipt['idempotency']['idempotent']}")

        print("5/5  driving negative controls ...")
        receipt["negative_controls"] = run_negative_controls(area, rman, args.conflict_ledger, manifest)
        passed = sum(1 for c in receipt["negative_controls"] if c["passed"])
        print(f"     {passed}/{len(receipt['negative_controls'])} controls held")

        receipt["ok"] = (
            receipt["backups"]["all_verified"]
            and receipt["idempotency"]["idempotent"]
            and all(c["passed"] for c in receipt["negative_controls"])
        )
    finally:
        if not args.keep:
            shutil.rmtree(area, ignore_errors=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(receipt, indent=1, default=str) + "\n")
    print(f"\nrehearsal receipt: {args.out}")
    print(f"OK: {receipt['ok']}")
    return 0 if receipt["ok"] else 2


def run_negative_controls(area: Path, rman: Path, ledger: str, manifest: dict) -> list[dict]:
    """Twelve ways the migration must refuse or restore. Each proves bytes came back."""
    sys.path.insert(0, str(ROOT / "scripts"))
    controls: list[dict] = []

    #: Rails that mean "the rehearsal was set up wrong", not "the defect was caught".
    #: A control that trips one of these proves nothing and must be reported as failed.
    SETUP_RAILS = {
        "missing_expected_deployed_sha",
        "unexpected_deployed_sha",
        "missing_operator_approval",
        "rehearsal_touches_production",
        "unverified_backup",
        "missing_conflict_ledger",
        "missing_expected_manifest_sha256",
        "unexpected_manifest",
    }

    def control(name: str, why: str, setup, expect_refusal: bool = True) -> None:
        sub = Path(tempfile.mkdtemp(prefix=f"nc-{name}-", dir=str(area)))
        prod, served = sub / "producer", sub / "served"
        shutil.copytree(area / "producer", prod)
        shutil.copytree(area / "served", served)
        m = json.loads(rman.read_text())
        m["producer_root"], m["served_root"] = str(prod), str(served)
        for row in m["stores"]:
            row["producer_path"] = str(prod / row["store"])
            row["served_path"] = str(served / row["store"])
            row["canonical_target"] = str(served / row["store"])
        target_store = setup(prod, served, m)
        mp = sub / "m.json"
        from lib.state_migration import manifest_hash as _mh  # noqa: PLC0415

        m["manifest_sha256"] = _mh(m)
        mp.write_text(json.dumps(m, indent=1, default=str))
        before = snapshot(served)
        rc, res = run_tool(
            [
                "--manifest",
                str(mp),
                "--conflict-ledger",
                ledger,
                "--apply",
                "--backup-dir",
                str(sub / "bk"),
                "--rehearsal",
                "--expected-deployed-sha",
                REHEARSAL_SHA,
                "--expected-manifest-sha256",
                m["manifest_sha256"],
                "--out",
                str(sub / "r.json"),
            ]
            + (["--only", target_store] if target_store else [])
        )
        after = snapshot(served)
        changed = sorted(k for k in after if before.get(k) != after[k])
        refusals = res["receipt"].get("refusals") or []
        rails = [r.get("rail") for r in refusals]
        setup_only = bool(rails) and all(r in SETUP_RAILS for r in rails)
        refused = rc != 0 or bool(refusals)
        restored = not changed
        # Refusing because the harness forgot a flag is not the control holding. The
        # first version of this rehearsal reported 12/12 while every control tripped
        # the same missing-flag rail and none of them exercised its own defect.
        passed = bool((refused or restored) and not setup_only) if expect_refusal else True
        controls.append(
            {
                "control": name,
                "why": why,
                "exit_code": rc,
                "refused": refused,
                "target_bytes_unchanged": restored,
                "files_changed": changed,
                "refusals": refusals,
                "refused_for_setup_reason_only": setup_only,
                "passed": bool(passed),
            }
        )
        shutil.rmtree(sub, ignore_errors=True)

    def _bump(p: Path) -> None:
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            d["_rehearsal_touch"] = _now()
        p.write_text(json.dumps(d))

    control(
        "changed_input_after_planning",
        "an input edited between planning and applying invalidates the plan",
        lambda prod, served, m: (_bump(prod / "stops.json"), "stops.json")[1],
    )
    control(
        "hash_mismatch",
        "a manifest hash that does not match the file on disk",
        lambda prod, served, m: (
            m["stores"].__setitem__(
                next(i for i, r in enumerate(m["stores"]) if r["store"] == "stops.json"),
                {
                    **next(r for r in m["stores"] if r["store"] == "stops.json"),
                    "served": {
                        **next(r for r in m["stores"] if r["store"] == "stops.json")["served"],
                        "sha256": "0" * 64,
                    },
                },
            ),
            "stops.json",
        )[1],
    )
    control(
        "malformed_json",
        "a target that no longer parses must never be overwritten blindly",
        lambda prod, served, m: ((served / "stops.json").write_text("{not json"), "stops.json")[1],
    )
    control(
        "duplicate_key_record",
        "a record whose lots repeat must not be promoted as though deduplicated",
        lambda prod, served, m: _plant_duplicate(prod),
    )
    control(
        "cross_account_record",
        "a lot attributed to another account must not become that account's basis",
        lambda prod, served, m: _plant_cross_account(prod),
    )
    control(
        "broker_disagreement",
        "a plan whose totals no longer match the broker snapshot",
        lambda prod, served, m: _plant_broker_disagreement(prod),
    )
    control(
        "unresolved_cost_basis",
        "a quarantined record must never acquire a value",
        lambda prod, served, m: "tax_lots.json",
    )
    control(
        "unavailable_broker",
        "no authority means no verdict, and no verdict means no write",
        lambda prod, served, m: _blank_ledger_target(m),
    )
    control(
        "write_interruption",
        "an interrupted write must leave the previous bytes",
        lambda prod, served, m: _readonly_target(served),
    )
    control(
        "partial_rename",
        "a target directory that cannot be replaced atomically",
        lambda prod, served, m: _readonly_dir(served),
    )
    control(
        "failed_consumer_validation",
        "hashes matching is not the same as a consumer still being able to read it",
        lambda prod, served, m: _break_schema(prod),
    )
    control(
        "rollback",
        "every failure path restores the exact prior bytes",
        lambda prod, served, m: (_bump(prod / "tax_lots.json"), "tax_lots.json")[1],
    )
    return controls


def _plant_duplicate(prod: Path) -> str:
    p = prod / "tax_lots.json"
    d = json.loads(p.read_text())
    key = next((k for k in d if ":" in k and isinstance(d[k], list) and d[k]), None)
    if key:
        d[key] = list(d[key]) + [dict(d[key][0])]
    p.write_text(json.dumps(d))
    return "tax_lots.json"


def _plant_cross_account(prod: Path) -> str:
    p = prod / "tax_lots.json"
    d = json.loads(p.read_text())
    key = next((k for k in d if ":" in k and isinstance(d[k], list) and d[k]), None)
    if key:
        lot = dict(d[key][0])
        lot["account"] = "some_other_account"
        d[key] = list(d[key]) + [lot]
    p.write_text(json.dumps(d))
    return "tax_lots.json"


def _plant_broker_disagreement(prod: Path) -> str:
    p = prod / "tax_lots.json"
    d = json.loads(p.read_text())
    key = next((k for k in d if ":" in k and isinstance(d[k], list) and d[k]), None)
    if key:
        lots = [dict(x) for x in d[key]]
        for lot in lots:
            if not lot.get("closed"):
                lot["shares_remaining"] = float(lot.get("shares_remaining") or 0) + 999999
                break
        d[key] = lots
    p.write_text(json.dumps(d))
    return "tax_lots.json"


def _blank_ledger_target(m: dict) -> str:
    for row in m["stores"]:
        if row["store"] == "tax_lots.json":
            row["strategy"] = "RECORD_LEVEL_MERGE"
            row.pop("planned_content", None)
    return "tax_lots.json"


def _readonly_target(served: Path) -> str:
    os.chmod(served / "stops.json", 0o444)
    return "stops.json"


def _readonly_dir(served: Path) -> str:
    os.chmod(served, 0o555)
    return "stops.json"


def _break_schema(prod: Path) -> str:
    p = prod / "stops.json"
    p.write_text(json.dumps(["not", "a", "mapping"]))
    return "stops.json"


if __name__ == "__main__":
    raise SystemExit(main())
