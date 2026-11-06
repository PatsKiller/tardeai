#!/usr/bin/env python3
"""n8n program 0.2c: restore drill for the whole n8n bundle (database AND data volume), scratch only.

scripts/n8n_lab_restore_drill.sh proves the newest *dump* restores and that the LIVE container's key decrypts a
restored credential. That cannot catch a lost or wrong volume: if ``/home/node/.n8n/config`` (the encryption key) is
not in the backup, every credential is unreadable after a rebuild. This drill takes the newest bundle written by
scripts/n8n_backup.py and proves, in scratch:

  bundle_intact        the tarball opens, MANIFEST.json parses, every member's size and sha256 match it
  volume_has_config    the volume tar holds ./config with a non-empty ``encryptionKey`` (never printed)
  db_restores          the bundle's dump restores into a throwaway database with no pg_restore error
  workflows_match      restored workflow_entity count equals the manifest's dump_workflow_count
  key_decrypts         one restored credential decrypts with the key taken FROM THE RESTORED VOLUME (not the live
                       container's) - checked by scripts/lib/n8n_credential_key_probe.js inside the app container,
                       the key passed through the environment, never argv
  drill_db_dropped     the throwaway database was dropped

It never touches the live ``n8n`` database, the live volume or production Postgres. The elapsed time is recorded
(``seconds``) so a restore that quietly became slow is visible. Receipt: <backups>/n8n/n8n_bundle_restore_drill_last.json
(N8nBundleRestoreDrill@v1), written on success AND failure. Exit 0 only for state PASSED.

    python3 scripts/n8n_bundle_restore_drill.py --dry-run | --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
APP_CONTAINER = os.environ.get("N8N_APP_CONTAINER", "m8m-n8n")
DB_CONTAINER = os.environ.get("N8N_DB_CONTAINER", "m8m-n8n-db")
OUT_DIR = Path(os.environ.get("N8N_BACKUP_DIR", str(Path.home() / "trade-ai-releases/persistent-state/backups/n8n")))
KEYPROBE = ROOT / "scripts/lib/n8n_credential_key_probe.js"
RECEIPT_NAME = "n8n_bundle_restore_drill_last.json"
SCHEMA = "N8nBundleRestoreDrill@v1"
CHECKS = ("bundle_intact", "volume_has_config", "db_restores", "workflows_match", "key_decrypts", "drill_db_dropped")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def newest_bundle(out_dir: Path) -> Optional[Path]:
    found = sorted(out_dir.glob("n8n_backup_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def check_bundle(bundle: Path, stage: Path) -> tuple[dict, list[str]]:
    """Extract the bundle into ``stage`` and compare every member with MANIFEST.json."""
    problems: list[str] = []
    try:
        with tarfile.open(bundle, "r:gz") as tf:
            tf.extractall(stage, filter="data")
    except (tarfile.TarError, OSError, EOFError) as exc:
        return {}, [f"bundle_unreadable:{type(exc).__name__}"]
    mpath = stage / "MANIFEST.json"
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, ["manifest_missing_or_invalid"]
    members = manifest.get("members")
    if not isinstance(members, dict) or not members:
        return manifest, ["manifest_has_no_members"]
    for rel, meta in sorted(members.items()):
        p = stage / rel
        if not p.is_file():
            problems.append(f"member_missing:{rel}")
        elif p.stat().st_size != meta.get("bytes") or _sha256(p) != meta.get("sha256"):
            problems.append(f"member_mismatch:{rel}")
    return manifest, problems


def volume_key(stage: Path) -> tuple[Optional[str], str]:
    """The encryption key from the bundle's volume tar. Returns (key or None, reason)."""
    vol = stage / "volume" / "n8n-data.tar.gz"
    if not vol.is_file():
        return None, "volume_tar_missing"
    out = stage / "vol_extract"
    out.mkdir()
    try:
        with tarfile.open(vol, "r:gz") as tf:
            tf.extractall(out, filter="data")
        cfg = json.loads((out / "config").read_text(encoding="utf-8"))
    except (tarfile.TarError, OSError, ValueError, KeyError):
        return None, "volume_config_missing_or_invalid"
    key = cfg.get("encryptionKey") if isinstance(cfg, dict) else None
    if not isinstance(key, str) or not key:
        return None, "volume_config_has_no_encryption_key"
    return key, "ok"


def _docker(args: list[str], *, stdin: Optional[str] = None, env: Optional[dict] = None, timeout: int = 600):
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout,
                          env=env, check=False)


def _psql(db: str, sql: str):
    return _docker(["exec", "-i", DB_CONTAINER, "sh", "-c",
                    'psql -v ON_ERROR_STOP=1 -tA -U "$POSTGRES_USER" -d "$1"', "sh", db], stdin=sql + "\n")


