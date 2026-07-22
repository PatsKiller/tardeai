#!/usr/bin/env python3
"""Store the Schwab BROKERAGE LOGIN credentials in Bitwarden Secrets Manager (trade-ai-prod).

Interactive + getpass only — values are never echoed, never written to disk, never logged.
Keys written (names read by scripts/schwab_auto_reauth.py via the tmpfs render):

    SCHWAB_LOGIN_ID        brokerage login id
    SCHWAB_LOGIN_PASSWORD  brokerage password
    SCHWAB_TOTP_SECRET     optional — only if 2FA is an authenticator TOTP (blank = push/SMS approval)

Upserts (create-or-edit) via bws using the write token, then re-renders the tmpfs env cache
and verifies the keys landed. Run:  .venv/bin/python scripts/secrets/store_schwab_login.py
"""
from __future__ import annotations

import getpass
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

BWS = str(Path.home() / ".local" / "bin" / "bws")
READ_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_read_token"
WRITE_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_write_token"
PROJECT_NAME = "trade-ai-prod"
RENDER = ROOT / "scripts" / "secrets" / "render_env.py"


def _bws(args: list[str], token: str) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["BWS_ACCESS_TOKEN"] = token
    env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"
    return subprocess.run([BWS, *args], env=env, capture_output=True, text=True, timeout=90)


def _project_id(token: str) -> str:
    r = _bws(["project", "list", "--output", "json"], token)
    if r.returncode != 0:
        raise RuntimeError(f"bws project list failed: {(r.stderr or r.stdout)[:200]}")
    for p in json.loads(r.stdout):
        if p.get("name") == PROJECT_NAME:
            return p["id"]
    raise RuntimeError(f"project {PROJECT_NAME!r} not found")


def _existing(token: str, project_id: str) -> dict[str, str]:
    r = _bws(["secret", "list", project_id, "--output", "json"], token)
    if r.returncode != 0:
        raise RuntimeError(f"bws secret list failed: {(r.stderr or r.stdout)[:200]}")
    return {s["key"]: s["id"] for s in json.loads(r.stdout)}


def _upsert(key: str, value: str, wtok: str, project_id: str, existing: dict[str, str]) -> str:
    if key in existing:
        r = _bws(["secret", "edit", "--key", key, "--value", value, existing[key]], wtok)
        action = "updated"
    else:
        r = _bws(["secret", "create", key, value, project_id], wtok)
        action = "created"
    if r.returncode != 0:
        raise RuntimeError(f"bws upsert {key} failed: {(r.stderr or r.stdout)[:200]}")
    return action


def main() -> int:
    for p in (READ_TOKEN, WRITE_TOKEN):
        if not p.exists():
            print(f"missing {p} — cannot reach Bitwarden SM")
            return 1
    print("Schwab brokerage login → Bitwarden SM (values are not echoed).")
    login = input("Schwab login ID: ").strip()
    pw = getpass.getpass("Schwab password (hidden): ").strip()
    totp = getpass.getpass("TOTP secret (hidden; ENTER to skip — skip if 2FA is app-push/SMS): ").strip()
    if not login or not pw:
        print("login id and password are both required — nothing written")
        return 1

    rtok, wtok = READ_TOKEN.read_text().strip(), WRITE_TOKEN.read_text().strip()
    project_id = _project_id(rtok)
    existing = _existing(rtok, project_id)
    wrote = {}
    wrote["SCHWAB_LOGIN_ID"] = _upsert("SCHWAB_LOGIN_ID", login, wtok, project_id, existing)
    wrote["SCHWAB_LOGIN_PASSWORD"] = _upsert("SCHWAB_LOGIN_PASSWORD", pw, wtok, project_id, existing)
    if totp:
        wrote["SCHWAB_TOTP_SECRET"] = _upsert("SCHWAB_TOTP_SECRET", totp, wtok, project_id, existing)
    for k, action in wrote.items():
        print(f"  {k}: {action}")

    print("re-rendering tmpfs env cache …")
    r = subprocess.run([sys.executable, str(RENDER), "--now"], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print(f"render failed (secrets ARE saved in SM): {(r.stderr or r.stdout)[:200]}")
        return 1
    import os
    rendered = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "tradeai" / "env"
    have = {ln.split("=", 1)[0] for ln in rendered.read_text().splitlines() if "=" in ln}
    missing = [k for k in wrote if k not in have]
    if missing:
        print(f"WARNING: rendered cache missing {missing}")
        return 1
    print("verified: keys present in rendered cache. Auto-reauth can now log in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
