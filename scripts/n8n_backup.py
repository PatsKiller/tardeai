#!/usr/bin/env python3
"""n8n_backup.py — the complete n8n backup bundle: database dump + data volume + workflow export + compose files,
encrypted and copied to Google Drive with the existing verify-before-prune rules (n8n program package 0.2a).

The nightly database dump (scripts/n8n_lab_backup.sh, 01:15-03:30 window, 14 kept) is KEPT as it is. This adds
what it lacks: the ``n8n-data`` volume (it holds the encryption key; without it stored credentials cannot be read),
a JSON export of every workflow, the compose files, and an off-server copy.

    python3 scripts/n8n_backup.py --dry-run     # checks every precondition, writes nothing
    python3 scripts/n8n_backup.py --apply       # bundle -> host copy -> gpg -> Drive -> md5 verify -> Drive N+1 -> receipt
    python3 scripts/n8n_backup.py --apply --no-drive   # bundle and host copy only (no upload, no Drive retention)

Bundle ``n8n_backup_<YYYYMMDD_HHMMSS>.tar.gz`` holds: ``MANIFEST.json`` (sizes + sha256 per member, workflow and
credential counts), ``db/<dump>`` (+ its manifest), ``volume/n8n-data.tar.gz``, ``workflows.json``, ``compose/*``.
Host: the newest ``HOST_KEEP`` bundles under ``<state>/backups/n8n/`` (0600). Drive: ``n8n_backup_*.gpg`` objects,
newest keep_n+1, deleted only after the newest is verified by name, size and md5 (``backup_enforcer.py --n8n``).
Receipt: ``<state>/backups/n8n/n8n_backup_last.json`` — written on success AND on failure (``ok`` false + reason).

Restore: ``gpg --batch --passphrase-file <pass> -d n8n_backup_<stamp>.tar.gz.gpg | tar xz`` then follow the n8n
restore procedure (volume first, then the database, then verify the workflows).

AUTHORITY: READ_ONLY_ADVISORY on n8n (reads the database and the volume; nothing in n8n changes). Writes only the
backup directory, a temp dir, and one encrypted object on the backup Drive folder. No broker, no credential value
is printed. Exit 1 whenever the receipt says ok:false.
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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import backup_enforcer as be  # noqa: E402 -- flat scripts/ import, the enforcer is a sibling script

APP_CONTAINER = os.environ.get("N8N_APP_CONTAINER", "m8m-n8n")
DB_CONTAINER = os.environ.get("N8N_DB_CONTAINER", "m8m-n8n-db")
OUT_DIR = Path(os.environ.get("N8N_BACKUP_DIR", str(Path.home() / "trade-ai-releases/persistent-state/backups/n8n")))
PASS_FILE = Path.home() / ".openclaw/credentials/env_data_backup.pass"
VOLUME_ROOT = "/home/node/.n8n"
#: event logs are 10 MB rotating run history (rebuilt by n8n); the key, settings and storage are what matter
VOLUME_EXCLUDES = ("./n8nEventLog*",)
HOST_KEEP = 3
DUMP_MAX_AGE_S = 26 * 3600
PREFIX = "n8n_backup"
RECEIPT_NAME = "n8n_backup_last.json"
SCHEMA = "N8nBackupReceipt@v1"


class BackupError(RuntimeError):
    """A step failed; the message is the receipt's reason."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], *, timeout: int = 600, stdout: Any = subprocess.PIPE) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=stdout, stderr=subprocess.PIPE, timeout=timeout, check=False)


def _need(ok: bool, reason: str) -> None:
    if not ok:
        raise BackupError(reason)