def restore_and_probe(stage: Path, manifest: dict, key: Optional[str]) -> dict:
    """Restore the bundle's dump into a throwaway DB, count workflows, decrypt one credential with ``key``."""
    facts: dict[str, Any] = {"restore_rc": None, "workflow_count": None, "key_word": "PROBE_NOT_RUN", "dropped": False}
    dump = stage / "db" / str(manifest.get("dump", ""))
    if not dump.is_file():
        facts["restore_rc"] = "dump_missing"
        return facts
    drill = "n8n_bundle_drill_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    created = False
    try:
        cp = _docker(["cp", str(dump), f"{DB_CONTAINER}:/tmp/bundle_drill.dump"])
        if cp.returncode != 0:
            facts["restore_rc"] = f"docker_cp_rc={cp.returncode}"
            return facts
        mk = _psql("postgres", f'create database "{drill}";')
        if mk.returncode != 0:
            facts["restore_rc"] = f"create_db_rc={mk.returncode}"
            return facts
        created = True
        rs = _docker(["exec", DB_CONTAINER, "sh", "-c",
                      'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-privileges /tmp/bundle_drill.dump',
                      "sh", drill])
        facts["restore_rc"] = rs.returncode
        facts["restore_stderr_errors"] = sum(1 for ln in (rs.stderr or "").splitlines() if "error" in ln.lower())
        wf = _psql(drill, "select count(*) from workflow_entity;")
        try:
            facts["workflow_count"] = int(wf.stdout.strip()) if wf.returncode == 0 else None
        except ValueError:
            facts["workflow_count"] = None
        cipher = _psql(drill, "select data from credentials_entity order by id limit 1;")
        if cipher.returncode == 0 and key:
            env = dict(os.environ, N8N_ENCRYPTION_KEY=key)
            pr = _docker(["exec", "-i", "-e", "N8N_ENCRYPTION_KEY", APP_CONTAINER, "node", "-e",
                          KEYPROBE.read_text(encoding="utf-8")], stdin=cipher.stdout.strip(), env=env)
            word = (pr.stdout or "").strip().splitlines()
            facts["key_word"] = word[0] if word else "PROBE_FAILED"
        elif cipher.returncode != 0:
            facts["key_word"] = "PROBE_FAILED"
    finally:
        if created:
            dr = _psql("postgres", f'drop database if exists "{drill}";')
            facts["dropped"] = dr.returncode == 0
        else:
            facts["dropped"] = True  # nothing was created
        _docker(["exec", DB_CONTAINER, "rm", "-f", "/tmp/bundle_drill.dump"])
    return facts


def verdict(*, bundle_problems: list[str], key_reason: str, facts: dict, manifest: dict, expect_credentials: bool) -> dict:
    """Pure decision. A missing fact fails its check; nothing defaults to passing."""
    checks = {
        "bundle_intact": not bundle_problems,
        "volume_has_config": key_reason == "ok",
        "db_restores": facts.get("restore_rc") == 0 and not facts.get("restore_stderr_errors"),
        "workflows_match": (isinstance(facts.get("workflow_count"), int) and facts["workflow_count"] > 0
                            and facts["workflow_count"] == manifest.get("dump_workflow_count")),
        "key_decrypts": facts.get("key_word") == "KEY_OK" or (facts.get("key_word") == "NO_CIPHERTEXT" and not expect_credentials),
        "drill_db_dropped": facts.get("dropped") is True,
    }
    failures = [k for k in CHECKS if not checks[k]]
    if bundle_problems:
        failures += bundle_problems[:5]
    if key_reason != "ok":
        failures.append(key_reason)
    return {"state": "PASSED" if not failures else "FAILED", "checks": checks, "failures": failures}


def write_receipt(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def apply(out_dir: Path = OUT_DIR) -> dict:
    t0 = time.monotonic()
    doc: dict[str, Any] = {"schema": SCHEMA, "started": _utc(), "state": "FAILED", "failures": ["not_run"]}
    stage = Path(tempfile.mkdtemp(prefix="n8n_bundle_drill_"))
    try:
        bundle = newest_bundle(out_dir)
        if bundle is None:
            doc.update(failures=["no_bundle_found"])
            return doc
        doc["bundle"] = bundle.name
        manifest, problems = check_bundle(bundle, stage)
        key, reason = volume_key(stage) if not problems else (None, "skipped_bundle_not_intact")
        facts = restore_and_probe(stage, manifest, key) if not problems else {"restore_rc": None}
        v = verdict(bundle_problems=problems, key_reason=reason, facts=facts, manifest=manifest,
                    expect_credentials=bool(manifest.get("credentials_count")))
        doc.update(v)
        doc.update(workflows_in_restore=facts.get("workflow_count"), manifest_workflows=manifest.get("dump_workflow_count"),
                   key_check=facts.get("key_word"), ok=v["state"] == "PASSED")
        return doc
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        doc.update(state="FAILED", failures=[f"drill_aborted:{type(exc).__name__}"], ok=False)
        return doc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        doc["finished"] = _utc()
        doc["seconds"] = round(time.monotonic() - t0, 1)
        write_receipt(out_dir / RECEIPT_NAME, doc)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        b = newest_bundle(OUT_DIR)
        print(json.dumps({"dry_run": True, "would_restore": b.name if b else None, "into": "throwaway db in " + DB_CONTAINER,
                          "receipt": str(OUT_DIR / RECEIPT_NAME)}, indent=1))
        return 0 if b else 2
    doc = apply()
    print(json.dumps({k: doc.get(k) for k in ("state", "bundle", "checks", "failures", "seconds")}, indent=1))
    return 0 if doc.get("state") == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
