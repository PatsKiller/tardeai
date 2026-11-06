#!/usr/bin/env python3
"""n8n program 0.1h: rehearse an n8n upgrade (or the current pin) on a restored scratch copy. Never touches live.

Builds, from the newest bundle written by scripts/n8n_backup.py, a fully isolated copy: an ``--internal`` docker
network (no route to the host, the relay, the bridge or the internet), its own throwaway Postgres (its own random
password; no lab credential is read), the bundle's dump restored into it, every workflow set inactive (belt and
braces: the internal network already stops anything reaching out), and the bundle's data volume mounted. Then it
starts ``--image`` against that copy and checks:

  image_matches_pin    --image equals config/n8n_version_pin.json ``n8n_image`` (the live pin) - or is named as
                       the TARGET of an upgrade (``--target``), in which case the pin is reported, not enforced
  boots                /healthz answers within the deadline (migrations from the dump's schema ran)
  no_migration_error   the container log holds no migration/ERROR line
  workflows_intact     workflow_entity count after boot equals the manifest's dump_workflow_count
  key_decrypts         the restored volume's key decrypts one restored credential (KEY_OK)
  cleaned_up           container, postgres and network were removed

    python3 scripts/n8n_upgrade_rehearsal.py --dry-run
    python3 scripts/n8n_upgrade_rehearsal.py --apply [--image n8nio/n8n:X.Y.Z --target]

Receipt: <backups>/n8n/n8n_upgrade_rehearsal_last.json (N8nUpgradeRehearsal@v1), written on success and failure.
Runbook: docs/runbooks/N8N_UPGRADE_RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
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
PIN_FILE = ROOT / "config/n8n_version_pin.json"
KEYPROBE = ROOT / "scripts/lib/n8n_credential_key_probe.js"
OUT_DIR = Path(os.environ.get("N8N_BACKUP_DIR", str(Path.home() / "trade-ai-releases/persistent-state/backups/n8n")))
RECEIPT_NAME = "n8n_upgrade_rehearsal_last.json"
SCHEMA = "N8nUpgradeRehearsal@v1"
CHECKS = ("image_matches_pin", "boots", "no_migration_error", "workflows_intact", "key_decrypts", "cleaned_up")
BOOT_DEADLINE_S = 240
HARDENING_ENV = {
    "N8N_DIAGNOSTICS_ENABLED": "false", "N8N_VERSION_NOTIFICATIONS_ENABLED": "false", "N8N_TEMPLATES_ENABLED": "false",
    "N8N_PUBLIC_API_DISABLED": "true", "N8N_COMMUNITY_PACKAGES_ENABLED": "false", "N8N_PYTHON_ENABLED": "false",
    "N8N_BLOCK_ENV_ACCESS_IN_NODE": "true", "DB_TYPE": "postgresdb", "DB_POSTGRESDB_HOST": "rehearsal-db",
    "DB_POSTGRESDB_PORT": "5432", "DB_POSTGRESDB_DATABASE": "n8n", "DB_POSTGRESDB_USER": "n8n",
    "GENERIC_TIMEZONE": "America/New_York",
    "NODES_EXCLUDE": '["n8n-nodes-base.executeCommand","n8n-nodes-base.ssh","n8n-nodes-base.ftp",'
                     '"n8n-nodes-base.emailSend","n8n-nodes-base.localFileTrigger"]',
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_pin(path: Path = PIN_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def newest_bundle(out_dir: Path) -> Optional[Path]:
    found = sorted(out_dir.glob("n8n_backup_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def _docker(args: list[str], *, stdin: Optional[str] = None, timeout: int = 300):
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout, check=False)


def verdict(*, pin: dict, image: str, target: bool, facts: dict, manifest: dict, expect_credentials: bool) -> dict:
    """Pure decision. A missing fact fails its check."""
    log_errors = facts.get("log_errors")
    checks = {
        "image_matches_pin": target or image == pin.get("n8n_image"),
        "boots": facts.get("healthy") is True,
        "no_migration_error": isinstance(log_errors, int) and log_errors == 0,
        "workflows_intact": (isinstance(facts.get("workflow_count"), int) and facts["workflow_count"] > 0
                             and facts["workflow_count"] == manifest.get("dump_workflow_count")),
        "key_decrypts": facts.get("key_word") == "KEY_OK" or (facts.get("key_word") == "NO_CIPHERTEXT" and not expect_credentials),
        "cleaned_up": facts.get("cleaned") is True,
    }
    failures = [k for k in CHECKS if not checks[k]]
    return {"state": "PASSED" if not failures else "FAILED", "checks": checks, "failures": failures,
            "kind": "upgrade_to_target" if target else "pin_rehearsal"}


def write_receipt(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _wait(fn, deadline_s: int, every: float = 3.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(every)
    return False


def rehearse(bundle: Path, image: str, pg_image: str, work: Path, run: str) -> tuple[dict, dict]:
    """Build the isolated copy, boot ``image`` on it, return (facts, manifest). Always tears down what it made."""
    facts: dict[str, Any] = {"healthy": False, "log_errors": None, "workflow_count": None, "key_word": "PROBE_NOT_RUN",
                             "cleaned": False}
    net, pg, app = f"n8n-rehearsal-{run}", f"n8n-rehearsal-db-{run}", f"n8n-rehearsal-app-{run}"
    made: list[tuple[str, str]] = []
    manifest: dict = {}
    try:
        with tarfile.open(bundle, "r:gz") as tf:
            tf.extractall(work / "b", filter="data")
        manifest = json.loads((work / "b/MANIFEST.json").read_text(encoding="utf-8"))
        vol = work / "vol"
        vol.mkdir(mode=0o700)
        with tarfile.open(work / "b/volume/n8n-data.tar.gz", "r:gz") as tf:
            tf.extractall(vol, filter="data")
        dump = work / "b/db" / str(manifest["dump"])
        pw = secrets.token_hex(16)
        if _docker(["network", "create", "--internal", net]).returncode != 0:
            facts["error"] = "network_create_failed"
            return facts, manifest
        made.append(("network", net))
        r = _docker(["run", "-d", "--name", pg, "--network", net, "--network-alias", "rehearsal-db", "-e", "POSTGRES_DB=n8n",
                     "-e", "POSTGRES_USER=n8n", "-e", f"POSTGRES_PASSWORD={pw}", "--memory", "512m", pg_image])
        if r.returncode != 0:
            facts["error"] = "postgres_start_failed"
            return facts, manifest
        made.append(("container", pg))
        ready = _wait(lambda: _docker(["exec", pg, "pg_isready", "-U", "n8n", "-d", "n8n"]).returncode == 0, 90)
        if not ready:
            facts["error"] = "postgres_not_ready"
            return facts, manifest
        _docker(["cp", str(dump), f"{pg}:/tmp/r.dump"])
        rs = _docker(["exec", pg, "pg_restore", "-U", "n8n", "-d", "n8n", "--no-owner", "--no-privileges", "/tmp/r.dump"])
        facts["restore_rc"] = rs.returncode
        # tables may already exist from the image's init? no: fresh DB; any restore error is a failed rehearsal
        _docker(["exec", "-i", pg, "psql", "-v", "ON_ERROR_STOP=1", "-U", "n8n", "-d", "n8n"],
                stdin="update workflow_entity set active=false;\n")
        env = dict(HARDENING_ENV, DB_POSTGRESDB_PASSWORD=pw)
        cmd = ["run", "-d", "--name", app, "--network", net, "--memory", "1g", "--pids-limit", "512",
               "--security-opt", "no-new-privileges:true", "-v", f"{vol}:/home/node/.n8n"]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(image)
        if _docker(cmd).returncode != 0:
            facts["error"] = "app_start_failed"
            return facts, manifest
        made.append(("container", app))
        facts["healthy"] = _wait(lambda: _docker(["exec", app, "wget", "-qO-", "http://127.0.0.1:5678/healthz"]).returncode == 0,
                                 BOOT_DEADLINE_S)
        logs = _docker(["logs", app])
        text = (logs.stdout or "") + (logs.stderr or "")
        facts["log_errors"] = sum(1 for ln in text.splitlines()
                                  if ("migration" in ln.lower() and "error" in ln.lower()) or ln.startswith("Error:"))
        wf = _docker(["exec", "-i", pg, "psql", "-tA", "-U", "n8n", "-d", "n8n"], stdin="select count(*) from workflow_entity;\n")
        try:
            facts["workflow_count"] = int(wf.stdout.strip()) if wf.returncode == 0 else None
        except ValueError:
            facts["workflow_count"] = None
        cipher = _docker(["exec", "-i", pg, "psql", "-tA", "-U", "n8n", "-d", "n8n"],
                         stdin="select data from credentials_entity order by id limit 1;\n")
        if cipher.returncode == 0 and facts["healthy"]:
            pr = _docker(["exec", "-i", app, "node", "-e", KEYPROBE.read_text(encoding="utf-8")], stdin=cipher.stdout.strip())
            word = (pr.stdout or "").strip().splitlines()
            facts["key_word"] = word[0] if word else "PROBE_FAILED"
        return facts, manifest
    finally:
        ok = True
        for kind, name in reversed(made):
            res = _docker(["rm", "-f", name] if kind == "container" else ["network", "rm", name])
            ok = ok and res.returncode == 0
        facts["cleaned"] = ok


def apply(image: str, target: bool, out_dir: Path = OUT_DIR) -> dict:
    t0 = time.monotonic()
    doc: dict[str, Any] = {"schema": SCHEMA, "started": _utc(), "image": image, "state": "FAILED", "failures": ["not_run"]}
    work = Path(tempfile.mkdtemp(prefix="n8n_rehearsal_"))
    try:
        pin = load_pin()
        doc["pin"] = pin.get("n8n_image")
        bundle = newest_bundle(out_dir)
        if bundle is None:
            doc["failures"] = ["no_bundle_found"]
            return doc
        doc["bundle"] = bundle.name
        run = datetime.now(timezone.utc).strftime("%H%M%S") + secrets.token_hex(2)
        facts, manifest = rehearse(bundle, image, pin["postgres_image"], work, run)
        v = verdict(pin=pin, image=image, target=target, facts=facts, manifest=manifest,
                    expect_credentials=bool(manifest.get("credentials_count")))
        doc.update(v)
        doc.update(ok=v["state"] == "PASSED", workflows_in_restore=facts.get("workflow_count"),
                   manifest_workflows=manifest.get("dump_workflow_count"), key_check=facts.get("key_word"),
                   error=facts.get("error"))
        return doc
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as exc:
        doc.update(state="FAILED", failures=[f"rehearsal_aborted:{type(exc).__name__}"], ok=False)
        return doc
    finally:
        shutil.rmtree(work, ignore_errors=True)
        doc["finished"] = _utc()
        doc["seconds"] = round(time.monotonic() - t0, 1)
        write_receipt(out_dir / RECEIPT_NAME, doc)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--image", default=None, help="n8n image to boot (default: the pin)")
    ap.add_argument("--target", action="store_true", help="--image is an upgrade target, not the pin")
    args = ap.parse_args(argv)
    pin = load_pin()
    image = args.image or pin["n8n_image"]
    if args.dry_run:
        b = newest_bundle(OUT_DIR)
        print(json.dumps({"dry_run": True, "bundle": b.name if b else None, "image": image, "postgres": pin["postgres_image"],
                          "network": "docker --internal (no host, no internet)", "receipt": str(OUT_DIR / RECEIPT_NAME)}, indent=1))
        return 0 if b else 2
    doc = apply(image, args.target)
    print(json.dumps({k: doc.get(k) for k in ("state", "image", "bundle", "checks", "failures", "seconds")}, indent=1))
    return 0 if doc.get("state") == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