def newest_dump(out_dir: Path) -> Optional[Path]:
    dumps = sorted(out_dir.glob("n8n-lab-*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    return dumps[0] if dumps else None


def ensure_fresh_dump(out_dir: Path, now: float) -> Path:
    """The newest nightly dump if it is younger than DUMP_MAX_AGE_S, else make one with the existing script."""
    dump = newest_dump(out_dir)
    if dump is not None and now - dump.stat().st_mtime <= DUMP_MAX_AGE_S and Path(str(dump) + ".manifest.json").exists():
        return dump
    res = _run(["bash", str(ROOT / "scripts/n8n_lab_backup.sh"), "--apply"], timeout=900)
    _need(res.returncode == 0, f"n8n_lab_backup_failed:rc={res.returncode}")
    dump = newest_dump(out_dir)
    _need(dump is not None and Path(str(dump) + ".manifest.json").exists(), "dump_missing_after_backup")
    return dump  # type: ignore[return-value] -- _need above raised if None


def export_volume(dest: Path) -> dict:
    """tar+gzip of the data volume read through the app container (no docker run, no host path to /var/lib)."""
    cmd = ["docker", "exec", APP_CONTAINER, "tar", "-C", VOLUME_ROOT, "-czf", "-"]
    for pat in VOLUME_EXCLUDES:
        cmd += ["--exclude", pat]
    cmd += ["."]
    with dest.open("wb") as fh:
        res = _run(cmd, stdout=fh)
    # tar rc 1 = a file changed while read (the event log is excluded; storage is quiet): the archive is checked below
    _need(res.returncode in (0, 1), f"volume_tar_failed:rc={res.returncode}")
    _need(_run(["gzip", "-t", str(dest)]).returncode == 0, "volume_tar_not_gzip")
    listing = _run(["tar", "-tzf", str(dest)])
    _need(listing.returncode == 0, "volume_tar_unreadable")
    names = listing.stdout.decode("utf-8", "replace").splitlines()
    # the encryption key is in ./config: a volume copy without it is not a backup of the credentials
    _need(any(n.rstrip("/").endswith("config") for n in names), "volume_tar_missing_config")
    return {"members": len(names), "bytes": dest.stat().st_size, "sha256": _sha256(dest)}


def export_workflows(dest: Path) -> dict:
    import n8n_export_workflows as ex  # noqa: PLC0415 -- only this step needs it
    rows = ex.read_workflows(DB_CONTAINER)
    _need(isinstance(rows, list) and len(rows) > 0, "workflow_export_empty")
    dest.write_text(json.dumps(rows, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"count": len(rows), "ids": sorted(str(r.get("id")) for r in rows), "bytes": dest.stat().st_size,
            "sha256": _sha256(dest)}


def copy_compose_files(dest_dir: Path) -> list[str]:
    res = _run(["docker", "inspect", APP_CONTAINER, "--format",
                '{{index .Config.Labels "com.docker.compose.project.config_files"}}'], timeout=60)
    _need(res.returncode == 0, "compose_label_unreadable")
    names: list[str] = []
    for raw in res.stdout.decode("utf-8", "replace").strip().split(","):
        src = Path(raw.strip())
        if raw.strip() and src.is_file():
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_dir / src.name)
            names.append(src.name)
    _need(bool(names), "compose_files_not_found")
    return names


def build_bundle(stage: Path, stamp: str, now: float) -> tuple[Path, dict]:
    dump = ensure_fresh_dump(OUT_DIR, now)
    dump_manifest = Path(str(dump) + ".manifest.json")
    dman = json.loads(dump_manifest.read_text(encoding="utf-8"))
    (stage / "db").mkdir()
    shutil.copy2(dump, stage / "db" / dump.name)
    shutil.copy2(dump_manifest, stage / "db" / dump_manifest.name)
    (stage / "volume").mkdir()
    vol = export_volume(stage / "volume" / "n8n-data.tar.gz")
    wf = export_workflows(stage / "workflows.json")
    compose = copy_compose_files(stage / "compose")
    # a workflow export that disagrees with the dump's own count by more than concurrent edits is a bad export
    dump_count = dman.get("workflow_count_after")
    members = {}
    for f in sorted(p for p in stage.rglob("*") if p.is_file()):
        members[str(f.relative_to(stage))] = {"bytes": f.stat().st_size, "sha256": _sha256(f)}
    manifest = {"schema": "N8nBackupManifest@v1", "as_of": _utc(), "stamp": stamp,
                "dump": dump.name, "dump_workflow_count": dump_count, "export_workflow_count": wf["count"],
                "credentials_count": dman.get("credentials_count_after"), "volume_members": vol["members"],
                "compose": compose, "members": members}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    bundle = stage.parent / f"{PREFIX}_{stamp}.tar.gz"
    res = _run(["tar", "-C", str(stage), "-czf", str(bundle), "."])
    _need(res.returncode == 0, f"bundle_tar_failed:rc={res.returncode}")
    _need(_run(["gzip", "-t", str(bundle)]).returncode == 0, "bundle_not_gzip")
    return bundle, {"manifest": manifest, "volume": vol, "workflows": {k: wf[k] for k in ("count", "bytes", "sha256")},
                    "dump": {"name": dump.name, "bytes": dump.stat().st_size, "sha256": dman.get("sha256")}}


def encrypt(plain: Path) -> Path:
    enc = Path(str(plain) + ".gpg")
    res = _run(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase-file", str(PASS_FILE),
                "--cipher-algo", "AES256", "-c", "-o", str(enc), str(plain)], timeout=1800)
    _need(res.returncode == 0 and enc.is_file() and enc.stat().st_size > 0, f"gpg_failed:rc={res.returncode}")
    return enc


def upload(enc: Path, dcfg: dict) -> None:
    gog = Path(os.path.expanduser(str(dcfg["gog_bin"])))
    pw = Path(os.path.expanduser(str(dcfg["keyring_password_file"]))).read_text(encoding="utf-8").strip()
    env = {**os.environ, "GOG_KEYRING_PASSWORD": pw}
    res = subprocess.run([str(gog), "drive", "upload", str(enc), "-a", str(dcfg["account"]),
                          "--parent", str(dcfg["folder_id"]), "-p"], capture_output=True, text=True,
                         timeout=int(dcfg["command_timeout_s"]) * 4, env=env, check=False)
    _need(res.returncode == 0, f"drive_upload_failed:rc={res.returncode}")


def prune_host(out_dir: Path, keep: int) -> list[str]:
    bundles = sorted(out_dir.glob(f"{PREFIX}_*.tar.gz"), key=lambda p: p.name, reverse=True)
    gone = []
    for old in bundles[keep:]:
        old.unlink()
        gone.append(old.name)
    return gone


def write_receipt(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def preconditions() -> dict:
    """Everything --dry-run reports; each False is a reason --apply would refuse."""
    pol = be._load_policy()
    out: dict = {}
    try:
        _, dcfg, _ = be.load_sections(be.n8n_policy(pol))
        out["policy_drive_n8n"] = True
        out["drive_prefix"] = dcfg["prefix"]
    except be.PolicyError as exc:
        out["policy_drive_n8n"] = False
        out["policy_error"] = str(exc)
    for name in (APP_CONTAINER, DB_CONTAINER):
        out[f"container_{name}"] = _run(["docker", "inspect", name], timeout=60).returncode == 0
    out["gpg_pass_file"] = PASS_FILE.is_file()
    out["gog_present"] = Path.home().joinpath(".local/bin/gog").is_file()
    dump = newest_dump(OUT_DIR) if OUT_DIR.is_dir() else None
    out["newest_dump"] = dump.name if dump else None
    out["newest_dump_age_h"] = round((time.time() - dump.stat().st_mtime) / 3600, 1) if dump else None
    out["free_bytes"] = shutil.disk_usage(OUT_DIR if OUT_DIR.is_dir() else Path.home()).free
    out["ready"] = all(v is True for k, v in out.items() if k.startswith(("policy_drive", "container_", "gpg_", "gog_")))
    return out


def apply(*, no_drive: bool) -> dict:
    started = time.time()
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")  # local wall clock, aware: same naming as backup_secrets_state.sh
    doc: dict = {"schema": SCHEMA, "as_of": _utc(), "stamp": stamp, "ok": False, "reason": None, "drive": None}
    tmp_root = Path(tempfile.mkdtemp(prefix="n8n_backup_", dir=os.environ.get("N8N_BACKUP_TMP") or None))
    try:
        os.chmod(tmp_root, 0o700)
        _need(PASS_FILE.is_file(), "passphrase_file_missing")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(OUT_DIR, 0o700)
        stage = tmp_root / "stage"
        stage.mkdir()
        bundle, facts = build_bundle(stage, stamp, started)
        doc.update(facts)
        host_copy = OUT_DIR / bundle.name
        shutil.copy2(bundle, host_copy)
        os.chmod(host_copy, 0o600)
        doc["host_bundle"] = {"path": str(host_copy), "bytes": host_copy.stat().st_size, "sha256": _sha256(host_copy)}
        doc["host_pruned"] = prune_host(OUT_DIR, HOST_KEEP)
        if no_drive:
            doc.update(ok=True, reason="host_only_no_drive_requested", drive={"skipped": True})
            return doc
        pol = be._load_policy()
        npol = be.n8n_policy(pol)
        _, dcfg, _ = be.load_sections(npol)
        enc = encrypt(bundle)
        upload(enc, dcfg)
        ver = be.verify_upload(npol, source=host_copy, plaintext=bundle, encrypted=enc,
                               condition=be.CONDITION_N8N_UPLOAD)
        doc["drive"] = {"verified": bool(ver.get("ok")), "reason": ver.get("reason"),
                        "object": (ver.get("record") or {}).get("drive")}
        _need(bool(ver.get("ok")), f"drive_verify_failed:{ver.get('reason')}")
        ret = be.run_n8n_drive(pol)
        doc["drive"]["retention"] = {k: ret.get(k) for k in ("ok", "refused", "remaining", "deleted", "kept")}
        _need(bool(ret.get("ok")), f"drive_retention_failed:{ret.get('refused')}")
        doc.update(ok=True, reason="verified_on_drive")
        return doc
    except (BackupError, OSError, subprocess.SubprocessError, be.PolicyError, ValueError, KeyError) as exc:
        doc["reason"] = str(exc) if isinstance(exc, BackupError) else f"{type(exc).__name__}: {str(exc)[:200]}"
        return doc
    finally:
        doc["duration_s"] = round(time.time() - started, 1)
        shutil.rmtree(tmp_root, ignore_errors=True)
        write_receipt(OUT_DIR / RECEIPT_NAME, doc)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--no-drive", action="store_true", help="host bundle only: no upload, no Drive retention")
    args = ap.parse_args(argv)
    if args.dry_run:
        pre = preconditions()
        print(json.dumps({"mode": "dry-run", **pre}, indent=1, default=str))
        return 0 if pre["ready"] else 1
    doc = apply(no_drive=args.no_drive)
    print(json.dumps({k: doc.get(k) for k in ("ok", "reason", "stamp", "host_bundle", "drive", "duration_s")},
                     indent=1, default=str))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
