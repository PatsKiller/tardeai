#!/usr/bin/env python3
"""Mirror SCHWAB_TOKEN_ENC_KEY (the Fernet key that encrypts broker OAuth tokens in
Postgres) from config/broker_credentials.env into Bitwarden SM (trade-ai-prod), so the
key survives a disk loss. Value is never printed. Restore = write the SM value back to
config/broker_credentials.env (chmod 600). Run:
    .venv/bin/python scripts/secrets/mirror_fernet_key_to_sm.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BWS = os.environ.get("BWS_BIN") or str(Path.home() / ".local" / "bin" / "bws")
READ_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_read_token"
WRITE_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_write_token"
PROJECT_NAME = "trade-ai-prod"
KEY = "SCHWAB_TOKEN_ENC_KEY"
SRC = ROOT / "config" / "broker_credentials.env"


def _bws(args: list[str], token: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["BWS_ACCESS_TOKEN"] = token
    env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"
    return subprocess.run([BWS, *args], env=env, capture_output=True, text=True, timeout=90)


def main() -> int:
    val = None
    for line in SRC.read_text().splitlines():
        if line.startswith(f"{KEY}="):
            val = line.split("=", 1)[1].strip()
    if not val:
        print(f"{KEY} not found in {SRC} — nothing to mirror")
        return 1
    rtok, wtok = READ_TOKEN.read_text().strip(), WRITE_TOKEN.read_text().strip()
    r = _bws(["project", "list", "--output", "json"], rtok)
    if r.returncode != 0:
        print(f"bws project list failed: {(r.stderr or r.stdout)[:200]}")
        return 1
    pid = next((p["id"] for p in json.loads(r.stdout) if p.get("name") == PROJECT_NAME), None)
    if not pid:
        print(f"project {PROJECT_NAME!r} not found")
        return 1
    r = _bws(["secret", "list", pid, "--output", "json"], rtok)
    existing = {s["key"]: s["id"] for s in json.loads(r.stdout)} if r.returncode == 0 else {}
    if KEY in existing:
        r = _bws(["secret", "edit", "--key", KEY, "--value", val, existing[KEY]], wtok)
        action = "updated"
    else:
        r = _bws(["secret", "create", KEY, val, pid], wtok)
        action = "created"
    if r.returncode != 0:
        print(f"bws upsert failed: {(r.stderr or r.stdout)[:200]}")
        return 1
    print(f"{KEY}: {action} in Bitwarden SM ({PROJECT_NAME}). "
          f"Restore = write the SM value back to {SRC.relative_to(ROOT)} (chmod 600).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
